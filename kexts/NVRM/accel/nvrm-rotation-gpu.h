/* Per-display GPU completion and scanout. Included after resource definitions. */
static IOLock *nvRotationGPULock()
{
    if (!gRotationGPULock) {
        IOLock *lock=IOLockAlloc();
        if(lock&&!OSCompareAndSwapPtr(nullptr,lock,(void *volatile *)&gRotationGPULock))IOLockFree(lock);
    }
    return gRotationGPULock;
}
static void nvRotationGPUObserve(IOService *fb,IOSurface *source,const NMRotationMode &mode)
{
    if(!gRotationGPUOn||!gSurfGpuOn||!source||mode.head>=NM_ROTATION_GPU_HEADS)return;
    IOLock *lock=nvRotationGPULock();if(!lock)return;
    IOSurface *old=nullptr;IOService *oldFB=nullptr;
    IOLockLock(lock);
    if(gRotationGPUFB[mode.head]&&gRotationGPUFB[mode.head]!=fb)
        gRotationGPUState.invalidateSources(mode.head);
    const unsigned index=gRotationGPUState.observe(source->getSurfaceID(),mode);
    if(index!=UINT32_MAX) {
        if(gRotationGPUSources[mode.head][index]!=source){((OSObject *)source)->retain();old=gRotationGPUSources[mode.head][index];gRotationGPUSources[mode.head][index]=source;}
        if(gRotationGPUFB[mode.head]!=fb){fb->retain();oldFB=gRotationGPUFB[mode.head];gRotationGPUFB[mode.head]=fb;}
    }
    IOLockUnlock(lock);
    if(old)((OSObject *)old)->release();if(oldFB)oldFB->release();
}
static void nvRotationGPUPending(unsigned source)
{
    IOLock *lock=gRotationGPULock;if(!lock)return;
    IOLockLock(lock);gRotationGPUState.pending(source);IOLockUnlock(lock);
}
// Metadata escapes never acquire the accelerator family lock, import an image,
// submit work or wait for completion. BIND only retains an existing IOSurface.
static unsigned nvRotationGPUEscape(const NVRMSurfShareEsc *p,task_t task)
{
    char name[32]={};proc_selfname(name,sizeof name);
    if(strcmp(name,"WindowServer"))return NVRM_SS_OFF;
    const unsigned op=p->plane&~NM_ROTATION_GPU_PAYLOAD,ticket=p->plane&NM_ROTATION_GPU_PAYLOAD;
    if(op!=NM_ROTATION_GPU_BEGIN&&op!=NM_ROTATION_GPU_BIND&&op!=NM_ROTATION_GPU_DONE&&op!=NM_ROTATION_GPU_CANCEL)return NVRM_SS_OFF;
    IOLock *lock=nvRotationGPULock();if(!lock)return NVRM_SS_OFF;
    if(op==NM_ROTATION_GPU_DONE||op==NM_ROTATION_GPU_CANCEL) {
        IOLockLock(lock);
        const int head=nmRotationGPUTicketHead(ticket);
        NMRotationGPUSlot *slot=gRotationGPUState.slotFor(ticket);
        auto *source=head<0?nullptr:gRotationGPUState.find(p->surfaceID,(unsigned)head);
        const bool owned=(slot&&slot->source==p->surfaceID)||
            (op==NM_ROTATION_GPU_CANCEL&&source&&source->latest==ticket);
        bool published=false;
        if(owned) {
            if(op==NM_ROTATION_GPU_DONE)published=gRotationGPUState.done(p->surfaceID,ticket);
            else gRotationGPUState.cancel(ticket,p->surfaceID);
            if(!gRotationGPUOn||!gSurfGpuOn){if(source)source->ready=0;published=false;}
            IOLockWakeup(lock,&gRotationGPUState,false);
        }
        IOLockUnlock(lock);
        if(published)OSAddAtomic64(1,&gCntRotationGPUReady);
        return owned?0:NVRM_SS_NO_SURFACE;
    }
    if(!gRotationGPUOn||!gSurfGpuOn||!task)return NVRM_SS_OFF;
    if(op==NM_ROTATION_GPU_BEGIN) {
        if(!ticket||ticket>NM_ROTATION_GPU_HEADS)return NVRM_SS_OFF;
        const unsigned head=ticket-1u;
        IOService *fb=nullptr;
        IOLockLock(lock);
        if(gRotationGPUState.find(p->surfaceID,head)){fb=gRotationGPUFB[head];if(fb)fb->retain();}
        IOLockUnlock(lock);
        if(!fb)return 0;
        NMRotationMode current={};current.version=NM_ROTATION_VERSION;
        const OSSymbol *sym=OSSymbol::withCStringNoCopy(NM_ROTATION_INFO);
        IOReturn r=sym?fb->callPlatformFunction(sym,false,&current,nullptr,nullptr,nullptr):kIOReturnNoMemory;
        if(sym)sym->release();
        unsigned result=0;
        if(r==kIOReturnSuccess&&nmRotationModeValid(&current)&&current.degrees&&current.head==head) {
            IOLockLock(lock);
            if(gRotationGPUFB[head]==fb)result=gRotationGPUState.begin(p->surfaceID,current);
            IOLockUnlock(lock);
        }
        fb->release();
        return result;
    }
    const int head=nmRotationGPUTicketHead(ticket);
    if(head<0||!p->surfaceID||!gNVSVRoot)return NVRM_SS_NO_SURFACE;
    NMRotationMode mode={};bool found=false;
    IOLockLock(lock);
    for(auto &source:gRotationGPUState.heads[head].sources)if(source.latest==ticket){mode=source.mode;found=true;break;}
    IOLockUnlock(lock);
    if(!found||!nmRotationModeValid(&mode))return NVRM_SS_NO_SURFACE;
    IOSurface *output=(IOSurface *)_ZN13IOSurfaceRoot13lookupSurfaceEjP4task(gNVSVRoot,p->surfaceID,task);
    if(!output)return NVRM_SS_NO_SURFACE;
    const uint64_t width=output->getWidth(),height=output->getHeight(),pitch=output->getBytesPerRow();
    if(output->getPixelFormat()!=0x42475241u||width!=mode.outputWidth||height!=mode.outputHeight||
       !nmRotationSourceGeometry(width,height,pitch,pitch*height)) {((OSObject *)output)->release();return NVRM_SS_TOO_SMALL;}
    IOSurface *old=nullptr;
    IOLockLock(lock);
    const int index=gRotationGPUState.bind(ticket,p->surfaceID);
    if(index>=0){old=gRotationGPUOutputs[head][index];gRotationGPUOutputs[head][index]=output;}
    IOLockUnlock(lock);
    if(old)((OSObject *)old)->release();
    if(index<0){((OSObject *)output)->release();return NVRM_SS_BUSY;}
    return 0;
}
// Called only by performTransaction with the family's existing lock ownership.
// Unlike the normal flip's cache-miss helper, this never reacquires that mutex.
static int nvRotationGPUTry(IOService *fb,unsigned head,IOSurface *source,const NMRotationMode &mode)
{
    if(!gRotationGPUOn||!gSurfGpuOn||!gRotationGPULock||head>=NM_ROTATION_GPU_HEADS||head!=mode.head)return -1;
    IOSurface *output=nullptr;uint32_t ticket=0;
    IOLockLock(gRotationGPULock);
    NMRotationGPUSlot *slot=gRotationGPUFB[head]==fb?gRotationGPUState.take(source->getSurfaceID(),mode):nullptr;
    // The normal source-ready mark is released before surface publication (a
    // page-off may hold the surface lock while waiting for that mark). DONE must
    // stay after publication. Bridge that small gap only for an exact registered
    // job, dropping this metadata lock while asleep. No family lock is acquired
    // by DONE/CANCEL; publication uses its existing nonblocking dirty re-mark.
    // Never wait for an unknown source, a stale job or a second GPU submission.
    const unsigned budget=gRotationGPUWaitUs<=0?0:gRotationGPUWaitUs>1000?1000:(unsigned)gRotationGPUWaitUs;
    if(!slot&&budget&&gRotationGPUFB[head]==fb&&gRotationGPUState.awaiting(source->getSurfaceID(),mode)) {
        uint64_t deadline=0;clock_interval_to_deadline(budget,kMicrosecondScale,&deadline);
        OSAddAtomic64(1,&gCntRotationGPUMetadataWait);
        while(!slot&&gRotationGPUOn&&gSurfGpuOn&&gRotationGPUFB[head]==fb&&
              gRotationGPUState.awaiting(source->getSurfaceID(),mode)&&mach_absolute_time()<deadline) {
            IOLockSleepDeadline(gRotationGPULock,&gRotationGPUState,deadline,THREAD_UNINT);
            if(gRotationGPUFB[head]==fb)slot=gRotationGPUState.take(source->getSurfaceID(),mode);
        }
        if(!slot&&gRotationGPUState.awaiting(source->getSurfaceID(),mode)&&mach_absolute_time()>=deadline)
            OSAddAtomic64(1,&gCntRotationGPUMetadataTimeout);
    }
    if(slot){ticket=slot->ticket;const unsigned index=(unsigned)(slot-gRotationGPUState.heads[head].slots);output=gRotationGPUOutputs[head][index];if(output)((OSObject *)output)->retain();}
    IOLockUnlock(gRotationGPULock);
    if(!ticket){OSAddAtomic64(1,&gCntRotationGPUNoReady);return -1;}
    bool flipped=false;int result=-1;
    if(output&&nvSurfWaitReady(output->getSurfaceID())) {
        // The source may have been CPU-written since READY. Only a GPU-current
        // source can name a reusable GPU result; normal CPU copy is the fallback.
        void *sourceCache=_ZN22IOGraphicsAccelerator223deviceCacheForIOSurfaceEP9IOSurfacej(NVAccel::gAccel,source,0);
        NVResource *sourceResource=sourceCache?OSDynamicCast(NVResource,*(OSObject *volatile *)((unsigned char *)sourceCache+0x20)):nullptr;
        volatile unsigned short *sourceValid=sourceResource?*(unsigned short *volatile *)((unsigned char *)sourceResource+0x30):nullptr;
        const bool sourceCurrent=sourceValid&&(sourceValid[6]&1u);
        if(!sourceCurrent)OSAddAtomic64(1,&gCntRotationGPUSourceStale);
        if(sourceCache)((OSObject *)sourceCache)->release();
        void *cache=sourceCurrent?_ZN22IOGraphicsAccelerator223deviceCacheForIOSurfaceEP9IOSurfacej(NVAccel::gAccel,output,0):nullptr;
        NVResource *resource=cache?OSDynamicCast(NVResource,*(OSObject *volatile *)((unsigned char *)cache+0x20)):nullptr;
        NVVidMemory *memory=resource?nvres_vidmem(resource):nullptr;
        volatile unsigned short *valid=resource?*(unsigned short *volatile *)((unsigned char *)resource+0x30):nullptr;
        if(memory&&nvAccelRestoreParkedForDirty(resource,memory,0)&&memory->fRmHandle&&!memory->fScanout&&valid&&(valid[6]&1u)&&
           nvAccelPluginWrote(resource->fPluginWroteCookie,memory->fAllocationCookie)&&
           output->getBytesPerRow()*output->getHeight()<=memory->fBytes) {
            NMRotationGPUFlip request={};request.version=NM_ROTATION_GPU_PROTOCOL;request.mode=mode;
            request.memory=memory->fRmHandle;request.allocationCookie=memory->fAllocationCookie;
            request.width=(uint32_t)output->getWidth();request.height=(uint32_t)output->getHeight();
            request.pitch=(uint32_t)output->getBytesPerRow();request.format=output->getPixelFormat();
            const OSSymbol *sym=OSSymbol::withCStringNoCopy(NM_ROTATION_GPU_FLIP);
            const IOReturn r=sym?fb->callPlatformFunction(sym,false,&request,nullptr,nullptr,nullptr):kIOReturnNoMemory;
            if(sym)sym->release();
            if(r==kIOReturnSuccess){flipped=true;result=1;gIopFlipped[head]=true;OSAddAtomic64(1,&gCntRotationGPUFlip);OSAddAtomic64(1,&gCntRotationGPUFlipHead[head]);}
            else if(r==kIOReturnBusy){result=0;OSAddAtomic64(1,&gCntRotationGPUHeld);}
            else OSAddAtomic64(1,&gCntRotationGPUFlipRefused);
        }
        else if(sourceCurrent)OSAddAtomic64(1,&gCntRotationGPUOutputRefused);
        if(cache)((OSObject *)cache)->release();
    }
    else OSAddAtomic64(1,&gCntRotationGPUOutputRefused);
    IOLockLock(gRotationGPULock);gRotationGPUState.put(ticket,flipped);IOLockUnlock(gRotationGPULock);
    if(output)((OSObject *)output)->release();
    return result;
}
