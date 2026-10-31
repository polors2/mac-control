// Keep only the built-in display at zero while Display Off is selected.
// No telemetry, keyboard hooks, privileged writes, or display-sleep assertions.
#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#include <dispatch/dispatch.h>
#include <dlfcn.h>
#include <signal.h>
#include <math.h>
#include <unistd.h>

static int (*getBrightness)(CGDirectDisplayID, float *);
static int (*setBrightness)(CGDirectDisplayID, float);
static unsigned failures = 0;

static void keepOff(void) {
    @autoreleasepool {
        CGDirectDisplayID displays[32]; uint32_t count = 0;
        if (CGGetOnlineDisplayList(32, displays, &count) != kCGErrorSuccess) return;
        BOOL attempted = NO, failed = NO;
        for (uint32_t i = 0; i < count; i++) {
            CGDirectDisplayID display = displays[i];
            // Never substitute an external/virtual main display, or wake a sleeping panel.
            if (!CGDisplayIsBuiltin(display) || CGDisplayIsAsleep(display)) continue;
            attempted = YES;
            float current = 0;
            if (getBrightness(display, &current) || !isfinite(current)) { failed = YES; continue; }
            if (current > .001f && setBrightness(display, 0)) failed = YES;
        }
        // Recreate the DisplayServices connection after a persistent graphics-service
        // failure. The normal-user supervisor restarts this child while Off remains set.
        if (attempted) failures = failed ? failures + 1 : 0;
        if (failures >= 3) exit(3);
    }
}
static void displayChanged(CGDirectDisplayID display, CGDisplayChangeSummaryFlags flags, void *context) {
    if (flags & kCGDisplayBeginConfigurationFlag) return;
    dispatch_async(dispatch_get_main_queue(), ^{ keepOff(); });
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC / 2), dispatch_get_main_queue(), ^{ keepOff(); });
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        if (argc != 2 || strcmp(argv[1], "hold-off")) return 2;
        void *library = dlopen("/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices", RTLD_LAZY);
        if (!library) return 3;
        getBrightness = dlsym(library, "DisplayServicesGetBrightness");
        setBrightness = dlsym(library, "DisplayServicesSetBrightness");
        if (!getBrightness || !setBrightness) return 3;
        signal(SIGPIPE, SIG_IGN);
        CGDisplayRegisterReconfigurationCallback(displayChanged, NULL);
        // Closing the parent's pipe releases this guard even if the web server crashes.
        dispatch_source_t input = dispatch_source_create(DISPATCH_SOURCE_TYPE_READ, STDIN_FILENO, 0, dispatch_get_main_queue());
        dispatch_source_set_event_handler(input, ^{
            char buffer[16];
            if (read(STDIN_FILENO, buffer, sizeof(buffer)) <= 0) exit(0);
        });
        dispatch_resume(input);
        // Classic VNC can restore brightness without a display-reconfiguration event.
        // One brightness read every two seconds catches that; writes happen only on drift.
        dispatch_source_t timer = dispatch_source_create(DISPATCH_SOURCE_TYPE_TIMER, 0, 0, dispatch_get_main_queue());
        dispatch_source_set_timer(timer, dispatch_time(DISPATCH_TIME_NOW, 0), 2 * NSEC_PER_SEC, NSEC_PER_MSEC * 200);
        dispatch_source_set_event_handler(timer, ^{ keepOff(); });
        dispatch_resume(timer);
        dispatch_main();
    }
}
