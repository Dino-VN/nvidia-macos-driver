/* Tahoe CoreDisplay rotation contract. Physical scanout stays raster-oriented. */
#pragma once
#include <stdint.h>

#define NM_ROTATION_IMPLEMENTATION_VERSION 13u
#define NM_NATIVE_ROTATION_PROTOCOL 1u
enum { kNVRMSetTransform = 0x00000400u, kNVRMTransformShift = 16 };

static inline bool nvrmRotationSupportedKernel(int major)
{
    return major == 25; // macOS Tahoe 26; later private layouts need validation.
}

static inline bool nvrmRotationBits(unsigned degrees, uint32_t *bits)
{
    if (!bits) return false;
    switch (degrees) {
    case 0: *bits = 0; return true;
    case 90: *bits = 0x30; return true;
    case 180: *bits = 0x60; return true;
    case 270: *bits = 0x50; return true;
    default: return false;
    }
}

static inline unsigned nvrmRotationDegrees(uint32_t bits)
{
    switch (bits) {
    case 0: return 0;
    case 3: case 0x30: return 90;
    case 6: case 0x60: return 180;
    case 5: case 0x50: return 270;
    default: return UINT32_MAX;
    }
}

// CoreDisplay rotates the desktop; the driver maps the cursor into that raster.
// Accept either public encoding, then consistently use the scaler encoding so
// IOFramebuffer does not apply the earlier low-bit cursor transformation too.
// Reflections, mixed encodings and unknown transform flags are rejected.
static inline bool nvrmRotationNormalizeProbe(uint32_t options, uint32_t *normalized)
{
    if (!normalized || !(options & kNVRMSetTransform)) return false;
    const uint32_t degrees = nvrmRotationDegrees(options >> kNVRMTransformShift);
    uint32_t bits = 0;
    if (!nvrmRotationBits(degrees, &bits)) return false;
    *normalized = (options & 0xffffu) | (bits << kNVRMTransformShift);
    return true;
}
