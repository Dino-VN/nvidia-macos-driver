#include <cassert>
#include <cstdio>
#include <initializer_list>
#include "resolution.h"

int main()
{
    unsigned cases = 0;
    for (auto m : {NMRotationResolution{1920,1080,1920,1080,75000},
                   NMRotationResolution{1720,720,3440,1440,144000},
                   NMRotationResolution{3840,2160,7680,4320,59940},
                   NMRotationResolution{1279,719,1279,719,0}}) {
        for (unsigned from : {0u,90u,180u,270u}) for (unsigned to : {0u,90u,180u,270u}) {
            NMRotationResolution target = {}, restored = {};
            assert(nmRotationResolutionTarget(m,from,to,&target));
            assert((uint64_t)target.pixelWidth * target.pixelHeight == (uint64_t)m.pixelWidth * m.pixelHeight);
            assert(target.milliHz == m.milliHz);
            assert(target.width == (nmRotationSwaps(from) != nmRotationSwaps(to) ? m.height : m.width));
            assert(nmRotationResolutionTarget(target,to,from,&restored));
            assert(nmRotationResolutionMatches(m,restored));
            ++cases;
        }
    }
    NMRotationResolution native = {1920,1080,1920,1080,75000};
    for (auto bad : {NMRotationResolution{1600,900,1600,900,75000},
                     NMRotationResolution{1920,1080,1920,1080,60000},
                     NMRotationResolution{1920,1080,3840,2160,75000},
                     NMRotationResolution{1920,1080,1920,1080,0},
                     NMRotationResolution{1920,1080,1920,1080,75501}})
        assert(!nmRotationResolutionMatches(native,bad));
    auto fractional=native;fractional.milliHz=74973;assert(nmRotationResolutionMatches(native,fractional));
    auto invalid=native;invalid.pixelWidth=UINT32_MAX;
    assert(!nmRotationResolutionValid(invalid));
    assert(!nmRotationResolutionTarget(native,45,90,&fractional));
    assert(!nmRotationResolutionTarget(native,0,90,nullptr));
    printf("PASS: %u rotation/resolution round trips, HiDPI/ultrawide/8K, fractional refresh, lower-resolution and refresh fallback refusal\n",cases);
}
