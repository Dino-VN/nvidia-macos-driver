#include <cassert>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include "copy_request.h"

int main()
{
    for (unsigned dimension = 1; dimension <= NM_ROTATION_MAX_DIM; ++dimension) {
        const float value = (float)dimension;
        uint32_t bits = 0; memcpy(&bits, &value, sizeof bits);
        assert(nmRotationDimensionBits(dimension) == bits);
    }
    assert(!nmRotationDimensionBits(0) && !nmRotationDimensionBits(16385));
    const unsigned sizes[][2] = {{1,1},{7,5},{1920,1080},{1080,1920},{2560,1440},
        {3440,1440},{3840,2160},{5120,2880},{7680,4320},{16384,16384}};
    unsigned cases = 0;
    for (const auto &size : sizes) for (unsigned angle : {0u,90u,180u,270u}) {
        const bool quarter = nmRotationSwaps(angle);
        NMRotationMode mode={NM_ROTATION_VERSION,angle,9,
            quarter?size[1]:size[0],quarter?size[0]:size[1],size[0],size[1],size[0]*4,0,1,2};
        uint32_t src[]={0,0,nmRotationDimensionBits(size[0]),nmRotationDimensionBits(size[1])};
        uint32_t dst[4];memcpy(dst,src,sizeof dst);uint32_t scaler[6]={};
        assert(nmRotationFullPhysicalPlane(mode,src,dst,scaler)==quarter);
        uint32_t copyAngle=999;
        assert(nmRotationCopyAngle(mode,NM_ROTATION_SOURCE_PHYSICAL,size[0],size[1],&copyAngle)==quarter);
        if(quarter)assert(copyAngle==180);
        assert(nmRotationCopyAngle(mode,NM_ROTATION_SOURCE_LOGICAL,mode.logicalWidth,mode.logicalHeight,&copyAngle)==(angle==180));
        if(angle==180)assert(copyAngle==180);
        assert(!nmRotationCopyAngle(mode,2,size[0],size[1],&copyAngle));
        assert(!nmRotationCopyAngle(mode,NM_ROTATION_SOURCE_PHYSICAL,size[0],size[1],nullptr));
        assert(!nmRotationFullPhysicalPlane(mode,nullptr,dst,scaler));
        assert(!nmRotationFullPhysicalPlane(mode,src,nullptr,scaler));
        assert(!nmRotationFullPhysicalPlane(mode,src,dst,nullptr));
        for(uint32_t *rectangle : {src,dst}) for(unsigned i=0;i<4;++i) {
            const uint32_t saved=rectangle[i];
            for(uint32_t bad : {0x7fc00000u,0x7f800000u,0xff800000u,0x3f800000u}) {
                if(bad==saved)continue;
                rectangle[i]=bad;assert(!nmRotationFullPhysicalPlane(mode,src,dst,scaler));
            }
            rectangle[i]=saved;
        }
        for(unsigned i=0;i<6;++i) {
            scaler[i]=0x3f800000;assert(!nmRotationFullPhysicalPlane(mode,src,dst,scaler));scaler[i]=0;
        }
        mode.version=7;assert(!nmRotationFullPhysicalPlane(mode,src,dst,scaler));
        assert(!nmRotationCopyAngle(mode,NM_ROTATION_SOURCE_PHYSICAL,size[0],size[1],&copyAngle));
        ++cases;
    }
    printf("PASS: all 16384 dimension encodings; %u plane/layout contracts including square/portrait/8K/max size; offsets, NaN/Inf, scaling, old ABI and invalid layouts rejected\n",cases);
}
