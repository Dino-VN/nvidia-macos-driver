/* Display rotation contract. Native physical modes remain unchanged. */
#pragma once
#include <stdint.h>

#define NM_ROTATION_IMPLEMENTATION_VERSION 12u
enum { kNVRMSetTransform = 0x00000400u, kNVRMTransformShift = 16 };

static inline bool nvrmRotationSupportedKernel(int major)
{
    return major == 25; // macOS Tahoe 26; later private layouts need validation.
}

// The v8 live capture shows this contract yields a complete preoriented physical
// image for quarter turns, rather than v7's cropped landscape image. V10 corrects
// its opposite direction to align with the cursor. No NVKMS rotation is claimed.
static inline bool nvrmRotationDriverBacked(bool rotationEnabled, uint32_t requestedBits)
{
    return rotationEnabled && (requestedBits == 3u || requestedBits == 5u);
}

static inline bool nvrmRotationBits(unsigned degrees, uint32_t *bits)
{
    if (!bits) return false;
    switch (degrees) {
    case 0: *bits = 0; return true;
    case 90: *bits = 3; return true;
    case 180: *bits = 6; return true;
    case 270: *bits = 5; return true;
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

// Low bits let IOGraphics transform the cursor and report logical axes. They do
// not rotate desktop pixels: the mode contract and presenter handle that image.
// High scaler encodings are accepted as UI input, then normalized to low bits.
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
