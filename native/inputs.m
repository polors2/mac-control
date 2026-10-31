#import <Foundation/Foundation.h>
#import <IOKit/hid/IOHIDLib.h>
#import <IOKit/hidsystem/IOHIDLib.h>
#import <AppKit/AppKit.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <signal.h>
#include <unistd.h>

#define INPUT_SOCKET "/var/run/local.maccontrol.inputs.sock"
static volatile sig_atomic_t stopping = 0;
static void stopHelper(int number) { stopping = 1; }

// Match only Apple's physical internal keyboard/trackpad, never a virtual,
// external USB/Bluetooth device, Touch Bar, or backlight interface.
static NSString *kind(IOHIDDeviceRef device) {
    NSDictionary *properties = @{
        @"product": (__bridge id)IOHIDDeviceGetProperty(device, CFSTR(kIOHIDProductKey)) ?: @"",
        @"transport": (__bridge id)IOHIDDeviceGetProperty(device, CFSTR(kIOHIDTransportKey)) ?: @"",
        @"vendor": (__bridge id)IOHIDDeviceGetProperty(device, CFSTR(kIOHIDVendorIDKey)) ?: @0,
        @"page": (__bridge id)IOHIDDeviceGetProperty(device, CFSTR(kIOHIDPrimaryUsagePageKey)) ?: @0,
        @"usage": (__bridge id)IOHIDDeviceGetProperty(device, CFSTR(kIOHIDPrimaryUsageKey)) ?: @0,
    };
    if ([properties[@"vendor"] intValue] != 1452 ||
        ![properties[@"product"] isEqual:@"Apple Internal Keyboard / Trackpad"] ||
        ![@[@"SPI", @"FIFO"] containsObject:properties[@"transport"]] ||
        [properties[@"page"] intValue] != 1) return nil;
    int usage = [properties[@"usage"] intValue];
    return usage == 6 ? @"keyboard" : usage == 2 ? @"trackpad" : nil;
}
static NSArray *devices(void) {
    NSMutableArray *result = [NSMutableArray array];
    io_iterator_t iterator = IO_OBJECT_NULL;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOHIDDevice"), &iterator)) return result;
    io_service_t service;
    while ((service = IOIteratorNext(iterator))) {
        IOHIDDeviceRef device = IOHIDDeviceCreate(kCFAllocatorDefault, service);
        if (device) { if (kind(device)) [result addObject:CFBridgingRelease(device)]; else CFRelease(device); }
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator); return result;
}
static BOOL alive(IOHIDDeviceRef device) {
    uint64_t entry = 0;
    return IORegistryEntryGetRegistryEntryID(IOHIDDeviceGetService(device), &entry) == KERN_SUCCESS;
}
static void releaseDevices(NSMutableArray *held) {
    for (id object in held) IOHIDDeviceClose((__bridge IOHIDDeviceRef)object, kIOHIDOptionsTypeSeizeDevice);
    [held removeAllObjects];
}
static NSDictionary *status(NSDictionary *held, BOOL installed) {
    NSMutableDictionary *result = [@{@"installed": @(installed), @"version": @2} mutableCopy];
    if (installed) result[@"permissionGranted"] = @((BOOL)(IOHIDCheckAccess(kIOHIDRequestTypeListenEvent) == kIOHIDAccessTypeGranted));
    NSArray *available = devices();
    for (NSString *name in @[@"keyboard", @"trackpad"]) {
        NSMutableArray *seized = held[name];
        for (id object in [seized copy]) if (!alive((__bridge IOHIDDeviceRef)object)) {
            IOHIDDeviceClose((__bridge IOHIDDeviceRef)object, kIOHIDOptionsTypeSeizeDevice); [seized removeObject:object];
        }
        NSUInteger count = 0;
        for (id object in available) if ([kind((__bridge IOHIDDeviceRef)object) isEqual:name]) count++;
        result[name] = @{@"present": @((BOOL)(count > 0)), @"enabled": installed && count ? @((BOOL)(!seized.count)) : NSNull.null,
                         @"controllable": @((BOOL)(installed && count > 0))};
    }
    return result;
}
static NSString *setEnabled(NSString *name, BOOL enabled, NSMutableDictionary *held) {
    NSMutableArray *seized = held[name];
    if (enabled) { releaseDevices(seized); return nil; }
    if (seized.count) return nil;
    for (id object in devices()) {
        IOHIDDeviceRef device = (__bridge IOHIDDeviceRef)object;
        if (![kind(device) isEqual:name]) continue;
        IOReturn code = IOHIDDeviceOpen(device, kIOHIDOptionsTypeSeizeDevice);
        if (code != kIOReturnSuccess) {
            releaseDevices(seized);
            return [NSString stringWithFormat:@"macOS denied exclusive %@ access (0x%08x). Allow Mac Control Inputs.app in Input Monitoring on the host Mac.", name, code];
        }
        [seized addObject:object];
    }
    return seized.count ? nil : @"No supported built-in input device was found. External devices are never disabled.";
}
static void reply(int fd, NSDictionary *result) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
    if (data) { write(fd, data.bytes, data.length); write(fd, "\n", 1); }
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc == 1 || (argc == 2 && !strcmp(argv[1], "permission"))) {
            [NSApplication sharedApplication];
            [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
            IOHIDRequestAccess(kIOHIDRequestTypeListenEvent);
            [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:@"x-apple.systempreferences:com.apple.preference.security?Privacy_ListenEvent"]];
            return 0;
        }
        NSMutableDictionary *held = [@{@"keyboard": [NSMutableArray array], @"trackpad": [NSMutableArray array]} mutableCopy];
        if (argc == 2 && !strcmp(argv[1], "inspect")) {
            NSDictionary *result = status(held, NO);
            NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
            puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String); return 0;
        }
        if (argc != 3 || strcmp(argv[1], "serve") || geteuid() != 0) return 2;
        char *end = NULL; unsigned long owner = strtoul(argv[2], &end, 10);
        if (!end || *end || owner < 501 || owner > UINT32_MAX) return 2;
        struct sigaction action = {0}; action.sa_handler = stopHelper;
        sigaction(SIGTERM, &action, NULL); sigaction(SIGINT, &action, NULL); signal(SIGPIPE, SIG_IGN);
        int server = socket(AF_UNIX, SOCK_STREAM, 0); if (server < 0) return 3;
        struct sockaddr_un address = {0}; address.sun_family = AF_UNIX;
        strlcpy(address.sun_path, INPUT_SOCKET, sizeof(address.sun_path));
        unlink(INPUT_SOCKET); umask(0077);
        if (bind(server, (struct sockaddr *)&address, sizeof(address)) || chown(INPUT_SOCKET, (uid_t)owner, -1) ||
            chmod(INPUT_SOCKET, 0600) || listen(server, 8)) { close(server); return 3; }
        while (!stopping) {
            int client = accept(server, NULL, NULL); if (client < 0) continue;
            uid_t user = -1; gid_t group = -1;
            struct timeval timeout = {.tv_sec = 2}; setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
            if (getpeereid(client, &user, &group) || (user != owner && user != 0)) { close(client); continue; }
            char buffer[64] = {0}; ssize_t length = read(client, buffer, sizeof(buffer)-1);
            NSString *command = length > 0 ? [[NSString alloc] initWithBytes:buffer length:length encoding:NSUTF8StringEncoding] : @"";
            command = [command stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
            @autoreleasepool {
                NSString *error = nil;
                if ([command isEqual:@"restart"]) { for (NSString *name in held) releaseDevices(held[name]); stopping = 1; }
                else if ([command isEqual:@"enable-all"]) for (NSString *name in held) releaseDevices(held[name]);
                else if (![command isEqual:@"status"]) {
                    NSArray *parts = [command componentsSeparatedByString:@" "];
                    if (parts.count == 2 && held[parts[0]] && [@[@"on", @"off"] containsObject:parts[1]])
                        error = setEnabled(parts[0], [parts[1] isEqual:@"on"], held);
                    else error = @"Only status, restart, enable-all, keyboard on/off, and trackpad on/off are supported.";
                }
                NSMutableDictionary *result = [status(held, YES) mutableCopy];
                if (error) result[@"error"] = error;
                reply(client, result);
            }
            close(client);
        }
        for (NSString *name in held) releaseDevices(held[name]);
        close(server); unlink(INPUT_SOCKET); return 0;
    }
}
