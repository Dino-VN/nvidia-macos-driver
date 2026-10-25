#!/usr/bin/env python3
"""Exercise the production framebuffer's rotation snapshot and transition guards."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
text=(root/'kexts/NVRMFB/fb/nvrm-fb.cpp').read_text()
def method(name):
    a=text.index(name);o=text.index('{',a);b=o+1;depth=1
    while depth:
        depth+=(text[b]=='{')-(text[b]=='}');b+=1
    return text[a:b]
methods='bool '+method('NVRMNVDAFramebuffer::rotationPending(')+'\n'
methods+='IOReturn '+method('NVRMNVDAFramebuffer::rotationMode(')
fixture=r'''
#include <cassert>
#include <cstdio>
#include <cstring>
#include <cstdint>
#include "copy_request.h"
#include "../../kexts/NVRMFB/fb/nvrm-rotation.h"
using SInt32=int32_t;using SInt64=int64_t;using UInt32=uint32_t;using UInt64=uint64_t;using IOReturn=int;
enum{kIOReturnSuccess=0,kIOReturnNotReady=-1,kIOReturnBadArgument=-2};
static SInt32 OSAddAtomic(SInt32 n,volatile SInt32 *p){SInt32 before=*p;*p+=n;return before;}
static SInt64 OSAddAtomic64(SInt64 n,volatile SInt64 *p){SInt64 before=*p;*p+=n;return before;}
static void nvu_zero(void *p,size_t n){memset(p,0,n);}
struct OSObject{virtual ~OSObject(){};void release(){}};
struct OSNumber:OSObject{UInt32 value=0;UInt32 unsigned32BitValue(){return value;}};
#define OSDynamicCast(C,p) dynamic_cast<C *>(p)
#define OSSafeReleaseNULL(p) do{if(p){p->release();p=nullptr;}}while(0)
struct NVRMDisplayGate{bool valid(){return true;}};
struct NVRMNVDAFramebuffer{
    bool fRotationPrototype=true,fHeadSlept=false,fSysSlept=false,fDpyLost=false,fSubmissionFaulted=false,fModeSet=true;
    volatile SInt32 fStopping=0,fRotationRequesting=0,fRotationRequestedBits=0;
    volatile SInt64 fRotationEpoch=1;
    void *fKva=this,*fSurf=this,*fMem=this;
    unsigned fW=1920,fH=1080,fPitch=7680,fIndex=0,fModeSwitches=3;
    bool missingTransform=false,epochChange=false;OSNumber transform;
    OSObject *copyProperty(const char *){if(epochChange)++fRotationEpoch;return missingTransform?nullptr:&transform;}
    bool rotationPending();IOReturn rotationMode(NMRotationMode *);
};
@@METHODS@@
int main(){
    NVRMNVDAFramebuffer fb;NMRotationMode mode={};
    auto snapshot=[&]{mode={};mode.version=NM_ROTATION_VERSION;return fb.rotationMode(&mode);};
    for(unsigned degrees:{0u,90u,180u,270u}){
        uint32_t bits=0;assert(nvrmRotationBits(degrees,&bits));
        fb.transform.value=bits;fb.fRotationRequestedBits=bits;
        assert(snapshot()==0&&mode.degrees==degrees&&mode.outputWidth==1920&&mode.outputHeight==1080&&mode.outputPitch==7680);
        assert(mode.logicalWidth==(nmRotationSwaps(degrees)?1080:1920));
        assert(mode.logicalHeight==(nmRotationSwaps(degrees)?1920:1080));
        assert(fb.rotationPending()==(degrees!=0));
    }
    fb.transform.value=0;fb.fRotationRequestedBits=3;
    assert(fb.rotationPending()&&snapshot()==kIOReturnNotReady);
    fb.transform.value=0x30;assert(snapshot()==kIOReturnNotReady);
    fb.transform.value=3;assert(snapshot()==0);
    const NMRotationMode before=mode;
    ++fb.fModeSwitches;assert(snapshot()==0&&!nmRotationSameMode(before,mode));
    fb.epochChange=true;assert(snapshot()==kIOReturnNotReady);fb.epochChange=false;
    fb.fRotationRequesting=1;assert(fb.rotationPending()&&snapshot()==kIOReturnNotReady);fb.fRotationRequesting=0;
    fb.fStopping=1;assert(snapshot()==kIOReturnNotReady);fb.fStopping=0;
    for(bool *condition:{&fb.fHeadSlept,&fb.fSysSlept,&fb.fDpyLost,&fb.fSubmissionFaulted}){
        *condition=true;assert(snapshot()==kIOReturnNotReady);*condition=false;
    }
    fb.fModeSet=false;assert(snapshot()==kIOReturnNotReady);fb.fModeSet=true;
    for(void **memory:{&fb.fKva,&fb.fSurf,&fb.fMem}){
        *memory=nullptr;assert(snapshot()==kIOReturnNotReady);*memory=&fb;
    }
    fb.missingTransform=true;assert(snapshot()==kIOReturnNotReady);fb.missingTransform=false;
    fb.fRotationPrototype=false;assert(!fb.rotationPending()&&snapshot()==kIOReturnNotReady);
    assert(fb.rotationMode(nullptr)==kIOReturnBadArgument);
    puts("PASS: production rotation snapshots; native physical geometry, low-bit logical axes, pending/high-bit transitions, epoch changes, mode sequence, stop/sleep/lost display and missing resources");
}
'''
fixture=fixture.replace('#include "../../kexts/NVRMFB/fb/nvrm-rotation.h"',
    '#include "'+str(root/'kexts/NVRMFB/fb/nvrm-rotation.h')+'"')
with tempfile.TemporaryDirectory(prefix='nm-rotation-state-') as directory:
    p=Path(directory);(p/'test.cpp').write_text(fixture.replace('@@METHODS@@',methods))
    subprocess.run(['xcrun','clang++','-std=c++17','-O1','-g','-fsanitize=address,undefined',
        '-include','initializer_list','-I'+str(root/'tools/rotation'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True,timeout=20)
