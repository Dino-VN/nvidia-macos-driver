/* Local rotation geometry. Shared by the two kexts and standalone tests. */
#pragma once
#include <stdint.h>
#include <stddef.h>

#define NM_ROTATION_VERSION 9u
#define NM_ROTATION_INFO "nvRotationMode"
#define NM_ROTATION_MAX_DIM 16384u

typedef struct NMRotationMode {
    uint32_t version, degrees;
    uint64_t epoch;
    uint32_t logicalWidth, logicalHeight, outputWidth, outputHeight;
    uint32_t outputPitch, head, ready, modeSequence;
} NMRotationMode;
#ifdef __cplusplus
static_assert(sizeof(NMRotationMode) == 48, "rotation mode ABI");
#endif

static inline int nmRotationValid(uint32_t degrees)
{
    return degrees == 0 || degrees == 90 || degrees == 180 || degrees == 270;
}
static inline int nmRotationSwaps(uint32_t degrees)
{
    return degrees == 90 || degrees == 270;
}
static inline uint32_t nmRotationDecode(uint32_t bits)
{
    switch (bits) {
    case 0: return 0;
    case 3: case 0x30: return 90;
    case 6: case 0x60: return 180;
    case 5: case 0x50: return 270;
    default: return UINT32_MAX;
    }
}
static inline uint32_t nmRotationEncode(uint32_t degrees)
{
    switch (degrees) {
    case 0: return 0;
    case 90: return 3;
    case 180: return 6;
    case 270: return 5;
    default: return UINT32_MAX;
    }
}
static inline int nmRotationPitch(uint32_t w, uint32_t h, uint32_t alignment,
                                  uint32_t *pitch, uint64_t *bytes)
{
    if (!pitch || !bytes || !w || !h || w > NM_ROTATION_MAX_DIM || h > NM_ROTATION_MAX_DIM ||
        alignment < 4 || alignment > 65536 || (alignment & (alignment - 1))) return 0;
    const uint64_t row = ((uint64_t)w * 4 + alignment - 1) & ~((uint64_t)alignment - 1);
    if (row > UINT32_MAX) return 0;
    *pitch = (uint32_t)row; *bytes = row * h;
    return 1;
}
static inline int nmRotationModeValid(const struct NMRotationMode *m)
{
    if (!m || m->version != NM_ROTATION_VERSION || !m->ready || !m->epoch ||
        !nmRotationValid(m->degrees) || !m->logicalWidth || !m->logicalHeight ||
        !m->outputWidth || !m->outputHeight || m->logicalWidth > NM_ROTATION_MAX_DIM ||
        m->logicalHeight > NM_ROTATION_MAX_DIM || m->outputWidth > NM_ROTATION_MAX_DIM ||
        m->outputHeight > NM_ROTATION_MAX_DIM || (m->outputPitch & 3) ||
        (uint64_t)m->outputWidth * 4 > m->outputPitch) return 0;
    return m->logicalWidth == (nmRotationSwaps(m->degrees) ? m->outputHeight : m->outputWidth) &&
           m->logicalHeight == (nmRotationSwaps(m->degrees) ? m->outputWidth : m->outputHeight);
}
/* Source pixel -> physically oriented output pixel. */
static inline int nmRotationPixel(uint32_t angle, uint32_t w, uint32_t h,
                                  uint32_t x, uint32_t y, uint32_t *dx, uint32_t *dy)
{
    if (!dx || !dy || !w || !h || x >= w || y >= h || !nmRotationValid(angle)) return 0;
    switch (angle) {
    case 90: *dx = h - 1 - y; *dy = x; break;
    case 180: *dx = w - 1 - x; *dy = h - 1 - y; break;
    case 270: *dx = y; *dy = w - 1 - x; break;
    default: *dx = x; *dy = y; break;
    }
    return 1;
}
/* Rotate the image's top-left, including the cursor hotspot offset already applied by IOGraphics. */
static inline int nmRotationOrigin(uint32_t angle, uint32_t w, uint32_t h,
                                   int32_t x, int32_t y, uint32_t cw, uint32_t ch,
                                   int64_t *dx, int64_t *dy)
{
    if (!dx || !dy || !nmRotationValid(angle) || !w || !h) return 0;
    switch (angle) {
    case 90: *dx = (int64_t)h - y - ch; *dy = x; break;
    case 180: *dx = (int64_t)w - x - cw; *dy = (int64_t)h - y - ch; break;
    case 270: *dx = y; *dy = (int64_t)w - x - cw; break;
    default: *dx = x; *dy = y; break;
    }
    return 1;
}
