/* DVI mode selection. SPDX-License-Identifier: PolyForm-Noncommercial-1.0.0 */
#pragma once
#include "nvkms-kapi.h"

// Enumeration validates NVKMS's internal mode, while KAPI returns a converted
// mode. A converted timing can fail explicit validation after losing metadata.
// Replace it only with an enumerated, explicitly validated mode at the same
// visible resolution. Keep a working initial mode and all validation limits.
static inline bool nvrmDviSelectSameRasterMode(
    const struct NvKmsKapiFunctionsTable *kms, struct NvKmsKapiDevice *device,
    NvKmsKapiDisplay display, const struct NvKmsKapiDisplayMode *original,
    struct NvKmsKapiDisplayMode *replacement, NvU32 *replacementIndex)
{
    if (!kms || !device || !display || !original || !replacement || !replacementIndex ||
        !kms->getDisplayMode || !kms->validateDisplayMode ||
        !original->timings.hVisible || !original->timings.vVisible ||
        !original->timings.refreshRate || kms->validateDisplayMode(device, display, original)) return false;

    bool have = false;
    NvU32 bestGap = 0, bestIndex = 0;
    struct NvKmsKapiDisplayMode best = {};
    for (NvU32 i = 0; i < 256; i++) {
        struct NvKmsKapiDisplayMode mode = {};
        NvBool valid = NV_FALSE, preferred = NV_FALSE;
        const int result = kms->getDisplayMode(device, display, i, &mode, &valid, &preferred);
        if (result < 0) return false; // An enumeration error changes nothing.
        if (result == 0) break;
        const struct NvKmsKapiDisplayModeTimings &t = mode.timings;
        if (!valid || t.hVisible != original->timings.hVisible ||
            t.vVisible != original->timings.vVisible || t.flags.interlaced ||
            t.flags.doubleScan || !t.pixelClockHz || !t.refreshRate ||
            !kms->validateDisplayMode(device, display, &mode)) continue;
        const NvU32 gap = t.refreshRate > original->timings.refreshRate ?
            t.refreshRate - original->timings.refreshRate : original->timings.refreshRate - t.refreshRate;
        if (!have || gap < bestGap || (gap == bestGap && t.pixelClockHz < best.timings.pixelClockHz)) {
            best = mode;
            bestGap = gap;
            bestIndex = i;
            have = true;
        }
    }
    if (!have) return false;
    *replacement = best;
    *replacementIndex = bestIndex;
    return true;
}
