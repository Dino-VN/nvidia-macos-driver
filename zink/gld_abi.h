/* SPDX-License-Identifier: MIT
 * Research notes, NOT a stable or complete Apple GLD ABI.
 * Observed on macOS 26.7.1 (25G241), x86_64, AMDRadeonX6000GLDriver.
 * Every opaque area and prototype marked UNCERTAIN needs caller-side evidence.
 */
#ifndef NVK_GLD_ABI_H
#define NVK_GLD_ABI_H
#include <stddef.h>
#include <stdint.h>

enum { GLD_OBSERVED_MAJOR = 4, GLD_OBSERVED_MINOR = 1,
       GLD_OBSERVED_THIRD_VERSION_WORD = 0x11 };
/* The third version word's meaning is UNCERTAIN; do not call it an ABI version. */
typedef int (*gld_get_version_fn)(uint32_t *, uint32_t *, uint32_t *, uint32_t *);
/* Observed: writes 4, 1, 0x11 and glrGetDriverID(), returns 1 when initialized;
 * otherwise returns 0 without writing. Driver ID is NOT yet known for this driver. */

/* Observed string selector in ESI, device in RDI; returns pointer in RAX.
 * Device layout and selector meanings outside GL_VENDOR/GL_RENDERER/GL_VERSION
 * are UNCERTAIN. */
typedef const char *(*gld_get_device_string_fn)(void *, uint32_t);

/* Inferred from register forwarding to gpumCreateDevice. UNCERTAIN: the second
 * argument, config type, lifetime, and return type. First arg is dereferenced
 * as an output pointer; config+7 is written before the gpum call. */
typedef int (*gld_create_device_guess_fn)(void **, uintptr_t, void *);
/* UNCERTAIN: first two args pass unchanged to gpumChoosePixelFormat. */
typedef int (*gld_choose_pixel_format_guess_fn)(uintptr_t, uintptr_t);
typedef int (*gld_destroy_pixel_format_guess_fn)(void *);
/* UNCERTAIN: initialization forwards RDI,RSI,RDX,RCX,R8,R9 unchanged to
 * gpumInitializeIOData, plus two driver arguments on the stack. No callable
 * declaration is provided until those six argument meanings are established. */

/* Observed: PopulateContextDispatch has context in RDI and internal callback
 * table in RSI. It does NOT install public OpenGL entrypoints. Return type is
 * UNCERTAIN (RAX contains a NoOp pointer at return; likely void). */
typedef void (*gld_populate_dispatch_guess_fn)(void *, void *);
/* Observed UpdateDispatch: RDI=context, RDX=dirty-state pointer. RSI and return
 * semantics are UNCERTAIN. */
typedef void (*gld_update_dispatch_guess_fn)(void *, uintptr_t, void *);
/* Present observes RDI=context, ESI=buffer selector; no IOSurface argument.
 * Return type and selector semantics are UNCERTAIN. */
typedef void (*gld_present_guess_fn)(void *, uint32_t);

/* Observed offsets only. All callback signatures are UNCERTAIN. This table
 * describes bytes touched by AMD, not the complete GLEngine structure. */
struct gld_dispatch_observed_prefix {
   uintptr_t unknown_00;
   uintptr_t draw_pixels;             /* +0x08, glrdATI_Hwl_DrawPixels */
   uintptr_t copy_pixels;             /* +0x10, glrdATICopyPixels */
   uintptr_t unknown_18_through_98[17]; /* no-op or NULL, semantics UNCERTAIN */
   uintptr_t begin_primitive_buffer;  /* +0xa0 */
   uintptr_t end_primitive_buffer;    /* +0xa8 */
   uintptr_t unknown_b0, unknown_b8;   /* observed NULL */
   uintptr_t render_vertex_array;     /* +0xc0 */
};
_Static_assert(offsetof(struct gld_dispatch_observed_prefix, render_vertex_array) == 0xc0,
               "GLD observations require x86_64 pointer layout");
enum { GLD_CONTEXT_DIRTY_POINTER_OFFSET = 0x78,
       GLD_CONTEXT_DISPATCH_POINTER_OFFSET = 0x80,
       GLD_CONTEXT_OBSERVED_FLAGS_OFFSET = 0x3191 };
#endif
