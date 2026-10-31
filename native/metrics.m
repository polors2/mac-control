#import <Foundation/Foundation.h>
#import <IOKit/IOKitLib.h>
#include <mach/mach.h>
#include <mach/host_info.h>
#include <net/if.h>
#include <net/route.h>
#include <netinet/in.h>
#include <ifaddrs.h>
#include <sys/sysctl.h>
#include <time.h>
#include <math.h>
#include "smc.h"

static id cpuTicks(void) {
    host_cpu_load_info_data_t info;
    mach_msg_type_number_t count = HOST_CPU_LOAD_INFO_COUNT;
    mach_port_t host = mach_host_self();
    kern_return_t result = host_statistics(host, HOST_CPU_LOAD_INFO, (host_info_t)&info, &count);
    mach_port_deallocate(mach_task_self(), host);
    if (result != KERN_SUCCESS) return NSNull.null;
    return @[@(info.cpu_ticks[CPU_STATE_USER]), @(info.cpu_ticks[CPU_STATE_SYSTEM]),
             @(info.cpu_ticks[CPU_STATE_IDLE]), @(info.cpu_ticks[CPU_STATE_NICE])];
}

static id networkCounters(void) {
    // Count physical IP interfaces once; exclude loopback and VPN tunnel duplicates.
    NSMutableSet *active = NSMutableSet.set;
    struct ifaddrs *addresses = NULL;
    if (getifaddrs(&addresses) != 0) return NSNull.null;
    for (struct ifaddrs *item = addresses; item; item = item->ifa_next) {
        if (!item->ifa_addr || !(item->ifa_flags & IFF_UP) || !(item->ifa_flags & IFF_RUNNING)) continue;
        NSString *name = @(item->ifa_name);
        if (![name hasPrefix:@"en"]) continue;
        BOOL usable = NO;
        if (item->ifa_addr->sa_family == AF_INET) {
            uint32_t address = ntohl(((struct sockaddr_in *)item->ifa_addr)->sin_addr.s_addr);
            usable = address && (address >> 24) != 127 && (address >> 16) != 0xa9fe;
        } else if (item->ifa_addr->sa_family == AF_INET6) {
            struct in6_addr *address = &((struct sockaddr_in6 *)item->ifa_addr)->sin6_addr;
            usable = !IN6_IS_ADDR_LINKLOCAL(address) && !IN6_IS_ADDR_LOOPBACK(address) && !IN6_IS_ADDR_UNSPECIFIED(address);
        }
        if (usable) [active addObject:name];
    }
    freeifaddrs(addresses);
    int mib[] = {CTL_NET, PF_ROUTE, 0, 0, NET_RT_IFLIST2, 0};
    size_t size = 0;
    if (sysctl(mib, 6, NULL, &size, NULL, 0) != 0) return NSNull.null;
    void *buffer = malloc(size);
    if (!buffer) return NSNull.null;
    if (sysctl(mib, 6, buffer, &size, NULL, 0) != 0) { free(buffer); return NSNull.null; }
    NSMutableDictionary *result = NSMutableDictionary.dictionary;
    for (char *cursor = buffer; cursor < (char *)buffer + size;) {
        struct if_msghdr *header = (struct if_msghdr *)cursor;
        if (!header->ifm_msglen || cursor + header->ifm_msglen > (char *)buffer + size) break;
        if (header->ifm_type == RTM_IFINFO2 && header->ifm_msglen >= sizeof(struct if_msghdr2)) {
            struct if_msghdr2 *info = (struct if_msghdr2 *)cursor;
            char name[IFNAMSIZ];
            if (if_indextoname(info->ifm_index, name) && [active containsObject:@(name)]) {
                result[@(name)] = @{@"received": @(info->ifm_data.ifi_ibytes), @"sent": @(info->ifm_data.ifi_obytes)};
            }
        }
        cursor += header->ifm_msglen;
    }
    free(buffer);
    return result;
}

