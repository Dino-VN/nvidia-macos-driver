#!/usr/bin/env python3
"""Exercise production parked-sampler restoration without a GPU."""
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/rotation'))
from test_support import method

source = (ROOT / 'plugin/nvmtl_vk.c').read_text()
methods = '\n'.join(method(source, name) for name in [
    'static int nvmtl_sampler_restore_on(', 'int nvmtl_vk_bind_parked_sampler(',
    'void nvmtl_vk_parked_samplers_keep('])
fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
enum { NVMTL_NSAMP=32, NVMTL_NBUF=32, NVMTL_NTEX=128,
       NVMTL_SLOT_NONE=0, NVMTL_SLOT_SAMP=3 };
#define nvlog(...) ((void)0)
typedef struct { uint8_t kind; void *h; } nvmtl_slot;
typedef struct {
    nvmtl_slot s[2][192]; uint32_t park_mask[2];
    uint8_t park_kind[2][32],park_saved_kind[2][32];
    void *park_h[2][32],*park_saved[2][32];
} nvmtl_bindtable;
typedef struct { void *table; } nvk_cmdbuf;
typedef struct { void *s; } nvk_sampler;
static unsigned writes;
static int nvmtl_bind_slot(nvk_cmdbuf *c,uint32_t set,uint32_t slot,uint8_t kind,void *h,size_t off) {
    ((nvmtl_bindtable *)c->table)->s[set][slot]=(nvmtl_slot){kind,h};++writes;return 0;
}
static int nvmtl_vk_bind_sampler(nvk_cmdbuf *c,uint32_t set,uint32_t index,nvk_sampler *s) {
    return nvmtl_bind_slot(c,set,NVMTL_NBUF+NVMTL_NTEX+index,
                         s?NVMTL_SLOT_SAMP:NVMTL_SLOT_NONE,s?s->s:NULL,0);
}
@@METHODS@@
static void *current(nvmtl_bindtable *t,unsigned set,unsigned index) { return t->s[set][160+index].h; }
int main(int argc,char **argv) {
    nvmtl_bindtable table={0};nvk_cmdbuf c={&table};
    nvk_sampler app={(void *)1},shader={(void *)2},next={(void *)3},changed={(void *)4};
    assert(!nvmtl_vk_bind_sampler(&c,0,7,&app));
    assert(!nvmtl_vk_bind_parked_sampler(&c,0,7,&shader));
    assert(current(&table,0,7)==shader.s);
    if(argc>1) {
        assert(!table.park_mask[0]);nvmtl_vk_parked_samplers_keep(&c,0,0);
        assert(current(&table,0,7)==shader.s);puts("PASS: sampler-restore opt-out keeps upstream fallback");return 0;
    }
    assert(!nvmtl_vk_bind_parked_sampler(&c,0,7,&next));
    assert(table.park_saved[0][7]==app.s);
    nvmtl_vk_parked_samplers_keep(&c,0,1u<<7);assert(current(&table,0,7)==next.s);
    nvmtl_vk_parked_samplers_keep(&c,0,0);assert(current(&table,0,7)==app.s&&!table.park_mask[0]);
    // A later app binding wins over the saved value; a subsequent park saves that new app sampler.
    nvmtl_vk_bind_parked_sampler(&c,0,7,&shader);nvmtl_vk_bind_sampler(&c,0,7,&changed);
    nvmtl_vk_parked_samplers_keep(&c,0,0);assert(current(&table,0,7)==changed.s);
    nvmtl_vk_bind_parked_sampler(&c,0,7,&shader);nvmtl_vk_bind_sampler(&c,0,7,&app);
    nvmtl_vk_bind_parked_sampler(&c,0,7,&next);nvmtl_vk_parked_samplers_keep(&c,0,0);
    assert(current(&table,0,7)==app.s);
    // Stage isolation, empty slots and the high sampler bit must survive restoration.
    nvmtl_vk_bind_sampler(&c,1,31,&changed);nvmtl_vk_bind_parked_sampler(&c,1,31,&shader);
    nvmtl_vk_bind_parked_sampler(&c,0,8,&next);
    nvmtl_vk_parked_samplers_keep(&c,1,0);assert(current(&table,1,31)==changed.s);
    assert(current(&table,0,8)==next.s);nvmtl_vk_parked_samplers_keep(&c,0,0);
    assert(!current(&table,0,8)&&table.s[0][168].kind==NVMTL_SLOT_NONE);
    unsigned saved=writes;assert(nvmtl_vk_bind_parked_sampler(&c,2,0,&app)==-1);
    assert(nvmtl_vk_bind_parked_sampler(&c,0,32,&app)==-1&&writes==saved);
    puts("PASS: displaced samplers restore once; replacement, app rebinding, stage isolation, empty/high slots and bounds");
}
'''
with tempfile.TemporaryDirectory(prefix='nvmtl-sampler-restore-') as directory:
    directory = Path(directory)
    (directory / 'test.c').write_text(fixture.replace('@@METHODS@@', methods))
    subprocess.run(['xcrun', 'clang', '-O1', '-g', '-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all', str(directory / 'test.c'), '-o', str(directory / 'test')], check=True)
    subprocess.run([str(directory / 'test')], check=True)
    import os
    subprocess.run([str(directory / 'test'), 'off'], env={**os.environ, 'NVMTL_NO_SAMPLER_RESTORE': '1'}, check=True)
