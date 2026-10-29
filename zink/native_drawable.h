/* SPDX-License-Identifier: MIT */
#ifndef NVK_NATIVE_DRAWABLE_H
#define NVK_NATIVE_DRAWABLE_H
#include <OpenGL/OpenGL.h>
#include <IOSurface/IOSurface.h>
#include <stdint.h>
/* AppKit calls bind on main. Rendering acquires only published layer state;
 * it never synchronously dispatches to main or changes a view's layer tree. */
void nvk_native_bind_view(CGLContextObj, void *view);
void nvk_native_remove(CGLContextObj);
/* 1 = drawable, 2 = resize/hidden/setup pending, 0 = unsupported/failed. */
int nvk_native_acquire(CGLContextObj, uint32_t vendor, uint32_t device,
                       unsigned width, unsigned height, int opaque, void **frame, IOSurfaceRef *surface);
int nvk_native_publish(void *frame);
void nvk_native_release(void *frame);
#endif