static NSArray *gpuStats(void) {
    io_iterator_t iterator = 0;
    if (IOServiceGetMatchingServices(kIOMainPortDefault, IOServiceMatching("IOAccelerator"), &iterator)) return @[];
    NSMutableArray *result = NSMutableArray.array;
    NSMutableSet *seen = NSMutableSet.set;
    io_service_t service;
    while ((service = IOIteratorNext(iterator))) {
        io_name_t className; IOObjectGetClass(service, className);
        uint64_t registryID = 0; IORegistryEntryGetRegistryEntryID(service, &registryID);
        NSString *identifier = [NSString stringWithFormat:@"%llu", registryID];
        if ([seen containsObject:identifier]) { IOObjectRelease(service); continue; }
        [seen addObject:identifier];
        NSString *driver = @(className);
        NSString *name = [driver containsString:@"Intel"] ? @"Intel graphics" : [driver containsString:@"AMD"] ? @"AMD graphics" : [driver containsString:@"AGX"] ? @"Apple graphics" : driver;
        NSString *vendor = [driver containsString:@"Intel"] ? @"intel" : [driver containsString:@"AMD"] ? @"amd" : [driver containsString:@"AGX"] ? @"apple" : @"other";
        CFTypeRef modelProperty = IORegistryEntrySearchCFProperty(service, kIOServicePlane, CFSTR("model"), kCFAllocatorDefault, kIORegistryIterateRecursively | kIORegistryIterateParents);
        id model = CFBridgingRelease(modelProperty);
        if ([model isKindOfClass:NSData.class]) {
            NSData *data = model;
            NSString *text = [[NSString alloc] initWithBytes:data.bytes length:strnlen(data.bytes, data.length) encoding:NSUTF8StringEncoding];
            if (text.length) name = text;
        } else if ([model isKindOfClass:NSString.class] && [model length]) name = model;
        NSDictionary *agc = CFBridgingRelease(IORegistryEntryCreateCFProperty(service, CFSTR("AGCInfo"), kCFAllocatorDefault, 0));
        id off = [agc isKindOfClass:NSDictionary.class] ? agc[@"poweredOffByAGC"] : nil;
        BOOL powerKnown = [off isKindOfClass:NSNumber.class];
        BOOL sleeping = powerKnown && [off boolValue];
        // Do not ask a power-gated GPU for performance counters just to monitor it.
        NSDictionary *stats = sleeping ? nil : CFBridgingRelease(IORegistryEntryCreateCFProperty(service, CFSTR("PerformanceStatistics"), kCFAllocatorDefault, 0));
        NSNumber *percent = nil;
        if ([stats isKindOfClass:NSDictionary.class]) {
            for (NSString *key in @[@"Device Utilization %", @"GPU Activity(%)", @"GPU Busy %"]) {
                id value = stats[key];
                if ([value isKindOfClass:NSNumber.class] && isfinite([value doubleValue]) && [value doubleValue] >= 0 && [value doubleValue] <= 100) { percent = value; break; }
            }
        }
        // A powered-down GPU cannot be busy; this zero is derived from AGC's explicit power state.
        if (sleeping) percent = @0;
        [result addObject:@{@"id": identifier, @"name": name, @"vendor": vendor,
            @"state": sleeping ? @"sleeping" : powerKnown ? @"active" : @"unknown",
            @"percent": percent ?: (id)NSNull.null}];
        IOObjectRelease(service);
    }
    IOObjectRelease(iterator);
    return result;
}

int main(void) {
    @autoreleasepool {
        struct timespec now; clock_gettime(CLOCK_MONOTONIC, &now);
        NSMutableDictionary *result = [@{@"monotonic": @(now.tv_sec + now.tv_nsec / 1e9),
            @"time": @([NSDate.date timeIntervalSince1970]), @"cpuTicks": cpuTicks(),
            @"interfaces": networkCounters(), @"gpus": gpuStats()} mutableCopy];
        [result addEntriesFromDictionary:mcThermals()];
        NSData *data = [NSJSONSerialization dataWithJSONObject:result options:0 error:nil];
        if (!data) return 1;
        puts([[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding].UTF8String);
    }
    return 0;
}
