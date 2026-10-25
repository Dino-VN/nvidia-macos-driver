#include <cassert>
#include <cstdio>
#include <initializer_list>
#include "gpu_state.h"
static NMRotationMode mode(unsigned head=0,unsigned angle=90,unsigned epoch=7) {
    return {NM_ROTATION_VERSION,angle,epoch,nmRotationSwaps(angle)?5u:7u,nmRotationSwaps(angle)?7u:5u,7,5,32,head,1,3};
}
int main() {
    NMRotationGPUState state={};auto current=mode();
    assert(!state.begin(1,current)&&!state.take(1,current));
    assert(state.observe(1,current)<NM_ROTATION_GPU_SOURCES);
    uint32_t ticket=state.begin(1,current);assert(nmRotationGPUTicketHead(ticket)==0);
    assert(state.bind(ticket,1)<0&&state.bind(ticket,0)<0);
    assert(state.bind(ticket,100)>=0&&!state.take(1,current));
    assert(!state.awaiting(1,current)); // BEGIN/BIND alone is not a GPU-pending witness.
    assert(!state.done(2,ticket)&&state.slotFor(ticket)->busy);
    assert(!state.done(1,ticket)&&!state.take(1,current)); // no producer-pending witness
    ticket=state.begin(1,current);assert(state.bind(ticket,100)>=0);state.pending(1);
    assert(state.awaiting(1,current));
    assert(state.done(1,ticket));auto *slot=state.take(1,current);assert(slot&&slot->id==100);
    assert(!state.awaiting(1,current));
    assert(!state.take(1,current)&&state.bind(ticket,100)<0);state.put(ticket,true);
    assert(state.heads[0].front==100&&state.bind(ticket,100)<0);
    auto newer=state.begin(1,current);assert(newer!=ticket&&!state.take(1,current));
    assert(state.bind(newer,101)>=0);state.pending(1);assert(state.done(1,newer));
    assert(state.take(1,current));state.put(newer,true);
    assert(state.heads[0].previous==100&&state.heads[0].front==101);
    auto third=state.begin(1,current);assert(state.bind(third,100)<0&&state.bind(third,101)<0&&state.bind(third,102)>=0);
    state.pending(1);assert(state.done(1,third));assert(state.take(1,current));state.put(third,true);
    assert(state.heads[0].front==102&&state.heads[0].previous==101);
    auto fourth=state.begin(1,current);assert(state.bind(fourth,100)>=0);
    state.pending(1);state.pending(1);assert(!state.done(1,fourth)&&!state.take(1,current)); // overlapping writer
    auto old=state.begin(1,current);assert(state.bind(old,100)>=0);state.pending(1);
    auto latest=state.begin(1,current);assert(latest!=old);
    assert(!state.done(1,old)&&!state.take(1,current));
    assert(state.bind(latest,100)>=0);state.pending(1);assert(state.done(1,latest));
    auto changed=current;changed.epoch++;
    assert(!state.take(1,changed)&&!state.begin(1,changed));
    state.observe(1,changed);assert(!state.take(1,changed));
    auto cancelled=state.begin(1,changed);assert(state.bind(cancelled,100)>=0);
    state.cancel(cancelled);assert(!state.slotFor(cancelled)->busy&&!state.done(1,cancelled));
    // A presentation lease prevents rebind until the FB result records front/previous.
    auto held=state.begin(1,changed);assert(state.bind(held,100)>=0);state.pending(1);assert(state.done(1,held));
    assert(state.take(1,changed));auto overlap=state.begin(1,changed);assert(state.bind(overlap,100)<0);
    state.put(held,false);assert(state.bind(overlap,100)>=0);state.cancel(overlap);
    auto second=mode(1,270);state.observe(2,second);auto other=state.begin(2,second);
    assert(nmRotationGPUTicketHead(other)==1&&state.bind(other,102)<0&&state.bind(other,103)>=0);
    // Eviction or new-mode reuse never makes an older ticket current again.
    state.pending(2);for(unsigned id=10;id<30;++id)state.observe(id,second);
    assert(!state.done(2,other));
    state.observe(1,changed);state.heads[0].serial=0x00ffffffu;assert(!state.begin(1,changed));
    for(unsigned angle:{0u,90u,180u,270u}) {
        auto sample=mode(4,angle);NMRotationGPUState fresh={};
        assert((fresh.observe(8,sample)!=UINT32_MAX)==(angle!=0));
    }
    puts("PASS: production GPU tickets; GPU/pending witness, exact mode/epoch, stale/out-of-order/overlapping writers, current/previous/presenting outputs, cancellation, head isolation, eviction and nonwrapping exhaustion");
}
