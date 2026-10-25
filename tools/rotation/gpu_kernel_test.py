#!/usr/bin/env python3
"""Exercise the actual metadata and GPU presenter with bounded host doubles."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[2]
production=(root/'kexts/NVRM/accel/nvrm-rotation-gpu.h').read_text()
fixture=r'''
#include <atomic>
#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstring>
#include <map>
#include <mutex>
#include <condition_variable>
#include <thread>
#include <chrono>
#include <functional>
#include "gpu_state.h"
#include "source_probe.h"
using IOReturn=int;using task_t=void *;
constexpr int kIOReturnSuccess=0,kIOReturnNoMemory=-1,kIOReturnBusy=-2,kIOReturnIOError=-3;
constexpr unsigned NVRM_SS_OFF=0x80000002u,NVRM_SS_NO_SURFACE=0x80000003u,NVRM_SS_TOO_SMALL=0x80000004u,NVRM_SS_BUSY=0x80000007u;
struct OSObject { int refs=1;void retain(){++refs;}void release(){assert(refs>0);--refs;} };
struct OSSymbol:OSObject {const char *name;static const OSSymbol *withCStringNoCopy(const char *s){static OSSymbol symbol;symbol.name=s;return &symbol;}void release()const{}};
struct NVVidMemory {void *fRmHandle=(void *)99;bool fScanout=false;uint64_t fAllocationCookie=7,fBytes=4096;};
struct NVResource:OSObject {char padding[128]={};NVVidMemory *memory=nullptr;uint64_t fPluginWroteCookie=7;};
struct Cache:OSObject {char padding[128]={};};
#define OSDynamicCast(type,pointer) static_cast<type *>(pointer)
struct IOSurface:OSObject {
 unsigned id;uint64_t width=7,height=5,pitch=32;uint32_t format=0x42475241u;Cache *cache=nullptr;
 unsigned getSurfaceID(){return id;}uint64_t getWidth(){return width;}uint64_t getHeight(){return height;}
 uint64_t getBytesPerRow(){return pitch;}uint32_t getPixelFormat(){return format;}
};
static std::function<void()> infoHook;
struct IOService:OSObject {
 NMRotationMode mode={NM_ROTATION_VERSION,180,7,7,5,7,5,32,0,1,3};unsigned flips=0;int result=0;
 IOReturn callPlatformFunction(const OSSymbol *symbol,bool,void *argument,void *,void *,void *){
  if(!strcmp(symbol->name,NM_ROTATION_INFO)){auto hook=std::move(infoHook);if(hook)hook();*(NMRotationMode *)argument=mode;return 0;}
  assert(!strcmp(symbol->name,NM_ROTATION_GPU_FLIP));auto *r=(NMRotationGPUFlip *)argument;
  assert(r->version==NM_ROTATION_GPU_PROTOCOL&&r->mode.head==mode.head&&r->memory==(void *)99&&r->allocationCookie==7&&r->width==7&&r->height==5&&r->pitch==32);
  ++flips;return result;
 }
};
using IOLock=std::mutex;static IOLock *IOLockAlloc(){return new IOLock;}static void IOLockFree(IOLock *p){delete p;}
static void IOLockLock(IOLock *p){p->lock();}static void IOLockUnlock(IOLock *p){p->unlock();}
static std::condition_variable handoff;static std::atomic<unsigned> sleeps;static bool relaxedHostDeadline=false;
constexpr unsigned kMicrosecondScale=1000;constexpr int THREAD_UNINT=0;
static uint64_t mach_absolute_time(){return (uint64_t)std::chrono::duration_cast<std::chrono::nanoseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();}
static void clock_interval_to_deadline(unsigned interval,unsigned scale,uint64_t *deadline){
 assert(interval<=1000&&scale==kMicrosecondScale);
 // The production budget stays <=1ms. Give an instrumented host's publisher
 // thread more scheduling slack for the positive wake-up test only.
 *deadline=mach_absolute_time()+(uint64_t)interval*scale*(relaxedHostDeadline?100:1);
}
static void IOLockWakeup(IOLock *,void *,bool){handoff.notify_all();}
static void IOLockSleepDeadline(IOLock *p,void *,uint64_t deadline,int){
 ++sleeps;std::unique_lock<std::mutex> held(*p,std::adopt_lock);
 handoff.wait_until(held,std::chrono::steady_clock::time_point(std::chrono::nanoseconds(deadline)));held.release();
}
static bool OSCompareAndSwapPtr(void *expected,void *value,void *volatile *p){return __atomic_compare_exchange_n(p,&expected,value,false,__ATOMIC_SEQ_CST,__ATOMIC_SEQ_CST);}
static int64_t OSAddAtomic64(int64_t n,int64_t *p){return *p+=n;}
static const char *caller="WindowServer";static void proc_selfname(char *p,unsigned n){snprintf(p,n,"%s",caller);}
static int gRotationGPUOn=1,gSurfGpuOn=1;static int64_t gCntRotationGPUReady,gCntRotationGPUFlip,gCntRotationGPUHeld;
static int64_t gCntRotationGPUFlipHead[NM_ROTATION_GPU_HEADS];
static int gRotationGPUWaitUs=1000;
static int64_t gCntRotationGPUMetadataWait,gCntRotationGPUMetadataTimeout,gCntRotationGPUNoReady;
static int64_t gCntRotationGPUSourceStale,gCntRotationGPUOutputRefused,gCntRotationGPUFlipRefused;
static IOLock *volatile gRotationGPULock;static NMRotationGPUState gRotationGPUState={};
static IOSurface *gRotationGPUSources[5][8],*gRotationGPUOutputs[5][3];static IOService *gRotationGPUFB[5];
static void *gNVSVRoot=(void *)1;static bool gIopFlipped[5],rights=true,gpuReady=true,restore=true;static unsigned restores=0,lookups=0;
static std::map<unsigned,IOSurface *> surfaces;
struct NVRMSurfShareEsc {unsigned plane,surfaceID;};
static void *_ZN13IOSurfaceRoot13lookupSurfaceEjP4task(void *,unsigned id,task_t){
 ++lookups;if(!rights||!surfaces.count(id))return nullptr;surfaces[id]->retain();return surfaces[id];
}
struct NVAccel {static inline void *gAccel=(void *)1;};
static void *_ZN22IOGraphicsAccelerator223deviceCacheForIOSurfaceEP9IOSurfacej(void *,IOSurface *s,unsigned){if(s->cache)s->cache->retain();return s->cache;}
static NVVidMemory *nvres_vidmem(NVResource *r){return r->memory;}
static bool nvAccelRestoreParkedForDirty(NVResource *,NVVidMemory *,unsigned plane){assert(!plane);++restores;return restore;}
static bool nvAccelPluginWrote(uint64_t a,uint64_t b){return a&&a==b;}
static bool nvSurfWaitReady(unsigned){return gpuReady;}
@@PRODUCTION@@
static unsigned control(unsigned sid,unsigned operation){
 if(operation==NM_ROTATION_GPU_BEGIN)operation=nmRotationGPUBegin(0);
 NVRMSurfShareEsc p={operation,sid};return nvRotationGPUEscape(&p,(void *)1);
}
static unsigned beginHead(unsigned sid,unsigned head){return control(sid,nmRotationGPUBegin(head));}
static void attach(IOSurface &s,Cache &cache,NVResource &resource,unsigned short *valid,NVVidMemory &memory){
 s.cache=&cache;resource.memory=&memory;*(OSObject **)((unsigned char *)&cache+0x20)=&resource;
 *(unsigned short **)((unsigned char *)&resource+0x30)=valid;
}
int main(){
 IOService fb;IOSurface source,output;source.id=10;output.id=20;surfaces[20]=&output;
 Cache sc,dc;NVResource sr,dr;NVVidMemory sm,dm;unsigned short sv[8]={},dv[8]={};sv[6]=dv[6]=1;
 attach(source,sc,sr,sv,sm);attach(output,dc,dr,dv,dm);
 nvRotationGPUObserve(&fb,&source,fb.mode);assert(source.refs==2&&fb.refs==2);
 assert(control(99,NM_ROTATION_GPU_BEGIN)==0);
 caller="other";assert(control(10,NM_ROTATION_GPU_BEGIN)==NVRM_SS_OFF);caller="WindowServer";
 auto ticket=control(10,NM_ROTATION_GPU_BEGIN);assert(nmRotationGPUTicketHead(ticket)==0);
 rights=false;assert(control(20,NM_ROTATION_GPU_BIND|ticket)==NVRM_SS_NO_SURFACE);rights=true;
 output.width=8;assert(control(20,NM_ROTATION_GPU_BIND|ticket)==NVRM_SS_TOO_SMALL);output.width=7;
 assert(output.refs==1&&control(20,NM_ROTATION_GPU_BIND|ticket)==0&&output.refs==2);
 assert(nvRotationGPUTry(&fb,0,&source,fb.mode)==-1&&!fb.flips);
 nvRotationGPUPending(10);assert(control(10,NM_ROTATION_GPU_DONE|ticket)==0&&gCntRotationGPUReady==1);
 // Destination must be GPU-current, cookie-owned and restored before scanout.
 dv[6]=0;assert(nvRotationGPUTry(&fb,0,&source,fb.mode)==-1&&!fb.flips);dv[6]=1;
 dr.fPluginWroteCookie=8;assert(nvRotationGPUTry(&fb,0,&source,fb.mode)==-1&&!fb.flips);dr.fPluginWroteCookie=7;
 restore=false;assert(nvRotationGPUTry(&fb,0,&source,fb.mode)==-1&&!fb.flips);restore=true;
 sv[6]=0;assert(nvRotationGPUTry(&fb,0,&source,fb.mode)==-1&&!fb.flips);sv[6]=1;
 gpuReady=false;assert(nvRotationGPUTry(&fb,0,&source,fb.mode)==-1&&!fb.flips);gpuReady=true;
 auto stale=fb.mode;++stale.epoch;assert(nvRotationGPUTry(&fb,0,&source,stale)==-1&&!fb.flips);
 assert(nvRotationGPUTry(&fb,1,&source,fb.mode)==-1&&!fb.flips);
 fb.result=kIOReturnBusy;assert(nvRotationGPUTry(&fb,0,&source,fb.mode)==0&&gCntRotationGPUHeld==1&&!gIopFlipped[0]);
 fb.result=0;assert(nvRotationGPUTry(&fb,0,&source,fb.mode)==1&&gIopFlipped[0]&&gCntRotationGPUFlip==1&&restores);
 assert(control(20,NM_ROTATION_GPU_BIND|ticket)==NVRM_SS_BUSY);
 // The source-ready mark can clear before DONE publishes its GPU output. The
 // exact in-flight job waits without holding the metadata mutex; DONE wakes it.
 IOSurface race;race.id=22;surfaces[22]=&race;Cache rc;NVResource rr;NVVidMemory rm;unsigned short rv[8]={};rv[6]=1;
 attach(race,rc,rr,rv,rm);ticket=control(10,NM_ROTATION_GPU_BEGIN);assert(control(22,NM_ROTATION_GPU_BIND|ticket)==0);nvRotationGPUPending(10);
 relaxedHostDeadline=true;const unsigned oldSleeps=sleeps;
 std::thread publication([&]{
  const auto end=std::chrono::steady_clock::now()+std::chrono::milliseconds(150);
  while(sleeps==oldSleeps&&std::chrono::steady_clock::now()<end)std::this_thread::yield();
  assert(control(10,NM_ROTATION_GPU_DONE|ticket)==0);
 });
 const int handed=nvRotationGPUTry(&fb,0,&source,fb.mode);publication.join();relaxedHostDeadline=false;
 assert(handed==1&&sleeps>oldSleeps&&gCntRotationGPUMetadataWait==1&&gCntRotationGPUMetadataTimeout==0);
 // A missing DONE is bounded and returns to CPU; no unknown/stale source wait.
 IOSurface late;late.id=23;surfaces[23]=&late;
 ticket=control(10,NM_ROTATION_GPU_BEGIN);assert(control(23,NM_ROTATION_GPU_BIND|ticket)==0);nvRotationGPUPending(10);
 gRotationGPUWaitUs=100000; // A runtime request cannot exceed the 1000-us cap.
 assert(nvRotationGPUTry(&fb,0,&source,fb.mode)==-1&&gCntRotationGPUMetadataTimeout==1);
 assert(control(10,NM_ROTATION_GPU_CANCEL|ticket)==0);
 const unsigned afterTimeout=sleeps;assert(nvRotationGPUTry(&fb,0,&source,fb.mode)==-1&&sleeps==afterTimeout);
 ticket=control(10,NM_ROTATION_GPU_BEGIN);assert(control(23,NM_ROTATION_GPU_BIND|ticket)==0);nvRotationGPUPending(10);
 gRotationGPUWaitUs=0;assert(nvRotationGPUTry(&fb,0,&source,fb.mode)==-1&&sleeps==afterTimeout);
 assert(control(10,NM_ROTATION_GPU_CANCEL|ticket)==0);gRotationGPUWaitUs=1000;
 // New mode refuses old tickets and reuses no live output. Completion disabled
 // at runtime clears READY even for an otherwise valid job.
 ++fb.mode.epoch;assert(control(10,NM_ROTATION_GPU_BEGIN)==0);nvRotationGPUObserve(&fb,&source,fb.mode);
 IOSurface second;second.id=21;surfaces[21]=&second;
 ticket=control(10,NM_ROTATION_GPU_BEGIN);assert(control(21,NM_ROTATION_GPU_BIND|ticket)==0);
 nvRotationGPUPending(10);gRotationGPUOn=0;assert(control(10,NM_ROTATION_GPU_DONE|ticket)==0);
 assert(!gRotationGPUState.find(10,0)->ready&&nvRotationGPUTry(&fb,0,&source,fb.mode)==-1);
 gRotationGPUOn=1;ticket=control(10,NM_ROTATION_GPU_BEGIN);assert(control(21,NM_ROTATION_GPU_BIND|ticket)==0);
 assert(control(10,NM_ROTATION_GPU_CANCEL|ticket)==0&&!gRotationGPUState.find(10,0)->ready);
 // Shared original image, independent framebuffer/mode and output on display 1.
 IOService fb1;fb1.mode.head=1;fb1.mode.degrees=270;fb1.mode.logicalWidth=5;fb1.mode.logicalHeight=7;
 nvRotationGPUObserve(&fb1,&source,fb1.mode);
 IOSurface out1;out1.id=35;surfaces[35]=&out1;Cache c1;NVResource r1;NVVidMemory m1;unsigned short v1[8]={};v1[6]=1;
 attach(out1,c1,r1,v1,m1);
 auto other=beginHead(10,1);assert(nmRotationGPUTicketHead(other)==1&&control(35,NM_ROTATION_GPU_BIND|other)==0);
 assert(beginHead(10,2)==0); // source never observed on this display
 nvRotationGPUPending(10);assert(control(10,NM_ROTATION_GPU_DONE|other)==0);
 assert(nvRotationGPUTry(&fb,1,&source,fb1.mode)==-1&&!fb1.flips); // wrong framebuffer identity
 assert(nvRotationGPUTry(&fb1,1,&source,fb1.mode)==1&&fb1.flips==1&&gIopFlipped[1]&&gCntRotationGPUFlipHead[1]==1);
 // Detach/reconnect with identical geometry/epoch still invalidates old results.
 IOService reconnected;reconnected.mode=fb1.mode;
 nvRotationGPUObserve(&reconnected,&source,reconnected.mode);
 assert(!gRotationGPUState.find(10,1)->ready&&nvRotationGPUTry(&reconnected,1,&source,reconnected.mode)==-1);
 // BEGIN queries modes outside the metadata mutex. Reject a result from an old
 // framebuffer if the owner changed while the mode query was in progress.
 IOService replacement;replacement.mode=reconnected.mode;
 infoHook=[&]{nvRotationGPUObserve(&replacement,&source,replacement.mode);};
 assert(beginHead(10,1)==0&&gRotationGPUFB[1]==&replacement);
 assert(beginHead(10,1));
 assert(sc.refs==1&&dc.refs==1&&second.refs==2);
 delete gRotationGPULock;
 puts("PASS: actual kernel GPU control/presenter; authorization, rights, geometry/mode, pending witness, retained surfaces, allocation cookie/parked restoration, Busy hold, source-ready-before-DONE handoff, unlocked wake, bounded missing-DONE fallback, no unknown/stale wait or family-lock recursion");
}
'''
with tempfile.TemporaryDirectory(prefix='nm-gpu-kernel-') as directory:
 p=Path(directory);(p/'test.cpp').write_text(fixture.replace('@@PRODUCTION@@',production))
 subprocess.run(['xcrun','clang++','-std=c++17','-O1','-g','-fsanitize=address,undefined',
  '-I'+str(root/'tools/rotation'),str(p/'test.cpp'),'-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=20)
 # Preserve the rest of the actual presenter, removing only the handoff wait.
 # The source-ready-before-DONE schedule must then miss the GPU output.
 a=production.index('    // The normal source-ready mark')
 b=production.index('    if(slot){ticket=',a)
 negative=production[:a]+production[b:]
 (p/'negative.cpp').write_text(fixture.replace('@@PRODUCTION@@',negative))
 subprocess.run(['xcrun','clang++','-std=c++17','-O1','-g','-fsanitize=address,undefined',
  '-I'+str(root/'tools/rotation'),str(p/'negative.cpp'),'-o',str(p/'negative')],check=True)
 failed=subprocess.run([str(p/'negative')],capture_output=True,text=True,timeout=20)
 assert failed.returncode!=0 and 'handed==1' in failed.stderr,failed.stderr
 print('PASS: negative control without the metadata wait misses the GPU handoff, as required')
