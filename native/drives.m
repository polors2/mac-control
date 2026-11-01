#import <Foundation/Foundation.h>
#import <DiskArbitration/DiskArbitration.h>
#import <IOKit/IOKitLib.h>
#include <time.h>
#include <sys/mount.h>
#include <signal.h>

static id readOnly(NSString *bsd) {
    struct statfs *mounts = NULL; int count = getmntinfo(&mounts, MNT_NOWAIT);
    for (int i = 0; i < count; i++) if ([@(mounts[i].f_mntfromname).lastPathComponent isEqual:bsd]) return @((mounts[i].f_flags & MNT_RDONLY) != 0);
    return NSNull.null;
}

static NSString *uuidString(id value) {
    return value ? CFBridgingRelease(CFUUIDCreateString(kCFAllocatorDefault, (__bridge CFUUIDRef)value)) : @"";
}
static BOOL externalUSB(NSDictionary *description) {
    return [description[(__bridge id)kDADiskDescriptionDeviceProtocolKey] isEqual:@"USB"] &&
        [description[(__bridge id)kDADiskDescriptionDeviceInternalKey] isEqual:@NO];
}
// Read APFS lock metadata only when an external APFS volume is unmounted.
static NSDictionary *apfsVolumes(void) {
    NSTask *task = [NSTask new]; task.executableURL = [NSURL fileURLWithPath:@"/usr/sbin/diskutil"];
    task.arguments = @[@"apfs", @"list", @"-plist"];
    NSPipe *output = [NSPipe pipe]; task.standardOutput = output;
    task.standardError = [NSFileHandle fileHandleWithNullDevice];
    if (![task launchAndReturnError:nil]) return @{};
    NSData *data = [output.fileHandleForReading readDataToEndOfFile]; [task waitUntilExit];
    if (task.terminationStatus || data.length > 2097152) return @{};
    NSDictionary *info = [NSPropertyListSerialization propertyListWithData:data options:NSPropertyListImmutable format:nil error:nil];
    NSMutableDictionary *volumes = NSMutableDictionary.dictionary;
    for (NSDictionary *container in info[@"Containers"])
        for (NSDictionary *volume in container[@"Volumes"])
            if ([volume[@"DeviceIdentifier"] isKindOfClass:NSString.class]) volumes[volume[@"DeviceIdentifier"]] = volume;
    return volumes;
}
static NSArray *enumerate(DASessionRef session) {
    NSMutableDictionary *groups = NSMutableDictionary.dictionary;
    NSDictionary *apfs = nil;
    io_iterator_t iterator = 0;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOMedia"), &iterator)) return @[];
    io_service_t media;
    while ((media = IOIteratorNext(iterator))) {
        DADiskRef disk = DADiskCreateFromIOMedia(kCFAllocatorDefault, session, media); IOObjectRelease(media);
        if (!disk) continue;
        NSDictionary *description = CFBridgingRelease(DADiskCopyDescription(disk));
        if (externalUSB(description)) {
            DADiskRef whole = DADiskCopyWholeDisk(disk);
            if (whole) {
                NSDictionary *physical = CFBridgingRelease(DADiskCopyDescription(whole));
                NSString *bsd = @(DADiskGetBSDName(whole));
                if (externalUSB(physical)) {
                    NSMutableDictionary *group = groups[bsd];
                    if (!group) {
                        group = [@{@"device": bsd, @"model": physical[(__bridge id)kDADiskDescriptionDeviceModelKey] ?: @"USB hard drive",
                            @"size": physical[(__bridge id)kDADiskDescriptionMediaSizeKey] ?: @0,
                            @"volumes": NSMutableArray.array, @"protected": @NO} mutableCopy];
                        groups[bsd] = group;
                    }
                    NSString *device = @(DADiskGetBSDName(disk));
                    NSString *uuid = uuidString(description[(__bridge id)kDADiskDescriptionVolumeUUIDKey]);
                    NSURL *path = description[(__bridge id)kDADiskDescriptionVolumePathKey];
                    if (path && ![path.path hasPrefix:@"/Volumes/"]) group[@"protected"] = @YES;
                    NSString *kind = description[(__bridge id)kDADiskDescriptionVolumeKindKey];
                    NSString *content = [description[(__bridge id)kDADiskDescriptionMediaContentKey] uppercaseString];
                    BOOL efi = [content isEqual:@"EFI"] || [content isEqual:@"C12A7328-F81F-11D2-BA4B-00A0C93EC93B"];
                    BOOL encrypted = [description[(__bridge id)kDADiskDescriptionMediaEncryptedKey] boolValue];
                    NSDictionary *crypto = nil;
                    if (!path && ((encrypted && uuid.length) || [kind isEqual:@"apfs"] || [content isEqual:@"41504653-0000-11AA-AA11-00306543ECAC"])) {
                        if (!apfs) apfs = apfsVolumes();
                        crypto = apfs[device];
                        if (crypto) {
                            uuid = crypto[@"APFSVolumeUUID"] ?: uuid;
                            kind = @"apfs";
                            encrypted = encrypted || [crypto[@"FileVault"] boolValue];
                        }
                    }
                    // Empty partition-map and EFI nodes do not become user controls.
                    if (uuid.length && kind.length && !efi) {
                        [group[@"volumes"] addObject:@{@"id": uuid, @"name": description[(__bridge id)kDADiskDescriptionVolumeNameKey] ?: crypto[@"Name"] ?: @"USB volume",
                            @"device": @(DADiskGetBSDName(disk)), @"mounted": @(path != nil),
                            @"mountPoint": path.path ?: @"", @"filesystem": kind,
                            @"readOnly": readOnly(device), @"encrypted": @(encrypted), @"locked": @([crypto[@"Locked"] boolValue])}];
                    }
                }
                CFRelease(whole);
            }
        }
        CFRelease(disk);
    }
    IOObjectRelease(iterator);
    NSMutableArray *result = NSMutableArray.array;
    for (NSMutableDictionary *group in groups.allValues) {
        NSArray *volumes = group[@"volumes"];
        if (!volumes.count || [group[@"protected"] boolValue]) continue;
        NSArray *sorted = [volumes sortedArrayUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) { return [a[@"id"] compare:b[@"id"]]; }];
        group[@"volumes"] = sorted; group[@"id"] = sorted[0][@"id"];
        group[@"name"] = sorted[0][@"name"];
        NSUInteger mounted = 0; for (NSDictionary *volume in volumes) if ([volume[@"mounted"] boolValue]) mounted++;
        BOOL encrypted = NO, locked = NO;
        for (NSDictionary *volume in volumes) { encrypted |= [volume[@"encrypted"] boolValue]; locked |= [volume[@"locked"] boolValue]; }
        group[@"encrypted"] = @(encrypted); group[@"locked"] = @(locked);
        group[@"mounted"] = @(mounted > 0);
        group[@"state"] = mounted == 0 ? (locked ? @"locked" : @"unmounted") : mounted == volumes.count ? @"mounted" : @"partial";
        group[@"connected"] = @YES;
        [group removeObjectForKey:@"protected"]; [result addObject:group];
    }
    return [result sortedArrayUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) { return [a[@"name"] compare:b[@"name"]]; }];
}

