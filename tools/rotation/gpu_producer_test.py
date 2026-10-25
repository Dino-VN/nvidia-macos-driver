#!/usr/bin/env python3
"""Exercise the production producer hook with gated host mocks and an import-lock reproducer."""
from pathlib import Path
import subprocess,tempfile
root=Path(__file__).resolve().parents[2]
code=(root/'plugin/NVMTLRotationInline.m').read_text()
def replace_function(source,signature,body):
 a=source.index(signature);opening=source.index('{',a);b=opening+1;depth=1
 while depth:
  depth+=(source[b]=='{')-(source[b]=='}');b+=1
 return source[:a]+source[a:opening]+body+source[b:]
# Only platform/process gates are substituted. Pool allocation, import placement,
# source eligibility, reservation, commands/resources and completion are production.
code=replace_function(code,'static BOOL nvmtl_rotation_enabled(void)','{ return fixtureEnabled; }')
code=replace_function(code,'static uint32_t nvmtl_rotation_heads(void)','{ return fixtureHeads; }')
code=code.replace('#include "../tools/rotation/gpu_protocol.h"','#include "gpu_protocol.h"')
events=(root/'plugin/NVMTLEventSync.m').read_text()
a=events.index('- (void)nvmtlSubmitWithEvents');text=events[a:events.index('\n@end',a)]
assert text.index('    }\n    // the commit')<text.index('nvmtl_rotation_prepare(self)')<text.index('nvmtl_ws_mark_pending(self)')
assert 'nvmtl_rotation_part_ready(part)' in events
assert 'nvmtl_rotation_has_work(self) ||' in (root/'plugin/NVMTLObjects.m').read_text()
fixture=r'''
#import <Foundation/Foundation.h>
#import <Metal/Metal.h>
#import <IOSurface/IOSurface.h>
#import <IOKit/IOKitLib.h>
#import <objc/runtime.h>
#include <mach/mach.h>
#include <cassert>
#include <cstdio>
#include <atomic>
#include "gpu_state.h"
extern "C" {
#include "nvmtl_vk.h"
}
static bool fixtureEnabled=true,refuseCompute=false;static uint32_t fixtureHeads=1;
static unsigned imports=0,controls=0,commands=0,aliases=0,releases=0;
static NMRotationGPUState state={};
static BOOL nvmtl_ws_kernel_waits(){return YES;}static BOOL nvmtl_ws_surface_wait(){return YES;}
static void nvlog(const char *,...){}
@interface NVMTLTexture:NSObject {
@public nvk_image _i;IOSurfaceRef _surf;MTLPixelFormat _fmt;BOOL _vramOn;
    id _parent,_viewParent;unsigned _baseLevel,_baseSlice,_plane;nvk_buffer _vramBuf;
}
@end
@implementation NVMTLTexture
- (void)dealloc{if(_surf)CFRelease(_surf);}
@end
@interface NVMTLResSet:NSObject<NSFastEnumeration>{NSMutableSet *_objects;}
- (void)addObject:(id)object;- (NSSet *)nvmtlTakeAll;
@end
@implementation NVMTLResSet
- (instancetype)init{if((self=[super init]))_objects=[NSMutableSet new];return self;}
- (void)addObject:(id)object{[_objects addObject:object];}
- (NSSet *)nvmtlTakeAll{return [_objects copy];}
- (NSUInteger)countByEnumeratingWithState:(NSFastEnumerationState *)s objects:(id __unsafe_unretained *)objects count:(NSUInteger)n{return [_objects countByEnumeratingWithState:s objects:objects count:n];}
@end
@interface NVMTLCommandQueue:NSObject{@public id _dev;nvk_queue _q;}
@end
@implementation NVMTLCommandQueue @end
@interface NVMTLSubmissionPart:NSObject{@public nvk_cmdbuf commands;NSSet *surfaces,*resources;NSArray *rotationWork;unsigned encoders;}
@end
@implementation NVMTLSubmissionPart @end
@interface NVMTLCommandBuffer:NSObject{@public NVMTLCommandQueue *_queue;NSMutableArray *_parts;NSSet *_gpuUses;}
@end
@implementation NVMTLCommandBuffer @end
static NSObject *nvmtl_rotation_lock(void);
@interface FixtureDevice:NSObject
- (id)newTextureWithDescriptor:(MTLTextureDescriptor *)descriptor iosurface:(IOSurfaceRef)surface plane:(NSUInteger)plane;
@end
@implementation FixtureDevice
- (id)newTextureWithDescriptor:(MTLTextureDescriptor *)descriptor iosurface:(IOSurfaceRef)surface plane:(NSUInteger)plane {
    // Old failure shape: a family-lock holder waits for GPU completion; the
    // import must allow its completion thread to acquire the class/pool monitors.
    dispatch_semaphore_t completed=dispatch_semaphore_create(0);
    dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED,0),^{@autoreleasepool{
        @synchronized(NVMTLCommandBuffer.class){@synchronized(nvmtl_rotation_lock()){
            dispatch_semaphore_signal(completed);
        }}
    }});
    assert(dispatch_semaphore_wait(completed,dispatch_time(DISPATCH_TIME_NOW,500000000))==0);
    ++imports;
    NVMTLTexture *texture=[NVMTLTexture new];texture->_surf=(IOSurfaceRef)CFRetain(surface);texture->_fmt=descriptor.pixelFormat;
    texture->_vramOn=YES;texture->_i.w=(uint32_t)descriptor.width;texture->_i.h=(uint32_t)descriptor.height;
    texture->_i.bpp=4;texture->_i.mtl_type=2;texture->_i.layers=texture->_i.mips=1;
    texture->_vramBuf.buf=(void *)(uintptr_t)IOSurfaceGetID(surface);texture->_vramBuf.mem=texture->_vramBuf.buf;
    texture->_vramBuf.size=IOSurfaceGetAllocSize(surface);return texture;
}
@end
extern "C" uint32_t nvmtl_vk_rotation_control(uint32_t surface,uint32_t operation){
    ++controls;unsigned op=operation&~NM_ROTATION_GPU_PAYLOAD,ticket=operation&NM_ROTATION_GPU_PAYLOAD;
    if(op==NM_ROTATION_GPU_BEGIN){if(!ticket||ticket>NM_ROTATION_GPU_HEADS)return 0x80000002u;auto *entry=state.find(surface,ticket-1u);return entry?state.begin(surface,entry->mode):0;}
    if(op==NM_ROTATION_GPU_BIND)return state.bind(ticket,surface)>=0?0:0x80000007u;
    if(op==NM_ROTATION_GPU_DONE){return state.done(surface,ticket)?0:0x80000003u;}
    assert(op==NM_ROTATION_GPU_CANCEL);state.cancel(ticket,surface);return 0;
}
extern "C" int nvmtl_vk_cmd_begin(nvk_queue *,nvk_cmdbuf *out){out->cb=(void *)1;return 0;}
extern "C" int nvmtl_vk_cmd_abandon(nvk_cmdbuf *c){c->cb=nullptr;return 0;}
extern "C" int nvmtl_vk_rotation_buffer_alias(const nvk_buffer *owner,nvk_buffer *out){*out=*owner;++aliases;return 0;}
extern "C" void nvmtl_vk_rotation_buffer_release(nvk_buffer *b){if(b->buf)++releases;*b={};}
extern "C" int nvmtl_vk_cmd_rotation_180(nvk_cmdbuf *,nvk_buffer *s,nvk_buffer *d,uint32_t w,uint32_t h,uint32_t sp,uint32_t dp){
    assert(s->buf!=d->buf&&w==7&&h==5&&sp>=28&&dp>=28);++commands;return refuseCompute?-1:0;
}
@@PRODUCTION@@
static NVMTLCommandBuffer *buffer(NVMTLTexture *source){
    auto *cb=[NVMTLCommandBuffer new];cb->_queue=[NVMTLCommandQueue new];cb->_queue->_dev=[FixtureDevice new];
    cb->_parts=[NSMutableArray new];NVMTLSubmissionPart *part=[NVMTLSubmissionPart new];
    part->surfaces=[NSSet setWithObject:source];part->resources=part->surfaces;
    cb->_gpuUses=part->resources;[cb->_parts addObject:part];return cb;
}
int main(){@autoreleasepool{
    NVMTLTexture *source=[NVMTLTexture new];source->_surf=IOSurfaceCreate((__bridge CFDictionaryRef)@{
        (__bridge id)kIOSurfaceWidth:@7,(__bridge id)kIOSurfaceHeight:@5,(__bridge id)kIOSurfaceBytesPerElement:@4,
        (__bridge id)kIOSurfaceBytesPerRow:@64,(__bridge id)kIOSurfaceAllocSize:@4096,(__bridge id)kIOSurfacePixelFormat:@(0x42475241u)});
    assert(source->_surf);source->_vramOn=YES;source->_fmt=MTLPixelFormatBGRA8Unorm;
    source->_i.w=7;source->_i.h=5;source->_i.bpp=4;source->_i.mtl_type=2;source->_i.layers=source->_i.mips=1;
    source->_vramBuf.buf=(void *)9999;source->_vramBuf.mem=(void *)9999;source->_vramBuf.size=4096;
    unsigned sid=IOSurfaceGetID(source->_surf);NMRotationMode mode={NM_ROTATION_VERSION,90,7,5,7,7,5,64,0,1,3};state.observe(sid,mode);
    fixtureHeads=0;auto *standard=buffer(source);nvmtl_rotation_prepare(standard);assert(!controls&&!imports&&standard->_parts.count==1);
    fixtureHeads=1;fixtureEnabled=false;nvmtl_rotation_prepare(standard);assert(!controls&&!imports);fixtureEnabled=true;
    auto *first=buffer(source);nvmtl_rotation_prepare(first);assert(first->_parts.count==2&&imports==1&&commands==1&&nvmtl_rotation_has_work(first));
    NVMTLSubmissionPart *tail=first->_parts.lastObject;NVMTLRotationWork *work=tail->rotationWork[0];
    assert(tail->surfaces.count==2&&tail->resources.count==2&&!state.take(sid,mode));
    state.pending(sid);nvmtl_rotation_part_ready(tail);assert(!work->slot->busy&&work->finished);
    assert(state.take(sid,mode));state.put(work->ticket,true);
    auto *second=buffer(source);nvmtl_rotation_prepare(second);assert(second->_parts.count==2&&imports==2&&commands==2);
    auto *secondTail=(NVMTLSubmissionPart *)second->_parts.lastObject;
    auto *secondWork=(NVMTLRotationWork *)secondTail->rotationWork[0];assert(secondWork->slot!=work->slot);
    state.pending(sid);nvmtl_rotation_part_ready(secondTail);assert(state.take(sid,mode));state.put(secondWork->ticket,true);
    // A refused command releases its reservation; no GPU part or forced wait.
    refuseCompute=true;auto *refused=buffer(source);nvmtl_rotation_prepare(refused);
    assert(refused->_parts.count==1&&!nvmtl_rotation_has_work(refused)&&!state.take(sid,mode));refuseCompute=false;
    // Invalid source layout still invalidates an old result, without importing.
    unsigned oldImports=imports;source->_parent=source;auto *view=buffer(source);nvmtl_rotation_prepare(view);
    state.pending(sid);assert(view->_parts.count==1&&imports==oldImports&&!state.take(sid,mode));source->_parent=nil;
    // The kernel has never observed this surface: geometry alone grants no job.
    auto *unknown=[NVMTLTexture new];unknown->_surf=IOSurfaceCreate((__bridge CFDictionaryRef)@{
        (__bridge id)kIOSurfaceWidth:@7,(__bridge id)kIOSurfaceHeight:@5,(__bridge id)kIOSurfaceBytesPerElement:@4});
    auto *unregistered=buffer(unknown);nvmtl_rotation_prepare(unregistered);assert(unregistered->_parts.count==1&&imports==oldImports);
    // The same IOSurface can feed two independently rotated displays. Prepare
    // both outputs on the original queue, with one pending witness for the input.
    NMRotationMode right=mode;right.head=1;right.degrees=270;state.observe(sid,right);fixtureHeads=3;
    auto *both=buffer(source);nvmtl_rotation_prepare(both);assert(both->_parts.count==2);
    auto *bothTail=(NVMTLSubmissionPart *)both->_parts.lastObject;
    assert(bothTail->rotationWork.count==2&&bothTail->surfaces.count==3&&bothTail->resources.count==3);
    auto *leftWork=(NVMTLRotationWork *)bothTail->rotationWork[0];
    auto *rightWork=(NVMTLRotationWork *)bothTail->rotationWork[1];
    assert(nmRotationGPUTicketHead(leftWork->ticket)==0&&nmRotationGPUTicketHead(rightWork->ticket)==1);
    assert(leftWork->slot!=rightWork->slot&&IOSurfaceGetID(leftWork->slot->surface)!=IOSurfaceGetID(rightWork->slot->surface));
    state.pending(sid);nvmtl_rotation_part_ready(bothTail);
    assert(state.take(sid,mode)&&state.take(sid,right));state.put(leftWork->ticket,true);state.put(rightWork->ticket,true);
    // Returning display 0 to Standard never suppresses display 1's GPU work.
    fixtureHeads=2;auto *onlyRight=buffer(source);nvmtl_rotation_prepare(onlyRight);
    auto *rightTail=(NVMTLSubmissionPart *)onlyRight->_parts.lastObject;assert(rightTail->rotationWork.count==1);
    auto *one=(NVMTLRotationWork *)rightTail->rotationWork[0];assert(nmRotationGPUTicketHead(one->ticket)==1);
    state.pending(sid);nvmtl_rotation_part_ready(rightTail);assert(state.take(sid,right)&&!state.take(sid,mode));state.put(one->ticket,true);
    puts("PASS: production producer hook; import completion acquires class+pool monitors, no import worker or lock inversion; exact registered source only, Standard bypass, same-queue tail/resources, GPU-fence publication, front-output exclusion and refusal cleanup");
}}
'''
with tempfile.TemporaryDirectory(prefix='nm-gpu-producer-') as directory:
 p=Path(directory);(p/'test.mm').write_text(fixture.replace('@@PRODUCTION@@',code))
 subprocess.run(['xcrun','clang++','-std=c++17','-O1','-g','-fobjc-arc','-fsanitize=address,undefined',
   '-I'+str(root/'tools/rotation'),'-I'+str(root/'plugin'),str(p/'test.mm'),'-framework','Foundation','-framework','Metal',
   '-framework','IOSurface','-framework','IOKit','-o',str(p/'test')],check=True)
 subprocess.run([str(p/'test')],check=True,timeout=20)
