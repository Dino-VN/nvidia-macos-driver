#include <cassert>
#include <cstdio>
#include <vector>
#include <initializer_list>
#include "source_probe.h"

int main()
{
    unsigned cases=0;
    for (auto size : {NMRotationMode{0,0,0,7,5},NMRotationMode{0,0,0,1920,1080},
                     NMRotationMode{0,0,0,1080,1920},NMRotationMode{0,0,0,3440,1440},
                     NMRotationMode{0,0,0,7680,4320}}) {
        const uint32_t pitch=(size.logicalWidth*4+255)&~255u;
        std::vector<uint32_t> source((size_t)pitch/4*size.logicalHeight,0xaabbccddu);
        for(unsigned y=0;y<size.logicalHeight;++y)for(unsigned x=0;x<size.logicalWidth;++x)
            source[(size_t)y*(pitch/4)+x]=0xff000000u|y*16384+x;
        std::vector<uint32_t> out(NM_ROTATION_PROBE_EDGE*NM_ROTATION_PROBE_EDGE+1,0x12345678);
        NMRotationSourceProbe h={};h.sourceWidth=size.logicalWidth;h.sourceHeight=size.logicalHeight;h.sourcePitch=pitch;
        assert(nmRotationProbePixels(&h,source.data(),source.size()*4,out.data(),(out.size()-1)*4));
        assert(h.imageWidth<=640&&h.imageHeight<=640&&h.headerBytes==160&&h.pixelBytes<=out.size()*4-4);
        assert(out.back()==0x12345678);
        for(unsigned y=0;y<h.imageHeight;++y)for(unsigned x=0;x<h.imageWidth;++x) {
            const size_t sx=(uint64_t)x*h.sourceWidth/h.imageWidth,sy=(uint64_t)y*h.sourceHeight/h.imageHeight;
            assert(out[(size_t)y*h.imageWidth+x]==source[sy*(pitch/4)+sx]);
        }
        const auto saved=out;
        assert(!nmRotationProbePixels(&h,source.data(),4,out.data(),out.size()*4)&&out==saved);
        assert(!nmRotationProbePixels(&h,source.data(),source.size()*4,source.data(),source.size()*4));
        assert(!nmRotationProbePixels(&h,source.data(),source.size()*4,out.data(),4)&&out==saved);
        ++cases;
    }
    assert(!nmRotationProbeGeometry(UINT64_MAX,2,4,16));
    assert(!nmRotationProbeGeometry(2,2,UINT64_MAX,16));
    assert(!nmRotationProbeGeometry(16384,16384,65536,1024ull*1024*1024));
    puts("PASS: bounded source samples through 8K, portrait/landscape/ultrawide layout, pitch/padding and overlap/size rejection");
    assert(cases==5);
}
