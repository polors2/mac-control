// AppleSMC ABI and sensor key references: exelban/Stats (MIT; see THIRD_PARTY_NOTICES.md).
#pragma once
#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#include <math.h>

typedef struct { uint8_t major, minor, build, reserved; uint16_t release; } MCVersion;
typedef struct { uint16_t version, length; uint32_t cpu, gpu, memory; } MCLimits;
typedef struct { uint32_t size, type; uint8_t attributes; } MCKeyInfo;
typedef struct {
    uint32_t key; MCVersion version; MCLimits limits; MCKeyInfo info;
    uint8_t result, status, command; uint32_t index; uint8_t bytes[32];
} MCPacket;
_Static_assert(sizeof(MCPacket) == 80, "AppleSMC packet ABI mismatch");
typedef struct { MCKeyInfo info; uint8_t bytes[32]; } MCValue;

static uint32_t mcKey(const char *key) {
    return (uint32_t)(uint8_t)key[0]<<24 | (uint32_t)(uint8_t)key[1]<<16 | (uint32_t)(uint8_t)key[2]<<8 | (uint8_t)key[3];
}
static io_connect_t mcOpen(void) {
    io_service_t service = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("AppleSMC"));
    if (!service) return 0;
    io_connect_t connection = 0;
    kern_return_t result = IOServiceOpen(service, mach_task_self(), 0, &connection);
    IOObjectRelease(service);
    return result == KERN_SUCCESS ? connection : 0;
}
static BOOL mcCall(io_connect_t connection, MCPacket *input, MCPacket *output) {
    size_t size = sizeof(*output);
    return connection && IOConnectCallStructMethod(connection, 2, input, sizeof(*input), output, &size) == KERN_SUCCESS && output->result == 0;
}
static BOOL mcRead(io_connect_t connection, const char *key, MCValue *value) {
    MCPacket input = {0}, output = {0}; input.key = mcKey(key); input.command = 9;
    if (!mcCall(connection, &input, &output) || !output.info.size || output.info.size > 32) return NO;
    value->info = output.info; input.info = output.info; input.command = 5;
    memset(&output, 0, sizeof(output));
    if (!mcCall(connection, &input, &output)) return NO;
    memcpy(value->bytes, output.bytes, value->info.size); return YES;
}
static double mcNumber(MCValue value) {
    uint32_t type = value.info.type;
    if (type == mcKey("sp78") && value.info.size == 2) return (int16_t)((value.bytes[0]<<8)|value.bytes[1]) / 256.0;
    if (type == mcKey("fpe2") && value.info.size == 2) return ((value.bytes[0]<<8)|value.bytes[1]) / 4.0;
    if (type == mcKey("ui8 ") && value.info.size == 1) return value.bytes[0];
    if (type == mcKey("ui16") && value.info.size == 2) return (value.bytes[0]<<8)|value.bytes[1];
    if (type == mcKey("ui32") && value.info.size == 4) return (uint32_t)value.bytes[0]<<24 | (uint32_t)value.bytes[1]<<16 | (uint32_t)value.bytes[2]<<8 | value.bytes[3];
    if (type == mcKey("flt ") && value.info.size == 4) { float number; memcpy(&number, value.bytes, 4); return number; }
    return NAN;
}
static double mcGet(io_connect_t connection, const char *key) {
    MCValue value = {0}; return mcRead(connection, key, &value) ? mcNumber(value) : NAN;
}
static BOOL mcWrite(io_connect_t connection, const char *key, MCValue value) {
    MCPacket input = {0}, output = {0}; input.key = mcKey(key); input.command = 6; input.info = value.info;
    memcpy(input.bytes, value.bytes, value.info.size); return mcCall(connection, &input, &output);
}
static BOOL mcSet(io_connect_t connection, const char *key, double number) {
    MCValue value = {0};
    if (!isfinite(number) || !mcRead(connection, key, &value)) return NO;
    memset(value.bytes, 0, 32);
    if (value.info.type == mcKey("fpe2") && number >= 0 && number < 16384) {
        uint16_t encoded = (uint16_t)round(number * 4); value.bytes[0] = encoded >> 8; value.bytes[1] = encoded & 255;
    } else if (value.info.type == mcKey("flt ")) { float encoded = number; memcpy(value.bytes, &encoded, 4); }
    else if (value.info.type == mcKey("ui8 ") && number >= 0 && number <= 255) value.bytes[0] = (uint8_t)number;
    else if (value.info.type == mcKey("ui16") && number >= 0 && number <= 65535) {
        uint16_t encoded = number; value.bytes[0] = encoded >> 8; value.bytes[1] = encoded & 255;
    } else return NO;
    return mcWrite(connection, key, value);
}
static id mcTemperature(io_connect_t connection, NSArray *keys, NSString *label) {
    for (NSString *key in keys) {
        double value = mcGet(connection, key.UTF8String);
        if (isfinite(value) && value > 0 && value < 130)
            return @{@"celsius": @(round(value * 10) / 10), @"key": key, @"label": label};
    }
    return NSNull.null;
}
static NSDictionary *mcThermals(void) {
    io_connect_t connection = mcOpen();
    if (!connection) return @{@"cpuTemperature": NSNull.null, @"gpuTemperature": NSNull.null, @"fans": @[], @"fanMode": @"unavailable"};
    id cpu = mcTemperature(connection, @[@"TC0D", @"TC0E", @"TC0F"], @"CPU die");
    if (cpu == NSNull.null) cpu = mcTemperature(connection, @[@"TC0P"], @"CPU proximity");
    id gpu = mcTemperature(connection, @[@"TCGC"], @"Intel GPU");
    id intel = gpu;
    id amd = mcTemperature(connection, @[@"TG0D"], @"AMD GPU diode");
    if (amd == NSNull.null) amd = mcTemperature(connection, @[@"TG0P"], @"AMD GPU proximity");
    if (gpu == NSNull.null) gpu = mcTemperature(connection, @[@"TG0D"], @"Discrete GPU diode");
    if (gpu == NSNull.null) gpu = mcTemperature(connection, @[@"TG0P"], @"GPU proximity");
    double countValue = mcGet(connection, "FNum"); int count = isfinite(countValue) ? (int)countValue : 0;
    NSMutableArray *fans = NSMutableArray.array; BOOL allAuto = YES, allMax = YES;
    double forced = mcGet(connection, "FS! ");
    for (int i = 0; i < MIN(count, 10); i++) {
        NSString *(^key)(NSString *) = ^NSString *(NSString *suffix) { return [NSString stringWithFormat:@"F%d%@", i, suffix]; };
        double rpm = mcGet(connection, key(@"Ac").UTF8String), maximum = mcGet(connection, key(@"Mx").UTF8String);
        double minimum = mcGet(connection, key(@"Mn").UTF8String);
        double target = mcGet(connection, key(@"Tg").UTF8String), mode = mcGet(connection, key(@"Md").UTF8String);
        BOOL known = isfinite(mode) || isfinite(forced);
        BOOL manual = (isfinite(mode) && (int)mode == 1) || (isfinite(forced) && ((uint16_t)forced & (1u<<i)));
        allAuto = allAuto && known && !manual;
        allMax = allMax && manual && isfinite(target) && isfinite(maximum) && target >= maximum - 50;
        [fans addObject:@{@"id": @(i), @"name": [NSString stringWithFormat:@"Fan %d", i+1],
            @"rpm": isfinite(rpm) ? @(round(rpm)) : (id)NSNull.null,
            @"minimum": isfinite(minimum) ? @(round(minimum)) : (id)NSNull.null,
            @"maximum": isfinite(maximum) ? @(round(maximum)) : (id)NSNull.null,
            @"target": isfinite(target) ? @(round(target)) : (id)NSNull.null}];
    }
    IOServiceClose(connection);
    return @{@"cpuTemperature": cpu, @"gpuTemperature": gpu, @"intelTemperature": intel, @"amdTemperature": amd, @"fans": fans,
             @"fanMode": !fans.count ? @"unavailable" : allAuto ? @"auto" : allMax ? @"max" : @"custom"};
}

