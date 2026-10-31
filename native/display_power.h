// Fixed display-sleep operations. No system sleep or input injection.
#import <IOKit/IOKitLib.h>
#import <IOKit/pwr_mgt/IOPMLib.h>
#import <CoreGraphics/CoreGraphics.h>

static io_registry_entry_t mcDisplayWrangler(void) {
    return IORegistryEntryFromPath(kIOMainPortDefault, kIOServicePlane ":/IOResources/IODisplayWrangler");
}
static BOOL mcCanSleepDisplays(void) {
    io_registry_entry_t entry = mcDisplayWrangler();
    if (!entry) return NO;
    IOObjectRelease(entry); return YES;
}
static id mcDisplayAsleep(void) {
    CGDirectDisplayID ids[32]; uint32_t count = 0;
    if (CGGetOnlineDisplayList(32, ids, &count) != kCGErrorSuccess) return NSNull.null;
    for (uint32_t i = 0; i < count; i++)
        if (CGDisplayIsBuiltin(ids[i])) return @(CGDisplayIsAsleep(ids[i]));
    if (!count) return NSNull.null;
    for (uint32_t i = 0; i < count; i++) if (!CGDisplayIsAsleep(ids[i])) return @NO;
    return @YES;
}
static IOReturn mcSleepDisplays(void) {
    io_registry_entry_t entry = mcDisplayWrangler();
    if (!entry) return kIOReturnUnsupported;
    IOReturn result = IORegistryEntrySetCFProperty(entry, CFSTR("IORequestIdle"), kCFBooleanTrue);
    IOObjectRelease(entry); return result;
}
static IOReturn mcWakeDisplays(void) {
    IOPMAssertionID assertion = kIOPMNullAssertionID;
    IOReturn result = IOPMAssertionDeclareUserActivity(CFSTR("Mac Control display wake"), kIOPMUserActiveLocal, &assertion);
    if (result == kIOReturnSuccess) IOPMAssertionRelease(assertion);
    return result;
}
