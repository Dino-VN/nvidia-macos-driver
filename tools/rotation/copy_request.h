/* Kernel-to-kernel request only. Never accepted from a userspace IOUserClient. */
#pragma once
#include "copy.h"
enum { NM_ROTATION_SOURCE_LOGICAL = 0u, NM_ROTATION_SOURCE_PHYSICAL = 1u };
struct NMRotationCopyRequest {
    NMRotationMode mode;
    const volatile uint32_t *source;
    uint64_t sourceBytes;
    uint32_t width, height, pitch, format;
    uint32_t sourceLayout, reserved;
};
static_assert(sizeof(NMRotationCopyRequest) == 88, "rotation copy request ABI v9");

// The v9 live test confirms CoreDisplay's preoriented quarter turns have the
// opposite direction to IOFramebuffer's cursor. Turn that physical image by 180
// so both mappings agree. Logical 180 keeps the proven v7 permutation. The ABI
// and accepted layouts stay v9; no row stride is reinterpreted.
static inline bool nmRotationCopyAngle(const NMRotationMode &mode, uint32_t layout,
                                       uint32_t width, uint32_t height, uint32_t *degrees)
{
    if (!degrees || !nmRotationModeValid(&mode)) return false;
    if (layout == NM_ROTATION_SOURCE_LOGICAL && mode.degrees == 180 &&
        width == mode.logicalWidth && height == mode.logicalHeight) {
        *degrees = 180; return true;
    }
    if (layout == NM_ROTATION_SOURCE_PHYSICAL && nmRotationSwaps(mode.degrees) &&
        width == mode.outputWidth && height == mode.outputHeight) {
        *degrees = 180; return true;
    }
    return false;
}

// Exact integer-to-binary32 encoding for bounded dimensions; no kernel FP/SIMD.
static inline uint32_t nmRotationDimensionBits(uint32_t value)
{
    if (!value || value > NM_ROTATION_MAX_DIM) return 0;
    uint32_t exponent = 0;
    for (uint32_t n = value; n > 1; n >>= 1) ++exponent;
    return ((127u + exponent) << 23) | ((value << (23u - exponent)) & 0x7fffffu);
}

static inline bool nmRotationFullPhysicalPlane(const NMRotationMode &mode,
    const uint32_t *sourceRect, const uint32_t *destinationRect, const uint32_t *scaler)
{
    if (!nmRotationModeValid(&mode) || !nmRotationSwaps(mode.degrees) ||
        !sourceRect || !destinationRect || !scaler) return false;
    const uint32_t *rectangles[] = {sourceRect, destinationRect};
    for (const uint32_t *r : rectangles) {
        if ((r[0] & 0x7fffffffu) || (r[1] & 0x7fffffffu) ||
            r[2] != nmRotationDimensionBits(mode.outputWidth) ||
            r[3] != nmRotationDimensionBits(mode.outputHeight)) return false;
    }
    // Accept only the exact no-scaling state observed in the v8 capture.
    for (unsigned i = 0; i < 6; ++i) if (scaler[i] & 0x7fffffffu) return false;
    return true;
}

static inline bool nmRotationSameMode(const NMRotationMode &a, const NMRotationMode &b)
{
    return nmRotationModeValid(&a) && nmRotationModeValid(&b) &&
        a.version == b.version && a.degrees == b.degrees && a.epoch == b.epoch &&
        a.logicalWidth == b.logicalWidth && a.logicalHeight == b.logicalHeight &&
        a.outputWidth == b.outputWidth && a.outputHeight == b.outputHeight &&
        a.outputPitch == b.outputPitch && a.head == b.head && a.modeSequence == b.modeSequence;
}
