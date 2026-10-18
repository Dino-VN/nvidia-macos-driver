#!/usr/bin/env python3
"""CPU checks for descriptor arrays, address-table pointer escapes and cursor-worker shutdown.

Build the translator dependencies first. --validator optionally checks the complete safe SPIR-V output.
The cursor test models ONCE cancel/wait semantics; it is not an in-kernel shutdown test.
"""
import argparse
import json
import pathlib
import struct
import subprocess
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--deps', type=pathlib.Path,
                    default=ROOT / 'out/translator/x86_64-apple-darwin/release/deps')
parser.add_argument('--host-deps', type=pathlib.Path, default=ROOT / 'out/translator/release/deps',
                    help='Cargo host dependency directory (procedural macros)')
parser.add_argument('--validator', type=pathlib.Path)
args = parser.parse_args()
vk = (ROOT / 'plugin/nvmtl_vk.c').read_text()
fb = (ROOT / 'kexts/NVRMFB/fb/nvrm-fb.cpp').read_text()


def section(text, start, end, last=False):
    at = text.rindex(start) if last else text.index(start)
    return text[at:text.index(end, at)]


scanner = section(vk, 'static int nvmtl_spirv_texel_mask(', '\nint nvmtl_vk_bind_texture_view(', last=True)
macros = section(vk, '#define NVMTL_NBUF ', '#define NVMTL_DISPATCH_PC_BYTES')
c = r'''
#include <assert.h>
#include <stdint.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
enum { NVMTL_STAGE_TEXTURE_SLOTS = 128, NVMTL_STAGE_SAMPLER_SLOTS = 32 };
static void nvlog(const char *fmt, ...) {}
''' + macros + scanner + r'''
static uint32_t w[256]; static size_t nw;
static void emit(unsigned op, unsigned n, ...) {
    w[nw++]=((n+1)<<16)|op; va_list ap; va_start(ap,n);
    while(n--) w[nw++]=va_arg(ap,unsigned); va_end(ap);
}
// Descriptor declarations only: pipeline parsing unit inputs, not complete executable shaders.
static void module(unsigned array, unsigned count, unsigned set, unsigned binding, unsigned kind) {
    memset(w,0,sizeof w); w[0]=0x07230203; w[1]=0x00010500; w[3]=32; nw=5;
    emit(71,3,10u,33u,binding); emit(71,3,10u,34u,set);
    emit(21,3,1u,32u,0u); emit(43,3,1u,2u,count);
    if(kind==0) emit(25,8,3u,1u,5u,0u,0u,0u,1u,0u); // sampled texel buffer
    if(kind==1) emit(25,8,3u,1u,1u,0u,0u,0u,1u,0u); // sampled image
    if(kind==2) emit(25,8,3u,1u,1u,0u,0u,0u,2u,4u); // storage image
    if(kind==3) emit(26,1,3u);                         // sampler
    if(kind==4) { emit(29,2,12u,1u); emit(30,2,3u,12u); } // SSBO with internal array
    if(array==1) emit(28,3,4u,3u,2u);
    if(array==2) emit(29,2,4u,3u);
    if(array==3) { emit(50,3,1u,11u,count); emit(28,3,4u,3u,11u); }
    emit(32,3,5u,kind==4?12u:0u,array?4u:3u);
    emit(59,3,5u,10u,kind==4?12u:0u);
}
int main(void) {
    uint64_t mask[4];
    module(0,1,0,32,0); assert(nvmtl_spirv_texel_mask(w,nw*4,mask) && mask[0]==1);
    module(1,1,0,159,0); assert(nvmtl_spirv_texel_mask(w,nw*4,mask) && mask[1]==(1ull<<63));
    module(1,1,1,607,0); assert(nvmtl_spirv_texel_mask(w,nw*4,mask) && mask[3]==(1ull<<63));
    for(unsigned kind=0;kind<5;kind++) {
        module(1,2,0,32,kind); assert(!nvmtl_spirv_texel_mask(w,nw*4,mask));
        for(unsigned k=0;k<4;k++) assert(!mask[k]);
        module(2,1,1,32,kind); assert(!nvmtl_spirv_texel_mask(w,nw*4,mask));
        module(3,1,0,32,kind); assert(!nvmtl_spirv_texel_mask(w,nw*4,mask));
    }
    module(1,2,2,0,1); assert(nvmtl_spirv_texel_mask(w,nw*4,mask) && !mask[0]);
    module(2,1,2,0,1); assert(nvmtl_spirv_texel_mask(w,nw*4,mask));
    module(0,1,0,0,4); assert(nvmtl_spirv_texel_mask(w,nw*4,mask));
    module(0,1,0,640,4); assert(nvmtl_spirv_texel_mask(w,nw*4,mask));
    module(0,1,0,32,0); assert(!nvmtl_spirv_texel_mask(w,nw*4-1,mask));
    w[nw++]=0; assert(!nvmtl_spirv_texel_mask(w,nw*4,mask));
    module(0,1,0,32,0); w[nw-3]=99; assert(!nvmtl_spirv_texel_mask(w,nw*4,mask));
    puts("PASS: texel scalar/array-of-one masks, array refusal, set-2 heaps, internal SSBO arrays, malformed declarations");
}
'''

