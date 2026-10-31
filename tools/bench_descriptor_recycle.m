// Pixel-verified descriptor-set reuse across command buffers on an isolated plugin; never installs it.
// Each frame is its own command buffer, so from the second frame on the snapshot sets come from the sets the previous
// frames retired. A frame draws a resource-free pipeline first (the command buffer has no binding table yet), then a
// textured draw whose texture alternates per frame, then a draw whose colour comes from setFragmentBytes. A set reused
// with a stale descriptor shows up as the previous frame's texture or colour.
// clang -fobjc-arc -O2 tools/bench_descriptor_recycle.m -framework Foundation -framework Metal -framework IOKit -o bench_descriptor_recycle
// bench_descriptor_recycle /absolute/path/NVMTLDriver [frames=64] [draws=600]
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <IOKit/IOKitLib.h>
#include <dlfcn.h>
#include <time.h>
#include <stdio.h>
#include <stdlib.h>

@interface NSObject (NVMTLProbe)
- (instancetype)initWithAcceleratorPort:(mach_port_t)port;
@end
static double cpu_ms(void) { struct timespec t; clock_gettime(CLOCK_THREAD_CPUTIME_ID, &t); return t.tv_sec * 1000.0 + t.tv_nsec / 1e6; }
static int compare(const void *a, const void *b) { double x = *(const double *)a, y = *(const double *)b; return (x > y) - (x < y); }

static id<MTLTexture> solid(id<MTLDevice> dev, uint32_t rgba)
{
    MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:4 height:4 mipmapped:NO];
    td.usage = MTLTextureUsageShaderRead; td.storageMode = MTLStorageModeShared;
    id<MTLTexture> t = [dev newTextureWithDescriptor:td];
    uint32_t px[16]; for (int i = 0; i < 16; i++) px[i] = rgba;
    [t replaceRegion:MTLRegionMake2D(0, 0, 4, 4) mipmapLevel:0 withBytes:px bytesPerRow:16];
    return t;
}

