#!/usr/bin/env python3
"""Exercise production GL committed-use accounting without a GPU."""
import pathlib
import subprocess
import tempfile

root = pathlib.Path(__file__).resolve().parents[1]
events = (root / "plugin/NVMTLEventSync.m").read_text()
gl = (root / "plugin/NVMTLGL.m").read_text()
start = events.index("static void nvmtl_gpu_uses_adjust(")
accounting = events[start:events.index("@implementation NVMTLCommandBuffer (EventSubmission)", start)]
start = gl.index("static BOOL nvmtl_sel1_idle(")
queries = gl[start:gl.index("@implementation NVMTLTexture (NVMTLGL)", start)]

# Both fence-timeout paths must preserve the busy counts. Completion status is
# published before the counters drop; a waiter must never see stale status.
assert events.count("_gpuUsesUncertain = YES;") == 2
finish = events[events.index("- (void)nvmtlFinishExecution:"):events.index("- (void)nvmtlFinishCallbacks")]
assert finish.index("_executionDone = YES;") < finish.index("nvmtl_gpu_uses_lower(self);")
commit = events[events.index("- (void)nvmtlSubmitWithEvents {"):events.index("static void nvmtl_pump_buffers_sync(void) {")]
assert commit.index("restart:NO];") < commit.index("nvmtl_gpu_uses_raise(self, _parts.lastObject);")

fixture = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
@interface NVMTLBuffer : NSObject { @public int _gpuRefs, _resRefs; } @end
@implementation NVMTLBuffer @end
@interface NVMTLTexture : NSObject { @public
    int _gpuRefs, _resRefs; NVMTLTexture *_parent; NVMTLBuffer *_backBuf;
} @end
@implementation NVMTLTexture @end
@interface NVMTLCommandBuffer : NSObject { @public
    NSSet *_gpuUses; BOOL _gpuUsesUncertain;
} @end
@implementation NVMTLCommandBuffer @end
@interface NVMTLSubmissionPart : NSObject { @public NSSet *resources; } @end
@implementation NVMTLSubmissionPart @end
@compatibility_alias NVMTLResSet NSSet;
'''
checks = r'''
static NVMTLSubmissionPart *part(NSSet *resources) {
    NVMTLSubmissionPart *p=[NVMTLSubmissionPart new]; p->resources=resources; return p;
}
int main(void) { @autoreleasepool {
    NVMTLBuffer *buffer=[NVMTLBuffer new]; buffer->_resRefs=11;
    NVMTLTexture *texture=[NVMTLTexture new]; texture->_backBuf=buffer; texture->_resRefs=7;
    NVMTLTexture *view=[NVMTLTexture new], *otherView=[NVMTLTexture new];
    view->_parent=texture; otherView->_parent=texture;
    NVMTLCommandBuffer *first=[NVMTLCommandBuffer new], *second=[NVMTLCommandBuffer new];
    // Encoding references alone are idle: an uncommitted buffer must not block GL.
    assert(nvmtl_tex_idle(texture) && nvmtl_tex_idle(view) && nvmtl_sel1_idle(&buffer->_gpuRefs));
    NVMTLSubmissionPart *p=part([NSSet setWithObjects:buffer,texture,view,otherView,[NSObject new],nil]);
    nvmtl_gpu_uses_raise(first,p);
    assert(first->_gpuUses==p->resources); // reuse the sealed snapshot, no second list
    assert(texture->_gpuRefs==3 && !view->_gpuRefs && !otherView->_gpuRefs && buffer->_gpuRefs==4);
    assert(!nvmtl_tex_idle(texture) && !nvmtl_tex_idle(view));
    nvmtl_gpu_uses_raise(second,part([NSSet setWithObject:buffer]));
    assert(buffer->_gpuRefs==5);
    nvmtl_gpu_uses_lower(first);
    assert(!first->_gpuUses && !texture->_gpuRefs && buffer->_gpuRefs==1);
    assert(!nvmtl_tex_idle(texture) && !nvmtl_tex_idle(view)); // the backing buffer is still in use
    nvmtl_gpu_uses_lower(second);
    assert(!buffer->_gpuRefs && nvmtl_tex_idle(texture) && nvmtl_tex_idle(view));
    assert(texture->_resRefs==7 && buffer->_resRefs==11); // residency is separate
    nvmtl_gpu_uses_lower(first); // nothing left to lower twice
    nvmtl_gpu_uses_raise(first,nil);
    nvmtl_gpu_uses_raise(first,part([NSSet set]));
    assert(!first->_gpuUses && !buffer->_gpuRefs);
    puts("PASS: encoded-only resources idle; committed snapshots reused; owners, views and backing buffers balanced; overlapping commits stay busy");

    __weak NVMTLTexture *kept;
    @autoreleasepool {
        NVMTLTexture *uncertain=[NVMTLTexture new]; kept=uncertain;
        uncertain->_backBuf=buffer;
        NVMTLCommandBuffer *failed=[NVMTLCommandBuffer new];
        nvmtl_gpu_uses_raise(failed,part([NSSet setWithObject:uncertain]));
        failed->_gpuUsesUncertain=YES;
        nvmtl_gpu_uses_lower(failed);
        assert(!failed->_gpuUses && uncertain->_gpuRefs==1 && buffer->_gpuRefs==1);
        assert(!nvmtl_tex_idle(uncertain));
        nvmtl_gpu_uses_lower(failed);
        assert(uncertain->_gpuRefs==1 && buffer->_gpuRefs==1);
    }
    NVMTLTexture *held=kept;
    assert(held && held->_gpuRefs==1 && buffer->_gpuRefs==1);
    puts("PASS: uncertain completion retains the snapshot and keeps GPU resources busy after command-buffer release");
} }
'''

with tempfile.TemporaryDirectory() as directory:
    path = pathlib.Path(directory)
    (path / "completion.m").write_text(fixture + accounting + queries + checks)
    subprocess.run(["clang", "-fobjc-arc", "-framework", "Foundation",
                    str(path / "completion.m"), "-o", str(path / "completion")], check=True)
    subprocess.run([str(path / "completion")], check=True)
