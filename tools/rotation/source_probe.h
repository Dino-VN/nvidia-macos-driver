/* Opt-in, one-frame diagnostic. Contains no kernel addresses or IOSurface handles. */
#pragma once
#include "shared.h"

#define NM_ROTATION_PROBE_VERSION 1u
#define NM_ROTATION_PROBE_MAGIC 0x34524d4eu
#define NM_ROTATION_PROBE_EDGE 640u
#define NM_ROTATION_PROBE_SOURCE_LIMIT (256ull * 1024 * 1024)

struct NMRotationSourceProbe {
    uint32_t magic, version, headerBytes, pixelBytes;
    uint64_t epoch;
    uint32_t surfaceID, head, degrees, format;
    uint32_t sourceWidth, sourceHeight, sourcePitch, imageWidth, imageHeight, imagePitch;
    uint32_t logicalWidth, logicalHeight, outputWidth, outputHeight;
    uint32_t resourceWidth, resourceHeight, resourcePitch, reserved;
    uint32_t sourceRectBits[4], destinationRectBits[4], pipeScalerBits[6];
    uint32_t padding[2];
};
static_assert(sizeof(NMRotationSourceProbe) == 160,"source probe ABI");
#define NM_ROTATION_PROBE_CAPACITY (sizeof(NMRotationSourceProbe) + NM_ROTATION_PROBE_EDGE * NM_ROTATION_PROBE_EDGE * 4u)

static inline bool nmRotationSourceGeometry(uint64_t width, uint64_t height, uint64_t pitch, uint64_t bytes)
{
    return width && height && width <= NM_ROTATION_MAX_DIM && height <= NM_ROTATION_MAX_DIM &&
        pitch >= width * 4 && pitch <= NM_ROTATION_MAX_DIM * 8ull && !(pitch & 3) &&
        pitch * height <= bytes;
}
static inline bool nmRotationProbeGeometry(uint64_t width, uint64_t height, uint64_t pitch, uint64_t bytes)
{
    return nmRotationSourceGeometry(width,height,pitch,bytes) && bytes <= NM_ROTATION_PROBE_SOURCE_LIMIT;
}

// Nearest samples preserve the real source layout. This does not rotate, filter,
// modify or present the source. Bounds are independent of the expected mode.
static inline bool nmRotationProbePixels(NMRotationSourceProbe *h, const volatile uint32_t *source,
    uint64_t sourceBytes, uint32_t *pixels, uint64_t pixelCapacity)
{
    if (!h || !source || !pixels || !nmRotationProbeGeometry(h->sourceWidth,h->sourceHeight,h->sourcePitch,sourceBytes)) return false;
    const unsigned edge = h->sourceWidth > h->sourceHeight ? h->sourceWidth : h->sourceHeight;
    h->imageWidth = edge <= NM_ROTATION_PROBE_EDGE ? h->sourceWidth :
        (uint32_t)((uint64_t)h->sourceWidth * NM_ROTATION_PROBE_EDGE / edge);
    h->imageHeight = edge <= NM_ROTATION_PROBE_EDGE ? h->sourceHeight :
        (uint32_t)((uint64_t)h->sourceHeight * NM_ROTATION_PROBE_EDGE / edge);
    if (!h->imageWidth) h->imageWidth = 1;
    if (!h->imageHeight) h->imageHeight = 1;
    h->imagePitch = h->imageWidth * 4;
    h->pixelBytes = h->imagePitch * h->imageHeight;
    const uintptr_t a=(uintptr_t)source,b=(uintptr_t)pixels;
    const uint64_t span=(uint64_t)h->sourcePitch*h->sourceHeight;
    if ((a & 3) || (b & 3) || pixelCapacity < h->pixelBytes || span > UINTPTR_MAX-a || h->pixelBytes > UINTPTR_MAX-b ||
        !(a+span <= b || b+h->pixelBytes <= a)) return false;
    for (uint32_t y=0;y<h->imageHeight;++y) {
        const size_t sy=(uint64_t)y*h->sourceHeight/h->imageHeight;
        for (uint32_t x=0;x<h->imageWidth;++x) {
            const size_t sx=(uint64_t)x*h->sourceWidth/h->imageWidth;
            pixels[(size_t)y*h->imageWidth+x]=source[sy*(h->sourcePitch/4)+sx];
        }
    }
    h->magic=NM_ROTATION_PROBE_MAGIC;h->version=NM_ROTATION_PROBE_VERSION;h->headerBytes=sizeof(*h);
    return true;
}
