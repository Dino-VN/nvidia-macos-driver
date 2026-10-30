#!/usr/bin/env python3
"""Exercise the production idle-import cache, including bounds and concurrent reuse."""
import os
from pathlib import Path
import subprocess
import tempfile

root = Path(__file__).resolve().parents[1]
source = (root / 'plugin/NVMTLDevice.m').read_text()
cache = source[source.index('#define NVMTL_VRAM_KEEP_N '):source.index('static int nvmtl_surface_image_create(')]
fixture = r'''
#import <Foundation/Foundation.h>
#include <assert.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdint.h>
#include <stdio.h>
struct __IOSurface { unsigned id; _Atomic unsigned refs; };
typedef struct { void *buf, *map; size_t size; } nvk_buffer;
static _Atomic uint64_t now = 1;
static _Atomic unsigned imports, drops, host_drops, scheduled;
static int threaded;
#define nvlog(...) ((void)0)
#define clock_gettime_nsec_np(c) atomic_load(&now)
#define CFRetain(s) atomic_fetch_add(&(s)->refs, 1)
#define CFRelease(s) assert(atomic_fetch_sub(&(s)->refs, 1) > 1)
#define IOSurfaceGetID(s) ((s)->id)
#define dispatch_after(t, q, b) ((void)atomic_fetch_add(&scheduled, 1))
static int nvmtl_vk_surface_vram(uint32_t sid, uint32_t plane, size_t need, nvk_buffer *out);
static void nvmtl_vk_buffer_destroy(nvk_buffer *out);
static void nvmtl_vk_host_pages_drop(nvk_buffer *out);
@@CACHE@@
static int nvmtl_vk_surface_vram(uint32_t sid, uint32_t plane, size_t need, nvk_buffer *out) {
    *out = (nvk_buffer){.buf=(void *)(uintptr_t)(atomic_fetch_add(&imports, 1)+256), .size=need};
    return 0;
}
static void nvmtl_vk_buffer_destroy(nvk_buffer *out) {
    assert(out->buf);
    // Freeing/importing the GPU object must happen outside the cache lock.
    if (!threaded) { assert(!pthread_mutex_trylock(&g_vram_kept_lock)); pthread_mutex_unlock(&g_vram_kept_lock); }
    drops++; memset(out, 0, sizeof *out);
}
static void nvmtl_vk_host_pages_drop(nvk_buffer *out) { host_drops++; nvmtl_vk_buffer_destroy(out); }
static struct __IOSurface surfaces[128];
static void drain(void) {
    now += NVMTL_VRAM_KEEP_AGE_NS + 1;
    nvmtl_vram_keep_sweep(); assert(!g_vram_kept_n && !g_vram_kept_bytes);
    for (unsigned i=0; i<128; i++) assert(surfaces[i].refs==1);
}
static void *worker(void *arg) {
    const unsigned id=(unsigned)(uintptr_t)arg;
    for (unsigned i=0; i<2500; i++) {
        nvk_buffer b={0}; uint64_t born;
        assert(!nvmtl_vram_keep_get(0, &surfaces[id], i%2, 4096, &b, &born));
        nvmtl_vram_keep_put(0, &surfaces[id], i%2, &b, born); assert(!b.buf);
    }
    return NULL;
}
int main(int argc, char **argv) { @autoreleasepool {
    for (unsigned i=0; i<128; i++) { surfaces[i].id=i+1; surfaces[i].refs=1; }
    nvk_buffer b={0}, other={0}; uint64_t born, other_born;
    const uint64_t cap=nvmtl_vram_keep_cap();
    if (argc>1 && !strcmp(argv[1], "invalid")) { assert(cap==(128ull<<20)); return 0; }
    if (argc>1) {
        assert(!cap && !nvmtl_vram_keep_get(0,&surfaces[0],0,4096,&b,&born));
        nvmtl_vram_keep_put(0,&surfaces[0],0,&b,born);
        assert(!g_vram_kept_n && drops==1 && surfaces[0].refs==1 && !b.buf);
        puts("PASS: disabled/zero-budget cache releases directly"); return 0;
    }
    assert(cap==(1ull<<20));
    assert(!nvmtl_vram_keep_get(0,&surfaces[0],0,4096,&b,&born));
    void *first=b.buf; uint64_t first_born=born;
    nvmtl_vram_keep_put(0,&surfaces[0],0,&b,born);
    assert(!b.buf && g_vram_kept_bytes==4096 && surfaces[0].refs==2);
    assert(nvmtl_vram_keep_get(1,&surfaces[0],0,0,&other,&other_born));
    assert(!other.buf && g_vram_kept_n==1); // host pages cannot take a VRAM import
    for (unsigned i=0;i<100;i++) {
        assert(!nvmtl_vram_keep_get(0,&surfaces[0],0,4096,&b,&born));
        assert(b.buf==first && born==first_born && imports==1 && surfaces[0].refs==1);
        nvmtl_vram_keep_put(0,&surfaces[0],0,&b,born);
    }
    assert(!nvmtl_vram_keep_get(0,&surfaces[0],1,4096,&other,&other_born));
    assert(other.buf!=first); nvmtl_vk_buffer_destroy(&other);
    assert(!nvmtl_vram_keep_get(0,&surfaces[0],0,8192,&other,&other_born));
    assert(other.buf!=first); nvmtl_vk_buffer_destroy(&other);
    drain();
    // Host imports preserve their size/map and use their own accounting destructor.
    b=(nvk_buffer){.buf=(void *)0x1234,.map=(void *)0x40000,.size=8192}; born=now;
    nvmtl_vram_keep_put(1,&surfaces[1],1,&b,born);
    assert(!nvmtl_vram_keep_get(1,&surfaces[1],1,0,&b,&born));
    assert(b.map==(void *)0x40000 && b.size==8192);
    nvmtl_vram_keep_put(1,&surfaces[1],1,&b,born); drain(); assert(host_drops==1);
    // Size and entry limits independently evict the oldest parked import.
    for (unsigned i=0;i<3;i++) {
        assert(!nvmtl_vram_keep_get(0,&surfaces[i],0,600*1024,&b,&born));
        nvmtl_vram_keep_put(0,&surfaces[i],0,&b,born);
        assert(g_vram_kept_n==1 && g_vram_kept_bytes==600*1024); now++;
    }
    drain();
    assert(!nvmtl_vram_keep_get(0,&surfaces[0],0,2*1024*1024,&b,&born));
    nvmtl_vram_keep_put(0,&surfaces[0],0,&b,born); assert(!g_vram_kept_n && !b.buf);
    for (unsigned i=0;i<65;i++) {
        assert(!nvmtl_vram_keep_get(0,&surfaces[i],0,1024,&b,&born));
        nvmtl_vram_keep_put(0,&surfaces[i],0,&b,born); now++;
    }
    assert(g_vram_kept_n==64 && g_vram_kept_bytes==64*1024 && surfaces[0].refs==1); drain();
    // Retrieval enforces expiry even before the asynchronous sweeper runs.
    assert(!nvmtl_vram_keep_get(0,&surfaces[0],0,4096,&b,&born)); first=b.buf;
    nvmtl_vram_keep_put(0,&surfaces[0],0,&b,born); now+=NVMTL_VRAM_KEEP_IDLE_NS;
    assert(!nvmtl_vram_keep_get(0,&surfaces[0],0,4096,&b,&born)); assert(first!=b.buf);
    now+=NVMTL_VRAM_KEEP_AGE_NS;
    nvmtl_vram_keep_put(0,&surfaces[0],0,&b,born); assert(!g_vram_kept_n); drain();
    threaded=1; pthread_t threads[4];
    for (unsigned i=0;i<4;i++) assert(!pthread_create(&threads[i],NULL,worker,(void *)(uintptr_t)i));
    for (unsigned i=0;i<4;i++) assert(!pthread_join(threads[i],NULL));
    threaded=0; drain(); assert(scheduled);
    puts("PASS: identity/plane/size isolation, import reuse, host accounting, byte/count bounds, expiry, ownership and 10000 concurrent transfers");
} }
'''
with tempfile.TemporaryDirectory(prefix='nvmtl-import-reuse-') as tmp:
    tmp = Path(tmp)
    (tmp / 'test.m').write_text(fixture.replace('@@CACHE@@', cache))
    subprocess.run(['xcrun', 'clang', '-O1', '-g', '-fobjc-arc', '-fsanitize=address,undefined',
                    '-fno-sanitize-recover=all', str(tmp / 'test.m'), '-framework', 'Foundation',
                    '-o', str(tmp / 'test')], check=True)
    for mb, enabled, args in [('1', '1', []), ('1', '0', ['off']), ('0', '1', ['off']),
                              ('-1', '1', ['invalid']), ('18446744073709551616', '1', ['invalid'])]:
        subprocess.run([str(tmp / 'test'), *args],
                       env={**os.environ, 'NVMTL_VRAM_KEEP_MB': mb, 'NVMTL_VRAM_KEEP': enabled}, check=True)
