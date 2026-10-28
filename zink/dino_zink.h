/* SPDX-License-Identifier: MIT */
#ifndef DINO_ZINK_H
#define DINO_ZINK_H
#include <stddef.h>
#include <stdint.h>
#ifdef __APPLE__
#include <IOSurface/IOSurface.h>
#endif
#ifdef __cplusplus
extern "C" {
#endif
struct dino_zink_context;
typedef void (*dino_zink_proc)(void);
/* Contexts belong to one thread at a time. Release before moving threads.
 * Configure VK_DRIVER_FILES before creation; this API never alters the process
 * environment. This is a Mesa context, not an Apple CGLContextObj. */
struct dino_zink_context *dino_zink_create(unsigned width, unsigned height);
struct dino_zink_context *dino_zink_create_shared(unsigned width, unsigned height,
                                                struct dino_zink_context *share);
struct dino_zink_context *dino_zink_create_drawable(unsigned width, unsigned height,
                                                  struct dino_zink_context *share,
                                                  int double_buffer);
int dino_zink_swap(struct dino_zink_context *ctx);
int dino_zink_make_current(struct dino_zink_context *ctx);
void dino_zink_destroy(struct dino_zink_context *ctx);
int dino_zink_resize(struct dino_zink_context *ctx, unsigned width, unsigned height);
dino_zink_proc dino_zink_get_proc_address(const char *name);
/* RGBA8, top row first. Requires ctx current on the calling thread. */
int dino_zink_readback(struct dino_zink_context *ctx, void *pixels,
                       size_t size, size_t stride);
/* RGBA8, bottom row first, for native GL upload. Stride must be a multiple of 4. */
int dino_zink_readback_bottom_up(struct dino_zink_context *ctx, void *pixels,
                                 size_t size, size_t stride);
#ifdef __APPLE__
/* Copy into a caller-owned, same-size, nonplanar RGBA/BGRA IOSurface. The
 * caller remains responsible for submitting the surface to its compositor. */
int dino_zink_present_iosurface(struct dino_zink_context *ctx, IOSurfaceRef surface);
#endif
#ifdef __cplusplus
}
#endif
#endif