typedef struct { BOOL done; DAReturn result; } Operation;
static void finished(DADiskRef disk, DADissenterRef dissenter, void *context) {
    Operation *operation = context; operation->result = dissenter ? DADissenterGetStatus(dissenter) : 0; operation->done = YES;
}
static NSString *operate(DASessionRef session, DADiskRef disk, BOOL mount) {
    Operation operation = {0};
    DASessionScheduleWithRunLoop(session, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
    if (mount) DADiskMount(disk, NULL, kDADiskMountOptionDefault, finished, &operation);
    else DADiskUnmount(disk, kDADiskUnmountOptionWhole, finished, &operation);
    double deadline = CFAbsoluteTimeGetCurrent() + 18;
    while (!operation.done && CFAbsoluteTimeGetCurrent() < deadline) CFRunLoopRunInMode(kCFRunLoopDefaultMode, .05, true);
    DASessionUnscheduleFromRunLoop(session, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
    if (!operation.done) return @"The drive operation is taking longer than expected. Check its mount state before retrying.";
    if (operation.result) {
        if (operation.result == kDAReturnBusy) return @"The drive is in use. Close files or copies using it, then try again.";
        if (operation.result == kDAReturnNotPermitted || operation.result == kDAReturnNotPrivileged) return @"macOS did not permit this mount operation for the current user.";
        return [NSString stringWithFormat:@"macOS could not %@ the drive (Disk Arbitration error 0x%x).", mount ? @"mount" : @"unmount", operation.result];
    }
    return nil;
}
static NSString *change(DASessionRef session, NSString *identifier, BOOL mount) {
    NSDictionary *target = nil;
    for (NSDictionary *drive in enumerate(session)) if ([drive[@"id"] isEqual:identifier]) { target = drive; break; }
    if (!target) return @"This external USB drive is disconnected or is not eligible for this control.";
    if (mount && [target[@"locked"] boolValue]) return @"Unlock this encrypted drive to mount it.";
    for (NSDictionary *volume in target[@"volumes"]) {
        if (mount && [volume[@"mounted"] boolValue]) continue;
        DADiskRef disk = DADiskCreateFromBSDName(kCFAllocatorDefault, session, [volume[@"device"] UTF8String]);
        if (!disk) return @"The drive disappeared before the operation began.";
        NSDictionary *fresh = CFBridgingRelease(DADiskCopyDescription(disk));
        NSString *uuid = uuidString(fresh[(__bridge id)kDADiskDescriptionVolumeUUIDKey]);
        if (!uuid.length) uuid = apfsVolumes()[volume[@"device"]][@"APFSVolumeUUID"];
        NSURL *path = fresh[(__bridge id)kDADiskDescriptionVolumePathKey];
        if (!externalUSB(fresh) || ![uuid isEqual:volume[@"id"]] || (path && ![path.path hasPrefix:@"/Volumes/"])) {
            CFRelease(disk); return @"The external drive identity changed. Refresh and try again.";
        }
        if (mount) {
            // Mount actual eligible volumes, not the synthetic APFS container.
            NSString *error = operate(session, disk, YES); CFRelease(disk);
            if (error) return error;
        } else {
            DADiskRef whole = DADiskCopyWholeDisk(disk); CFRelease(disk);
            if (!whole) return @"The physical drive is unavailable.";
            NSString *error = operate(session, whole, NO); CFRelease(whole); return error;
        }
    }
    return nil;
}
static NSString *unlockDrive(DASessionRef session, NSString *identifier) {
    NSDictionary *target = nil;
    for (NSDictionary *drive in enumerate(session)) if ([drive[@"id"] isEqual:identifier]) { target = drive; break; }
    if (!target) return @"This external USB drive is disconnected or unavailable.";
    if (![target[@"locked"] boolValue]) { NSString *mounted = change(session, identifier, YES); if (!mounted) return nil; }
    NSDictionary *volume = target[@"volumes"][0];
    for (NSDictionary *candidate in target[@"volumes"]) if ([candidate[@"locked"] boolValue]) { volume = candidate; break; }
    if (![volume[@"filesystem"] isEqual:@"apfs"]) return @"Password unlock currently supports APFS. Unlock this format in Disk Utility first.";
    DADiskRef disk = DADiskCreateFromBSDName(kCFAllocatorDefault, session, [volume[@"device"] UTF8String]);
    if (!disk) return @"The drive disappeared before unlocking.";
    NSDictionary *fresh = CFBridgingRelease(DADiskCopyDescription(disk));
    NSString *uuid = uuidString(fresh[(__bridge id)kDADiskDescriptionVolumeUUIDKey]);
    if (!uuid.length) uuid = apfsVolumes()[volume[@"device"]][@"APFSVolumeUUID"];
    if (!externalUSB(fresh) || ![uuid isEqual:volume[@"id"]]) { CFRelease(disk); return @"The external drive identity changed. Refresh and try again."; }
    NSMutableData *secret = [[[NSFileHandle fileHandleWithStandardInput] readDataToEndOfFile] mutableCopy];
    if (!secret.length || secret.length > 4096) { CFRelease(disk); return @"Enter the volume password."; }
    NSTask *task = [NSTask new]; task.executableURL = [NSURL fileURLWithPath:@"/usr/sbin/diskutil"];
    task.arguments = @[@"apfs", @"unlockVolume", volume[@"device"], @"-stdinpassphrase", @"-nomount"];
    NSPipe *input = [NSPipe pipe]; task.standardInput = input;
    task.standardOutput = [NSFileHandle fileHandleWithNullDevice]; task.standardError = [NSFileHandle fileHandleWithNullDevice];
    if (![task launchAndReturnError:nil]) { CFRelease(disk); return @"The macOS unlock tool could not start."; }
    @try { [input.fileHandleForWriting writeData:secret]; [input.fileHandleForWriting closeFile]; }
    @catch (NSException *exception) { memset(secret.mutableBytes, 0, secret.length); if (task.running) kill(task.processIdentifier, SIGKILL); [task waitUntilExit]; CFRelease(disk); return @"The macOS unlock tool did not accept the request. Try again."; }
    memset(secret.mutableBytes, 0, secret.length);
    double deadline = CFAbsoluteTimeGetCurrent() + 20;
    while (task.running && CFAbsoluteTimeGetCurrent() < deadline) [NSThread sleepForTimeInterval:.05];
    if (task.running) { kill(task.processIdentifier, SIGKILL); [task waitUntilExit]; CFRelease(disk); return @"Unlock timed out. Check the drive and try again."; }
    [task waitUntilExit]; CFRelease(disk);
    if (task.terminationStatus) return @"Could not unlock the drive. Check its password and try again.";
    return change(session, identifier, YES);
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        signal(SIGPIPE, SIG_IGN);
        DASessionRef session = DASessionCreate(kCFAllocatorDefault); if (!session) return 2;
        NSString *error = nil;
        if (argc == 3 && (!strcmp(argv[1], "mount") || !strcmp(argv[1], "unmount") || !strcmp(argv[1], "unlock"))) {
            NSString *identifier = @(argv[2]);
            if (![[NSUUID alloc] initWithUUIDString:identifier]) error = @"A valid volume UUID is required.";
            else error = !strcmp(argv[1], "unlock") ? unlockDrive(session, identifier) : change(session, identifier, !strcmp(argv[1], "mount"));
        } else if (argc != 2 || strcmp(argv[1], "list")) error = @"Only list, mount UUID, unmount UUID, and unlock UUID are supported.";
        NSMutableDictionary *result = [@{@"drives": enumerate(session)} mutableCopy]; if (error) {
            result[@"error"] = error;
            if (argc == 3 && (strcmp(argv[1], "unmount")))
                for (NSDictionary *drive in result[@"drives"])
                    if ([drive[@"id"] isEqual:@(argv[2])] && [drive[@"encrypted"] boolValue] && ![drive[@"mounted"] boolValue]) result[@"requiresPassword"] = @YES;
        }
        NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
        puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String); CFRelease(session);
        return error ? 1 : 0;
    }
}
