#pragma once
#import <Foundation/Foundation.h>
#include "fan_model.h"
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <unistd.h>

static BOOL mcWriteLearning(NSString *path, NSData *data) {
    if (!data) return NO;
    char *temporary = strdup([[path stringByAppendingString:@".XXXXXX"] fileSystemRepresentation]);
    if (!temporary) return NO;
    int fd = mkstemp(temporary);
    if (fd < 0) { free(temporary); return NO; }
    BOOL ok = fchmod(fd, 0600) == 0;
    const unsigned char *bytes = data.bytes;
    NSUInteger offset = 0;
    while (ok && offset < data.length) {
        ssize_t written = write(fd, bytes+offset, data.length-offset);
        if (written < 0 && errno == EINTR) continue;
        if (written <= 0) ok = NO;
        else offset += written;
    }
    // Flush learned statistics to disk BEFORE replacing the raw log.
    if (ok && fsync(fd) != 0) ok = NO;
    if (close(fd) != 0) ok = NO;
    if (ok && rename(temporary, path.fileSystemRepresentation) != 0) ok = NO;
    if (!ok) unlink(temporary);
    free(temporary);
    return ok;
}

// Persist the sufficient statistics as well as the fitted coefficients. Raw
// samples may expire without losing what they taught us or replaying them twice.
static NSDictionary *mcLearningCheckpoint(const MCFanModel *model) {
    NSMutableArray *gram = NSMutableArray.array, *rhs = NSMutableArray.array, *theta = NSMutableArray.array;
    for (int i = 0; i < 4; i++) {
        [rhs addObject:@(model->rhs[i])]; [theta addObject:@(model->theta[i])];
        for (int j = 0; j < 4; j++) [gram addObject:@(model->gram[i][j])];
    }
    return @{@"gram": gram, @"rhs": rhs, @"theta": theta,
             @"error": @(model->error), @"samples": @(model->samples)};
}

static BOOL mcLearningNumber(id value, double lower, double upper) {
    return [value isKindOfClass:NSNumber.class] && isfinite([value doubleValue]) &&
           [value doubleValue] >= lower && [value doubleValue] <= upper;
}

static BOOL mcRestoreLearning(MCFanModel *model, id checkpoint) {
    if (![checkpoint isKindOfClass:NSDictionary.class]) return NO;
    for (NSString *key in @[@"gram", @"rhs", @"theta"])
        if (![checkpoint[key] isKindOfClass:NSArray.class] || [checkpoint[key] count] != ([key isEqual:@"gram"] ? 16 : 4)) return NO;
    if (!mcLearningNumber(checkpoint[@"error"], 0, 5) || !mcLearningNumber(checkpoint[@"samples"], 0, 1e12) ||
        floor([checkpoint[@"samples"] doubleValue]) != [checkpoint[@"samples"] doubleValue]) return NO;
    MCFanModel restored; mcModelInit(&restored);
    const double lower[] = {-2, -4, .05, .15}, upper[] = {2, -.02, 4, 4};
    double cholesky[4][4] = {0};
    for (int i = 0; i < 4; i++) {
        if (!mcLearningNumber(checkpoint[@"rhs"][i], -10000, 10000) ||
            !mcLearningNumber(checkpoint[@"theta"][i], lower[i], upper[i])) return NO;
        restored.rhs[i] = [checkpoint[@"rhs"][i] doubleValue];
        restored.theta[i] = [checkpoint[@"theta"][i] doubleValue];
        for (int j = 0; j < 4; j++) {
            id value = checkpoint[@"gram"][4*i+j];
            if (!mcLearningNumber(value, -10000, 10000)) return NO;
            restored.gram[i][j] = [value doubleValue];
        }
    }
    // Validate symmetry and positive definiteness of the regularized system
    // before allowing a damaged checkpoint to influence the next online fit.
    for (int i = 0; i < 4; i++) for (int j = 0; j <= i; j++) {
        if (fabs(restored.gram[i][j]-restored.gram[j][i]) > 1e-6) return NO;
        double value = restored.gram[i][j] + (i == j ? 5 : 0);
        for (int k = 0; k < j; k++) value -= cholesky[i][k]*cholesky[j][k];
        if (i == j && value <= 0) return NO;
        cholesky[i][j] = i == j ? sqrt(value) : value/cholesky[j][j];
    }
    restored.error = [checkpoint[@"error"] doubleValue];
    restored.samples = [checkpoint[@"samples"] unsignedLongValue];
    *model = restored; // Temperature trend, mode and fan demand stay reset.
    return YES;
}

static BOOL mcLearningRow(id row) {
    return [row isKindOfClass:NSArray.class] && [row count] == 4 &&
        mcLearningNumber(row[0], 1, 1e12) && mcLearningNumber(row[1], .001, 129.999) &&
        mcLearningNumber(row[2], 0, 1) && mcLearningNumber(row[3], 0, 1);
}
