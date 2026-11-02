#import <Foundation/Foundation.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <sys/stat.h>
#include <signal.h>
#include <unistd.h>
#include <errno.h>

#ifndef GRAPHICS_SOCKET
#define GRAPHICS_SOCKET "/var/run/local.maccontrol.graphics.sock"
#endif
#ifndef GRAPHICS_PMSET
#define GRAPHICS_PMSET @"/usr/bin/pmset"
#endif
static volatile sig_atomic_t stopping = 0;
static void stopHelper(int number) { stopping = 1; }
static void reply(int fd, NSDictionary *result) {
    NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
    if (data) { write(fd, data.bytes, data.length); write(fd, "\n", 1); }
}
static NSDictionary *perform(NSString *command) {
    if ([command isEqual:@"status"]) return @{@"installed": @YES, @"version": @1};
    NSDictionary *modes = @{@"auto": @"2", @"intel": @"0", @"amd": @"1"};
    NSString *value = modes[command];
    if (!value) return @{@"error": @"Only Auto, Intel, AMD, and status are supported."};
    NSTask *task = [NSTask new];
    task.executableURL = [NSURL fileURLWithPath:GRAPHICS_PMSET];
    task.arguments = @[@"-a", @"gpuswitch", value];
    task.environment = @{@"PATH": @"/usr/bin:/bin:/usr/sbin:/sbin", @"LANG": @"C"};
    task.currentDirectoryURL = [NSURL fileURLWithPath:@"/"];
    task.standardInput = NSFileHandle.fileHandleWithNullDevice;
    task.standardOutput = NSFileHandle.fileHandleWithNullDevice;
    task.standardError = NSFileHandle.fileHandleWithNullDevice;
    NSError *error = nil;
    if (![task launchAndReturnError:&error]) return @{@"error": @"Could not start the macOS graphics command."};
    double deadline = NSProcessInfo.processInfo.systemUptime + 10;
    while (task.running && !stopping && NSProcessInfo.processInfo.systemUptime < deadline) usleep(20000);
    if (task.running) {
        kill(task.processIdentifier, SIGKILL); [task waitUntilExit];
        return @{@"error": @"The macOS graphics command timed out. Check the current mode and try again."};
    }
    [task waitUntilExit];
    if (task.terminationStatus) return @{@"error": @"macOS rejected the graphics change. Check the current mode and try again."};
    return @{@"installed": @YES, @"version": @1, @"applied": command};
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 3 || strcmp(argv[1], "serve") || geteuid() != 0) return 2;
        char *end = NULL; errno = 0;
        unsigned long owner = strtoul(argv[2], &end, 10);
        if (errno || !end || *end || owner < 501 || owner > UINT32_MAX) return 2;
        struct sigaction action = {0}; action.sa_handler = stopHelper;
        sigaction(SIGTERM, &action, NULL); sigaction(SIGINT, &action, NULL); signal(SIGPIPE, SIG_IGN);
        int server = socket(AF_UNIX, SOCK_STREAM, 0); if (server < 0) return 3;
        struct sockaddr_un address = {0}; address.sun_family = AF_UNIX;
        strlcpy(address.sun_path, GRAPHICS_SOCKET, sizeof(address.sun_path));
        unlink(GRAPHICS_SOCKET); umask(0077);
        if (bind(server, (struct sockaddr *)&address, sizeof(address)) || chown(GRAPHICS_SOCKET, (uid_t)owner, -1) ||
            chmod(GRAPHICS_SOCKET, 0600) || listen(server, 8)) { close(server); return 3; }
        // Starting/restarting the helper never changes the user's GPU policy.
        while (!stopping) {
            int client = accept(server, NULL, NULL); if (client < 0) continue;
            uid_t user = -1; gid_t group = -1;
            struct timeval timeout = {.tv_sec = 2};
            setsockopt(client, SOL_SOCKET, SO_RCVTIMEO, &timeout, sizeof(timeout));
            setsockopt(client, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
            if (getpeereid(client, &user, &group) || (user != owner && user != 0)) { close(client); continue; }
            @autoreleasepool {
                char buffer[32] = {0}; size_t used = 0; BOOL complete = NO;
                while (used < sizeof(buffer)-1) {
                    ssize_t length = read(client, buffer + used, sizeof(buffer)-1-used);
                    if (length <= 0) break;
                    used += length;
                    if (memchr(buffer, '\n', used)) { complete = buffer[used-1] == '\n'; break; }
                }
                NSString *command = complete ? [[NSString alloc] initWithBytes:buffer length:used-1 encoding:NSUTF8StringEncoding] : nil;
                reply(client, command ? perform(command) : @{@"error": @"Send one bounded graphics command."});
            }
            close(client);
        }
        close(server); unlink(GRAPHICS_SOCKET); return 0;
    }
}
