/* SPDX-License-Identifier: MIT */
#include "nvk_cgl_gld.h"
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define EXPORT __attribute__((visibility("default")))
#include "gld_forward.inc"
static int available;

__attribute__((constructor)) static void initialize(void)
{
   void *apple = dlopen("/System/Library/Extensions/AppleMetalOpenGLRenderer.bundle/Contents/MacOS/AppleMetalOpenGLRenderer",
                        RTLD_NOW | RTLD_LOCAL);
   if (!apple) { fprintf(stderr, "NVKZinkGLDriver: %s\n", dlerror()); return; }
   for (size_t i = 0; i < sizeof(gld_names) / sizeof(gld_names[0]); ++i) {
      gld_targets[i] = dlsym(apple, gld_names[i]);
      if (!gld_targets[i]) {
         fprintf(stderr, "NVKZinkGLDriver: missing delegate %s\n", gld_names[i]); return;
      }
   }
   available = 1;
   /* Zink loads its private Vulkan frontend; do not change process ICD selection. */
}

EXPORT int gldGetVersion(uint32_t *a, uint32_t *b, uint32_t *c, uint32_t *d)
{
   if (!available) return 0;
   return ((int (*)(uint32_t *, uint32_t *, uint32_t *, uint32_t *))gld_targets[GLD_INDEX_gldGetVersion])(a,b,c,d);
}

/* Caller-side GLEngine evidence establishes six pointer arguments, an output
 * GLD context in the second argument, and GLD state at GLI+8e0 in the fifth.
 * Keep pixel format, device/share group and plugin state owned by Apple. */
EXPORT int gldCreateContext(void *share, void **output, void *pixel_format,
                           void *config, void *state, void *plugin_state)
{
   if (!available) return 10006;
   int result = ((int (*)(void *, void **, void *, void *, void *, void *))
                 gld_targets[GLD_INDEX_gldCreateContext])(share, output, pixel_format, config, state, plugin_state);
   if (!result && output && *output && state)
      nvk_cgl_prepare_gld((char *)state - 0x8e0, *output);
   return result;
}

EXPORT int gldDestroyContext(void *context)
{
   nvk_cgl_destroy_gld(context);
   return ((int (*)(void *))gld_targets[GLD_INDEX_gldDestroyContext])(context);
}
