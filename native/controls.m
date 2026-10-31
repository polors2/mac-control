#import <Foundation/Foundation.h>
#import <AppKit/AppKit.h>
#import <CoreAudio/CoreAudio.h>
#import <ApplicationServices/ApplicationServices.h>
#import <objc/message.h>
#import <dlfcn.h>
#include <math.h>

// Private brightness APIs are resolved dynamically: unsupported systems fail closed.
static int (*displayGet)(CGDirectDisplayID, float *);
static int (*displaySet)(CGDirectDisplayID, float);
static bool (*displayCan)(CGDirectDisplayID);
static id keyboardClient;
static uint64_t keyboardID;
static BOOL hasKeyboard;

static void loadBrightness(void) {
    void *display = dlopen("/System/Library/PrivateFrameworks/DisplayServices.framework/DisplayServices", RTLD_LAZY);
    if (display) {
        displayGet = dlsym(display, "DisplayServicesGetBrightness");
        displaySet = dlsym(display, "DisplayServicesSetBrightness");
        displayCan = dlsym(display, "DisplayServicesCanChangeBrightness");
    }
    dlopen("/System/Library/PrivateFrameworks/CoreBrightness.framework/CoreBrightness", RTLD_LAZY);
    Class cls = NSClassFromString(@"KeyboardBrightnessClient");
    if (!cls) cls = NSClassFromString(@"CBKeyboardBacklightClient");
    keyboardClient = [[cls alloc] init];
    SEL idsSelector = NSSelectorFromString(@"copyKeyboardBacklightIDs");
    if ([keyboardClient respondsToSelector:idsSelector]) {
        NSArray *ids = ((id (*)(id, SEL))objc_msgSend)(keyboardClient, idsSelector);
        if (ids.count) { keyboardID = [ids[0] unsignedLongLongValue]; hasKeyboard = YES; }
    }
    hasKeyboard = hasKeyboard && [keyboardClient respondsToSelector:NSSelectorFromString(@"brightnessForKeyboard:")] &&
        [keyboardClient respondsToSelector:NSSelectorFromString(@"setBrightness:forKeyboard:")];
}

static CGDirectDisplayID targetDisplay(void) {
    CGDirectDisplayID ids[32]; uint32_t count = 0;
    if (CGGetOnlineDisplayList(32, ids, &count) == kCGErrorSuccess)
        for (uint32_t i = 0; i < count; i++) if (CGDisplayIsBuiltin(ids[i])) return ids[i];
    return CGMainDisplayID();
}

static AudioDeviceID audioDevice(void) {
    AudioDeviceID device = kAudioObjectUnknown; UInt32 size = sizeof(device);
    AudioObjectPropertyAddress prop = {kAudioHardwarePropertyDefaultOutputDevice, kAudioObjectPropertyScopeGlobal, kAudioObjectPropertyElementMain};
    if (AudioObjectGetPropertyData(kAudioObjectSystemObject, &prop, 0, NULL, &size, &device)) return kAudioObjectUnknown;
    return device;
}

static BOOL audioGet(AudioDeviceID device, AudioObjectPropertySelector selector, AudioObjectPropertyElement element, void *value, UInt32 size) {
    AudioObjectPropertyAddress prop = {selector, kAudioDevicePropertyScopeOutput, element};
    return device != kAudioObjectUnknown && AudioObjectHasProperty(device, &prop) && AudioObjectGetPropertyData(device, &prop, 0, NULL, &size, value) == noErr;
}

static BOOL audioWritable(AudioDeviceID device, AudioObjectPropertySelector selector, AudioObjectPropertyElement element) {
    AudioObjectPropertyAddress prop = {selector, kAudioDevicePropertyScopeOutput, element}; Boolean writable = false;
    return device != kAudioObjectUnknown && AudioObjectIsPropertySettable(device, &prop, &writable) == noErr && writable;
}

static BOOL audioSet(AudioDeviceID device, AudioObjectPropertySelector selector, AudioObjectPropertyElement element, void *value, UInt32 size) {
    AudioObjectPropertyAddress prop = {selector, kAudioDevicePropertyScopeOutput, element};
    return audioWritable(device, selector, element) && AudioObjectSetPropertyData(device, &prop, 0, NULL, size, value) == noErr;
}

