#include <cassert>
#include <cstdio>
#include <initializer_list>
#include "../../kexts/NVRMFB/fb/nvrm-rotation.h"

int main()
{
    const unsigned angles[] = {0,90,180,270};
    const uint32_t bits[] = {0,3,6,5};
    for (unsigned i=0; i<4; ++i) {
        uint32_t encoded=UINT32_MAX;
        assert(nvrmRotationBits(angles[i],&encoded) && encoded==bits[i]);
        assert(nvrmRotationDegrees(encoded)==angles[i]);
        for (unsigned shift : {0u,4u}) {
            uint32_t normalized=0;
            assert(nvrmRotationNormalizeProbe((bits[i]<<shift)<<16|0x0501u,&normalized));
            assert(normalized==(bits[i]<<16|0x0501u));
            // IOGraphics transforms the cursor and reports the logical axes.
            // The presenter, rather than a physical scaler, rotates desktop pixels.
            assert(((normalized>>16)&0xf0u)==0);
        }
    }
    unsigned accepted=0;
    for (uint32_t raw=0;raw<65536;++raw) {
        const bool wanted=raw==0 || raw==3 || raw==5 || raw==6 || raw==0x30 || raw==0x50 || raw==0x60;
        uint32_t out=0xdeadbeefu;
        assert(nvrmRotationNormalizeProbe(raw<<16|0x400u,&out)==wanted);
        if (wanted) {++accepted;assert((out&0xffffu)==0x400u && ((out>>16)&0xf0u)==0);}
        else assert(out==0xdeadbeefu);
        assert(!nvrmRotationNormalizeProbe(raw<<16,&out));
    }
    uint32_t value=0;
    assert(!nvrmRotationNormalizeProbe(0x400,nullptr));
    assert(!nvrmRotationBits(45,&value) && !nvrmRotationBits(90,nullptr));
    assert(accepted==7);
    puts("PASS: 65536 transform encodings; only 0/90/180/270, low compositor output, UI high input, unknown/mixed/reflection rejection");
}
