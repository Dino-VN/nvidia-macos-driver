#!/usr/bin/env python3
"""Run the production imported-page cache lifecycle with mocked GPU imports."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools/rotation'))
from test_support import method

source = (ROOT / 'plugin/nvmtl_vk.c').read_text()
methods = '\n'.join(method(source, name) for name in [
    'static uint64_t nvmtl_host_pages_cap(', 'void nvmtl_vk_host_pages_drop(',
    'static nvk_buffer *nvmtl_host_pages(', 'static void nvmtl_host_pages_done('])
fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <stdatomic.h>
#include <string.h>
typedef struct { void *buf,*map; size_t size; } nvk_buffer;
static _Atomic uint64_t g_host_pages_kept;
static unsigned imports,drops;static int refused;
static int nvmtl_vk_buffer_import_host(void *base,size_t bytes,nvk_buffer *out) {
    ++imports;if(refused)return -1;*out=(nvk_buffer){base,base,bytes};return 0;
}
static void nvmtl_vk_buffer_destroy(nvk_buffer *buffer) { assert(buffer->buf);++drops;memset(buffer,0,sizeof *buffer); }
@@METHODS@@
int main(int argc,char **argv) {
    nvk_buffer a={0},b={0},tmp={0};const size_t bytes=600*1024;
    nvk_buffer *one=nvmtl_host_pages(&a,(void *)0x10000,bytes,&tmp);assert(one);
    if(argc>1) {
        assert(one==&tmp&&!a.buf&&!g_host_pages_kept);nvmtl_host_pages_done(&a,one);
        assert(imports==1&&drops==1);puts("PASS: zero cache budget uses a temporary import");return 0;
    }
    assert(one==&a&&imports==1&&g_host_pages_kept==bytes);
    nvmtl_host_pages_done(&a,one);assert(!drops);
    for(unsigned i=0;i<100;++i)assert(nvmtl_host_pages(&a,(void *)0x10000,bytes,&tmp)==&a);
    assert(imports==1&&g_host_pages_kept==bytes);
    nvk_buffer *two=nvmtl_host_pages(&b,(void *)0x20000,bytes,&tmp);
    assert(two==&tmp&&!b.buf&&g_host_pages_kept==bytes);nvmtl_host_pages_done(&b,two);assert(drops==1);
    // Moving or resizing a surface drops its old mapping and charges only the replacement.
    assert(nvmtl_host_pages(&a,(void *)0x30000,bytes/2,&tmp)==&a);
    assert(drops==2&&g_host_pages_kept==bytes/2&&a.map==(void *)0x30000);
    refused=1;assert(!nvmtl_host_pages(&a,(void *)0x40000,bytes,&tmp));
    assert(!a.buf&&!g_host_pages_kept&&drops==3);
    refused=0;assert(nvmtl_host_pages(&b,(void *)0x50000,bytes,&tmp)==&b);
    nvmtl_vk_host_pages_drop(&b);assert(!g_host_pages_kept&&!b.buf);
    unsigned saved=drops;nvmtl_vk_host_pages_drop(&b);nvmtl_vk_host_pages_drop(NULL);assert(drops==saved);
    one=nvmtl_host_pages(NULL,(void *)0x60000,bytes,&tmp);assert(one==&tmp&&!g_host_pages_kept);
    nvmtl_host_pages_done(NULL,one);assert(drops==saved+1);
    puts("PASS: import reuse, shared budget, temporary fallback, moved/resized pages, refusal accounting and idempotent cleanup");
}
'''
with tempfile.TemporaryDirectory(prefix='nvmtl-host-page-cache-') as directory:
    directory = Path(directory)
    (directory / 'test.c').write_text(fixture.replace('@@METHODS@@', methods))
    subprocess.run(['xcrun', 'clang', '-O1', '-g', '-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all', str(directory / 'test.c'), '-o', str(directory / 'test')], check=True)
    subprocess.run([str(directory / 'test')], env={**os.environ, 'NVMTL_HOST_PAGES_MB': '1'}, check=True)
    subprocess.run([str(directory / 'test'), 'off'], env={**os.environ, 'NVMTL_HOST_PAGES_MB': '0'}, check=True)
