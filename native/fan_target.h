#pragma once
#import "smc.h"
#include "fan_learning.h"
#include <mach/mach.h>
#include <mach/host_info.h>
#include <sys/stat.h>
#include <unistd.h>

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

// Fixed, root-private learning log. No dashboard credentials or activity data.
#ifndef MC_FAN_HISTORY_DIR
#define MC_FAN_HISTORY_DIR @"/var/db/local.maccontrol"
#endif
#define MC_FAN_HISTORY_PATH MC_FAN_HISTORY_DIR @"/fan-learning.json"
@interface MCTargetController : NSObject {
    MCFanModel model;
    uint32_t cpuTicks[CPU_STATE_MAX];
    BOOL haveTicks;
}
@property BOOL enabled;
@property double target;
@property double temperature;
@property double lastWrite;
@property double writtenDemand;
@property BOOL learningAvailable;
@property BOOL learningDirty;
@property(nonatomic, strong) NSMutableArray *history;
@property(nonatomic, copy) NSString *lastError;
@property(nonatomic, copy) NSString *learningError;
- (NSString *)start:(double)target;
- (void)tick;
- (void)saveLearning;
- (void)saveLearningAtTime:(double)now;
- (NSDictionary *)status;
@end
@implementation MCTargetController
- (instancetype)init {
    if ((self = [super init])) {
        mcModelInit(&model); self.history = NSMutableArray.array;
        self.temperature = NAN;
        // Reject unexpected ownership/types before reading or writing this log.
        struct stat directory;
        if (lstat(MC_FAN_HISTORY_DIR.fileSystemRepresentation, &directory) != 0) {
            [NSFileManager.defaultManager createDirectoryAtPath:MC_FAN_HISTORY_DIR withIntermediateDirectories:NO
                attributes:@{NSFilePosixPermissions: @0700} error:nil];
        }
        if (lstat(MC_FAN_HISTORY_DIR.fileSystemRepresentation, &directory) != 0 || !S_ISDIR(directory.st_mode) ||
            directory.st_uid != geteuid() || (directory.st_mode & 0077)) {
            self.learningError = @"Learning log unavailable; using session learning.";
            return self;
        }
        self.learningAvailable = YES;
        NSData *data = [NSData dataWithContentsOfFile:MC_FAN_HISTORY_PATH];
        NSDictionary *saved = data ? [NSJSONSerialization JSONObjectWithData:data options:0 error:nil] : nil;
        BOOL dictionary = [saved isKindOfClass:NSDictionary.class];
        BOOL checkpointed = dictionary && [saved[@"version"] isEqual:@2] && mcRestoreLearning(&model, saved[@"model"]);
        // Version 1 logs have no checkpoint. Learn from ALL usable rows before
        // retention runs, including expired rows, then checkpoint that learning.
        // Version 2 rows are already included in its model: never replay twice.
        self.learningDirty = data && !checkpointed;
        if (dictionary && [@[@1, @2] containsObject:saved[@"version"]] &&
            [saved[@"samples"] isKindOfClass:NSArray.class] && [saved[@"samples"] count] <= 300) {
            double previous = 0;
            for (id row in saved[@"samples"]) {
                if (!mcLearningRow(row) || [row[0] doubleValue] <= previous) { self.learningDirty = YES; continue; }
                double time = [row[0] doubleValue];
                if (!checkpointed) mcModelStep(&model, time, [row[1] doubleValue], [row[2] doubleValue], [row[3] doubleValue], 70);
                [self.history addObject:row]; previous = time;
            }
        } else if (data) self.learningDirty = YES;
        model.previous = false; model.demand = 1;
        [self saveLearning]; // Migration and startup expiry are atomic with the model.
    }
    return self;
}
- (void)saveLearning { [self saveLearningAtTime:NSDate.date.timeIntervalSince1970]; }
- (void)saveLearningAtTime:(double)now {
    if (!self.learningAvailable || !isfinite(now)) return;
    NSMutableArray *retained = NSMutableArray.array;
    for (NSArray *row in self.history) if ([row[0] doubleValue] >= now-86400) [retained addObject:row];
    if (retained.count != self.history.count) self.learningDirty = YES;
    if (!self.learningDirty) return;
    // One atomic replacement commits the already-learned statistics and removes
    // expired raw rows together. On failure, keep the old log and retry later.
    NSData *data = [NSJSONSerialization dataWithJSONObject:@{@"version": @2, @"model": mcLearningCheckpoint(&model), @"samples": retained} options:0 error:nil];
    if (!mcWriteLearning(MC_FAN_HISTORY_PATH, data)) {
        self.learningError = @"Learning log could not be saved; using session learning.";
        return;
    }
    self.history = retained; self.learningDirty = NO; self.learningError = nil;
}
- (NSString *)start:(double)target {
    if (!isfinite(target) || target < 50 || target > 85) return @"Choose a CPU temperature from 50 to 85°C.";
    self.target = target; self.lastWrite = 0; model.previous = false; model.demand = 1; haveTicks = NO;
    self.lastError = nil; self.enabled = YES; self.temperature = NAN;
    [self tick]; return self.lastError;
}
- (void)tick {
    if (!self.enabled) return;
    io_connect_t connection = mcOpen();
    id sensor = connection ? mcTemperature(connection, @[@"TC0D", @"TC0E", @"TC0F"], @"CPU die") : NSNull.null;
    double countValue = connection ? mcGet(connection, "FNum") : NAN;
    double actualFan = 0;
    BOOL fanValid = isfinite(countValue) && countValue >= 1 && countValue <= 10 && floor(countValue) == countValue;
    for (int i = 0; fanValid && i < (int)countValue; i++) {
        double rpm = mcGet(connection, [NSString stringWithFormat:@"F%dAc", i].UTF8String);
        double minimum = mcGet(connection, [NSString stringWithFormat:@"F%dMn", i].UTF8String);
        double maximum = mcGet(connection, [NSString stringWithFormat:@"F%dMx", i].UTF8String);
        fanValid = isfinite(rpm) && isfinite(minimum) && isfinite(maximum) && rpm >= 0 && minimum >= 500 && maximum > minimum && maximum < 16384;
        if (fanValid) actualFan += mcClamp((rpm-minimum)/(maximum-minimum), 0, 1)/countValue;
    }
    if (connection) IOServiceClose(connection);
    if (![sensor isKindOfClass:NSDictionary.class] || !fanValid) {
        mcFanMode(NO); self.enabled = NO;
        self.lastError = @"CPU temperature or fan feedback unavailable. Returned fan management to Apple."; return;
    }
    self.temperature = [sensor[@"celsius"] doubleValue];
    host_cpu_load_info_data_t info;
    mach_msg_type_number_t count = HOST_CPU_LOAD_INFO_COUNT;
    mach_port_t host = mach_host_self();
    kern_return_t result = host_statistics(host, HOST_CPU_LOAD_INFO, (host_info_t)&info, &count);
    mach_port_deallocate(mach_task_self(), host);
    double load = 1; // Conservative until two valid load samples are available.
    if (result == KERN_SUCCESS) {
        uint64_t total = 0, idle = 0;
        if (haveTicks) for (int i = 0; i < CPU_STATE_MAX; i++) {
            uint32_t delta = info.cpu_ticks[i] - cpuTicks[i]; total += delta;
            if (i == CPU_STATE_IDLE) idle = delta;
        }
        if (total) load = 1 - (double)idle/total;
        memcpy(cpuTicks, info.cpu_ticks, sizeof(cpuTicks)); haveTicks = YES;
    } else haveTicks = NO;
    double now = NSProcessInfo.processInfo.systemUptime;
    if (!mcModelStep(&model, now, self.temperature, load, actualFan, self.target)) {
        mcFanMode(NO); self.enabled = NO; self.lastError = @"Invalid thermal sample. Returned fan management to Apple."; return;
    }
    // Compare with the last actual write, so small decreases accumulate.
    if (fabs(model.demand - self.writtenDemand) >= .015 || now - self.lastWrite >= 10 || self.lastWrite == 0 || model.safety) {
        NSString *errorMessage = mcFanDemand(model.demand);
        if (errorMessage) { self.enabled = NO; self.lastError = errorMessage; return; }
        self.lastWrite = now; self.writtenDemand = model.demand;
    }
    [self.history addObject:@[@(NSDate.date.timeIntervalSince1970), @(self.temperature), @(load), @(actualFan)]];
    if (self.history.count > 300) [self.history removeObjectAtIndex:0];
    self.learningDirty = YES;
}
- (NSDictionary *)status {
    NSMutableDictionary *result = [@{@"installed": @YES, @"version": @4, @"controllerMode": self.enabled ? @"target" : @"manual-or-auto",
        @"targetTemperature": @(self.target ?: 70), @"coolingDemand": @(model.demand), @"safetyOverride": @(model.safety),
        @"targetAlgorithm": @"predictive", @"learningSamples": @(model.samples), @"forecastSeconds": @20,
        @"headroom": @(model.headroom), @"coolingEffect": @(model.theta[3])} mutableCopy];
    if (self.enabled) result[@"predictedTemperature"] = @(model.forecast);
    if (isfinite(self.temperature) && self.temperature > 0) result[@"cpuTemperature"] = @(self.temperature);
    if (self.lastError) result[@"controllerError"] = self.lastError;
    if (self.learningError) result[@"learningWarning"] = self.learningError;
    return result;
}
@end
