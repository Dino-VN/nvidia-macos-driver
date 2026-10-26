#include <cassert>
#include <cstdio>
#include "../../kexts/NVRMFB/fb/nvrm-rotation.h"
int main()
{
    unsigned accepted = 0;
    for (unsigned bits = 0; bits < 65536; ++bits) {
        uint32_t canonical = 0;
        const bool allowed = bits == 0 || bits == 3 || bits == 5 || bits == 6 ||
                             bits == 0x30 || bits == 0x50 || bits == 0x60;
        assert(nvrmRotationNormalizeProbe(kNVRMSetTransform | bits << 16, &canonical) == allowed);
        if (!allowed) continue;
        const unsigned angle = nvrmRotationDegrees(bits);
        assert(nvrmRotationDegrees(canonical >> 16) == angle);
        assert((canonical >> 16) == 0 || (canonical >> 16) >= 0x30);
        ++accepted;
    }
    uint32_t result = 0;
    assert(!nvrmRotationNormalizeProbe(0, &result));
    assert(!nvrmRotationNormalizeProbe(kNVRMSetTransform, nullptr));
    assert(!nvrmRotationBits(45, &result));
    assert(nvrmRotationSupportedKernel(25) && !nvrmRotationSupportedKernel(24) && !nvrmRotationSupportedKernel(26));
    printf("PASS: 65536 transform encodings, %u accepted; canonical scaler encoding, unknown/reflected/mixed refusal and Tahoe gate\n", accepted);
}
