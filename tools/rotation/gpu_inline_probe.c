/* Offscreen C-only probe: loads the candidate plugin's Vulkan helpers, no Metal device or desktop rotation. */
#include <dlfcn.h>
#include <mach/mach.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "../../plugin/nvmtl_vk.h"
#define FN(name) __typeof__(&name) p_##name=(__typeof__(&name))dlsym(library,#name);if(!p_##name){fprintf(stderr,"missing %s\n",#name);return 2;}
static uint32_t pattern(unsigned x,unsigned y){return ((x*17+y*31)&255u)|(((x*7+y*13)&255u)<<8)|(((x*43+y*3)&255u)<<16)|(((x*53+y*11)&255u)<<24);}
int main(int argc,char **argv) {
    if(argc!=2)return 2;
    void *library=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL);if(!library){fprintf(stderr,"dlopen: %s\n",dlerror());return 2;}
    FN(nvmtl_vk_init);FN(nvmtl_vk_queue_create);FN(nvmtl_vk_queue_destroy);FN(nvmtl_vk_buffer_create);FN(nvmtl_vk_buffer_destroy);
    FN(nvmtl_vk_heap_create);FN(nvmtl_vk_heap_destroy);FN(nvmtl_vk_buffer_create_placed);
    FN(nvmtl_vk_copy_buffer);FN(nvmtl_vk_rotation_buffer_alias);FN(nvmtl_vk_rotation_buffer_release);
    FN(nvmtl_vk_cmd_begin);FN(nvmtl_vk_cmd_rotation_180);FN(nvmtl_vk_submit_wait_at);FN(nvmtl_vk_cmd_abandon);
    if(p_nvmtl_vk_init())return 2;
    nvk_queue queue={};if(p_nvmtl_vk_queue_create(&queue))return 2;
    const unsigned sizes[][2]={{7,5},{1,17},{17,1},{1279,719},{1920,1080},{1080,1920},{3440,1440},{3840,2160},{7680,4320}};
    unsigned cases=0;uint64_t totalBad=0;
    puts("{\"scope\":\"candidate production raw-buffer compute helper, offscreen VRAM; no display/driver install\",\"cases\":[");fflush(stdout);
    for(unsigned format=44;format<=50;format+=6)for(unsigned index=0;index<sizeof(sizes)/sizeof(sizes[0]);++index) {
        unsigned width=sizes[index][0],height=sizes[index][1],pitch=(width*4+19+255)&~255u;
        size_t bytes=((size_t)pitch*height+65535)&~(size_t)65535;
        nvk_buffer upload={},readback={},source={},destination={},si={},di={};nvk_heap sourceHeap={},destinationHeap={};
        int rc;
        #define CHECK(label,call) do { rc=(call); if(rc){fprintf(stderr,"%s %ux%u bytes %zu rc %d src sparse %d dst sparse %d\n",label,width,height,bytes,rc,source.sparse,destination.sparse);return 3;} } while(0)
        CHECK("upload allocation",p_nvmtl_vk_buffer_create(bytes,1,&upload));
        CHECK("readback allocation",p_nvmtl_vk_buffer_create(bytes,1,&readback));
        CHECK("source heap",p_nvmtl_vk_heap_create(bytes,0,&sourceHeap));
        CHECK("destination heap",p_nvmtl_vk_heap_create(bytes,0,&destinationHeap));
        CHECK("source allocation",p_nvmtl_vk_buffer_create_placed(bytes,&sourceHeap,0,&source));
        CHECK("destination allocation",p_nvmtl_vk_buffer_create_placed(bytes,&destinationHeap,0,&destination));
        uint32_t *input=upload.map;for(size_t i=0;i<bytes/4;++i)input[i]=0x12345678u;
        for(unsigned y=0;y<height;++y)for(unsigned x=0;x<width;++x)input[(size_t)y*pitch/4+x]=pattern(x,y);
        CHECK("source upload",p_nvmtl_vk_copy_buffer(&queue,&upload,0,&source,0,bytes));
        for(size_t i=0;i<bytes/4;++i)((uint32_t *)readback.map)[i]=0x526f7447u;
        CHECK("destination initialize",p_nvmtl_vk_copy_buffer(&queue,&readback,0,&destination,0,bytes));
        CHECK("source alias",p_nvmtl_vk_rotation_buffer_alias(&source,&si));
        CHECK("destination alias",p_nvmtl_vk_rotation_buffer_alias(&destination,&di));
        nvk_cmdbuf command={};if(p_nvmtl_vk_cmd_begin(&queue,&command))return 3;
        if(p_nvmtl_vk_cmd_rotation_180(&command,&si,&si,width,height,pitch,pitch)!=-1||
           p_nvmtl_vk_cmd_rotation_180(&command,&si,&di,width,height,pitch-1,pitch)!=-1||
           p_nvmtl_vk_cmd_rotation_180(&command,&si,&di,width+pitch,height,pitch,pitch)!=-1)return 4;
        struct timespec a,b;clock_gettime(CLOCK_MONOTONIC,&a);
        int rotated=p_nvmtl_vk_cmd_rotation_180(&command,&si,&di,width,height,pitch,pitch);
        if(rotated){p_nvmtl_vk_cmd_abandon(&command);fprintf(stderr,"compute refused %ux%u rc %d\n",width,height,rotated);return 4;}
        if(p_nvmtl_vk_submit_wait_at(&command,"rotation GPU offscreen probe"))return 5;
        clock_gettime(CLOCK_MONOTONIC,&b);
        double elapsed=(b.tv_sec-a.tv_sec)*1000.0+(b.tv_nsec-a.tv_nsec)/1e6;
        if(p_nvmtl_vk_copy_buffer(&queue,&destination,0,&readback,0,bytes))return 5;
        uint64_t bad=0,padding=0;
        for(size_t i=0;i<bytes/4;++i) {
            size_t y=i/(pitch/4),x=i%(pitch/4);uint32_t expected=y<height&&x<width?pattern(width-1-(unsigned)x,height-1-(unsigned)y):0x526f7447u;
            if(((uint32_t *)readback.map)[i]!=expected){if(y<height&&x<width)++bad;else ++padding;}
        }
        if(p_nvmtl_vk_copy_buffer(&queue,&source,0,&readback,0,bytes))return 5;
        uint64_t changed=memcmp(readback.map,input,bytes)!=0;
        printf("%s{\"width\":%u,\"height\":%u,\"pitch\":%u,\"format\":%u,\"mismatched_pixels\":%llu,\"padding_writes\":%llu,\"source_changed\":%llu,\"submit_wait_ms\":%.3f}",cases?",\n":"",width,height,pitch,format,(unsigned long long)bad,(unsigned long long)padding,(unsigned long long)changed,elapsed);fflush(stdout);
        totalBad+=bad+padding+changed;++cases;
        p_nvmtl_vk_rotation_buffer_release(&di);p_nvmtl_vk_rotation_buffer_release(&si);
        p_nvmtl_vk_buffer_destroy(&destination);p_nvmtl_vk_buffer_destroy(&source);p_nvmtl_vk_heap_destroy(&destinationHeap);p_nvmtl_vk_heap_destroy(&sourceHeap);p_nvmtl_vk_buffer_destroy(&readback);p_nvmtl_vk_buffer_destroy(&upload);
    }

    // Two differently sized outputs in ONE recording exercise descriptor and
    // push-constant isolation when a compositor updates multiple displays.
    const unsigned pairedWidths[2]={1279,2560},pairedHeights[2]={719,1440};
    unsigned pairPitch[2];size_t pairBytes[2];
    nvk_buffer up[2]={},down[2]={},src[2]={},dst[2]={},srcAlias[2]={},dstAlias[2]={};
    nvk_heap srcHeap[2]={},dstHeap[2]={};
    #define PAIR_CHECK(call) do { int result=(call);if(result){fprintf(stderr,"paired GPU operation refused: %s (%d)\n",#call,result);return 6;} } while(0)
    for(unsigned i=0;i<2;++i) {
        pairPitch[i]=(pairedWidths[i]*4+19+255)&~255u;
        pairBytes[i]=((size_t)pairPitch[i]*pairedHeights[i]+65535)&~(size_t)65535;
        PAIR_CHECK(p_nvmtl_vk_buffer_create(pairBytes[i],1,&up[i]));
        PAIR_CHECK(p_nvmtl_vk_buffer_create(pairBytes[i],1,&down[i]));
        PAIR_CHECK(p_nvmtl_vk_heap_create(pairBytes[i],0,&srcHeap[i]));
        PAIR_CHECK(p_nvmtl_vk_heap_create(pairBytes[i],0,&dstHeap[i]));
        PAIR_CHECK(p_nvmtl_vk_buffer_create_placed(pairBytes[i],&srcHeap[i],0,&src[i]));
        PAIR_CHECK(p_nvmtl_vk_buffer_create_placed(pairBytes[i],&dstHeap[i],0,&dst[i]));
        for(size_t j=0;j<pairBytes[i]/4;++j)((uint32_t *)up[i].map)[j]=0x12345678u;
        for(unsigned y=0;y<pairedHeights[i];++y)for(unsigned x=0;x<pairedWidths[i];++x)
            ((uint32_t *)up[i].map)[(size_t)y*pairPitch[i]/4+x]=pattern(x,y)^(0x01010101u*i);
        PAIR_CHECK(p_nvmtl_vk_copy_buffer(&queue,&up[i],0,&src[i],0,pairBytes[i]));
        for(size_t j=0;j<pairBytes[i]/4;++j)((uint32_t *)down[i].map)[j]=0x526f7447u;
        PAIR_CHECK(p_nvmtl_vk_copy_buffer(&queue,&down[i],0,&dst[i],0,pairBytes[i]));
        PAIR_CHECK(p_nvmtl_vk_rotation_buffer_alias(&src[i],&srcAlias[i]));
        PAIR_CHECK(p_nvmtl_vk_rotation_buffer_alias(&dst[i],&dstAlias[i]));
    }
    nvk_cmdbuf pair={};PAIR_CHECK(p_nvmtl_vk_cmd_begin(&queue,&pair));
    for(unsigned i=0;i<2;++i)PAIR_CHECK(p_nvmtl_vk_cmd_rotation_180(&pair,&srcAlias[i],&dstAlias[i],pairedWidths[i],pairedHeights[i],pairPitch[i],pairPitch[i]));
    PAIR_CHECK(p_nvmtl_vk_submit_wait_at(&pair,"paired rotation GPU check"));
    uint64_t pairedBad=0;
    for(unsigned i=0;i<2;++i) {
        PAIR_CHECK(p_nvmtl_vk_copy_buffer(&queue,&dst[i],0,&down[i],0,pairBytes[i]));
        for(size_t j=0;j<pairBytes[i]/4;++j) {
            size_t y=j/(pairPitch[i]/4),x=j%(pairPitch[i]/4);
            uint32_t expected=y<pairedHeights[i]&&x<pairedWidths[i]?
                pattern(pairedWidths[i]-1-(unsigned)x,pairedHeights[i]-1-(unsigned)y)^(0x01010101u*i):0x526f7447u;
            pairedBad+=((uint32_t *)down[i].map)[j]!=expected;
        }
        PAIR_CHECK(p_nvmtl_vk_copy_buffer(&queue,&src[i],0,&down[i],0,pairBytes[i]));
        pairedBad+=memcmp(down[i].map,up[i].map,pairBytes[i])!=0;
        p_nvmtl_vk_rotation_buffer_release(&dstAlias[i]);p_nvmtl_vk_rotation_buffer_release(&srcAlias[i]);
        p_nvmtl_vk_buffer_destroy(&dst[i]);p_nvmtl_vk_buffer_destroy(&src[i]);
        p_nvmtl_vk_heap_destroy(&dstHeap[i]);p_nvmtl_vk_heap_destroy(&srcHeap[i]);
        p_nvmtl_vk_buffer_destroy(&down[i]);p_nvmtl_vk_buffer_destroy(&up[i]);
    }
    totalBad+=pairedBad;
    printf("\n],\"paired_outputs\":2,\"paired_mismatches\":%llu,\"passed\":%s,\"total_mismatches\":%llu}\n",(unsigned long long)pairedBad,totalBad?"false":"true",(unsigned long long)totalBad);
    p_nvmtl_vk_queue_destroy(&queue);return totalBad?1:0;
}
