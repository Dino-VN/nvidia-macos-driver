#include <cassert>
#include <cstdio>
#include "gpu_state.h"

static NMRotationMode mode(unsigned head,unsigned angle,unsigned width=7,unsigned height=5,unsigned epoch=7) {
    return {NM_ROTATION_VERSION,angle,epoch,nmRotationSwaps(angle)?height:width,
        nmRotationSwaps(angle)?width:height,width,height,width*4,head,1,3};
}
int main() {
    NMRotationGPUState shared={};
    const auto left=mode(0,90),right=mode(1,270);
    assert(shared.observe(77,left)!=UINT32_MAX&&shared.observe(77,right)!=UINT32_MAX);
    assert(shared.find(77,0)!=shared.find(77,1));
    const auto a=shared.begin(77,left),b=shared.begin(77,right);
    assert(a!=b&&nmRotationGPUTicketHead(a)==0&&nmRotationGPUTicketHead(b)==1);
    assert(shared.bind(a,100)>=0&&shared.bind(b,200)>=0);
    shared.pending(77);
    assert(shared.awaiting(77,left)&&shared.awaiting(77,right));
    assert(shared.done(77,a)&&shared.take(77,left)&&!shared.take(77,right));
    shared.put(a,true);
    assert(shared.awaiting(77,right)&&shared.done(77,b)&&shared.take(77,right));
    shared.put(b,true);
    assert(shared.heads[0].front==100&&shared.heads[1].front==200);
    assert(shared.bind(a,200)<0&&shared.bind(b,100)<0);
    // Changing one display's mode or framebuffer never discards the other.
    auto nextLeft=left;++nextLeft.epoch;shared.observe(77,nextLeft);
    assert(!shared.take(77,left)&&shared.take(77,right));shared.put(b,false);
    auto old=shared.begin(77,nextLeft);assert(shared.bind(old,101)>=0);shared.pending(77);
    assert(shared.done(77,b)==false); // completed tickets cannot publish twice
    // A new write to the shared image invalidates both consumers.
    assert(!shared.take(77,right));
    shared.invalidateSources(0);shared.observe(77,nextLeft);
    assert(!shared.done(77,old)&&!shared.take(77,nextLeft)&&shared.find(77,1));
    const auto replacement=shared.begin(77,nextLeft);assert(replacement!=old);
    assert(shared.bind(replacement,101)>=0);shared.pending(77);assert(shared.done(77,replacement));
    // A failed reservation is cancellable without binding an output.
    auto unused=shared.begin(77,nextLeft);assert(shared.cancel(unused,77));
    assert(!shared.find(77,0)->latest&&!shared.find(77,0)->ready);
    // Exhaustion is isolated to one display and never wraps into an old job.
    shared.heads[0].serial=0x00ffffffu;assert(!shared.begin(77,nextLeft));
    assert(shared.begin(77,right));

    NMRotationGPUState independent={};
    NMRotationMode modes[NM_ROTATION_GPU_HEADS]={};
    for(unsigned h=0;h<NM_ROTATION_GPU_HEADS;++h) {
        modes[h]=mode(h,h%3==0?180:h%3==1?90:270,7+2*h,5+2*h);
        assert(independent.observe(10+h,modes[h])!=UINT32_MAX);
        assert(!independent.find(10+h,(h+1)%NM_ROTATION_GPU_HEADS));
    }
    for(unsigned frame=0;frame<1000;++frame) {
        uint32_t tickets[NM_ROTATION_GPU_HEADS]={};
        for(unsigned h=0;h<NM_ROTATION_GPU_HEADS;++h) {
            tickets[h]=independent.begin(10+h,modes[h]);assert(tickets[h]);
            // Each display owns its three buffers, dimensions, epoch and nonce.
            const unsigned output=1000+h*10+frame%3;
            assert(independent.bind(tickets[h],output)>=0);
            independent.pending(10+h);
        }
        // Complete in reverse order, independent of display registration order.
        for(unsigned h=NM_ROTATION_GPU_HEADS;h--;) {
            assert(independent.done(10+h,tickets[h]));
            auto *lease=independent.take(10+h,modes[h]);assert(lease&&lease->id==1000+h*10+frame%3);
            independent.put(tickets[h],true);
        }
    }
    // Standard has no GPU job; a different display continues rotating normally.
    auto standard=mode(0,0);assert(independent.observe(10,standard)==UINT32_MAX);
    auto changed=modes[1];++changed.epoch;independent.observe(11,changed);
    assert(!independent.take(11,modes[1])&&independent.take(12,modes[2]));
    auto bad=modes[2];bad.head=NM_ROTATION_GPU_HEADS;
    assert(!independent.take(12,bad)&&!independent.awaiting(12,bad));
    puts("PASS: per-display sources/nonces/outputs; shared IOSurface with independent angles, writes, completion and reconnect; Standard/mixed resolutions; cross-display alias refusal; 5000 reverse-order presentations; isolated exhaustion");
}