static NSDictionary *status(void) {
    CGDirectDisplayID display = targetDisplay(); float light = 0;
    BOOL hasDisplay = displayGet && displaySet && (!displayCan || displayCan(display)) && displayGet(display, &light) == 0;
    float keys = hasKeyboard ? ((float (*)(id, SEL, uint64_t))objc_msgSend)(keyboardClient, NSSelectorFromString(@"brightnessForKeyboard:"), keyboardID) : 0;
    BOOL keyboardAvailable = hasKeyboard && isfinite(keys) && keys >= 0 && keys <= 1;
    AudioDeviceID device = audioDevice(); Float32 volume = 0;
    BOOL hasVolume = audioGet(device, kAudioDevicePropertyVolumeScalar, 0, &volume, sizeof(volume)) && audioWritable(device, kAudioDevicePropertyVolumeScalar, 0);
    if (!hasVolume) {
        Float32 left = 0, right = 0;
        hasVolume = audioGet(device, kAudioDevicePropertyVolumeScalar, 1, &left, sizeof(left)) && audioGet(device, kAudioDevicePropertyVolumeScalar, 2, &right, sizeof(right)) && audioWritable(device, kAudioDevicePropertyVolumeScalar, 1) && audioWritable(device, kAudioDevicePropertyVolumeScalar, 2);
        if (hasVolume) volume = (left + right) / 2;
    }
    UInt32 muted = 0;
    BOOL hasMute = audioGet(device, kAudioDevicePropertyMute, 0, &muted, sizeof(muted)) && audioWritable(device, kAudioDevicePropertyMute, 0);
    CFStringRef name = NULL; UInt32 size = sizeof(name);
    AudioObjectPropertyAddress prop = {kAudioObjectPropertyName, kAudioObjectPropertyScopeGlobal, kAudioObjectPropertyElementMain};
    NSString *output = @"Audio output";
    if (device != kAudioObjectUnknown && !AudioObjectGetPropertyData(device, &prop, 0, NULL, &size, &name) && name) output = CFBridgingRelease(name);
    BOOL autoKeys = NO, hasAuto = hasKeyboard && [keyboardClient respondsToSelector:NSSelectorFromString(@"isAutoBrightnessEnabledForKeyboard:")] && [keyboardClient respondsToSelector:NSSelectorFromString(@"enableAutoBrightness:forKeyboard:")];
    if (hasAuto) autoKeys = ((BOOL (*)(id, SEL, uint64_t))objc_msgSend)(keyboardClient, NSSelectorFromString(@"isAutoBrightnessEnabledForKeyboard:"), keyboardID);
    BOOL suppressed = NO;
    if (hasKeyboard && [keyboardClient respondsToSelector:NSSelectorFromString(@"isBacklightSuppressedOnKeyboard:")]) suppressed = ((BOOL (*)(id, SEL, uint64_t))objc_msgSend)(keyboardClient, NSSelectorFromString(@"isBacklightSuppressedOnKeyboard:"), keyboardID);
    return @{@"brightness": hasDisplay ? @(roundf(light * 100)) : (id)[NSNull null],
        @"keyboard": keyboardAvailable ? @(roundf(keys * 100)) : (id)[NSNull null],
        @"volume": hasVolume ? @(roundf(volume * 100)) : (id)[NSNull null], @"muted": @(muted != 0),
        @"keyboardAuto": @(autoKeys), @"keyboardSuppressed": @(suppressed), @"audioOutput": output,
        @"capabilities": @{@"brightness": @(hasDisplay), @"keyboard": @(keyboardAvailable), @"volume": @(hasVolume), @"mute": @(hasMute), @"keyboardAuto": @(hasAuto), @"media": @(AXIsProcessTrusted())}};
}

