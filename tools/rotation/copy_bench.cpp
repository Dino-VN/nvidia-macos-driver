#include <cstdio>
#include <vector>
#include <chrono>
#include <algorithm>
#include "copy.h"
int main() {
    const unsigned sizes[][2]={{1344,756},{1920,1080},{2560,1440},{3840,2160},{7680,4320}};
    for(const auto &size:sizes)for(unsigned a:{90u,180u,270u}) {
        const unsigned w=size[0],h=size[1],ow=nmRotationSwaps(a)?h:w,oh=nmRotationSwaps(a)?w:h;
        uint32_t sp=0,dp=0;uint64_t sb=0,db=0;
        if(!nmRotationPitch(w,h,256,&sp,&sb)||!nmRotationPitch(ow,oh,256,&dp,&db))return 1;
        std::vector<uint32_t> s(sb/4,0x12345678),d(db/4);std::vector<double> ms;
        for(unsigned n=0;n<13;++n){
            auto start=std::chrono::steady_clock::now();
            if(!nmRotationCopy32(s.data(),sb,w,h,sp,d.data(),db,ow,oh,dp,a))return 1;
            auto end=std::chrono::steady_clock::now();
            if(n)ms.push_back(std::chrono::duration<double,std::milli>(end-start).count());
        }
        std::sort(ms.begin(),ms.end());
        printf("{\"source_width\":%u,\"source_height\":%u,\"degrees\":%u,\"median_ms\":%.3f,\"max_ms\":%.3f,\"scope\":\"cached system memory only, excludes GPU pageoff, BAR stores and presentation\"}\n",w,h,a,ms[ms.size()/2],ms.back());
    }
}
