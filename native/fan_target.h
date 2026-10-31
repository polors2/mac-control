#pragma once
#import "smc.h"

static BOOL mcRPMWithinBounds(double rpm, double minimum, double maximum) {
    return isfinite(rpm) && isfinite(minimum) && isfinite(maximum) && minimum >= 500 &&
           maximum >= minimum && maximum < 16384 && rpm >= ceil(minimum) && rpm <= floor(maximum);
}
static NSString *mcConstantFanSpeeds(NSArray<NSNumber *> *targets, BOOL *attempted) {
    *attempted = NO;
    io_connect_t connection = mcOpen(); if (!connection) return @"AppleSMC is unavailable.";
    double n = mcGet(connection, "FNum");
    if (!isfinite(n) || n < 1 || n > 10 || targets.count != (NSUInteger)n) {
        IOServiceClose(connection); return @"Provide one RPM target for every detected fan.";
    }
    int count = (int)n;
    for (int i = 0; i < count; i++) {
        double minimum = mcGet(connection, [NSString stringWithFormat:@"F%dMn", i].UTF8String);
        double maximum = mcGet(connection, [NSString stringWithFormat:@"F%dMx", i].UTF8String);
        if (!mcRPMWithinBounds(targets[i].doubleValue, minimum, maximum)) {
            IOServiceClose(connection); return @"Each fan speed must be within its firmware minimum and maximum RPM.";
        }
    }
    *attempted = YES; BOOL ok = YES;
    for (int i = 0; i < count; i++) {
        NSString *mode = [NSString stringWithFormat:@"F%dMd", i]; MCValue value = {0};
        if (mcRead(connection, mode.UTF8String, &value) && !mcSet(connection, mode.UTF8String, 1)) ok = NO;
    }
    double forced = mcGet(connection, "FS! ");
    if (isfinite(forced)) {
        uint16_t mask = (uint16_t)((1u<<count)-1), bits = (uint16_t)forced;
        if (!mcSet(connection, "FS! ", bits | mask)) ok = NO;
    }
    if (ok) for (int i = 0; i < count; i++) {
        if (!mcSet(connection, [NSString stringWithFormat:@"F%dTg", i].UTF8String, targets[i].doubleValue)) { ok = NO; break; }
    }
    // Confirm every target and the manual override before reporting success.
    if (ok) for (int i = 0; i < count; i++) {
        double actual = mcGet(connection, [NSString stringWithFormat:@"F%dTg", i].UTF8String);
        double mode = mcGet(connection, [NSString stringWithFormat:@"F%dMd", i].UTF8String);
        double bits = mcGet(connection, "FS! ");
        BOOL manual = (isfinite(mode) && (int)mode == 1) || (isfinite(bits) && ((uint16_t)bits & (1u<<i)));
        if (!manual || !isfinite(actual) || fabs(actual - targets[i].doubleValue) > 2) { ok = NO; break; }
    }
    IOServiceClose(connection);
    if (!ok) { mcFanMode(NO); return @"Constant fan targets could not be confirmed. Returned management to Apple."; }
    return nil;
}