drain = section(fb, '    if (fCursorCall) {\n        if (thread_call_cancel_wait(', '    thread_call_t *calls[]')
cpp = r'''
#include <atomic>
#include <cassert>
#include <condition_variable>
#include <mutex>
#include <thread>
#include <cstdio>
struct Work {
    std::mutex mutex; std::condition_variable cv;
    bool active=false, pending=false, mayFinish=false, waiting=false, freed=false;
};
static bool thread_call_cancel_wait(Work *w) {
    std::unique_lock<std::mutex> lock(w->mutex);
    bool cancelled=w->pending; w->pending=false; w->waiting=true; w->cv.notify_all();
    w->cv.wait(lock,[&]{return !w->active;}); return cancelled;
}
static bool thread_call_free(Work *w) {
    assert(!w->active && !w->pending); w->freed=true; return true;
}
struct Framebuffer {
    Work *fCursorCall; std::atomic<int> refs{1}; std::atomic<bool> stopped{false};
    void release() { assert(refs.fetch_sub(1)>1); }
    void stop() {
''' + drain + r'''
        stopped=true;
    }
};
int main(void) {
    for(bool active : {false,true}) for(bool pending : {false,true}) {
        Work w; w.active=active; w.pending=pending;
        Framebuffer fb; fb.fCursorCall=&w; fb.refs=1+active+pending;
        std::thread callback;
        if(active) callback=std::thread([&] {
            std::unique_lock<std::mutex> lock(w.mutex);
            w.cv.wait(lock,[&]{return w.mayFinish;});
            fb.release(); w.active=false; w.cv.notify_all();
        });
        std::thread stopper([&]{fb.stop();});
        if(active) {
            std::unique_lock<std::mutex> lock(w.mutex);
            w.cv.wait(lock,[&]{return w.waiting;});
            assert(!w.freed && !fb.stopped);
            w.mayFinish=true; w.cv.notify_all();
        }
        if(callback.joinable()) callback.join(); stopper.join();
        assert(w.freed && fb.stopped && !fb.fCursorCall && fb.refs==1);
    }
    puts("PASS: cursor stop drains an active worker, cancels pending reruns and balances all four retain cases");
}
'''
cursor = section(fb, 'bool NVRMNVDAFramebuffer::cursorApply(', '    struct NvKmsKapiRequestedModeSetConfig')
assert cursor.index('NVRMDisplayGate gate') < cursor.index('OSAddAtomic(0, &fStopping)')
assert 'THREAD_CALL_PRIORITY_KERNEL, THREAD_CALL_OPTIONS_ONCE' in fb
assert '&fCursorCall' not in section(fb, '    thread_call_t *calls[]', '    // vblFire retries')
assert 'if (!nvmtl_spirv_texel_mask(vs' in vk and 'if (!nvmtl_spirv_texel_mask(cs' in vk


def ins(op, *operands):
    return [((len(operands)+1) << 16) | op, *operands]