// Auto/Max write only the known fan mode/target keys. Constant mode below also
// validates each target against that fan's firmware minimum and maximum.
static NSString *mcFanMode(BOOL maximum) {
    io_connect_t connection = mcOpen();
    if (!connection) return @"AppleSMC is unavailable.";
    double n = mcGet(connection, "FNum");
    if (!isfinite(n) || n < 1 || n > 10) { IOServiceClose(connection); return @"No supported fans were found."; }
    int count = (int)n; BOOL ok = YES;
    // Resolve and validate every maximum before attempting any write.
    double maxima[10] = {0};
    for (int i = 0; i < count; i++) {
        NSString *key = [NSString stringWithFormat:@"F%dMx", i]; maxima[i] = mcGet(connection, key.UTF8String);
        if (maximum && (!isfinite(maxima[i]) || maxima[i] < 500 || maxima[i] >= 16384)) ok = NO;
    }
    // Set per-fan mode where present, plus the Intel forced-mode bitmask.
    if (ok || !maximum) {
        for (int i = 0; i < count; i++) {
            NSString *mode = [NSString stringWithFormat:@"F%dMd", i]; MCValue value = {0};
            if (mcRead(connection, mode.UTF8String, &value) && !mcSet(connection, mode.UTF8String, maximum ? 1 : 0)) ok = NO;
        }
        double forced = mcGet(connection, "FS! ");
        if (isfinite(forced)) {
            uint16_t mask = (uint16_t)((1u<<count)-1), bits = (uint16_t)forced;
            if (!mcSet(connection, "FS! ", maximum ? bits | mask : bits & ~mask)) ok = NO;
        }
    }
    if (ok && maximum) {
        for (int i = 0; i < count; i++) {
            NSString *target = [NSString stringWithFormat:@"F%dTg", i];
            if (!mcSet(connection, target.UTF8String, maxima[i])) { ok = NO; break; }
        }
    }
    IOServiceClose(connection);
    if (ok) {
        NSString *actual = mcThermals()[@"fanMode"];
        if (![actual isEqual:maximum ? @"max" : @"auto"]) ok = NO;
    }
    if (!ok && maximum) mcFanMode(NO); // Roll back partial overrides to Apple management.
    return ok ? nil : @"macOS denied the fan write. Install the administrator fan helper on this Mac.";
}
