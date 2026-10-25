#!/usr/bin/env python3
"""Run production mode publication against the pre-rotation fork's mode getter."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
name='kexts/NVRMFB/fb/nvrm-fb.cpp'
text=(root/name).read_text()
old=subprocess.check_output(['git','show','6d715894d05fca2a90f5886b1ac5f14fdc32a673:'+name],cwd=root,text=True)
def method(source,signature):
    a=source.index(signature);b=source.index('{',a)+1;depth=1
    while depth:
        depth+=(source[b]=='{')-(source[b]=='}');b+=1
    return source[a:b]
helper=method(text,'void NVRMNVDAFramebuffer::rotationModeFlags(')
getter=method(text,'IOReturn NVRMNVDAFramebuffer::getInformationForDisplayMode(')
control=method(old,'IOReturn NVRMNVDAFramebuffer::getInformationForDisplayMode(').replace('::getInformationForDisplayMode(','::control(')
assert 'rotationModeFlags(info);' in method(text,'IOReturn NVRMNVDAFramebuffer::validateDetailedTiming(')
fixture=r'''
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <initializer_list>
#include "nvrm-rotation.h"
using UInt32=uint32_t;using NvU32=uint32_t;using UInt64=uint64_t;using SInt32=int32_t;
using IOReturn=int;using IODisplayModeID=uint32_t;
enum{kIOReturnSuccess=0,kIOReturnBadArgument=-1,kDisplayModeValidFlag=1,kDisplayModeSafeFlag=2,
    kDisplayModeDefaultFlag=4,kDisplayModeNotPresetFlag=0x200,kDisplayModeNativeFlag=0x2000000,
    kDisplayModeAcceleratorBackedFlag=0x400000,kModeId=1};
struct IODisplayModeInformation{
    UInt32 nominalWidth,nominalHeight,refreshRate,maxDepthIndex,flags;
    uint16_t imageWidth,imageHeight;UInt32 reserved[3];
};
struct IODetailedTimingInformationV2{UInt32 horizontalActive,verticalActive,horizontalScaled,verticalScaled,
    horizontalBlanking,verticalBlanking;UInt64 pixelClock;};
static void nvu_zero(void *p,size_t n){memset(p,0,n);}
static SInt32 OSAddAtomic(SInt32 n,volatile SInt32 *p){auto before=*p;*p+=n;return before;}
struct NVRMNVDAFramebuffer{
    bool fRotationEnabled=true;volatile SInt32 fRotationRequestedBits=0;
    UInt32 fBootW=0,fBootH=0,fW=0,fH=0;uint16_t fEdidMmW=480,fEdidMmH=270;
    struct Mode{struct{NvU32 refreshRate;}timings;}fBootMode{},fMode{};
    IODetailedTimingInformationV2 fDT[2]{};
    int dtIndex(IODisplayModeID id){return id==10?0:id==11?1:-1;}
    void rotationModeFlags(IODisplayModeInformation *);
    IOReturn getInformationForDisplayMode(IODisplayModeID,IODisplayModeInformation *);
    IOReturn control(IODisplayModeID,IODisplayModeInformation *);
};
@@METHODS@@
int main(){
    unsigned cases=0;
    const unsigned sizes[][2]={{1280,720},{1920,1080},{2560,1440},{3440,1440},{3840,2160},{5120,2880},{7680,4320}};
    for(const auto &size:sizes)for(bool rotationEnabled:{false,true})for(unsigned bits:{0u,3u,5u,6u,0x30u,2u}){
        NVRMNVDAFramebuffer fb;fb.fBootW=fb.fW=size[0];fb.fBootH=fb.fH=size[1];
        fb.fRotationEnabled=rotationEnabled;fb.fRotationRequestedBits=bits;
        fb.fBootMode.timings.refreshRate=74974;
        for(unsigned i=0;i<2;i++)fb.fDT[i]={size[0],size[1],i?size[0]/2:0,i?size[1]/2:0,160,45,179800000};
        for(unsigned mode:{1u,10u,11u}){
            IODisplayModeInformation actual{},expected{};
            assert(fb.getInformationForDisplayMode(mode,&actual)==0&&fb.control(mode,&expected)==0);
            if(rotationEnabled&&(bits==3||bits==5))expected.flags|=kDisplayModeAcceleratorBackedFlag;
            assert(memcmp(&actual,&expected,sizeof actual)==0);
            ++cases;
        }
        assert(fb.getInformationForDisplayMode(1,nullptr)==kIOReturnBadArgument);
        IODisplayModeInformation untouched{};untouched.flags=0xabcdef12;
        assert(fb.getInformationForDisplayMode(99,&untouched)==kIOReturnBadArgument&&untouched.flags==0xabcdef12);
        for(unsigned flags:{0u,0x400000u,0x12345678u,0xffffffffu}){
            IODisplayModeInformation info{};info.flags=flags;fb.rotationModeFlags(&info);
            const unsigned expected=flags|((rotationEnabled&&(bits==3||bits==5))?kDisplayModeAcceleratorBackedFlag:0u);
            assert(info.flags==expected);
        }
        fb.rotationModeFlags(nullptr);
    }
    printf("PASS: %u production mode records through 8K; only enabled quarter-turn backing flag differs; geometry/refresh/physical size/other flags, Standard and 180 preserved\n",cases);
}
'''
with tempfile.TemporaryDirectory(prefix='nm-portrait-contract-') as directory:
    p=Path(directory);(p/'test.cpp').write_text(fixture.replace('@@METHODS@@',helper+'\n'+getter+'\n'+control))
    subprocess.run(['xcrun','clang++','-std=c++17','-O1','-g','-fsanitize=address,undefined','-Werror',
        '-I'+str(root/'kexts/NVRMFB/fb'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True,timeout=20)
