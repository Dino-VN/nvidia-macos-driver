/* Preserve the selected pixel density and refresh rate across a rotation. */
#pragma once
#include "shared.h"

struct NMRotationResolution {
    uint32_t width, height, pixelWidth, pixelHeight, milliHz;
};

static inline bool nmRotationResolutionValid(const NMRotationResolution &m)
{
    return m.width && m.height && m.pixelWidth && m.pixelHeight &&
        m.width <= NM_ROTATION_MAX_DIM && m.height <= NM_ROTATION_MAX_DIM &&
        m.pixelWidth <= NM_ROTATION_MAX_DIM && m.pixelHeight <= NM_ROTATION_MAX_DIM &&
        m.milliHz <= 1000000;
}

static inline bool nmRotationResolutionTarget(const NMRotationResolution &before,
    unsigned from, unsigned to, NMRotationResolution *after)
{
    if (!after || !nmRotationResolutionValid(before) || !nmRotationValid(from) || !nmRotationValid(to))
        return false;
    *after = before;
    if (nmRotationSwaps(from) != nmRotationSwaps(to)) {
        after->width = before.height; after->height = before.width;
        after->pixelWidth = before.pixelHeight; after->pixelHeight = before.pixelWidth;
    }
    return true;
}

// Zero refresh is unknown, not a wildcard for replacing a known refresh rate.
static inline bool nmRotationResolutionMatches(const NMRotationResolution &a, const NMRotationResolution &b)
{
    const unsigned delta = a.milliHz > b.milliHz ? a.milliHz - b.milliHz : b.milliHz - a.milliHz;
    return nmRotationResolutionValid(a) && nmRotationResolutionValid(b) &&
        a.width == b.width && a.height == b.height && a.pixelWidth == b.pixelWidth &&
        a.pixelHeight == b.pixelHeight && ((!a.milliHz && !b.milliHz) || (a.milliHz && b.milliHz && delta <= 500));
}
