/* Local prototype: exact BGRA pixel permutation, without allocation or GPU calls. */
#pragma once
#include "shared.h"

#define NM_ROTATION_COPY_PROTOCOL 9u
#define NM_ROTATION_COPY "nvRotationCopy"

static inline int nmRotationCopyBounds(const volatile uint32_t *source, uint64_t sourceBytes,
                                       uint32_t width, uint32_t height, uint32_t sourcePitch,
                                       volatile uint32_t *destination, uint64_t destinationBytes,
                                       uint32_t outputWidth, uint32_t outputHeight, uint32_t outputPitch,
                                       uint32_t degrees)
{
    if (!source || !destination || !nmRotationValid(degrees) || !width || !height ||
        width > NM_ROTATION_MAX_DIM || height > NM_ROTATION_MAX_DIM ||
        outputWidth != (nmRotationSwaps(degrees) ? height : width) ||
        outputHeight != (nmRotationSwaps(degrees) ? width : height) ||
        (sourcePitch & 3u) || (outputPitch & 3u) ||
        sourcePitch < (uint64_t)width * 4 || outputPitch < (uint64_t)outputWidth * 4 ||
        sourceBytes < (uint64_t)sourcePitch * height ||
        destinationBytes < (uint64_t)outputPitch * outputHeight) return 0;
    const uintptr_t a = (uintptr_t)source, b = (uintptr_t)destination;
    const uint64_t an = (uint64_t)sourcePitch * height, bn = (uint64_t)outputPitch * outputHeight;
    if ((a & 3u) || (b & 3u) || an > UINTPTR_MAX - a || bn > UINTPTR_MAX - b) return 0;
    // In-place rotation would corrupt pixels still to be read.
    return a + an <= b || b + bn <= a;
}

static inline int nmRotationCopy32(const volatile uint32_t *source, uint64_t sourceBytes,
                                   uint32_t width, uint32_t height, uint32_t sourcePitch,
                                   volatile uint32_t *destination, uint64_t destinationBytes,
                                   uint32_t outputWidth, uint32_t outputHeight, uint32_t outputPitch,
                                   uint32_t degrees)
{
    if (!nmRotationCopyBounds(source, sourceBytes, width, height, sourcePitch,
                              destination, destinationBytes, outputWidth, outputHeight, outputPitch, degrees)) return 0;
    const size_t sp = sourcePitch / 4, dp = outputPitch / 4;
    if (degrees == 0 || degrees == 180) {
        for (uint32_t y = 0; y < outputHeight; ++y) {
            const volatile uint32_t *s = source + (size_t)(degrees ? height - 1 - y : y) * sp;
            volatile uint32_t *d = destination + (size_t)y * dp;
            for (uint32_t x = 0; x < outputWidth; ++x) d[x] = s[degrees ? width - 1 - x : x];
        }
    } else {
        // A small transpose tile bounds source cache misses and keeps BAR writes
        // in contiguous runs. Padding is never read or written as image pixels.
        const uint32_t tile = 32;
        for (uint32_t by = 0; by < outputHeight; by += tile)
            for (uint32_t bx = 0; bx < outputWidth; bx += tile) {
                const uint32_t ey = outputHeight - by < tile ? outputHeight : by + tile;
                const uint32_t ex = outputWidth - bx < tile ? outputWidth : bx + tile;
                for (uint32_t y = by; y < ey; ++y) {
                    volatile uint32_t *d = destination + (size_t)y * dp;
                    if (degrees == 90) {
                        for (uint32_t x = bx; x < ex; ++x) d[x] = source[(size_t)(height - 1 - x) * sp + y];
                    } else {
                        for (uint32_t x = bx; x < ex; ++x) d[x] = source[(size_t)x * sp + width - 1 - y];
                    }
                }
            }
    }
    return 1;
}
