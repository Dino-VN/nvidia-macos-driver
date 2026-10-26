#!/usr/bin/env python3
"""Run actual cursor image/move methods with serialized geometry and bounded inputs."""
from test_support import FB, method, run

methods = '\n'.join(method(FB, name) for name in [
    'static bool nvrmPackCursor(', 'void NVRMNVDAFramebuffer::publishCursorGeometry(',
    'IOReturn NVRMNVDAFramebuffer::setCursorImageLocked(', 'IOReturn NVRMNVDAFramebuffer::setCursorState('])
fixture = r'''
#include <IOKit/graphics/IOGraphicsTypes.h>
#include <IOKit/IOReturn.h>
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <cstdlib>
#include <mutex>
#include <thread>
#include <initializer_list>
#include "nvrm-rotation.h"
using NvU32=uint32_t;using IOInterruptState=int;using IOSimpleLock=std::mutex;
enum {NV_KMS_FLIP_RESULT_SUCCESS=0};
#define FBLOG(...) ((void)0)
static void nvu_zero(void *p,size_t n){memset(p,0,n);}
static unsigned allocs=0,failAt=0;
static void *IOMalloc(size_t bytes){++allocs;return allocs==failAt?nullptr:malloc(bytes);}
static void IOFree(void *p,size_t){free(p);}
static IOInterruptState IOSimpleLockLockDisableInterrupt(IOSimpleLock *l){l->lock();return 0;}
static void IOSimpleLockUnlockEnableInterrupt(IOSimpleLock *l,IOInterruptState){l->unlock();}
struct NVRMNVDAFramebuffer{
 IOSimpleLock mutex,*fCurStateLock=&mutex;void *fCurSurf=this,*fCursorCall=this;
 UInt32 pixels[16]{};void *fCurKva=pixels;unsigned fCurDim=4;
 UInt32 fCurTransform=0,fCurMapTransform=0;NvU32 fW=1920,fH=1080,fCurRasterW=0,fCurRasterH=0,fCurDesktopW=0,fCurDesktopH=0;
 SInt32 fCurHotX=0,fCurHotY=0,fCurTurnedHotX=0,fCurTurnedHotY=0,fCurX=0,fCurY=0;
 bool fCurHaveImage=false,fCurVisible=false;int fCurRc=0;unsigned scheduled=0,applies=0;
 bool convertCursorImage(void *,IOHardwareCursorDescriptor *,IOHardwareCursorInfo *ci){
  ci->cursorWidth=3;ci->cursorHeight=2;ci->cursorHotSpotX=1;ci->cursorHotSpotY=0;
  auto *out=(UInt32 *)ci->hardwareCursorData;for(unsigned i=0;i<6;++i)out[i]=0xff000001+i;return true;
 }
 bool cursorApply(bool=false){++applies;return true;}void scheduleCall(void *,unsigned){++scheduled;}
 void publishCursorGeometry(const IODetailedTimingInformationV2 *);
 IOReturn setCursorImageLocked(void *);IOReturn setCursorState(SInt32,SInt32,bool);
};
@@METHODS@@
int main(){
 unsigned cases=0;
 for(unsigned transform:{0u,0x30u,0x60u,0x50u}){
  NVRMNVDAFramebuffer f;f.fCurTransform=transform;f.publishCursorGeometry(nullptr);
  allocs=0;failAt=0;assert(f.setCursorImageLocked(nullptr)==0&&f.fCurHaveImage);
  const bool swap=transform&kIOScaleSwapAxes;
  const unsigned w=swap?2:3,h=swap?3:2;
  // Independent inverse mapping from each original bitmap pixel into the rotated cursor.
  for(unsigned sy=0;sy<2;++sy)for(unsigned sx=0;sx<3;++sx){
   unsigned x=swap?sy:sx,y=swap?sx:sy;
   if(transform&kIOScaleInvertY)x=w-1-x;
   if(transform&kIOScaleInvertX)y=h-1-y;
   assert(f.pixels[y*4+x]==0xff000001+sy*3+sx);
  }
  for(unsigned y=0;y<4;++y)for(unsigned x=0;x<4;++x)if(x>=w||y>=h)assert(!f.pixels[y*4+x]);
  const unsigned lw=swap?1080:1920,lh=swap?1920:1080;
  for(unsigned y:{0u,lh/2,lh-1})for(unsigned x:{0u,lw/2,lw-1}){
   // The caller's top-left already includes the original cursor hotspot.
   assert(f.setCursorState((SInt32)x-1,(SInt32)y,true)==0);
   unsigned px=swap?y:x,py=swap?x:y;
   if(transform&kIOScaleInvertY)px=1919-px;
   if(transform&kIOScaleInvertX)py=1079-py;
   assert(f.fCurX==(SInt32)px-f.fCurTurnedHotX&&f.fCurY==(SInt32)py-f.fCurTurnedHotY);++cases;
  }
  assert(f.setCursorState(INT32_MAX,INT32_MIN,true)==0); // sanitizer catches arithmetic overflow
  if(transform){allocs=0;failAt=2;assert(f.setCursorImageLocked(nullptr)!=0&&!f.fCurHaveImage);failAt=0;}
 }
 // HiDPI logical coordinates scale to the physical raster without changing the desktop.
 NVRMNVDAFramebuffer hidpi;hidpi.fW=3840;hidpi.fH=2160;
 IODetailedTimingInformationV2 d{};d.horizontalScaled=1920;d.verticalScaled=1080;
 hidpi.publishCursorGeometry(&d);hidpi.setCursorState(100,50,true);
 assert(hidpi.fCurX==200&&hidpi.fCurY==100);
 // Concurrent moves see complete old/new geometry snapshots, never mixed widths/heights.
 NVRMNVDAFramebuffer changing;
 changing.publishCursorGeometry(nullptr);
 std::thread writer([&]{for(unsigned i=0;i<5000;++i){changing.fW=i&1?1920:3840;changing.fH=i&1?1080:2160;changing.publishCursorGeometry(&d);}});
 for(unsigned i=0;i<5000;++i){changing.setCursorState(100,50,true);assert((changing.fCurX==100&&changing.fCurY==50)||(changing.fCurX==200&&changing.fCurY==100));}
 writer.join();
 puts("PASS: production cursor bitmap/hotspot/position for all angles; HiDPI, negative/edge/extreme coordinates, allocation refusal and concurrent geometry publication");
}
'''
run(fixture.replace('@@METHODS@@', methods))
