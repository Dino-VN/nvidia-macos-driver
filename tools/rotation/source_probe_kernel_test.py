#!/usr/bin/env python3
"""Exercise the actual root-only probe handlers and reference handoff with host stubs."""
from pathlib import Path
import subprocess
import tempfile

root=Path(__file__).resolve().parents[2]
text=(root/'kexts/NVRM/accel/nvrm-accel.cpp').read_text()
start=text.index('static OSData *gRotationProbeArmed, *gRotationProbeComplete;')
methods=text[start:text.index('static bool gSysctlInstalled = false;',start)]
fixture=r'''
#include <cassert>
#include <cerrno>
#include <cstring>
#include <cstdio>
#include <mutex>
#include <atomic>
#include <thread>
#include <vector>
#include "source_probe.h"
static std::atomic<unsigned> live{0};
static std::atomic<bool> copyEntered{false},copyResume{false},dataEntered{false},dataResume{false};
static thread_local bool blockData=false;
struct OSObject{virtual ~OSObject(){};virtual void release(){}};
static OSObject yes;static OSObject *kOSBooleanTrue=&yes;
struct OSData:OSObject{
    std::atomic<unsigned> refs{1};std::vector<unsigned char> bytes;
    static OSData *withCapacity(size_t n){auto *p=new OSData;p->bytes.reserve(n);++live;return p;}
    bool appendBytes(const void *,size_t n){bytes.resize(n);return true;}
    void retain(){++refs;}void release()override{if(--refs==0){--live;delete this;}}
    void *getBytesNoCopy(){if(blockData){dataEntered=true;while(!dataResume)std::this_thread::yield();}return bytes.data();}
    unsigned getLength(){return (unsigned)bytes.size();}
};
struct IOLock{std::mutex mutex;};static IOLock sharedLock,*gSurfPendLock=&sharedLock;
static IOLock *nvSurfLock(){return gSurfPendLock;}
static void IOLockLock(IOLock *l){l->mutex.lock();}static bool IOLockTryLock(IOLock *l){return l->mutex.try_lock();}
static void IOLockUnlock(IOLock *l){l->mutex.unlock();}
static uint64_t now=100;static uint64_t mach_absolute_time(){return now;}
enum{kSecondScale=1};static void clock_interval_to_deadline(unsigned n,unsigned,uint64_t *out){*out=now+n;}
static thread_local bool rootUser=true;static int kauth_cred_get(){return rootUser?1:0;}static bool kauth_cred_issuser(int c){return c;}
struct IOService{bool prototype=true;OSObject *getProperty(const char *){return prototype?kOSBooleanTrue:nullptr;}};
struct NVAccel{IOService *fFB;static NVAccel *gAccel;};static IOService fb;static NVAccel accel{&fb};NVAccel *NVAccel::gAccel=&accel;
struct IOSurface{unsigned getSurfaceID(){return 9;}unsigned getPixelFormat(){return 0x42475241u;}
    uint64_t getWidth(){return 7;}uint64_t getHeight(){return 5;}uint64_t getBytesPerRow(){return 32;}};
struct NVResource:OSObject{unsigned char bytes[256]={};};static NVResource resource;
#define OSDynamicCast(C,p) dynamic_cast<C *>(p)
struct IOAccelDisplayPipeTransaction2{
    void *opaque[7]={};unsigned char *args;unsigned char storage[0x108]={};
    IOAccelDisplayPipeTransaction2(){args=storage;}
    OSObject *getPlaneResource(unsigned,unsigned){return &resource;}
};
static_assert(offsetof(IOAccelDisplayPipeTransaction2,args)==0x38);
struct Request{void *newptr=nullptr;int value=0;std::vector<unsigned char> output;bool block=false;};
#define SYSCTL_HANDLER_ARGS (void *oidp,void *arg1,int arg2,Request *req)
#define SYSCTL_PROC(...)
static int sysctl_handle_int(void *,int *v,int,Request *req){if(req->newptr)*v=req->value;return 0;}
static int output(Request *req,const void *p,size_t n){
    if(req->block){copyEntered=true;while(!copyResume)std::this_thread::yield();}
    req->output.assign((const unsigned char *)p,(const unsigned char *)p+n);return 0;
}
#define SYSCTL_OUT(req,p,n) output(req,p,n)
@@METHODS@@
static int arm(unsigned value){Request r;r.newptr=&r;r.value=(int)value;return nvRotationProbeArmSysctl(nullptr,nullptr,0,&r);}
static void capture(){
    NMRotationMode mode={NM_ROTATION_VERSION,90,4,5,7,7,5,32,0,1,0};
    IOSurface surface;IOAccelDisplayPipeTransaction2 transaction;
    uint32_t src[40]={};for(unsigned i=0;i<40;++i)src[i]=i;
    *(uint16_t *)((unsigned char *)&resource+0xb0)=7;
    *(uint16_t *)((unsigned char *)&resource+0xb2)=5;
    *(uint32_t *)((unsigned char *)&resource+0xb8)=32;
    *(uint32_t *)(transaction.args+0x48)=0x3f800000;
    *(uint32_t *)(transaction.args+0xf0)=0x40000000;
    nvRotationProbeCapture(mode,&surface,&transaction,src,sizeof(src));
}
int main(){
    Request read;
    rootUser=false;assert(arm(90)==EPERM);assert(nvRotationProbeReadSysctl(nullptr,nullptr,0,&read)==EPERM);rootUser=true;
    fb.prototype=false;assert(arm(90)==EINVAL);fb.prototype=true;assert(arm(45)==EINVAL);
    assert(nvRotationProbeReadSysctl(nullptr,nullptr,0,&read)==EAGAIN);
    assert(arm(90)==0&&nvRotationProbeArmed(90)&&!nvRotationProbeArmed(180)&&live==1);
    capture();assert(!nvRotationProbeArmed(90)&&live==1);
    assert(nvRotationProbeReadSysctl(nullptr,nullptr,0,&read)==0);
    auto *h=(const NMRotationSourceProbe *)read.output.data();
    assert(h->sourceWidth==7&&h->sourceHeight==5&&h->logicalWidth==5&&h->logicalHeight==7);
    assert(h->resourceWidth==7&&h->resourceHeight==5&&h->resourcePitch==32);
    assert(h->sourceRectBits[0]==0x3f800000&&h->pipeScalerBits[0]==0x40000000);
    assert(h->headerBytes==160&&read.output.size()==160+7*5*4);
    // A blocked copyout retains its immutable buffer. It holds no presenter lock,
    // and root can discard/rearm while that read is in progress.
    Request blocked;blocked.block=true;
    std::thread reader([&]{assert(nvRotationProbeReadSysctl(nullptr,nullptr,0,&blocked)==0);});
    while(!copyEntered)std::this_thread::yield();
    assert(arm(0)==0&&live==1);copyResume=true;reader.join();assert(live==0&&blocked.output==read.output);
    assert(arm(90)==0);now+=21;assert(!nvRotationProbeArmed(90));capture();
    assert(nvRotationProbeReadSysctl(nullptr,nullptr,0,&read)==EAGAIN);assert(arm(0)==0&&live==0);
    // A cancel after the transaction claims its preallocated buffer must not
    // publish a late screenshot, or repopulate memory after root discarded it.
    assert(arm(90)==0);
    std::thread copying([&]{blockData=true;capture();});
    while(!dataEntered)std::this_thread::yield();
    assert(arm(0)==0);dataResume=true;copying.join();assert(live==0);
    assert(nvRotationProbeReadSysctl(nullptr,nullptr,0,&read)==EAGAIN);
    puts("PASS: production probe handlers; root-only access, single-frame/expiry, real source stride and rect metadata, no locks across copyout, retained reader/discard/rearm, cancel during capture, no leaked buffers");
}
'''
with tempfile.TemporaryDirectory(prefix='nm-rotation-probe-') as directory:
    tmp=Path(directory)
    (tmp/'test.cpp').write_text(fixture.replace('@@METHODS@@',methods))
    subprocess.run(['xcrun','clang++','-std=c++17','-O1','-g','-fsanitize=address,undefined','-pthread',
                    '-I'+str(root/'tools/rotation'),str(tmp/'test.cpp'),'-o',str(tmp/'test')],check=True)
    subprocess.run([str(tmp/'test')],check=True,timeout=20)
