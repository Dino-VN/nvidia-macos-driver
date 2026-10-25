#!/usr/bin/env python3
"""Exercise production Tahoe defaults, opt-outs and matched-accelerator probe guards."""
from pathlib import Path
import subprocess
import tempfile
root=Path(__file__).resolve().parents[2]
text=(root/'kexts/NVRMFB/fb/nvrm-fb.cpp').read_text()
def method(signature):
    start=text.index(signature);end=text.index('{',start)+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[start:end]
methods=method('void NVRMNVDAFramebuffer::configureRotation(')+'\n'+method('IOReturn NVRMNVDAFramebuffer::requestProbe(')
fixture=r'''
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <initializer_list>
#include <map>
#include <string>
#include <vector>
#include "nvrm-rotation.h"
#include "copy_request.h"
using UInt32=uint32_t;using SInt32=int32_t;using UInt64=uint64_t;using SInt64=int64_t;
using IOOptionBits=uint32_t;using IOReturn=int;
enum{kIOFBUserRequestProbe=1,kIOReturnSuccess=0,kIOReturnBadArgument=-1,kIOReturnNotReady=-2,kIOReturnBusy=-3};
static const char *kIOFBProbeOptionsKey="IOFBProbeOptions";
static int version_major=25,bootArg=-1;
static void PE_parse_boot_argn(const char *name,int *out,size_t n){assert(!strcmp(name,"nvrmrotation")&&n==sizeof(*out));if(bootArg!=-1)*out=bootArg;}
static SInt32 OSAddAtomic(SInt32 n,volatile SInt32 *p){SInt32 old=*p;*p+=n;return old;}
static SInt64 OSAddAtomic64(SInt64 n,volatile SInt64 *p){SInt64 old=*p;*p+=n;return old;}
static bool OSCompareAndSwap(SInt32 old,SInt32 n,volatile SInt32 *p){if(*p!=old)return false;*p=n;return true;}
#define FBLOG(...) ((void)0)
struct OSObject{virtual ~OSObject(){};void release(){}};
static OSObject yes,no;static OSObject *kOSBooleanTrue=&yes,*kOSBooleanFalse=&no;
struct OSNumber:OSObject{uint64_t value=0;UInt32 unsigned32BitValue(){return (UInt32)value;}};
#define OSDynamicCast(C,p) dynamic_cast<C *>(p)
struct OSDictionary:OSObject{};
struct IOService:OSObject{
    std::map<std::string,OSObject *> properties;std::map<std::string,OSNumber> numbers;
    IOService *provider=nullptr;
    OSObject *getProperty(const char *key){auto i=properties.find(key);return i==properties.end()?nullptr:i->second;}
    bool setProperty(const char *key,OSObject *p){properties[key]=p;return true;}
    bool setProperty(const char *key,unsigned long long n,unsigned){numbers[key].value=n;properties[key]=&numbers[key];return true;}
    bool setProperty(const char *,const char *){return true;}
    IOService *getProvider(){return provider;}
};
struct OSIterator:OSObject{std::vector<IOService *> services;size_t at=0;OSObject *getNextObject(){return at<services.size()?services[at++]:nullptr;}};
static OSDictionary match;static OSIterator iterator;
struct Base:IOService{
    unsigned calls=0;IOOptionBits last=0;IOReturn nextResult=kIOReturnSuccess;
    IOReturn requestProbe(IOOptionBits options){++calls;last=options;return nextResult;}
};
struct NVRMNVDAFramebuffer:Base{
    using super=Base;
    bool fRotationEnabled=false;volatile SInt32 fRotationRequesting=0,fRotationRequestedBits=0,fStopping=0;
    volatile SInt64 fRotationEpoch=1;unsigned fIndex=0;IOService pci;
    IOService *pciNub(){return &pci;}
    OSDictionary *serviceMatching(const char *){return &match;}
    OSIterator *getMatchingServices(OSDictionary *){iterator.at=0;return &iterator;}
    void configureRotation();IOReturn requestProbe(IOOptionBits);
};
@@METHODS@@
int main(){
    unsigned configs=0;
    for(int os:{24,25,26})for(int property:{-1,0,1})for(int argument:{-1,0,1,2}){
        NVRMNVDAFramebuffer fb;version_major=os;bootArg=argument;
        fb.setProperty(kIOFBProbeOptionsKey,0x200ULL,32);
        if(property!=-1)fb.setProperty("NVRMRotationEnabled",property?kOSBooleanTrue:kOSBooleanFalse);
        fb.configureRotation();
        const int selected=argument!=-1?argument:(property==-1?1:property);
        const bool wanted=os==25&&selected==1;
        assert(fb.fRotationEnabled==wanted);
        assert(fb.getProperty("NVRMRotationEnabled")== (wanted?kOSBooleanTrue:kOSBooleanFalse));
        const auto flags=OSDynamicCast(OSNumber,fb.getProperty(kIOFBProbeOptionsKey))->unsigned32BitValue();
        assert(flags==(wanted?0x601u:0x200u));
        assert((fb.getProperty("NVRMRotationImplementationVersion")!=nullptr)==wanted);
        ++configs;
    }
    version_major=25;bootArg=-1;NVRMNVDAFramebuffer fb;fb.configureRotation();
    assert(fb.fRotationEnabled);
    assert(fb.requestProbe(0x300400)==kIOReturnNotReady&&!fb.calls); // no matching accelerator
    IOService accel;OSNumber protocol;protocol.value=8;accel.setProperty("NVAccelRotationCopyProtocol",&protocol);accel.provider=fb.pciNub();
    iterator.services={&accel};assert(fb.requestProbe(0x300400)==kIOReturnNotReady&&!fb.calls);
    protocol.value=NM_ROTATION_COPY_PROTOCOL;IOService otherGPU;accel.provider=&otherGPU;
    assert(fb.requestProbe(0x300400)==kIOReturnNotReady&&!fb.calls);
    accel.provider=fb.pciNub();
    assert(fb.requestProbe(0x300400)==0&&fb.last==0x30400&&fb.fRotationRequestedBits==3&&fb.fRotationEpoch==3&&!fb.fRotationRequesting);
    const auto accepted=fb.fRotationEpoch;
    fb.nextResult=kIOReturnBadArgument;
    assert(fb.requestProbe(0x500400)==kIOReturnBadArgument&&fb.fRotationRequestedBits==3&&fb.fRotationEpoch==accepted+2&&!fb.fRotationRequesting);
    fb.nextResult=0;
    fb.fRotationRequesting=1;const auto count=fb.calls;
    assert(fb.requestProbe(0x600400)==kIOReturnBusy&&fb.calls==count);fb.fRotationRequesting=0;
    fb.fStopping=1;assert(fb.requestProbe(0x500400)==kIOReturnNotReady&&fb.calls==count);fb.fStopping=0;
    assert(fb.requestProbe(0x400400)==kIOReturnBadArgument&&fb.calls==count);
    iterator.services.clear(); // restoring Standard never depends on a matching accelerator
    assert(fb.requestProbe(0x400)==0&&fb.last==0x400&&!fb.fRotationRequestedBits);
    fb.fRotationEnabled=false;
    assert(fb.requestProbe(0x300400)==0&&fb.last==0x300400); // original family dispatch
    printf("PASS: %u production enablement cases; Tahoe default and property/boot opt-outs; OS gate, matching GPU/protocol, normalized transforms, failed/busy/stopping requests, accelerator-independent Standard restore\n",configs);
}
'''
with tempfile.TemporaryDirectory(prefix='nm-rotation-enable-') as directory:
    p=Path(directory);(p/'test.cpp').write_text(fixture.replace('@@METHODS@@',methods))
    subprocess.run(['xcrun','clang++','-std=c++17','-O1','-g','-fsanitize=address,undefined','-Werror',
        '-I'+str(root/'tools/rotation'),'-I'+str(root/'kexts/NVRMFB/fb'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
    subprocess.run([str(p/'test')],check=True,timeout=20)
