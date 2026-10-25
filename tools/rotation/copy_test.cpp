#include <cassert>
#include <cstdio>
#include <vector>
#include <algorithm>
#include <initializer_list>
#include "copy.h"

static uint32_t pixel(unsigned x, unsigned y) {
    return (x * 0x379283u) ^ (y * 0x73ab194u) ^ 0x678abc12u;
}
int main() {
    const unsigned sizes[][2] = {{1,1},{1,17},{17,1},{7,5},{31,33},{33,31},{1279,719},
        {1344,756},{1920,1080},{2560,1440},{3440,1440},{3840,2160},{2160,3840},
        {5120,1440},{5120,2880},{7680,4320}};
    unsigned cases=0;
    for (const auto &size:sizes) for (unsigned angle:{0u,90u,180u,270u}) {
        const unsigned w=size[0],h=size[1],ow=nmRotationSwaps(angle)?h:w,oh=nmRotationSwaps(angle)?w:h;
        const unsigned sp=w+11,dp=ow+13,guard=19; const uint32_t sentinel=0xdeaf12f3;
        std::vector<uint32_t> source(guard+(size_t)sp*h+guard,sentinel);
        std::vector<uint32_t> dest(guard+(size_t)dp*oh+guard,sentinel);
        for(unsigned y=0;y<h;++y)for(unsigned x=0;x<w;++x) source[guard+(size_t)y*sp+x]=pixel(x,y);
        const auto before=source;
        assert(nmRotationCopy32(source.data()+guard,(uint64_t)sp*h*4,w,h,sp*4,
            dest.data()+guard,(uint64_t)dp*oh*4,ow,oh,dp*4,angle));
        // Independent forward mapping, production implementation reads an inverse map.
        for(unsigned y=0;y<h;++y)for(unsigned x=0;x<w;++x) {
            unsigned dx=x,dy=y;
            if(angle==90){dx=h-1-y;dy=x;}
            if(angle==180){dx=w-1-x;dy=h-1-y;}
            if(angle==270){dx=y;dy=w-1-x;}
            assert(dest[guard+(size_t)dy*dp+dx]==pixel(x,y));
        }
        assert(source==before);
        for(unsigned i=0;i<guard;++i)assert(dest[i]==sentinel&&dest[dest.size()-1-i]==sentinel);
        for(unsigned y=0;y<oh;++y)for(unsigned x=ow;x<dp;++x)assert(dest[guard+(size_t)y*dp+x]==sentinel);
        ++cases;
    }
    uint32_t src[64]={},dst[64]={};
    auto bounds=[&](uint64_t sb,uint64_t db,unsigned w,unsigned h,unsigned sp,unsigned ow,unsigned oh,unsigned dp,unsigned a){
        return nmRotationCopyBounds(src,sb,w,h,sp,dst,db,ow,oh,dp,a);};
    assert(bounds(sizeof src,sizeof dst,7,5,32,5,7,32,90));
    assert(!bounds(sizeof src,sizeof dst,7,5,28,5,7,16,90));
    assert(!bounds(159,sizeof dst,7,5,32,5,7,32,90));
    assert(!bounds(sizeof src,223,7,5,32,5,7,32,90));
    assert(!bounds(sizeof src,sizeof dst,7,5,31,5,7,32,90));
    assert(!bounds(sizeof src,sizeof dst,7,5,32,7,5,32,90));
    assert(!bounds(sizeof src,sizeof dst,7,5,32,7,5,32,45));
    assert(!bounds(sizeof src,sizeof dst,0,5,32,5,0,32,90));
    assert(!nmRotationCopyBounds(src,sizeof src,7,5,32,src,sizeof src,5,7,32,90));
    assert(!nmRotationCopyBounds(src,sizeof src,7,5,32,src+1,sizeof src-4,5,7,32,90));
    assert(!nmRotationCopyBounds((const uint32_t *)(UINTPTR_MAX-3),sizeof src,7,5,32,dst,sizeof dst,5,7,32,90));
    std::fill(std::begin(dst),std::end(dst),0x123abc45u);
    assert(!nmRotationCopy32(src,1,7,5,32,dst,sizeof dst,5,7,32,90));
    for(uint32_t value:dst)assert(value==0x123abc45u);
    printf("PASS: %u exact-pixel cases through 8K; source unchanged, padded rows/guards intact, invalid/overlap/overflow refused before writes\n",cases);
}
