// SPDX-License-Identifier: MIT
// Build the cold probe without linking Metal. Build a separate fresh-process
// control with -DVT_CAPABILITY_PREWARM=1 and -framework Metal.
#import <Foundation/Foundation.h>
#import <VideoToolbox/VideoToolbox.h>
#import <mach-o/dyld.h>
#include <stdbool.h>
#include <stdio.h>
#include <string.h>
#ifdef VT_CAPABILITY_PREWARM
#import <Metal/Metal.h>
#endif

static bool driver_loaded(void) {
    for (uint32_t i = 0; i < _dyld_image_count(); ++i) {
        const char *name = _dyld_get_image_name(i);
        if (name && strstr(name, "/NVMTLDriver.bundle/Contents/MacOS/NVMTLDriver"))
            return true;
    }
    return false;
}

int main(int argc, const char **argv) {
    bool require_first = false;
    for (int i = 1; i < argc; ++i) {
        if (!strcmp(argv[i], "--require-first-h264")) require_first = true;
        else {
            fprintf(stderr, "usage: %s [--require-first-h264]\n", argv[0]);
            return 2;
        }
    }
    @autoreleasepool {
        const bool loaded_at_entry = driver_loaded();
#ifdef VT_CAPABILITY_PREWARM
        NSArray<id<MTLDevice>> *devices = MTLCopyAllDevices();
        const NSUInteger device_count = devices.count;
        const char *mode = "prewarmed-control";
#else
        const char *mode = "cold";
#endif
        const bool loaded_before_query = driver_loaded();
        // In the cold build, this is the first codec/device API operation.
        // Do not preload the plugin, enumerate Metal, or call a registrar here.
        const bool first_h264 = VTIsHardwareDecodeSupported(kCMVideoCodecType_H264);
        const bool loaded_after_first = driver_loaded();
        const bool hevc = VTIsHardwareDecodeSupported(kCMVideoCodecType_HEVC);
        const bool vp9 = VTIsHardwareDecodeSupported(kCMVideoCodecType_VP9);
        const bool h264_after_other_queries = VTIsHardwareDecodeSupported(kCMVideoCodecType_H264);

        NSMutableDictionary *result = [@{
            @"mode": @(mode),
            @"driver_loaded_at_entry": @(loaded_at_entry),
            @"driver_loaded_before_first_query": @(loaded_before_query),
            @"first_h264_hardware_supported": @(first_h264),
            @"driver_loaded_after_first_query": @(loaded_after_first),
            @"hevc_hardware_supported": @(hevc),
            @"vp9_hardware_supported": @(vp9),
            @"h264_hardware_supported_after_other_queries": @(h264_after_other_queries),
            @"hardware_playback_tested": @NO,
            @"browser_sandbox_tested": @NO,
        } mutableCopy];
#ifdef VT_CAPABILITY_PREWARM
        result[@"prewarmed_metal_devices"] = @(device_count);
#endif
        NSError *error = nil;
        NSData *json = [NSJSONSerialization dataWithJSONObject:result options:NSJSONWritingPrettyPrinted error:&error];
        if (!json || fwrite(json.bytes, 1, json.length, stdout) != json.length || putchar('\n') == EOF) {
            fprintf(stderr, "capability report failed: %s\n", error ? error.description.UTF8String : "write error");
            return 2;
        }
        // A driver loaded before a supposedly cold first query invalidates the
        // cold-start experiment. A false capability is otherwise valid on GPUs
        // without a decoder or with an explicit opt-out; assert only on request.
#ifndef VT_CAPABILITY_PREWARM
        if (loaded_before_query) return 2;
#endif
        return require_first && !first_h264 ? 1 : 0;
    }
}
