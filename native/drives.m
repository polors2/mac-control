#import <Foundation/Foundation.h>
#import <DiskArbitration/DiskArbitration.h>
#import <IOKit/IOKitLib.h>
#include <time.h>
#include <sys/mount.h>

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
static NSArray *enumerate(DASessionRef session) {
    NSMutableDictionary *groups = NSMutableDictionary.dictionary;
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
                    NSString *uuid = uuidString(description[(__bridge id)kDADiskDescriptionVolumeUUIDKey]);
                    NSURL *path = description[(__bridge id)kDADiskDescriptionVolumePathKey];
                    if (path && ![path.path hasPrefix:@"/Volumes/"]) group[@"protected"] = @YES;
                    NSString *kind = description[(__bridge id)kDADiskDescriptionVolumeKindKey];
                    NSString *content = [description[(__bridge id)kDADiskDescriptionMediaContentKey] uppercaseString];
                    BOOL efi = [content isEqual:@"EFI"] || [content isEqual:@"C12A7328-F81F-11D2-BA4B-00A0C93EC93B"];
                    // Empty partition-map and EFI nodes do not become user controls.
                    if (uuid.length && kind.length && !efi) {
                        [group[@"volumes"] addObject:@{@"id": uuid, @"name": description[(__bridge id)kDADiskDescriptionVolumeNameKey] ?: @"USB volume",
                            @"device": @(DADiskGetBSDName(disk)), @"mounted": @(path != nil),
                            @"mountPoint": path.path ?: @"", @"filesystem": kind,
                            @"readOnly": readOnly(@(DADiskGetBSDName(disk)))}];
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
        group[@"mounted"] = @(mounted > 0);
        group[@"state"] = mounted == 0 ? @"unmounted" : mounted == volumes.count ? @"mounted" : @"partial";
        group[@"connected"] = @YES;
        [group removeObjectForKey:@"protected"]; [result addObject:group];
    }
    return [result sortedArrayUsingComparator:^NSComparisonResult(NSDictionary *a, NSDictionary *b) { return [a[@"name"] compare:b[@"name"]]; }];
}

typedef struct { BOOL done; DAReturn result; } Operation;
static void finished(DADiskRef disk, DADissenterRef dissenter, void *context) {
    Operation *operation = context; operation->result = dissenter ? DADissenterGetStatus(dissenter) : 0; operation->done = YES;
}
static NSString *change(DASessionRef session, NSString *identifier, BOOL mount) {
    NSArray *drives = enumerate(session); NSDictionary *target = nil;
    for (NSDictionary *drive in drives) if ([drive[@"id"] isEqual:identifier]) { target = drive; break; }
    if (!target) return @"This external USB drive is disconnected or is not eligible for this control.";
    NSDictionary *volume = target[@"volumes"][0];
    DADiskRef disk = DADiskCreateFromBSDName(kCFAllocatorDefault, session, [volume[@"device"] UTF8String]);
    if (!disk) return @"The drive disappeared before the operation began.";
    NSDictionary *fresh = CFBridgingRelease(DADiskCopyDescription(disk));
    if (!externalUSB(fresh) || ![uuidString(fresh[(__bridge id)kDADiskDescriptionVolumeUUIDKey]) isEqual:identifier]) {
        CFRelease(disk); return @"The drive identity changed. Refresh and try again.";
    }
    DADiskRef whole = DADiskCopyWholeDisk(disk); CFRelease(disk);
    if (!whole) return @"The physical drive is unavailable.";
    Operation operation = {0};
    DASessionScheduleWithRunLoop(session, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode);
    if (mount) DADiskMount(whole, NULL, kDADiskMountOptionWhole, finished, &operation);
    else DADiskUnmount(whole, kDADiskUnmountOptionWhole, finished, &operation); // Never force.
    double deadline = CFAbsoluteTimeGetCurrent() + 18;
    while (!operation.done && CFAbsoluteTimeGetCurrent() < deadline) CFRunLoopRunInMode(kCFRunLoopDefaultMode, .05, true);
    DASessionUnscheduleFromRunLoop(session, CFRunLoopGetCurrent(), kCFRunLoopDefaultMode); CFRelease(whole);
    if (!operation.done) return @"The drive operation is taking longer than expected. Check the updated mount state before retrying.";
    if (operation.result) {
        if (operation.result == kDAReturnBusy) return @"The drive is in use. Close files, copies, or apps using it, then try again. Nothing was force-unmounted.";
        if (operation.result == kDAReturnNotPermitted || operation.result == kDAReturnNotPrivileged) return @"macOS did not permit this mount operation for the current user.";
        return [NSString stringWithFormat:@"macOS could not %@ the drive (Disk Arbitration error 0x%x).", mount ? @"mount" : @"unmount", operation.result];
    }
    return nil;
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        DASessionRef session = DASessionCreate(kCFAllocatorDefault); if (!session) return 2;
        NSString *error = nil;
        if (argc == 3 && (!strcmp(argv[1], "mount") || !strcmp(argv[1], "unmount"))) {
            NSString *identifier = @(argv[2]);
            if (![[NSUUID alloc] initWithUUIDString:identifier]) error = @"A valid volume UUID is required.";
            else error = change(session, identifier, !strcmp(argv[1], "mount"));
        } else if (argc != 2 || strcmp(argv[1], "list")) error = @"Only list, mount UUID, and unmount UUID are supported.";
        NSMutableDictionary *result = [@{@"drives": enumerate(session)} mutableCopy]; if (error) result[@"error"] = error;
        NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
        puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String); CFRelease(session);
        return error ? 1 : 0;
    }
}
