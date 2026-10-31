#import "fan_target.h"
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <signal.h>
#include <unistd.h>
#include <poll.h>

#define FAN_SOCKET "/var/run/local.maccontrol.fans.sock"
static volatile sig_atomic_t stopping = 0;
static void stopHelper(int signalNumber) { stopping = 1; }
static void reply(int fd, NSDictionary *result) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
    if (data) { write(fd, data.bytes, data.length); write(fd, "\n", 1); }
}
static NSDictionary *fanStatus(MCTargetController *controller, NSArray *constantTargets) {
    NSMutableDictionary *result = [mcThermals() mutableCopy];
    [result addEntriesFromDictionary:controller.status]; result[@"version"] = @3;
    if (controller.enabled) result[@"fanMode"] = @"target";
    else if (constantTargets && [result[@"fans"] count] == constantTargets.count) {
        BOOL confirmed = [@[@"custom", @"max"] containsObject:result[@"fanMode"]];
        for (NSUInteger i = 0; i < constantTargets.count; i++) {
            id target = result[@"fans"][i][@"target"];
            if (![target isKindOfClass:NSNumber.class] || fabs([target doubleValue] - [constantTargets[i] doubleValue]) > 2) confirmed = NO;
        }
        if (confirmed) { result[@"fanMode"] = @"constant"; result[@"controllerMode"] = @"constant"; result[@"constantTargets"] = constantTargets; }
    }
    return result;
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc == 4 && !strcmp(argv[1], "curve")) {
            double target = strtod(argv[2], NULL), temperature = strtod(argv[3], NULL);
            if (!isfinite(target) || !isfinite(temperature) || target < 50 || target > 85) return 2;
            printf("%.6f\n", mcCurve(temperature - target)); return 0;
        }
        if (argc == 2 && (!strcmp(argv[1], "status") || !strcmp(argv[1], "auto") || !strcmp(argv[1], "max"))) {
            NSString *error = strcmp(argv[1], "status") ? mcFanMode(!strcmp(argv[1], "max")) : nil;
            NSMutableDictionary *status = [mcThermals() mutableCopy]; if (error) status[@"error"] = error;
            NSData *data = [NSJSONSerialization dataWithJSONObject:status options:0 error:nil];
            puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String); return error ? 1 : 0;
        }
        if (argc != 3 || strcmp(argv[1], "serve") || geteuid() != 0) return 2;
        char *end = NULL; unsigned long owner = strtoul(argv[2], &end, 10);
        if (!end || *end || owner < 501 || owner > UINT32_MAX) return 2;
        signal(SIGTERM, stopHelper); signal(SIGINT, stopHelper); signal(SIGPIPE, SIG_IGN);
        mcFanMode(NO); // Always start with Apple management; Max is never persisted across restarts.
        MCTargetController *controller = [MCTargetController new];
        NSArray *constantTargets = nil;
        double nextTick = 0;
        int server = socket(AF_UNIX, SOCK_STREAM, 0); if (server < 0) return 3;
        struct sockaddr_un address = {0}; address.sun_family = AF_UNIX;
        strlcpy(address.sun_path, FAN_SOCKET, sizeof(address.sun_path));
        unlink(FAN_SOCKET); umask(0077);
        if (bind(server, (struct sockaddr *)&address, sizeof(address)) || chown(FAN_SOCKET, (uid_t)owner, -1) || chmod(FAN_SOCKET, 0600) || listen(server, 8)) { close(server); return 3; }
        while (!stopping) {
            double now = NSProcessInfo.processInfo.systemUptime;
            if (controller.enabled && now >= nextTick) { [controller tick]; nextTick = now + 2; }
            struct pollfd ready = {.fd = server, .events = POLLIN};
            int timeoutMS = controller.enabled ? (int)fmax(1, fmin(2000, (nextTick - NSProcessInfo.processInfo.systemUptime) * 1000)) : -1;
            if (poll(&ready, 1, timeoutMS) <= 0) continue;
            int client = accept(server, NULL, NULL); if (client < 0) continue;
            uid_t user = -1; gid_t group = -1;
            struct timeval timeout = {.tv_sec = 2}; setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
            if (getpeereid(client, &user, &group) || (user != owner && user != 0)) { close(client); continue; }
            char buffer[128] = {0}; ssize_t length = read(client, buffer, sizeof(buffer)-1);
            NSString *command = length > 0 ? [[NSString alloc] initWithBytes:buffer length:length encoding:NSUTF8StringEncoding] : @"";
            command = [command stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
            @autoreleasepool {
                if ([command isEqual:@"status"]) reply(client, fanStatus(controller, constantTargets));
                else if ([command isEqual:@"auto"] || [command isEqual:@"max"]) {
                    controller.enabled = NO; controller.lastError = nil;
                    constantTargets = nil;
                    NSString *error = mcFanMode([command isEqual:@"max"]);
                    NSMutableDictionary *result = [fanStatus(controller, constantTargets) mutableCopy];
                    if (error) result[@"error"] = error;
                    reply(client, result);
                } else if ([command hasPrefix:@"constant "]) {
                    NSArray *parts = [command componentsSeparatedByString:@" "];
                    NSMutableArray *targets = [NSMutableArray array]; NSString *error = nil;
                    NSCharacterSet *nonDigits = [[NSCharacterSet characterSetWithCharactersInString:@"0123456789"] invertedSet];
                    for (NSUInteger i = 1; i < parts.count; i++) {
                        NSString *part = parts[i]; NSInteger rpm = part.integerValue;
                        if (!part.length || part.length > 5 || [part rangeOfCharacterFromSet:nonDigits].location != NSNotFound || rpm < 500 || rpm >= 16384) {
                            error = @"Provide a bounded whole-number RPM for every fan."; break;
                        }
                        [targets addObject:@(rpm)];
                    }
                    BOOL attempted = NO;
                    if (!error) error = mcConstantFanSpeeds(targets, &attempted);
                    if (!error) { controller.enabled = NO; controller.lastError = nil; constantTargets = [targets copy]; }
                    else if (attempted) { controller.enabled = NO; controller.lastError = error; constantTargets = nil; }
                    NSMutableDictionary *result = [fanStatus(controller, constantTargets) mutableCopy];
                    if (error) result[@"error"] = error;
                    reply(client, result);
                } else if ([command hasPrefix:@"target "]) {
                    double target = 0; char extra;
                    BOOL valid = sscanf(command.UTF8String, "target %lf %c", &target, &extra) == 1 && isfinite(target) && target >= 50 && target <= 85;
                    NSString *error = nil;
                    if (valid) { constantTargets = nil; error = [controller start:target]; }
                    else error = @"Choose a CPU temperature from 50 to 85°C.";
                    nextTick = NSProcessInfo.processInfo.systemUptime + 2;
                    NSMutableDictionary *result = [fanStatus(controller, constantTargets) mutableCopy];
                    if (error) result[@"error"] = error;
                    reply(client, result);
                } else reply(client, @{@"error": @"Only Auto, Max, bounded Constant RPMs, and a 50–85°C CPU target are supported."});
            }
            close(client);
        }
        mcFanMode(NO); close(server); unlink(FAN_SOCKET); return 0;
    }
}