static NSString *setControl(NSString *control, double value) {
    if (!isfinite(value) || value < 0 || value > 100) return @"Value must be between 0 and 100.";
    if ([control isEqual:@"brightness"]) {
        CGDirectDisplayID display = targetDisplay();
        if (!displaySet || (displayCan && !displayCan(display)) || displaySet(display, value / 100) != 0) return @"This display does not support brightness control.";
    } else if ([control isEqual:@"keyboard"]) {
        if (!hasKeyboard) return @"No supported backlit keyboard was found.";
        ((BOOL (*)(id, SEL, float, uint64_t))objc_msgSend)(keyboardClient, NSSelectorFromString(@"setBrightness:forKeyboard:"), (float)(value / 100), keyboardID);
        usleep(100000);
        float readback = ((float (*)(id, SEL, uint64_t))objc_msgSend)(keyboardClient, NSSelectorFromString(@"brightnessForKeyboard:"), keyboardID);
        if (!isfinite(readback) || fabs(readback - value / 100) > .08) return @"macOS did not apply the keyboard backlight change. Ambient light or automatic brightness may be overriding it.";
    } else if ([control isEqual:@"keyboardAuto"]) {
        SEL sel = NSSelectorFromString(@"enableAutoBrightness:forKeyboard:");
        if (!hasKeyboard || ![keyboardClient respondsToSelector:sel]) return @"Automatic keyboard brightness is unavailable.";
        ((BOOL (*)(id, SEL, BOOL, uint64_t))objc_msgSend)(keyboardClient, sel, value != 0, keyboardID);
    } else if ([control isEqual:@"volume"]) {
        AudioDeviceID device = audioDevice(); Float32 volume = value / 100;
        if (!audioSet(device, kAudioDevicePropertyVolumeScalar, 0, &volume, sizeof(volume))) {
            if (!audioWritable(device, kAudioDevicePropertyVolumeScalar, 1) || !audioWritable(device, kAudioDevicePropertyVolumeScalar, 2)) return @"The current audio output has no software volume control.";
            BOOL left = audioSet(device, kAudioDevicePropertyVolumeScalar, 1, &volume, sizeof(volume));
            BOOL right = audioSet(device, kAudioDevicePropertyVolumeScalar, 2, &volume, sizeof(volume));
            if (!left || !right) return @"Unable to change the output volume.";
        }
    } else if ([control isEqual:@"mute"]) {
        UInt32 muted = value != 0;
        if (!audioSet(audioDevice(), kAudioDevicePropertyMute, 0, &muted, sizeof(muted))) return @"Mute is unavailable for the current audio output.";
    } else return @"Unknown control.";
    return nil;
}

static NSString *media(NSString *action) {
    if (!AXIsProcessTrusted()) return @"Media keys need Accessibility access for the native controls helper. See the setup instructions.";
    NSDictionary *keys = @{@"play": @16, @"next": @17, @"previous": @18};
    NSNumber *key = keys[action]; if (!key) return @"Unknown media key.";
    for (NSNumber *pressed in @[@YES, @NO]) {
        int data = (key.intValue << 16) | ((pressed.boolValue ? 0xA : 0xB) << 8);
        NSEvent *event = [NSEvent otherEventWithType:NSEventTypeSystemDefined location:NSZeroPoint modifierFlags:pressed.boolValue ? 0xA00 : 0xB00 timestamp:0 windowNumber:0 context:nil subtype:8 data1:data data2:-1];
        CGEventRef cg = event.CGEvent; if (!cg) return @"Could not create a media key event.";
        CGEventPost(kCGHIDEventTap, cg);
    }
    return nil;
}

int main(int argc, const char *argv[]) {
    @autoreleasepool {
        @try {
            if (argc == 1 || (argc == 2 && !strcmp(argv[1], "permission"))) {
                [NSApplication sharedApplication];
                [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
                NSDictionary *options = @{(__bridge id)kAXTrustedCheckOptionPrompt: @YES};
                AXIsProcessTrustedWithOptions((__bridge CFDictionaryRef)options);
                [[NSWorkspace sharedWorkspace] openURL:[NSURL URLWithString:@"x-apple.systempreferences:com.apple.preference.security?Privacy_Accessibility"]];
                return 0;
            }
            loadBrightness(); NSString *error = nil;
            if (argc == 4 && !strcmp(argv[1], "set")) {
                char *end = NULL; double value = strtod(argv[3], &end);
                error = (!end || *end) ? @"Invalid numeric value." : setControl(@(argv[2]), value);
            } else if (argc == 3 && !strcmp(argv[1], "media")) error = media(@(argv[2]));
            else if (argc != 2 || strcmp(argv[1], "status")) error = @"Usage: controls status | set CONTROL VALUE | media ACTION";
            NSMutableDictionary *result = [status() mutableCopy];
            if (error) result[@"error"] = error;
            NSData *json = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
            puts([[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding].UTF8String);
            return error ? 1 : 0;
        } @catch (NSException *exception) {
            NSData *json = [NSJSONSerialization dataWithJSONObject:@{@"error": @"The macOS hardware interface is unavailable on this system."} options:0 error:nil];
            puts([[NSString alloc] initWithData:json encoding:NSUTF8StringEncoding].UTF8String); return 1;
        }
    }
}
