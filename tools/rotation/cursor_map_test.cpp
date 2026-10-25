#include <cassert>
#include <cstdio>
#include <initializer_list>
#include "copy_request.h"
#include "../../kexts/NVRMFB/fb/nvrm-rotation.h"

int main()
{
    const unsigned modes[][2] = {{7,5},{1344,756},{1920,1080},{2560,1440},
        {3440,1440},{3840,2160},{5120,1440},{5120,2880},{7680,4320}};
    unsigned points = 0, composed = 0;
    for (const auto &r : modes) for (unsigned angle : {0u,90u,180u,270u}) {
        uint32_t bits = 0; assert(nvrmRotationBits(angle, &bits));
        const unsigned logicalW = nmRotationSwaps(angle) ? r[1] : r[0];
        const unsigned logicalH = nmRotationSwaps(angle) ? r[0] : r[1];
        // Independently reproduce IOFramebuffer::transformLocation's low-bit
        // swap/invert order. The desktop permutation must land on the same pixels.
        for (unsigned y : {0u,logicalH/2,logicalH-1}) for (unsigned x : {0u,logicalW/2,logicalW-1}) {
            unsigned cx=x,cy=y;
            if (bits & 1) {const unsigned t=cx;cx=cy;cy=t;}
            if (bits & 2) cx=r[0]-cx-1;
            if (bits & 4) cy=r[1]-cy-1;
            unsigned dx=0,dy=0;
            assert(nmRotationPixel(angle,logicalW,logicalH,x,y,&dx,&dy));
            assert(dx==cx && dy==cy && dx<r[0] && dy<r[1]);
            ++points;
            if (nmRotationSwaps(angle)) {
                // Observed CoreDisplay image: inverse quarter turn. Its top edge
                // is on the opposite side from IOFramebuffer's cursor mapping.
                const unsigned sx = angle==90 ? y : logicalH-1-y;
                const unsigned sy = angle==90 ? logicalW-1-x : x;
                NMRotationMode mode={NM_ROTATION_VERSION,angle,1,logicalW,logicalH,
                    r[0],r[1],r[0]*4,0,1,1};
                unsigned correction=999;
                assert(nmRotationCopyAngle(mode,NM_ROTATION_SOURCE_PHYSICAL,r[0],r[1],&correction));
                assert(nmRotationPixel(correction,r[0],r[1],sx,sy,&dx,&dy));
                assert(dx==cx && dy==cy);
                ++composed;
            }
        }
    }
    NMRotationMode mode={NM_ROTATION_VERSION,90,7,5,7,7,5,32,0,1,3};
    assert(nmRotationModeValid(&mode) && nmRotationSameMode(mode,mode));
    auto other=mode;
    other.epoch++; assert(!nmRotationSameMode(mode,other)); other=mode;
    other.modeSequence++; assert(!nmRotationSameMode(mode,other)); other=mode;
    other.head++; assert(!nmRotationSameMode(mode,other)); other=mode;
    other.degrees=270; assert(!nmRotationSameMode(mode,other)); other=mode;
    other.ready=0; assert(!nmRotationSameMode(mode,other)); other=mode;
    other.outputPitch+=4; assert(!nmRotationSameMode(mode,other)); other=mode;
    other.logicalWidth++; assert(!nmRotationSameMode(mode,other));
    printf("PASS: %u cursor/desktop coordinates plus %u observed-quarter-turn/correction compositions through 8K; stale request/mode/head/geometry rejected\n",points,composed);
}
