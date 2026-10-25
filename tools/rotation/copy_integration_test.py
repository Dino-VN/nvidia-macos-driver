#!/usr/bin/env python3
"""Run the production copy presenter and framebuffer method with gated host stubs."""
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[2]
accel = (root / 'kexts/NVRM/accel/nvrm-accel.cpp').read_text()
fb = (root / 'kexts/NVRMFB/fb/nvrm-fb.cpp').read_text()
a = accel.index('static bool nvRotationRequested(IOService *fb)\n{')
present = accel[a:accel.index('\nIOReturn NVAccel::callPlatformFunction', a)]
a = fb.index('IOReturn NVRMNVDAFramebuffer::rotationCopy(')
opening=fb.index('{',a); end=opening+1; depth=1
while depth:
    depth += (fb[end]=='{')-(fb[end]=='}'); end+=1
copy=fb[a:end]
fixture = r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <vector>
#include <thread>
#include <atomic>
#include <mutex>
#include <chrono>
#include "copy_request.h"
#include "gpu_state.h"
#include "source_probe.h"
using IOReturn=int;using SInt64=int64_t;using UInt64=uint64_t;
enum {kIOReturnSuccess=0,kIOReturnNotReady=-1,kIOReturnBadArgument=-2,kIOReturnBusy=-3,kIOReturnIOError=-4,kIOReturnNoMemory=-5,NV_KMS_FLIP_RESULT_IN_PROGRESS=5};
#define ALOG(...) ((void)0)
static std::recursive_mutex displayLock;
static thread_local unsigned gateDepth;
struct NVRMDisplayGate {
    NVRMDisplayGate(){displayLock.lock();++gateDepth;}
    ~NVRMDisplayGate(){--gateDepth;displayLock.unlock();}
    bool valid(){return true;}
};
struct OSObject{virtual ~OSObject(){};virtual void release(){}};
struct OSNumber:OSObject{unsigned value=0;unsigned unsigned32BitValue(){return value;}};
struct OSSymbol:OSObject {
    const char *name;explicit OSSymbol(const char *n):name(n){}
    static const OSSymbol *withCStringNoCopy(const char *s){return new OSSymbol(s);}
    void release()const{delete this;}
};
#define OSDynamicCast(C,p) dynamic_cast<C *>(p)
#define OSSafeReleaseNULL(p) do { if(p){p->release();p=nullptr;} } while(0)
static OSObject yes;
static OSObject *kOSBooleanTrue=&yes;
struct IOService {
    virtual OSObject *getProperty(const char *)=0;
    virtual OSObject *copyProperty(const char *)=0;
    virtual IOReturn callPlatformFunction(const OSSymbol *,bool,void *,void *,void *,void *)=0;
};
struct IOMemoryDescriptor {void *data;uint64_t bytes;};
struct IOSurface {
    unsigned w=7,h=5,pitch=32,fmt=0x42475241u,id=9;IOMemoryDescriptor descriptor;
    uint64_t getWidth(){return w;}uint64_t getHeight(){return h;}uint64_t getBytesPerRow(){return pitch;}
    unsigned getPixelFormat(){return fmt;}unsigned getSurfaceID(){return id;}
    IOMemoryDescriptor *getMemoryDescriptor(){return &descriptor;}
};
static unsigned waits,pageoffs,maps;static bool gpuReady=true,cpuReady=true,pending=false,asyncBusy=false;
static bool nvSurfWaitReady(unsigned){assert(!gateDepth);++waits;return gpuReady;}
static bool familyHeld=true;
static unsigned cacheLookups;
struct NVResource:OSObject{
    alignas(8) unsigned char storage[128]={};unsigned short valid[8]={};bool wrote=true;
    NVResource(){auto *p=valid;memcpy((unsigned char *)this+0x30,&p,sizeof p);}
    void pageoff(void *,bool,bool *out,unsigned long long){assert(familyHeld&&!gateDepth);++pageoffs;*out=cpuReady;if(cpuReady)valid[0]|=1;}
};
struct NVAccel{static NVAccel *gAccel;};NVAccel instance;NVAccel *NVAccel::gAccel=&instance;
static NVResource resource;
struct Cache:OSObject{
    alignas(8) unsigned char bytes[64]={};unsigned releases=0;
    Cache(){OSObject *p=&resource;memcpy((unsigned char *)this+0x20,&p,sizeof p);}
    void release()override{++releases;}
};
static Cache cache;static bool haveCache=true;
static void *_ZN22IOGraphicsAccelerator223deviceCacheForIOSurfaceEP9IOSurfacej(void *,void *,unsigned){
    assert(familyHeld&&!gateDepth);++cacheLookups;return haveCache?&cache:nullptr;
}
static bool nvAccelResPluginWrote(NVResource *r){return r->wrote;}
static bool nvAccelIopCopyNeedsPageoff(bool cpu,bool wrote){return !cpu&&wrote;}
static bool nvSVPend(unsigned,int op){if(op==0)pending=false;return pending;}
struct NVDisplayPipe {
    const void *iopMapSurface(unsigned,IOMemoryDescriptor *md,uint64_t bytes){assert(!gateDepth);++maps;return bytes<=md->bytes?md->data:nullptr;}
};
static bool nvAccelIopAsyncBusy(const void *){return asyncBusy;}
static void nvRotationGPUObserve(IOService *,IOSurface *,const NMRotationMode &){}
static int nvRotationGPUTry(IOService *,unsigned,IOSurface *,const NMRotationMode &){return -1;}
struct IOAccelDisplayPipeTransaction2 {
    void *opaque[7]={};unsigned char *args;alignas(4) unsigned char storage[0x108]={};
    IOAccelDisplayPipeTransaction2():args(storage){}
    void full(unsigned w,unsigned h){
        memset(storage,0,sizeof storage);args=storage;
        uint32_t rect[4]={0,0,nmRotationDimensionBits(w),nmRotationDimensionBits(h)};
        memcpy(args+0x48,rect,sizeof rect);memcpy(args+0x58,rect,sizeof rect);
    }
};
static_assert(offsetof(IOAccelDisplayPipeTransaction2,args)==0x38);
static bool probeArmed=false;static unsigned probes=0;
static bool nvRotationProbeArmed(unsigned){return probeArmed;}
static void nvRotationProbeCapture(const NMRotationMode &,IOSurface *,IOAccelDisplayPipeTransaction2 *,const void *,uint64_t){++probes;probeArmed=false;}
static bool gIopFlipped[5];static SInt64 gCntRotationCopy,gCntRotationSkip,gCntRotationBadGeometry;
static const unsigned kNvMaxFB=5;static SInt64 gCntRotationCopyHead[kNvMaxFB];
static SInt64 gRotationCopyUs,gRotationCopyMaxUs;
static SInt64 OSAddAtomic64(SInt64 n,SInt64 *p){SInt64 old=*p;*p+=n;return old;}
static bool OSCompareAndSwap64(UInt64 a,UInt64 b,volatile UInt64 *p){if(*p!=a)return false;*p=b;return true;}
static uint64_t mach_absolute_time(){static uint64_t now;return now+=1000;}
static void absolutetime_to_nanoseconds(uint64_t t,uint64_t *n){*n=t;}
struct NVRMNVDAFramebuffer:IOService {
    NMRotationMode mode={NM_ROTATION_VERSION,180,1,7,5,7,5,32,0,1,0};
    bool rotationEnabled=true,ready=true,homeSucceeds=true,fRotationGPUFlipActive=false;unsigned infoCalls=0,copyCalls=0,homeCalls=0;
    void *fKva=nullptr,*fSurf=this,*fMem=this,*fFrontSurf=this;uint64_t fMemBytes=0;
    unsigned fW=7,fH=5,fPitch=32;OSNumber number;
    std::atomic<bool> pause{false},entered{false},resume{false};
    OSObject *getProperty(const char *)override{return rotationEnabled?kOSBooleanTrue:nullptr;}
    OSObject *copyProperty(const char *)override{number.value=mode.degrees;return &number;}
    IOReturn rotationMode(NMRotationMode *out){
        NVRMDisplayGate gate;
        if(pause){entered=true;while(!resume)std::this_thread::yield();}
        if(!ready)return kIOReturnNotReady;*out=mode;return kIOReturnSuccess;
    }
    bool flipToMemory(void *,unsigned,unsigned,unsigned,int *rc,bool,uint64_t cookie=0){
        assert(gateDepth);++homeCalls;*rc=homeSucceeds?0:NV_KMS_FLIP_RESULT_IN_PROGRESS;
        if(homeSucceeds)fFrontSurf=fSurf;return homeSucceeds;
    }
    IOReturn rotationCopy(const NMRotationCopyRequest *);
    IOReturn callPlatformFunction(const OSSymbol *s,bool,void *p,void *,void *,void *)override{
        if(!strcmp(s->name,NM_ROTATION_INFO)){++infoCalls;return rotationMode((NMRotationMode *)p);}
        assert(!strcmp(s->name,NM_ROTATION_COPY));++copyCalls;return rotationCopy((const NMRotationCopyRequest *)p);
    }
};
@@COPY@@
@@PRESENT@@
int main(){
    NVRMNVDAFramebuffer fb;NVDisplayPipe pipe;IOSurface source;
    std::vector<uint32_t> src(40),dst(40,0x12345678);
    for(unsigned y=0;y<5;++y)for(unsigned x=0;x<7;++x)src[y*8+x]=x+100*y;
    fb.fKva=dst.data();fb.fMemBytes=dst.size()*4;source.descriptor={src.data(),src.size()*4};
    bool handled=false;
    auto run=[&]{return nvRotationCopyPresent(&pipe,&fb,0,&source,nullptr,&handled);};
    fb.rotationEnabled=false;assert(run()==0&&!handled&&!fb.infoCalls&&!waits&&!maps);
    fb.rotationEnabled=true;fb.mode.degrees=0;assert(run()==0&&!handled&&!fb.infoCalls&&!waits&&!maps);
    fb.mode.degrees=180;fb.ready=false;assert(run()==0&&handled&&!waits&&!maps&&!fb.copyCalls);
    fb.ready=true;asyncBusy=true;assert(run()==0&&handled&&!waits&&!maps&&!fb.copyCalls);asyncBusy=false;
    source.w=6;assert(run()==0&&handled&&!waits&&!maps&&gCntRotationBadGeometry==1);source.w=7;
    source.fmt=1;assert(run()==0&&!waits&&!maps&&gCntRotationBadGeometry==2);source.fmt=0x42475241u;
    gpuReady=false;assert(run()==0&&handled&&waits==1&&!pageoffs&&!maps);gpuReady=true;
    pending=true;cpuReady=false;assert(run()==0&&pageoffs==1&&!maps&&pending);cpuReady=true;
    haveCache=false;assert(run()==0&&!maps&&pending);haveCache=true;
    resource.wrote=false;assert(nvRotationCopySourceReady(&source)&&!pending);resource.wrote=true;
    pending=true;resource.valid[0]=1;const unsigned oldPageoffs=pageoffs;
    assert(nvRotationCopySourceReady(&source)&&!pending&&pageoffs==oldPageoffs);
    pending=true;resource.valid[0]=0;
    assert(nvRotationCopySourceReady(&source)&&!pending&&pageoffs==oldPageoffs+1);
    assert(cache.releases==cacheLookups-1);
    source.descriptor.bytes=4;assert(run()==0&&!fb.copyCalls);source.descriptor.bytes=src.size()*4;
    gIopFlipped[0]=true;assert(run()==0&&handled&&gCntRotationCopy==1&&!gIopFlipped[0]);
    for(unsigned y=0;y<5;++y)for(unsigned x=0;x<7;++x)assert(dst[(4-y)*8+(6-x)]==x+100*y);
    // Inspecting an actual landscape-layout source does not relax presentation
    // geometry or overwrite the existing home scanout with reinterpreted rows.
    const auto beforeProbe=dst;const unsigned oldCopies=fb.copyCalls;
    source.w=6;probeArmed=true;assert(run()==0&&probes==1&&dst==beforeProbe&&fb.copyCalls==oldCopies);source.w=7;
    NMRotationCopyRequest request={fb.mode,src.data(),src.size()*4,7,5,32,0x42475241u,NM_ROTATION_SOURCE_LOGICAL,0};
    const auto good=dst;
    request.mode.modeSequence++;assert(fb.rotationCopy(&request)==kIOReturnNotReady&&dst==good);request.mode.modeSequence--;
    request.mode.epoch++;assert(fb.rotationCopy(&request)==kIOReturnNotReady&&dst==good);request.mode.epoch--;
    request.mode.degrees=270;assert(fb.rotationCopy(&request)==kIOReturnNotReady&&dst==good);request.mode.degrees=180;
    request.mode.head=1;assert(fb.rotationCopy(&request)==kIOReturnNotReady&&dst==good);request.mode.head=0;
    request.mode.outputPitch=28;assert(fb.rotationCopy(&request)==kIOReturnNotReady&&dst==good);request.mode.outputPitch=32;
    request.sourceBytes=4;assert(fb.rotationCopy(&request)==kIOReturnBadArgument&&dst==good);request.sourceBytes=src.size()*4;
    request.format=1;assert(fb.rotationCopy(&request)==kIOReturnBadArgument&&dst==good);request.format=0x42475241u;
    request.source=dst.data();assert(fb.rotationCopy(&request)==kIOReturnBadArgument&&dst==good);request.source=src.data();
    request.sourceLayout=NM_ROTATION_SOURCE_PHYSICAL;assert(fb.rotationCopy(&request)==kIOReturnBadArgument&&dst==good);request.sourceLayout=NM_ROTATION_SOURCE_LOGICAL;
    request.reserved=1;assert(fb.rotationCopy(&request)==kIOReturnBadArgument&&dst==good);request.reserved=0;
    fb.fFrontSurf=nullptr;fb.homeSucceeds=false;assert(fb.rotationCopy(&request)==kIOReturnBusy);
    assert(fb.homeCalls==1&&fb.fFrontSurf==nullptr);fb.homeSucceeds=true;
    assert(fb.rotationCopy(&request)==0&&fb.homeCalls==2&&fb.fFrontSurf==fb.fSurf);
    // A mode/teardown operation cannot invalidate the destination during a copy.
    fb.pause=true;std::atomic<bool> switching=false,changed=false;
    std::thread copying([&]{assert(fb.rotationCopy(&request)==0);});
    while(!fb.entered)std::this_thread::yield();
    std::thread modeChange([&]{switching=true;NVRMDisplayGate gate;fb.fKva=nullptr;++fb.mode.epoch;changed=true;});
    while(!switching)std::this_thread::yield();
    std::this_thread::sleep_for(std::chrono::milliseconds(15));assert(!changed);
    fb.resume=true;copying.join();modeChange.join();assert(changed&&dst==good);
    assert(fb.rotationCopy(&request)==kIOReturnNotReady);
    // V8 captured a full physical plane already rotated by the compositor.
    // Correct its opposite direction by 180; never reinterpret its physical pitch.
    for(unsigned angle:{90u,270u}) {
        NVRMNVDAFramebuffer portrait;IOSurface physical;NVDisplayPipe portraitPipe;
        portrait.mode={NM_ROTATION_VERSION,angle,9,7,5,5,7,32,0,1,3};
        portrait.fW=5;portrait.fH=7;
        std::vector<uint32_t> pixels(56),panel(56,0x87654321);
        for(unsigned y=0;y<7;++y)for(unsigned x=0;x<5;++x)pixels[y*8+x]=x+100*y+angle;
        portrait.fKva=panel.data();portrait.fMemBytes=panel.size()*4;
        physical.w=5;physical.h=7;physical.pitch=32;physical.descriptor={pixels.data(),pixels.size()*4};
        IOAccelDisplayPipeTransaction2 transaction;transaction.full(5,7);
        auto present=[&]{return nvRotationCopyPresent(&portraitPipe,&portrait,0,&physical,&transaction,&handled);};
        const unsigned copies=portrait.copyCalls;const auto untouched=panel;
        assert(nvRotationCopyPresent(&portraitPipe,&portrait,0,&physical,nullptr,&handled)==0&&handled&&portrait.copyCalls==copies&&panel==untouched);
        transaction.args=nullptr;assert(present()==0&&portrait.copyCalls==copies&&panel==untouched);transaction.full(5,7);
        // The old v7 clipped landscape source had a logical-portrait destination.
        *(uint32_t *)(transaction.args+0x60)=nmRotationDimensionBits(7);
        *(uint32_t *)(transaction.args+0x64)=nmRotationDimensionBits(5);
        assert(present()==0&&portrait.copyCalls==copies&&panel==untouched);transaction.full(5,7);
        for(unsigned offset:{0x48u,0x4cu,0x50u,0x54u,0x58u,0x5cu,0x60u,0x64u,0xf0u,0xf4u,0xf8u,0xfcu,0x100u,0x104u}) {
            uint32_t saved;memcpy(&saved,transaction.args+offset,4);
            *(uint32_t *)(transaction.args+offset)=0x7fc00000u;
            assert(present()==0&&portrait.copyCalls==copies&&panel==untouched);
            memcpy(transaction.args+offset,&saved,4);
        }
        physical.w=7;physical.h=5;assert(present()==0&&portrait.copyCalls==copies&&panel==untouched);physical.w=5;physical.h=7;
        gpuReady=false;assert(present()==0&&portrait.copyCalls==copies&&panel==untouched);gpuReady=true;
        pending=true;resource.valid[0]=0;cpuReady=false;
        assert(present()==0&&portrait.copyCalls==copies&&panel==untouched&&pending);cpuReady=true;
        assert(present()==0&&portrait.copyCalls==copies+1);
        for(unsigned y=0;y<7;++y)for(unsigned x=0;x<8;++x)
            assert(panel[y*8+x]==(x<5?pixels[(6-y)*8+(4-x)]:0x87654321u));
        // Stale physical-copy requests are still rejected inside the FB gate.
        NMRotationCopyRequest request={portrait.mode,pixels.data(),pixels.size()*4,5,7,32,0x42475241u,NM_ROTATION_SOURCE_PHYSICAL,0};
        const auto accepted=panel;request.mode.epoch++;
        assert(portrait.rotationCopy(&request)==kIOReturnNotReady&&panel==accepted);request.mode.epoch--;
        request.sourceLayout=NM_ROTATION_SOURCE_LOGICAL;
        assert(portrait.rotationCopy(&request)==kIOReturnBadArgument&&panel==accepted);
    }
    // The primary stays Standard while an independent secondary uses CPU
    // fallback. Reject a misrouted display index before mapping or copying.
    NVRMNVDAFramebuffer primary,secondary;NVDisplayPipe secondPipe;IOSurface secondSource;
    primary.mode.degrees=0;secondary.mode={NM_ROTATION_VERSION,270,11,7,5,5,7,32,1,1,2};
    secondary.fW=5;secondary.fH=7;
    std::vector<uint32_t> idle(40,0x11223344),input(56),output(56,0x55667788);
    for(unsigned y=0;y<7;++y)for(unsigned x=0;x<5;++x)input[y*8+x]=y*100+x;
    primary.fKva=idle.data();primary.fMemBytes=idle.size()*4;
    secondary.fKva=output.data();secondary.fMemBytes=output.size()*4;
    secondSource.id=31;secondSource.w=5;secondSource.h=7;secondSource.pitch=32;secondSource.descriptor={input.data(),input.size()*4};
    IOAccelDisplayPipeTransaction2 secondTransaction;secondTransaction.full(5,7);
    gpuReady=cpuReady=haveCache=true;pending=asyncBusy=false;
    assert(nvRotationCopyPresent(&pipe,&primary,0,&source,nullptr,&handled)==0&&!handled&&!primary.copyCalls);
    assert(nvRotationCopyPresent(&secondPipe,&secondary,0,&secondSource,&secondTransaction,&handled)==0&&handled&&!secondary.copyCalls);
    const auto firstCount=gCntRotationCopyHead[0],secondCount=gCntRotationCopyHead[1];
    assert(nvRotationCopyPresent(&secondPipe,&secondary,1,&secondSource,&secondTransaction,&handled)==0&&handled&&secondary.copyCalls==1);
    assert(gCntRotationCopyHead[0]==firstCount&&gCntRotationCopyHead[1]==secondCount+1);
    for(auto pixel:idle)assert(pixel==0x11223344);
    for(unsigned y=0;y<7;++y)for(unsigned x=0;x<8;++x)
        assert(output[y*8+x]==(x<5?input[(6-y)*8+(4-x)]:0x55667788u));
    puts("PASS: actual presenter/FB methods; exact 180 and quarter-turn pixels; independent Standard primary and rotated secondary; per-display counts and wrong-head refusal; geometry/layout/epoch/GPU/page-off/overlap guards and concurrent teardown");
}
'''
with tempfile.TemporaryDirectory(prefix='nm-rotation-copy-') as directory:
    tmp = Path(directory)
    (tmp / 'test.cpp').write_text(fixture.replace('@@COPY@@', copy).replace('@@PRESENT@@', present))
    subprocess.run(['xcrun', 'clang++', '-std=c++17', '-O1', '-g', '-fsanitize=address,undefined',
                    '-pthread', '-DNM_TAHOE', '-I' + str(root / 'tools/rotation'), str(tmp / 'test.cpp'), '-o', str(tmp / 'test')], check=True)
    subprocess.run([str(tmp / 'test')], check=True, timeout=30)
