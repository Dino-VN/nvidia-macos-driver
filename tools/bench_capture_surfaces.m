// Pixel-verified capture copies using a process-local plugin; never installs it.
// clang -fobjc-arc -O2 tools/bench_capture_surfaces.m -o bench_capture_surfaces \
//   -framework Foundation -framework Metal -framework IOSurface -framework CoreVideo -framework IOKit
// bench_capture_surfaces /absolute/path/to/NVMTLDriver [frames-per-case]
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <IOSurface/IOSurface.h>
#import <CoreVideo/CoreVideo.h>
#import <IOKit/IOKitLib.h>
#import <objc/message.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>

@interface NSObject (CaptureProbe)
- (void)nvmtlSurfaceIn;
@end

static uint8_t pattern(size_t x, size_t y, unsigned plane, unsigned frame) {
    return (uint8_t)(x * 37 + y * 13 + plane * 71 + frame * 29);
}
static unsigned verify(const uint8_t *pixels, size_t row, size_t width, size_t height,
                       unsigned plane, unsigned frame) {
    unsigned bad = 0;
    for (size_t y = 0; y < height; y++) for (size_t x = 0; x < width; x++)
        bad += pixels[y * row + x] != pattern(x, y, plane, frame);
    return bad;
}

int main(int argc, char **argv) { @autoreleasepool {
    setvbuf(stdout, NULL, _IONBF, 0);
    if (argc < 2 || !dlopen(argv[1], RTLD_NOW | RTLD_LOCAL)) { fprintf(stderr, "plugin: %s\n", dlerror()); return 2; }
    io_service_t accelerator = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("NVAccel"));
    if (!accelerator) return 3;
    id<MTLDevice> dev = ((id(*)(id, SEL, mach_port_t))objc_msgSend)([NSClassFromString(@"NVMTLDevice") alloc],
        NSSelectorFromString(@"initWithAcceleratorPort:"), accelerator);
    IOObjectRelease(accelerator);
    if (!dev) return 4;
    printf("device=%s\n", dev.name.UTF8String);
    const unsigned frames = argc > 2 ? (unsigned)strtoul(argv[2], NULL, 10) : 8;
    if (!frames || frames > 1000) return 5;
    const size_t sizes[][2] = {{1920,1080}, {2560,1440}, {3840,2160}, {1000,750}};
    const OSType formats[] = {kCVPixelFormatType_32BGRA, kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange,
        kCVPixelFormatType_420YpCbCr8BiPlanarFullRange, kCVPixelFormatType_420YpCbCr10BiPlanarVideoRange};
    unsigned cases = 0, totalBad = 0;
    const uint64_t start = clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW);
    for (unsigned f = 0; f < sizeof(formats)/sizeof(formats[0]); f++)
    for (unsigned s = 0; s < sizeof(sizes)/sizeof(sizes[0]); s++) @autoreleasepool {
        const size_t width = sizes[s][0], height = sizes[s][1];
        NSDictionary *attrs = @{(id)kCVPixelBufferIOSurfacePropertiesKey:@{}, (id)kCVPixelBufferMetalCompatibilityKey:@YES};
        CVPixelBufferRef pb = NULL;
        if (CVPixelBufferCreate(NULL, width, height, formats[f], (__bridge CFDictionaryRef)attrs, &pb)) return 6;
        IOSurfaceRef surface = CVPixelBufferGetIOSurface(pb);
        if (!surface) return 7;
        const size_t count = MAX((size_t)1, IOSurfaceGetPlaneCount(surface));
        unsigned bad = 0;
        for (unsigned frame = 0; frame < frames; frame++) @autoreleasepool {
            for (unsigned plane = 0; plane < count; plane++) @autoreleasepool {
                const size_t pw = IOSurfaceGetWidthOfPlane(surface, plane), ph = IOSurfaceGetHeightOfPlane(surface, plane);
                const size_t bpp = IOSurfaceGetBytesPerElementOfPlane(surface, plane), row = IOSurfaceGetBytesPerRowOfPlane(surface, plane);
                const size_t active = pw * bpp;
                const MTLPixelFormat pixel = f == 0 ? MTLPixelFormatBGRA8Unorm : f == 3
                    ? (plane ? MTLPixelFormatRG16Unorm : MTLPixelFormatR16Unorm)
                    : (plane ? MTLPixelFormatRG8Unorm : MTLPixelFormatR8Unorm);
                if (IOSurfaceLock(surface, 0, NULL)) return 8;
                uint8_t *base = IOSurfaceGetBaseAddressOfPlane(surface, plane);
                for (size_t y = 0; y < ph; y++) {
                    for (size_t x = 0; x < active; x++) base[y*row+x] = pattern(x,y,plane,frame*2);
                    memset(base+y*row+active, 0xcd, row-active);
                }
                IOSurfaceUnlock(surface, 0, NULL);
                MTLTextureDescriptor *desc = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:pixel width:pw height:ph mipmapped:NO];
                desc.storageMode = MTLStorageModeShared;
                desc.usage = MTLTextureUsageShaderRead | MTLTextureUsageShaderWrite | (f == 0 ? MTLTextureUsageRenderTarget : 0);
                uint8_t *read = malloc(active*ph), *write = malloc(active*ph);
                if (!read || !write) return 10;
                @autoreleasepool {
                id<MTLTexture> texture = [dev newTextureWithDescriptor:desc iosurface:surface plane:plane];
                if (!texture) return 9;
                [(NSObject *)texture nvmtlSurfaceIn];
                memset(read, 0xa5, active*ph);
                [texture getBytes:read bytesPerRow:active fromRegion:MTLRegionMake2D(0,0,pw,ph) mipmapLevel:0];
                bad += verify(read,active,active,ph,plane,frame*2);
                for (size_t y = 0; y < ph; y++) for (size_t x = 0; x < active; x++) write[y*active+x] = pattern(x,y,plane,frame*2+1);
                [texture replaceRegion:MTLRegionMake2D(0,0,pw,ph) mipmapLevel:0 withBytes:write bytesPerRow:active];
                if (IOSurfaceLock(surface, kIOSurfaceLockReadOnly, NULL)) return 11;
                base = IOSurfaceGetBaseAddressOfPlane(surface,plane);
                bad += verify(base,row,active,ph,plane,frame*2+1);
                // The family may page off padding from shared BGRA VRAM. Private
                // planar copies must leave the adjacent row padding untouched.
                if (count > 1) for (size_t y = 0; y < ph; y++) for (size_t x = active; x < row; x++) bad += base[y*row+x] != 0xcd;
                IOSurfaceUnlock(surface,kIOSurfaceLockReadOnly,NULL);
                if (!frame) printf("format=%08x %zux%zu plane=%u offset=%zu row=%zu bpp=%zu\n", formats[f],width,height,plane,
                    (size_t)((uintptr_t)base-(uintptr_t)IOSurfaceGetBaseAddress(surface)),row,bpp);
                }
                // Rewrap after the writer is destroyed, without a CPU overwrite.
                // Reusing an import must preserve the completed GPU pixels.
                @autoreleasepool {
                    id<MTLTexture> reader = [dev newTextureWithDescriptor:desc iosurface:surface plane:plane];
                    if (!reader) return 12;
                    memset(read,0xa5,active*ph);
                    [reader getBytes:read bytesPerRow:active fromRegion:MTLRegionMake2D(0,0,pw,ph) mipmapLevel:0];
                    bad += verify(read,active,active,ph,plane,frame*2+1);
                }
                free(read); free(write);
            }
        }
        cases++; totalBad += bad;
        printf("CASE format=%08x %zux%zu frames=%u bad=%u\n",formats[f],width,height,frames,bad);
        CVPixelBufferRelease(pb);
    }
    printf("RESULT cases=%u frames-per-case=%u bad=%u elapsed-ms=%.1f\n",cases,frames,totalBad,
        (clock_gettime_nsec_np(CLOCK_MONOTONIC_RAW)-start)/1e6);
    return totalBad ? 1 : 0;
} }
