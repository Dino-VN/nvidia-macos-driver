#!/usr/bin/env python3
"""Exercise the native rotation mode contract with actual IOGraphics structures."""
from test_support import FB, method, run

names = ['void NVRMNVDAFramebuffer::dtSurfaceSize(', 'static void dtRasterTurned(',
         'bool NVRMNVDAFramebuffer::dtIsCurrent(', 'bool NVRMNVDAFramebuffer::dtIsBootRaster(',
         'void NVRMNVDAFramebuffer::dtToKapi(', 'IOReturn NVRMNVDAFramebuffer::getInformationForDisplayMode(',
         'IOReturn NVRMNVDAFramebuffer::getTimingInfoForDisplayMode(',
         'IOReturn NVRMNVDAFramebuffer::validateDetailedTiming(',
         'IOReturn NVRMNVDAFramebuffer::setDetailedTimings(',
         'IOReturn NVRMNVDAFramebuffer::getCurrentDisplayMode(',
         'IOReturn NVRMNVDAFramebuffer::setDisplayMode(']
methods = '\n'.join(method(FB, name) for name in names)
fixture = r'''
#include <IOKit/graphics/IOGraphicsTypes.h>
#include <IOKit/IOReturn.h>
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <vector>
#include <initializer_list>
#include "nvrm-rotation.h"
#define detailedTimingModeID __reservedA[0]
using NvU32=uint32_t;using NvU64=uint64_t;
enum {kModeId=1};
#define FBLOG(...) ((void)0)
static void nvu_zero(void *p,size_t n){memset(p,0,n);}
static void nvu_copy(void *p,const void *q,size_t n){memcpy(p,q,n);}
static bool OSCompareAndSwap(UInt32 old,UInt32 n,volatile UInt32 *p){if(*p!=old)return false;*p=n;return true;}
struct OSObject{virtual ~OSObject(){};};
struct OSData:OSObject{
 std::vector<unsigned char> bytes;
 explicit OSData(const IODetailedTimingInformationV2 &d):bytes(sizeof d){memcpy(bytes.data(),&d,sizeof d);}
 size_t getLength(){return bytes.size();}const void *getBytesNoCopy(){return bytes.data();}
};
struct OSArray:OSObject{std::vector<OSData> values;unsigned getCount(){return values.size();}
 OSObject *getObject(unsigned i){return &values.at(i);}};
#define OSDynamicCast(C,p) dynamic_cast<C *>(p)
struct NvKmsKapiDisplayModeTimings{
 NvU32 pixelClockHz=0,hVisible=0,hSyncStart=0,hSyncEnd=0,hTotal=0,vVisible=0,vSyncStart=0,vSyncEnd=0,vTotal=0,refreshRate=0;
 struct {bool hSyncPos=false,hSyncNeg=false,vSyncPos=false,vSyncNeg=false;}flags;
 };
struct NvKmsKapiDisplayMode{NvKmsKapiDisplayModeTimings timings;};
struct Kms{bool allowed=true;bool validateDisplayMode(void *,unsigned,NvKmsKapiDisplayMode *){return allowed;}};
struct NVRMNVDAFramebuffer{
 bool fRotationEnabled=true,fModeSet=true,fBootInDT=false;unsigned fIndex=0,fNDT=0,fValidateCalls=0,fValidateOk=0,fEdidHits=0;
 static const unsigned kMaxMacTimings=224;
 IODetailedTimingInformationV2 fDT[256]{},fCurDT{};
 IODisplayModeID fCurId=1;volatile UInt32 fNewIdOnce=0;UInt32 fTransform=0,fCurTransform=0;
 NvU32 fW=1920,fH=1080,fRasterW=1920,fRasterH=1080,fBootW=1920,fBootH=1080,fScalerMaxW=7680,fScalerMaxH=4320;
 UInt16 fEdidMmW=480,fEdidMmH=270;NvKmsKapiDisplayMode fMode{},fBootMode{};Kms kms,*fKms=&kms;
 void *fDev=this;unsigned fDisplay=1,publishes=0,switches=0;
 void dtSurfaceSize(const IODetailedTimingInformationV2 *,NvU32 *,NvU32 *)const;
 bool dtIsCurrent(const IODetailedTimingInformationV2 &)const;bool dtIsBootRaster(const IODetailedTimingInformationV2 &)const;
 static void dtToKapi(const IODetailedTimingInformationV2 *,NvKmsKapiDisplayMode *);
 IOReturn getInformationForDisplayMode(IODisplayModeID,IODisplayModeInformation *);
 IOReturn getTimingInfoForDisplayMode(IODisplayModeID,IOTimingInformation *);
 IOReturn validateDetailedTiming(void *,IOByteCount);IOReturn setDetailedTimings(OSArray *);
 IOReturn getCurrentDisplayMode(IODisplayModeID *,IOIndex *);IOReturn setDisplayMode(IODisplayModeID,IOIndex);
 int dtIndex(IODisplayModeID id)const{for(unsigned i=0;i<fNDT;i++)if((IODisplayModeID)fDT[i].detailedTimingModeID==id)return i;return -1;}
 unsigned addKmsRefreshModes(unsigned n){return n;}
 void setProperty(const char *,OSObject *){}void setProperty(const char *,unsigned long long,unsigned){}
 void removeProperty(const char *){}void publishRotatedSizes(){}void publishStartupTiming(){++publishes;}
 void publishCursorGeometry(const IODetailedTimingInformationV2 *){}
 bool edidModeFor(const IODetailedTimingInformationV2 *,NvKmsKapiDisplayMode *){return false;}
 bool applyMode(){return true;}
 IOReturn switchMode(IODisplayModeID id,const NvKmsKapiDisplayMode &mode,NvU32 w,NvU32 h,UInt32 transform){
  ++switches;fCurId=id;fMode=mode;fW=w;fH=h;fRasterW=mode.timings.hVisible;fRasterH=mode.timings.vVisible;fCurTransform=transform;return 0;
 }
};
@@METHODS@@
static IODetailedTimingInformationV2 timing(unsigned w,unsigned h,unsigned hz,unsigned transform,unsigned id){
 IODetailedTimingInformationV2 d{};d.horizontalActive=w;d.verticalActive=h;
 d.horizontalBlanking=160;d.verticalBlanking=45;d.horizontalSyncOffset=32;d.horizontalSyncPulseWidth=32;
 d.verticalSyncOffset=3;d.verticalSyncPulseWidth=5;d.horizontalSyncConfig=1;d.verticalSyncConfig=1;
 d.pixelClock=(uint64_t)(w+160)*(h+45)*hz;d.detailedTimingModeID=id;d.scalerFlags=transform;
 if(transform){d.horizontalScaled=(transform&kIOScaleSwapAxes)?h:w;d.verticalScaled=(transform&kIOScaleSwapAxes)?w:h;}
 return d;
}
static void adopt(NVRMNVDAFramebuffer &f,const IODetailedTimingInformationV2 &d){
 f.fNDT=1;f.fDT[0]=d;assert(f.setDisplayMode(d.detailedTimingModeID,0)==0);
}
int main(){
 unsigned cases=0;
 for(auto size:{std::pair<unsigned,unsigned>{1280,720},{1920,1080},{2560,1440},{3440,1440},{3840,2160},{5120,1440},{7680,4320}})
 for(unsigned transform:{0u,0x30u,0x60u,0x50u}){
  NVRMNVDAFramebuffer f;f.fBootW=size.first;f.fBootH=size.second;f.fTransform=transform;
  auto d=timing(size.first,size.second,size.first==7680?24:75,transform,0x1234);
  IOFBDisplayModeDescription desc{};desc.timingInfo.detailedInfo.v2=d;
  assert(f.validateDetailedTiming(&desc,sizeof desc)==0);
  assert(desc.info.flags&kDisplayModeAcceleratorBackedFlag);
  adopt(f,d);assert(f.fW==size.first&&f.fH==size.second&&f.fCurTransform==transform);
  assert(f.dtIsCurrent(d));auto other=d;other.verticalBlanking++;assert(!f.dtIsCurrent(other));
  other=d;other.horizontalSyncOffset++;assert(!f.dtIsCurrent(other));
  other=d;other.scalerFlags^=kIOScaleInvertX;assert(!f.dtIsCurrent(other));
  if(transform){other=d;other.horizontalScaled--;assert(!f.dtIsCurrent(other));}
  IOTimingInformation info{};assert(f.getTimingInfoForDisplayMode(d.detailedTimingModeID,&info)==0);
  assert(info.detailedInfo.v2.horizontalActive==size.first&&info.detailedInfo.v2.verticalActive==size.second);
  auto rebuilt=d;rebuilt.detailedTimingModeID=0x9999;OSArray array;array.values.emplace_back(rebuilt);
  assert(f.setDetailedTimings(&array)==0);IODisplayModeID reported=0;
  assert(f.getCurrentDisplayMode(&reported,nullptr)==0&&reported==0x9999);
  if(transform)assert(f.getCurrentDisplayMode(&reported,nullptr)==0&&reported==0x1234);
  else assert(f.fCurId==0x9999);
  ++cases;
 }
 // Native unrotated timings must produce a complete rotated copy, not mirror-only synthetic modes.
 NVRMNVDAFramebuffer portrait;portrait.fTransform=0x30;
 auto d=timing(1920,1080,144,0,0x10000);portrait.fNDT=1;portrait.fDT[0]=d;
 IOTimingInformation ti{};assert(portrait.getTimingInfoForDisplayMode(0x10000,&ti)==0);
 assert((ti.flags&kIOScalingInfoValid)&&ti.detailedInfo.v2.horizontalScaled==1920&&ti.detailedInfo.v2.verticalScaled==1080);
 IODisplayModeInformation mi{};assert(portrait.getInformationForDisplayMode(0x10000,&mi)==0);
 assert(mi.flags&kDisplayModeAcceleratorBackedFlag);
 // Malformed/unknown transforms and non-full rotated desktops remain refused.
 auto invalid=timing(1920,1080,75,0x30,0x10000);invalid.horizontalScaled--;
 assert(portrait.validateDetailedTiming(&invalid,sizeof invalid)==kIOReturnUnsupportedMode);
 invalid=timing(1920,1080,75,0x10,0x10000);
 assert(portrait.validateDetailedTiming(&invalid,sizeof invalid)==kIOReturnUnsupportedMode);
 invalid=timing(1920,1080,75,0x30,0x10000);invalid.horizontalScaled=0;
 assert(portrait.validateDetailedTiming(&invalid,sizeof invalid)==kIOReturnUnsupportedMode);
 // More than 64 modes from macOS survive; reserve entries beyond 224 for driver/active aliases.
 OSArray many;for(unsigned i=0;i<240;++i)many.values.emplace_back(timing(1920,1080,60,0,100+i));
 assert(portrait.setDetailedTimings(&many)==0&&portrait.fNDT==224);
 // Disabled/non-Tahoe behavior retains the original physical/scaled sizes and flags.
 NVRMNVDAFramebuffer disabled;disabled.fRotationEnabled=false;
 auto scaled=timing(1920,1080,60,0,10);scaled.horizontalScaled=2560;scaled.verticalScaled=1440;
 disabled.fNDT=1;disabled.fDT[0]=scaled;assert(disabled.setDisplayMode(10,0)==0);
 assert(disabled.fW==2560&&disabled.fH==1440);
 assert(disabled.getInformationForDisplayMode(10,&mi)==0&&!(mi.flags&kDisplayModeAcceleratorBackedFlag));
 assert(disabled.validateDetailedTiming(&scaled,sizeof scaled)==0);
 scaled.horizontalScaled=5000;assert(disabled.validateDetailedTiming(&scaled,sizeof scaled)==kIOReturnUnsupportedMode);
 auto rotated=timing(1920,1080,60,0x30,11);
 assert(disabled.validateDetailedTiming(&rotated,sizeof rotated)==kIOReturnUnsupportedMode);
 // One head's mode rebuild cannot overwrite another head's mode, transform or physical size.
 NVRMNVDAFramebuffer first,second;adopt(first,timing(1920,1080,75,0x30,8));adopt(second,timing(2560,1440,165,0,9));
 auto saved=second.fCurDT;OSArray change;change.values.emplace_back(timing(1920,1080,75,0x30,44));first.setDetailedTimings(&change);
 assert(second.fCurId==9&&!second.fCurTransform&&memcmp(&saved,&second.fCurDT,sizeof saved)==0);
 printf("PASS: %u native mode/refresh/angle cases through 8K; timing renumber/alias, full-raster guards, 224 timings, disabled scaled path and independent heads\n",cases);
}
'''
run(fixture.replace('@@METHODS@@', methods))
