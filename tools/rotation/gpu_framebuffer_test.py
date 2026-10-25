#!/usr/bin/env python3
"""Run the actual framebuffer GPU flip method, including its scoped rotation bypass."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[2]
s=(root/'kexts/NVRMFB/fb/nvrm-fb.cpp').read_text();a=s.index('IOReturn NVRMNVDAFramebuffer::rotationGPUFlip(');b=s.index('{',a)+1;depth=1
while depth:
 depth+=(s[b]=='{')-(s[b]=='}');b+=1
method=s[a:b]
fixture=r'''
#include <cassert>
#include <cstdio>
#include <mutex>
#include <thread>
#include <atomic>
#include "gpu_state.h"
using IOReturn=int;
enum{kIOReturnSuccess=0,kIOReturnNotReady=-1,kIOReturnBadArgument=-2,kIOReturnBusy=-3,kIOReturnIOError=-4,NV_KMS_FLIP_RESULT_IN_PROGRESS=5};
struct NvKmsKapiMemory{};
static std::recursive_mutex gateMutex;static thread_local unsigned gateDepth;
struct NVRMDisplayGate{NVRMDisplayGate(){gateMutex.lock();++gateDepth;}~NVRMDisplayGate(){--gateDepth;gateMutex.unlock();}bool valid(){return true;}};
struct NVRMNVDAFramebuffer{
    bool fRotationGPUFlipActive=false,ready=true,accept=true;int rc=0;unsigned calls=0;
    NMRotationMode mode={NM_ROTATION_VERSION,90,7,5,7,7,5,32,0,1,3};
    std::atomic<bool> enter{false},resume{true};
    IOReturn rotationMode(NMRotationMode *out){assert(gateDepth);if(!ready)return kIOReturnNotReady;*out=mode;return 0;}
    bool flipToMemory(NvKmsKapiMemory *memory,unsigned w,unsigned h,unsigned pitch,int *out,bool pure,uint64_t cookie){
        assert(gateDepth&&fRotationGPUFlipActive&&memory&&w==7&&h==5&&pitch==32&&pure);++calls;
        enter=true;while(!resume)std::this_thread::yield();
        *out=rc;return accept&&cookie==123;
    }
    IOReturn rotationGPUFlip(NMRotationGPUFlip *);
};
@@METHOD@@
int main(){
    NVRMNVDAFramebuffer fb;NMRotationGPUFlip request={};request.version=NM_ROTATION_GPU_PROTOCOL;request.mode=fb.mode;
    NvKmsKapiMemory memory;request.memory=&memory;request.allocationCookie=123;request.width=7;request.height=5;request.pitch=32;request.format=0x42475241u;
    auto run=[&]{int r=fb.rotationGPUFlip(&request);assert(!fb.fRotationGPUFlipActive);return r;};
    assert(fb.rotationGPUFlip(nullptr)==kIOReturnNotReady&&!fb.calls);
    assert(run()==0&&fb.calls==1);
    const auto valid=request;
    request.version=9;assert(run()==kIOReturnNotReady&&fb.calls==1);request=valid;
    request.reserved=1;assert(run()==kIOReturnNotReady);request=valid;
    request.flags=1;assert(run()==kIOReturnNotReady);request=valid;
    request.format=1;assert(run()==kIOReturnNotReady);request=valid;
    request.memory=nullptr;assert(run()==kIOReturnNotReady);request=valid;
    request.mode.epoch++;assert(run()==kIOReturnNotReady);request=valid;
    request.mode.modeSequence++;assert(run()==kIOReturnNotReady);request=valid;
    request.mode.head++;assert(run()==kIOReturnNotReady);request=valid;
    request.width=5;request.height=7;assert(run()==kIOReturnBadArgument);request=valid;
    request.pitch=27;assert(run()==kIOReturnBadArgument);request=valid;
    request.allocationCookie=999;assert(run()==kIOReturnIOError);request=valid;
    fb.accept=false;fb.rc=NV_KMS_FLIP_RESULT_IN_PROGRESS;assert(run()==kIOReturnBusy);fb.rc=-1;assert(run()==kIOReturnIOError);
    fb.accept=true;fb.rc=0;fb.ready=false;assert(run()==kIOReturnNotReady);fb.ready=true;
    fb.mode.degrees=0;fb.mode.logicalWidth=7;fb.mode.logicalHeight=5;request.mode=fb.mode;assert(run()==kIOReturnNotReady);
    fb.mode=valid.mode;request=valid;
    fb.enter=false;fb.resume=false;std::atomic<bool> changed{false};
    std::thread flip([&]{assert(fb.rotationGPUFlip(&request)==0);});
    while(!fb.enter)std::this_thread::yield();
    std::thread modeChange([&]{NVRMDisplayGate gate;assert(!fb.fRotationGPUFlipActive);++fb.mode.epoch;changed=true;});
    assert(!changed);fb.resume=true;flip.join();modeChange.join();assert(changed&&!fb.fRotationGPUFlipActive&&run()==kIOReturnNotReady);
    puts("PASS: actual FB GPU flip; protocol, mode/epoch/head, physical geometry, format, cookie handoff and Busy/error guards; bypass resets on every path; mode change waits outside active GPU flip");
}
'''
with tempfile.TemporaryDirectory(prefix='nm-gpu-fb-') as directory:
 p=Path(directory);(p/'test.cpp').write_text(fixture.replace('@@METHOD@@',method))
 subprocess.run(['xcrun','clang++','-std=c++17','-O1','-g','-fsanitize=address,undefined','-pthread',
   '-I'+str(root/'tools/rotation'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=20)
