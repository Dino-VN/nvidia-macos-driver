#!/usr/bin/env python3
"""Check production host-import spans against allocation ends and overflow."""
from pathlib import Path
import subprocess
import sys
import tempfile

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools/rotation'))
from test_support import method

source = (root / 'plugin/nvmtl_vk.c').read_text()
body = method(source, 'static int nvmtl_host_page_span(')
owner_check = method((root / 'plugin/NVMTLObjects.m').read_text(), 'static bool nvmtl_surface_host_importable(')
fixture = r'''
#include <assert.h>
#include <stdint.h>
#include <stddef.h>
#include <stdio.h>
#include <stdbool.h>
static size_t g_host_align=4096;
typedef struct { void *base; } Surface;
typedef struct { Surface *_surf; } NVMTLTexture;
static size_t nvmtl_vk_host_import_align(void) { return g_host_align; }
static void *IOSurfaceGetBaseAddress(Surface *s) { return s->base; }
@@OWNER@@
@@BODY@@
static int span(uintptr_t address, size_t bytes, size_t bpp, size_t row, uint32_t w, uint32_t h) {
    void *base=(void *)address; size_t size=bytes, offset=SIZE_MAX;
    int result=nvmtl_host_page_span(&base,&size,bpp,row,w,h,&offset);
    if (!result) {
        assert((uintptr_t)base+offset==address && !((uintptr_t)base%g_host_align) && !(size%g_host_align));
        assert((uintptr_t)base+size<=address+bytes);
        assert(offset+(size_t)(h-1)*row+(size_t)w*bpp<=size);
    } else { assert(base==(void *)address && size==bytes && offset==SIZE_MAX); }
    return result;
}
int main(void) {
    Surface surface={(void *)0x10000}; NVMTLTexture texture={&surface};
    assert(nvmtl_surface_host_importable(&texture,(void *)0x10040));
    assert(!nvmtl_surface_host_importable(&texture,(void *)0xffff));
    g_host_align=16384; surface.base=(void *)0x11000;
    assert(!nvmtl_surface_host_importable(&texture,(void *)0x11040));
    surface.base=(void *)0x10000;
    assert(nvmtl_surface_host_importable(&texture,(void *)0x11040));
    surface.base=NULL; assert(!nvmtl_surface_host_importable(&texture,(void *)0x10040));
    g_host_align=4096;
    // Header-offset NV12/P010 planes and ordinary packed BGRA, with padding.
    for (size_t bpp=1;bpp<=4;bpp*=2) for (size_t at=0;at<4096;at+=bpp) {
        assert(!span(0x10000+at,65536-at,bpp,256,64,16));
        assert(span(0x10000+at,((16-1)*256+64*bpp)-1,bpp,256,64,16));
    }
    assert(!span(0x10040,8192-64,2,256,128,16));
    assert(span(0x10041,8192-65,2,256,128,16)); // offset is not a complete texel
    assert(span(0x10000,4095,4,256,64,16)); // no rounding into the next page
    assert(span(0x10000,4096,4,257,64,16));
    assert(span(0x10000,4096,4,128,64,16));
    assert(span(0x10000,4096,4,256,64,0));
    assert(span(0x10000,4096,4,256,0,16));
    assert(span(0,4096,4,256,64,16));
    assert(span(0x10040,SIZE_MAX,4,256,64,16));
    assert(span(UINTPTR_MAX-4095,8192,4,256,64,16));
    assert(span(0x10000,65536,4,SIZE_MAX-3,1,3));
    assert(span(0x10000,65536,1,(size_t)UINT32_MAX+1,1,1));
    g_host_align=0; assert(span(0x10000,65536,4,256,64,16));
    g_host_align=3000; assert(span(0x10000,65536,4,256,64,16));
    puts("PASS: 14336 varied texel offsets/bounds plus malformed spans, partial pages and integer overflow");
}
'''
with tempfile.TemporaryDirectory(prefix='nvmtl-host-span-') as tmp:
    tmp = Path(tmp)
    (tmp / 'test.c').write_text(fixture.replace('@@BODY@@', body).replace('@@OWNER@@', owner_check))
    subprocess.run(['xcrun', 'clang', '-O1', '-g', '-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all', str(tmp / 'test.c'), '-o', str(tmp / 'test')], check=True)
    subprocess.run([str(tmp / 'test')], check=True)