int main(int argc, char **argv) { @autoreleasepool {
    if (argc < 2) return 2;
    int frames = argc > 2 ? atoi(argv[2]) : 64, draws = argc > 3 ? atoi(argv[3]) : 600;
    if (frames < 2 || frames > 4096 || draws < 3 || draws > 100000) return 2;
    if (!dlopen(argv[1], RTLD_NOW | RTLD_LOCAL)) { fprintf(stderr, "load: %s\n", dlerror()); return 2; }
    Class cls = NSClassFromString(@"NVMTLDevice");
    io_service_t accel = IOServiceGetMatchingService(kIOMainPortDefault, IOServiceMatching("NVAccel"));
    id<MTLDevice> dev = [[cls alloc] initWithAcceleratorPort:accel]; if (accel) IOObjectRelease(accel);
    if (!dev) { fprintf(stderr, "No isolated NVMTL device\n"); return 2; }
    NSError *error = nil;
    NSString *src = @"#include <metal_stdlib>\nusing namespace metal;\n"
      "struct V { float4 p [[position]]; float2 uv; };\n"
      "vertex V v(uint i [[vertex_id]]) { float2 p=float2((i<<1)&2,i&2); V o; o.p=float4(p*2.0-1.0,0,1); o.uv=p; return o; }\n"
      "fragment float4 plain() { return float4(0,0,1,1); }\n"
      "fragment float4 tex(V in [[stage_in]], texture2d<float> t [[texture(0)]]) { constexpr sampler s(filter::nearest); return t.sample(s, in.uv); }\n"
      "fragment float4 bytes(constant float4 &c [[buffer(0)]]) { return c; }\n";
    id<MTLLibrary> lib = [dev newLibraryWithSource:src options:nil error:&error];
    if (!lib) { fprintf(stderr, "library: %s\n", error.description.UTF8String); return 2; }
    id<MTLRenderPipelineState> ps[3]; NSString *names[3] = { @"plain", @"tex", @"bytes" };
    for (int i = 0; i < 3; i++) {
        MTLRenderPipelineDescriptor *pd = [MTLRenderPipelineDescriptor new];
        pd.vertexFunction = [lib newFunctionWithName:@"v"]; pd.fragmentFunction = [lib newFunctionWithName:names[i]];
        pd.colorAttachments[0].pixelFormat = MTLPixelFormatRGBA8Unorm;
        ps[i] = [dev newRenderPipelineStateWithDescriptor:pd error:&error];
        if (!ps[i]) { fprintf(stderr, "pipeline %s: %s\n", names[i].UTF8String, error.description.UTF8String); return 2; }
    }
    id<MTLTexture> texs[2] = { solid(dev, 0xff0000ffu), solid(dev, 0xff00ff00u) };   // red, green (RGBA8 little-endian)
    const uint32_t texpx[2] = { 0xff0000ffu, 0xff00ff00u };
    id<MTLCommandQueue> queue = [dev newCommandQueue];
    MTLTextureDescriptor *td = [MTLTextureDescriptor texture2DDescriptorWithPixelFormat:MTLPixelFormatRGBA8Unorm width:48 height:16 mipmapped:NO];
    td.usage = MTLTextureUsageRenderTarget | MTLTextureUsageShaderRead; td.storageMode = MTLStorageModeShared;
    id<MTLTexture> target = [dev newTextureWithDescriptor:td];
    printf("device: %s\nplugin: %s\n", dev.name.UTF8String, argv[1]);
    double *times = calloc((size_t)frames, sizeof *times); int bad = 0;
    for (int frame = 0; frame < frames; frame++) @autoreleasepool {
        MTLRenderPassDescriptor *rd = [MTLRenderPassDescriptor renderPassDescriptor];
        rd.colorAttachments[0].texture = target; rd.colorAttachments[0].loadAction = MTLLoadActionClear;
        rd.colorAttachments[0].clearColor = MTLClearColorMake(0, 0, 0, 0); rd.colorAttachments[0].storeAction = MTLStoreActionStore;
        id<MTLCommandBuffer> cb = [queue commandBuffer]; id<MTLRenderCommandEncoder> enc = [cb renderCommandEncoderWithDescriptor:rd];
        const int t = frame & 1; const float shade = (float)((frame * 37) % 200 + 40) / 255.0f;
        double start = cpu_ms();
        for (int i = 0; i < draws; i++) {
            const int kind = i * 3 / draws;   // all resource-free draws first, then textured, then bytes
            [enc setRenderPipelineState:ps[kind]];
            [enc setViewport:(MTLViewport){ 16.0 * kind, 0, 16, 16, 0, 1 }];
            if (kind == 1) [enc setFragmentTexture:texs[(t + i) & 1 ? (t ^ 1) : t] atIndex:0];
            if (kind == 1 && i == (draws * 2 / 3) - 1) [enc setFragmentTexture:texs[t] atIndex:0];
            if (kind == 2) { float c[4] = { shade, 1.0f - shade, 0.5f, 1.0f }; [enc setFragmentBytes:c length:sizeof c atIndex:0]; }
            [enc drawPrimitives:MTLPrimitiveTypeTriangle vertexStart:0 vertexCount:3];
        }
        times[frame] = cpu_ms() - start;
        [enc endEncoding]; [cb commit]; [cb waitUntilCompleted];
        uint32_t px[48 * 16];
        [target getBytes:px bytesPerRow:48 * 4 fromRegion:MTLRegionMake2D(0, 0, 48, 16) mipmapLevel:0];
        uint8_t sb = (uint8_t)(shade * 255.0f + 0.5f), sg = (uint8_t)((1.0f - shade) * 255.0f + 0.5f);
        int wrong = 0;
        for (int y = 0; y < 16; y++) for (int x = 0; x < 48; x++) {
            uint32_t p = px[y * 48 + x];
            if (x < 16) { if (p != 0xffff0000u) wrong++; }
            else if (x < 32) { if (p != texpx[t]) wrong++; }
            else {
                int r = p & 0xff, g = (p >> 8) & 0xff;
                if (abs(r - sb) > 1 || abs(g - sg) > 1 || (p >> 24) != 0xff) wrong++;
            }
        }
        if (wrong) { bad++; if (bad <= 4) fprintf(stderr, "frame %d: %d wrong pixels (first %08x %08x %08x)\n", frame, wrong, px[0], px[16], px[32]); }
    }
    qsort(times + 1, (size_t)frames - 1, sizeof *times, compare);
    printf("%s frames=%d draws=%d bad_frames=%d median_record_cpu_ms=%.6f\n", bad ? "FAIL" : "PASS", frames, draws, bad, times[1 + (frames - 1) / 2]);
    return bad ? 1 : 0;
}}