def string(value):
    data = value.encode()+b'\0'
    data += b'\0' * (-len(data) % 4)
    return list(struct.unpack('<'+'I'*(len(data)//4), data))


# Complete Vulkan 1.2 shader: a normal storage buffer and the shared address table; a helper reads a table entry.
words = [0x07230203, 0x00010500, 0, 50, 0]
rows = [(17,1),(17,4441),(14,0,1),(15,5,17,*string('main'),11,15),(16,17,17,1,1,1),
        (71,7,6,4),(71,8,2),(72,8,0,35,0),(71,11,34,0),(71,11,33,0),
        (71,12,6,8),(71,13,2),(72,13,0,35,0),(71,15,34,0),(71,15,33,640),(71,15,24),
        (19,1),(21,2,32,0),(23,3,2,2),(43,2,4,0),(43,2,5,1),
        (29,7,2),(30,8,7),(32,9,12,8),(32,10,12,2),(59,9,11,12),
        (29,12,3),(30,13,12),(32,14,12,13),(32,32,12,3),(59,14,15,12),
        (33,16,1),(33,25,2,32),
        (54,1,17,0,16),(248,18),(65,32,19,15,4,4),(57,2,31,26,19),
        (65,10,21,11,4,5),(61,2,22,21),(128,2,23,31,22),(65,10,24,11,4,4),(62,24,23),(253,),(56,),
        (54,2,26,0,25),(55,32,27),(248,28),(61,3,29,27),(81,2,30,29,0),(254,30),(56,)]
for row in rows:
    words.extend(ins(*row))
rust = '#![allow(dead_code)]\n'
for name in ('buffer_addresses', 'linearize', 'wide_loads'):
    rust += '#[path=' + json.dumps(str(ROOT/'translator/wrapper/src'/f'{name}.rs')) + f'] mod {name};\n'
rust += r'''
use rspirv::{binary::Assemble, dr::{Instruction, Operand}, spirv::Op};
fn bytes(m: &rspirv::dr::Module) -> Vec<u8> { m.assemble().iter().flat_map(|w|w.to_le_bytes()).collect() }
fn main() {
    let args:Vec<_>=std::env::args().collect();
    let input=std::fs::read(&args[1]).unwrap();
    assert!(buffer_addresses::lower(&input).unwrap_err().contains("FunctionCall"));
    let mut safe=rspirv::dr::load_bytes(&input).unwrap();
    safe.functions.truncate(1);
    let b=&mut safe.functions[0].blocks[0].instructions;
    let at=b.iter().position(|i|i.class.opcode==Op::FunctionCall).unwrap();
    b.splice(at..at+1,[
        Instruction::new(Op::Load,Some(3),Some(33),vec![Operand::IdRef(19)]),
        Instruction::new(Op::CompositeExtract,Some(2),Some(31),vec![Operand::IdRef(33),Operand::LiteralBit32(0)]),
    ]);
    let safe_input=bytes(&safe);
    std::fs::write(&args[2],&safe_input).unwrap();
    let output=buffer_addresses::lower(&safe_input).unwrap();
    assert_ne!(output,safe_input);
    std::fs::write(&args[3],&output).unwrap();
    // Logical pointer copies still lower, including a scalar loaded through that copied table pointer.
    let mut copy=safe.clone();
    let b=&mut copy.functions[0].blocks[0].instructions;
    let at=b.iter().position(|i|i.result_id==Some(33)).unwrap();
    b[at].operands[0]=Operand::IdRef(34);
    b.insert(at,Instruction::new(Op::CopyObject,Some(32),Some(34),vec![Operand::IdRef(19)]));
    std::fs::write(&args[4],buffer_addresses::lower(&bytes(&copy)).unwrap()).unwrap();
    // Escape detection unit inputs; these injected instructions are not claimed as complete valid shaders.
    for (op,operands) in [
        (Op::Phi,vec![Operand::IdRef(19),Operand::IdRef(18)]),
        (Op::Select,vec![Operand::IdRef(5),Operand::IdRef(19),Operand::IdRef(19)]),
        (Op::Store,vec![Operand::IdRef(21),Operand::IdRef(19)]),
        (Op::ReturnValue,vec![Operand::IdRef(19)]),
    ] {
        let mut m=safe.clone();
        let typed=matches!(op,Op::Phi|Op::Select);
        let instruction=Instruction::new(op,typed.then_some(32),typed.then_some(40),operands);
        let b=&mut m.functions[0].blocks[0].instructions;
        if op==Op::ReturnValue { *b.last_mut().unwrap()=instruction; } else { b.insert(1,instruction); }
        let error=buffer_addresses::lower(&bytes(&m)).err().unwrap_or_else(||panic!("accepted table pointer escape: {op:?}"));
        assert!(error.contains(&format!("{:?}",op)),"{error}");
    }
    println!("PASS: real address lowering keeps safe table loads/copies and refuses helper/phi/select/store/return pointer escapes");
}
'''

with tempfile.TemporaryDirectory(prefix='nvmtl-audit-repairs-') as directory:
    work = pathlib.Path(directory)
    for name, source, compiler, flags in [('descriptors', c, 'clang', ['-fsanitize=address,undefined']),
                                           ('cursor', cpp, 'clang++', ['-std=c++17', '-pthread'])]:
        path = work/(name+('.cpp' if compiler=='clang++' else '.c'))
        path.write_text(source)
        subprocess.run(['xcrun', compiler, '-O1', *flags, str(path), '-o', str(work/name)], check=True)
        subprocess.run([str(work/name)], check=True)
    (work/'input.spv').write_bytes(struct.pack('<'+'I'*len(words), *words))
    (work/'addresses.rs').write_text(rust)
    deps = args.deps.resolve()
    libraries = []
    for name in ('rspirv', 'metal2vulkan'):
        matches = sorted(deps.glob('lib'+name+'-*.rlib'), key=lambda p:p.stat().st_mtime, reverse=True)
        if not matches:
            raise SystemExit('Build translator dependencies first: missing '+name)
        libraries += ['--extern', name+'='+str(matches[0])]
    subprocess.run(['rustc', '--edition=2021', '-O', str(work/'addresses.rs'), *libraries,
                    '-L', 'dependency='+str(deps), '-L', 'dependency='+str(args.host_deps.resolve()),
                    '-o', str(work/'addresses')], check=True)
    subprocess.run([str(work/'addresses'), *(str(work/p) for p in
                    ('input.spv', 'safe-input.spv', 'safe-output.spv', 'copy-output.spv'))], check=True)
    if args.validator:
        for name in ('input.spv', 'safe-input.spv', 'safe-output.spv', 'copy-output.spv'):
            subprocess.run([str(args.validator.resolve()), '--target-env', 'vulkan1.2', str(work/name)], check=True)
        print('PASS: helper input, safe input and both lowered outputs pass Vulkan 1.2 SPIR-V validation')
