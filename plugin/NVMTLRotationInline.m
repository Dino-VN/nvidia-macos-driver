/* GPU rotation on the producer queue, with an immutable source and CPU fallback. */
#include "../tools/rotation/gpu_protocol.h"
@interface NVMTLRotationSlot : NSObject {
@public IOSurfaceRef surface; NVMTLTexture *texture; BOOL busy,poisoned;
}
@end
@implementation NVMTLRotationSlot
- (void)dealloc { if(surface)CFRelease(surface); }
@end
@interface NVMTLRotationWork : NSObject {
@public NVMTLRotationSlot *slot; NVMTLTexture *source; uint32_t ticket; BOOL finished; nvk_buffer sourceAlias,destinationAlias;
}
@end
static NSObject *nvmtl_rotation_lock(void) {
    static NSObject *lock;static dispatch_once_t once;
    dispatch_once(&once,^{lock=[NSObject new];});return lock;
}
static NVMTLRotationSlot *nvmtl_rotation_slots[NM_ROTATION_GPU_HEADS][NM_ROTATION_GPU_SLOTS];
static const char nvmtl_rotation_work_key=0;
@implementation NVMTLRotationWork
- (void)dealloc {
    // Unknown/failed GPU work must never make its output reusable. Quarantine
    // this bounded slot; the CPU path remains available for later frames.
    if(!finished)@synchronized(nvmtl_rotation_lock()){slot->poisoned=YES;}
    nvmtl_vk_rotation_buffer_release(&sourceAlias);nvmtl_vk_rotation_buffer_release(&destinationAlias);
}
@end
static BOOL nvmtl_rotation_enabled(void) {
    static _Atomic int enabled=-1;
    const int cached=atomic_load(&enabled);
    if(cached>=0)return cached;
    const char *opt=getenv("NVMTL_ROTATION_GPU");
    if(!getprogname()||strcmp(getprogname(),"WindowServer")||(opt&&opt[0]=='0')){atomic_store(&enabled,0);return NO;}
    io_service_t accelerator=IOServiceGetMatchingService(kIOMainPortDefault,IOServiceMatching("NVAccel"));
    uint32_t version=0;
    if(accelerator) {
        CFTypeRef property=IORegistryEntryCreateCFProperty(accelerator,CFSTR("NVAccelRotationGPUProtocol"),kCFAllocatorDefault,0);
        if(property&&CFGetTypeID(property)==CFNumberGetTypeID())CFNumberGetValue((CFNumberRef)property,kCFNumberSInt32Type,&version);
        if(property)CFRelease(property);IOObjectRelease(accelerator);
    }
    const BOOL available=version==NM_ROTATION_GPU_PROTOCOL;
    atomic_store(&enabled,available);
    nvlog("GPU rotation protocol 12: %s, producer queue and CPU fallback",available?"enabled":"matching kernel unavailable");
    return available;
}
// Standard avoids per-surface control escapes. A short read-only cache can
// delay GPU use after rotation, but the kernel's exact epoch check remains final.
static uint32_t nvmtl_rotation_heads(void) {
    static _Atomic uint64_t checked;
    static _Atomic uint32_t heads;
    uint64_t previous=atomic_load(&checked),now=clock_gettime_nsec_np(CLOCK_UPTIME_RAW);
    if(now-previous<100000000ull)return atomic_load(&heads);
    if(!atomic_compare_exchange_strong(&checked,&previous,now))return atomic_load(&heads);
    uint32_t rotated=0;io_iterator_t iterator=0;
    if(IOServiceGetMatchingServices(kIOMainPortDefault,IOServiceMatching("NVRMNVDAFramebuffer"),&iterator)==KERN_SUCCESS) {
        io_service_t service;
        while((service=IOIteratorNext(iterator))) {
            CFTypeRef enabled=IORegistryEntryCreateCFProperty(service,CFSTR("NVRMRotationEnabled"),kCFAllocatorDefault,0);
            CFTypeRef value=IORegistryEntryCreateCFProperty(service,CFSTR("NVRMRotationRequestedTransform"),kCFAllocatorDefault,0);
            CFTypeRef index=IORegistryEntryCreateCFProperty(service,CFSTR("IOFBDependentIndex"),kCFAllocatorDefault,0);
            int bits=0,head=-1;
            if(value&&CFGetTypeID(value)==CFNumberGetTypeID())CFNumberGetValue((CFNumberRef)value,kCFNumberIntType,&bits);
            if(index&&CFGetTypeID(index)==CFNumberGetTypeID())CFNumberGetValue((CFNumberRef)index,kCFNumberIntType,&head);
            if(enabled==kCFBooleanTrue&&head>=0&&(unsigned)head<NM_ROTATION_GPU_HEADS&&(bits==3||bits==5||bits==6))
                rotated|=1u<<(unsigned)head;
            if(enabled)CFRelease(enabled);if(value)CFRelease(value);if(index)CFRelease(index);IOObjectRelease(service);
        }
        IOObjectRelease(iterator);
    }
    atomic_store(&heads,rotated);return rotated;
}
static BOOL nvmtl_rotation_has_work(NVMTLCommandBuffer *cb) {
    return [objc_getAssociatedObject(cb,&nvmtl_rotation_work_key) boolValue];
}
static NVMTLRotationSlot *nvmtl_rotation_make(NVMTLCommandBuffer *cb,NVMTLTexture *source) {
    const uint32_t width=source->_i.w,height=source->_i.h;
    const size_t pitch=IOSurfaceAlignProperty(kIOSurfaceBytesPerRow,(size_t)width*4);
    if(!width||!height||width>16384||height>16384||pitch<width*4ull||pitch>UINT32_MAX||pitch%32)return nil;
    NVMTLRotationSlot *slot=[NVMTLRotationSlot new];slot->busy=YES;
    slot->surface=IOSurfaceCreate((__bridge CFDictionaryRef)@{
        (__bridge id)kIOSurfaceWidth:@(width),(__bridge id)kIOSurfaceHeight:@(height),
        (__bridge id)kIOSurfaceBytesPerElement:@4,(__bridge id)kIOSurfaceBytesPerRow:@(pitch),
        (__bridge id)kIOSurfacePixelFormat:@(0x42475241u),(__bridge id)kIOSurfaceAllocSize:@(pitch*height)});
    if(!slot->surface)return nil;
    MTLTextureDescriptor *descriptor=[MTLTextureDescriptor texture2DDescriptorWithPixelFormat:source->_fmt width:width height:height mipmapped:NO];
    descriptor.storageMode=MTLStorageModeShared;
    descriptor.usage=MTLTextureUsageRenderTarget|MTLTextureUsageShaderRead;
    slot->texture=(NVMTLTexture *)[(id<MTLDevice>)cb->_queue->_dev newTextureWithDescriptor:descriptor iosurface:slot->surface plane:0];
    if(![slot->texture isKindOfClass:NVMTLTexture.class]||!slot->texture->_vramOn)return nil;
    return slot;
}
static NVMTLRotationWork *nvmtl_rotation_reserve(NVMTLCommandBuffer *cb,NVMTLTexture *source,uint32_t ticket) {
    int head=nmRotationGPUTicketHead(ticket);if(head<0)return nil;
    for(unsigned index=0;index<NM_ROTATION_GPU_SLOTS;++index) {
        __attribute__((objc_precise_lifetime)) NVMTLRotationSlot *old=nil;
        @synchronized(nvmtl_rotation_lock()) {
            old=nvmtl_rotation_slots[head][index];
            if(old&&(old->busy||old->poisoned))continue;
            if(!old)old=nvmtl_rotation_slots[head][index]=[NVMTLRotationSlot new];
            old->busy=YES;
        }
        NVMTLRotationSlot *slot=old;
        if(!slot->texture||slot->texture->_i.w!=source->_i.w||slot->texture->_i.h!=source->_i.h||slot->texture->_fmt!=source->_fmt) {
            // All IOSurface/texture allocation/import is on the calling producer
            // thread, OUTSIDE both the CB class lock and the pool monitor, before
            // this command buffer's pending GPU marks are installed.
            slot=nvmtl_rotation_make(cb,source);
            @synchronized(nvmtl_rotation_lock()) {
                if(slot)nvmtl_rotation_slots[head][index]=slot;
                else old->busy=NO;
            }
            if(!slot)continue;
        }
        const uint32_t destination=IOSurfaceGetID(slot->surface);
        uint32_t status=nvmtl_vk_rotation_control(destination,NM_ROTATION_GPU_BIND|ticket);
        if(status) {@synchronized(nvmtl_rotation_lock()){slot->busy=NO;}continue;}
        NVMTLRotationWork *work=[NVMTLRotationWork new];work->slot=slot;work->source=source;work->ticket=ticket;
        return work;
    }
    return nil;
}
static void nvmtl_rotation_cancel(NVMTLRotationWork *work) {
    nvmtl_vk_rotation_control(IOSurfaceGetID(work->source->_surf),NM_ROTATION_GPU_CANCEL|work->ticket);
    work->finished=YES;@synchronized(nvmtl_rotation_lock()){work->slot->busy=NO;}
}
static void nvmtl_rotation_part_ready(NVMTLSubmissionPart *part) {
    for(NVMTLRotationWork *work in part->rotationWork) {
        // Called only after the fence and ordinary surface publication. The
        // synchronous completion path does not return to CoreDisplay before this finishes.
        const uint32_t status=nvmtl_vk_rotation_control(IOSurfaceGetID(work->source->_surf),NM_ROTATION_GPU_DONE|work->ticket);
        work->finished=YES;@synchronized(nvmtl_rotation_lock()){work->slot->busy=NO;}
        static unsigned count;if(count++<4||status)nvlog("rotation GPU inline: completed source %u output %u ticket %u status %#x",
            IOSurfaceGetID(work->source->_surf),IOSurfaceGetID(work->slot->surface),work->ticket,status);
    }
}
static void nvmtl_rotation_prepare(NVMTLCommandBuffer *cb) {
    if(!nvmtl_rotation_enabled()||!nvmtl_ws_kernel_waits()||!nvmtl_ws_surface_wait())return;
    const uint32_t heads=nvmtl_rotation_heads();if(!heads)return;
    NSMutableSet *sources=[NSMutableSet new];
    for(NVMTLSubmissionPart *part in cb->_parts)for(NVMTLTexture *source in part->surfaces)if(source->_surf)[sources addObject:source];
    NSMutableArray *work=[NSMutableArray new];
    for(NVMTLTexture *source in sources) {
        // Only surfaces the kernel has actually observed as an accepted full
        // rotated display plane can get a ticket. Size alone is insufficient.
        if(!source->_vramOn||source->_parent||source->_viewParent||source->_baseLevel||source->_baseSlice||
           source->_plane||source->_i.bpp!=4||source->_i.mtl_type!=2||source->_i.layers!=1||source->_i.mips!=1||source->_i.samples>1||
           (source->_fmt!=MTLPixelFormatBGRA8Unorm&&source->_fmt!=MTLPixelFormatBGRA8Unorm_sRGB))continue;
        for(unsigned head=0;head<NM_ROTATION_GPU_HEADS;++head) {
            if(!(heads&(1u<<head)))continue;
            const uint32_t sid=IOSurfaceGetID(source->_surf);
            const uint32_t ticket=nvmtl_vk_rotation_control(sid,nmRotationGPUBegin(head));
            if(nmRotationGPUTicketHead(ticket)!=(int)head)continue;
            NVMTLRotationWork *item=nvmtl_rotation_reserve(cb,source,ticket);
            if(item)[work addObject:item];
            else nvmtl_vk_rotation_control(sid,NM_ROTATION_GPU_CANCEL|ticket);
        }
    }
    if(!work.count)return;
    NVMTLSubmissionPart *part=[NVMTLSubmissionPart new];
    if(nvmtl_vk_cmd_begin(&cb->_queue->_q,&part->commands)){for(NVMTLRotationWork *w in work)nvmtl_rotation_cancel(w);return;}
    NSMutableArray *accepted=[NSMutableArray new];NVMTLResSet *resources=[NVMTLResSet new];NSMutableSet *surfaces=[NSMutableSet new];
    for(id resource in (NVMTLResSet *)cb->_gpuUses)[resources addObject:resource];
    for(NVMTLRotationWork *item in work) {
        if(nvmtl_vk_rotation_buffer_alias(&item->source->_vramBuf,&item->sourceAlias)||
           nvmtl_vk_rotation_buffer_alias(&item->slot->texture->_vramBuf,&item->destinationAlias)||
           nvmtl_vk_cmd_rotation_180(&part->commands,&item->sourceAlias,&item->destinationAlias,
               item->source->_i.w,item->source->_i.h,(uint32_t)IOSurfaceGetBytesPerRow(item->source->_surf),
               (uint32_t)IOSurfaceGetBytesPerRow(item->slot->surface))){nvmtl_rotation_cancel(item);continue;}
        [accepted addObject:item];[resources addObject:item->source];[resources addObject:item->slot->texture];
        [surfaces addObject:item->source];[surfaces addObject:item->slot->texture];
    }
    if(!accepted.count){nvmtl_vk_cmd_abandon(&part->commands);return;}
    part->resources=[resources nvmtlTakeAll];part->surfaces=surfaces;part->encoders=1;part->rotationWork=accepted;
    [cb->_parts addObject:part];
    objc_setAssociatedObject(cb,&nvmtl_rotation_work_key,@YES,OBJC_ASSOCIATION_RETAIN_NONATOMIC);
}