// Conservative feed-forward curve, shifted by the user's desired CPU temperature.
// The adaptive term slowly backs off/increases cooling to account for actual heat load.
static double mcCurve(double delta) {
    const double temperatures[] = {-15, -10, -5, 0, 3, 6};
    const double speeds[] = {0, .15, .35, .60, .85, 1};
    if (delta <= temperatures[0]) return speeds[0];
    for (int i = 1; i < 6; i++) if (delta <= temperatures[i]) {
        double fraction = (delta - temperatures[i-1]) / (temperatures[i] - temperatures[i-1]);
        return speeds[i-1] + fraction * (speeds[i] - speeds[i-1]);
    }
    return 1;
}
static NSString *mcFanDemand(double fraction) {
    if (!isfinite(fraction) || fraction < 0 || fraction > 1) return @"Invalid cooling demand.";
    io_connect_t connection = mcOpen(); if (!connection) return @"AppleSMC is unavailable.";
    double countValue = mcGet(connection, "FNum"); int count = isfinite(countValue) ? (int)countValue : 0;
    if (count < 1 || count > 10) { IOServiceClose(connection); return @"No supported fans were found."; }
    BOOL ok = YES; double targets[10] = {0};
    for (int i = 0; i < count; i++) {
        double minimum = mcGet(connection, [NSString stringWithFormat:@"F%dMn", i].UTF8String);
        double maximum = mcGet(connection, [NSString stringWithFormat:@"F%dMx", i].UTF8String);
        if (!isfinite(minimum) || !isfinite(maximum) || minimum < 500 || maximum < minimum || maximum >= 16384) { ok = NO; break; }
        targets[i] = round(minimum + fraction * (maximum - minimum));
    }
    if (ok) {
        for (int i = 0; i < count; i++) {
            NSString *mode = [NSString stringWithFormat:@"F%dMd", i]; MCValue value = {0};
            if (mcRead(connection, mode.UTF8String, &value) && mcNumber(value) != 1 && !mcSet(connection, mode.UTF8String, 1)) ok = NO;
        }
        double forced = mcGet(connection, "FS! ");
        if (isfinite(forced)) {
            uint16_t mask = (uint16_t)((1u<<count)-1), bits = (uint16_t)forced;
            if ((bits & mask) != mask && !mcSet(connection, "FS! ", bits | mask)) ok = NO;
        }
        if (ok) for (int i = 0; i < count; i++) {
            NSString *key = [NSString stringWithFormat:@"F%dTg", i]; double current = mcGet(connection, key.UTF8String);
            if (!isfinite(current) || fabs(current - targets[i]) >= 60) if (!mcSet(connection, key.UTF8String, targets[i])) ok = NO;
        }
    }
    IOServiceClose(connection);
    if (!ok) { mcFanMode(NO); return @"The fan curve could not be applied. Returned fan management to Apple."; }
    return nil;
}

@interface MCTargetController : NSObject
@property BOOL enabled;
@property double target;
@property double integral;
@property double demand;
@property double temperature;
@property double lastWrite;
@property BOOL safetyOverride;
@property(nonatomic, copy) NSString *lastError;
- (NSString *)start:(double)target;
- (void)tick;
- (NSDictionary *)status;
@end
@implementation MCTargetController
- (NSString *)start:(double)target {
    if (!isfinite(target) || target < 50 || target > 85) return @"Choose a CPU temperature from 50 to 85°C.";
    self.target = target; self.integral = 0; self.demand = 1; self.lastWrite = 0;
    self.lastError = nil; self.enabled = YES; self.temperature = NAN;
    [self tick]; return self.lastError;
}
- (void)tick {
    if (!self.enabled) return;
    io_connect_t connection = mcOpen();
    id sensor = connection ? mcTemperature(connection, @[@"TC0D", @"TC0E", @"TC0F"], @"CPU die") : NSNull.null;
    if (connection) IOServiceClose(connection);
    if (![sensor isKindOfClass:NSDictionary.class]) {
        mcFanMode(NO); self.enabled = NO; self.lastError = @"CPU temperature unavailable. Returned fan management to Apple."; return;
    }
    self.temperature = [sensor[@"celsius"] doubleValue];
    double error = self.temperature - self.target;
    self.safetyOverride = self.temperature >= 90 || error >= 6;
    self.integral = fmax(-.35, fmin(.25, self.integral + error * .003));
    double desired = self.safetyOverride ? 1 : fmax(0, fmin(1, mcCurve(error) + self.integral));
    // Fast increases, gentle decreases, and no repeated writes for tiny variations.
    double next = self.safetyOverride ? 1 : fmax(self.demand - .05, fmin(self.demand + .25, desired));
    double now = [NSDate.date timeIntervalSince1970];
    if (fabs(next - self.demand) >= .015 || now - self.lastWrite >= 10 || self.lastWrite == 0) {
        NSString *errorMessage = mcFanDemand(next);
        if (errorMessage) { self.enabled = NO; self.lastError = errorMessage; return; }
        self.lastWrite = now;
    }
    self.demand = next;
}
- (NSDictionary *)status {
    NSMutableDictionary *result = [@{@"installed": @YES, @"version": @2, @"controllerMode": self.enabled ? @"target" : @"manual-or-auto",
        @"targetTemperature": @(self.target ?: 70), @"coolingDemand": @(self.demand), @"safetyOverride": @(self.safetyOverride)} mutableCopy];
    if (isfinite(self.temperature) && self.temperature > 0) result[@"cpuTemperature"] = @(self.temperature);
    if (self.lastError) result[@"controllerError"] = self.lastError;
    return result;
}
@end
