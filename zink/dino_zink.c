/* SPDX-License-Identifier: MIT */
#include "dino_zink.h"
#include "pipe/p_screen.h"
#include "pipe/p_context.h"
#include "util/u_inlines.h"
#include "util/u_atomic.h"
#include "state_tracker/st_context.h"
#include "glapi/glapi/glapi.h"
#include "zink/zink_public.h"
#include <limits.h>
#include <stdlib.h>
#include <string.h>

#define DZ_EXPORT __attribute__((visibility("default")))
struct dino_zink_screen {
   struct pipe_frontend_screen fscreen;
   int refs;
};
struct dino_zink_context {
   struct pipe_frontend_drawable drawable;
   struct dino_zink_screen *screen;
   struct st_visual visual;
   struct st_context *st;
   struct pipe_resource *attachments[ST_ATTACHMENT_COUNT];
   unsigned width, height;
   bool double_buffer;
};
static uint32_t next_drawable_id;

static void finish(struct dino_zink_context *ctx)
{
   struct pipe_fence_handle *fence = NULL;
   st_context_flush(ctx->st, ST_FLUSH_WAIT, &fence, NULL, NULL);
   ctx->screen->fscreen.screen->fence_reference(ctx->screen->fscreen.screen, &fence, NULL);
}

static bool flush_front(struct st_context *st, struct pipe_frontend_drawable *drawable,
                         enum st_attachment_type attachment)
{
   /* Presentation is explicit through readback/present_iosurface. */
   return true;
}

static int get_param(struct pipe_frontend_screen *fscreen,
                     enum st_manager_param param)
{
   return 0;
}

static bool validate(struct st_context *st, struct pipe_frontend_drawable *drawable,
                     const enum st_attachment_type *requested, unsigned count,
                     struct pipe_resource **out, struct pipe_resource **resolve)
{
   struct dino_zink_context *ctx = (void *)drawable;
   if (resolve) *resolve = NULL;
   for (unsigned i = 0; i < count; ++i) {
      enum st_attachment_type a = requested[i];
      if (a != ST_ATTACHMENT_FRONT_LEFT && a != ST_ATTACHMENT_DEPTH_STENCIL &&
          !(ctx->double_buffer && a == ST_ATTACHMENT_BACK_LEFT))
         return false;
      if (!ctx->attachments[a]) {
         struct pipe_resource t = {0};
         t.target = PIPE_TEXTURE_2D;
         t.format = a == ST_ATTACHMENT_DEPTH_STENCIL ? ctx->visual.depth_stencil_format
                                                    : ctx->visual.color_format;
         t.width0 = ctx->width;
         t.height0 = ctx->height;
         t.depth0 = t.array_size = 1;
         t.bind = a == ST_ATTACHMENT_DEPTH_STENCIL ? PIPE_BIND_DEPTH_STENCIL
                                                 : PIPE_BIND_RENDER_TARGET | PIPE_BIND_SAMPLER_VIEW;
         ctx->attachments[a] = ctx->screen->fscreen.screen->resource_create(ctx->screen->fscreen.screen, &t);
         if (!ctx->attachments[a]) return false;
      }
      pipe_resource_reference(&out[i], ctx->attachments[a]);
   }
   return true;
}

DZ_EXPORT struct dino_zink_context *
dino_zink_create(unsigned width, unsigned height)
{
   return dino_zink_create_shared(width, height, NULL);
}

DZ_EXPORT struct dino_zink_context *
dino_zink_create_shared(unsigned width, unsigned height, struct dino_zink_context *share)
{
   return dino_zink_create_drawable(width, height, share, 0);
}

DZ_EXPORT struct dino_zink_context *
dino_zink_create_drawable(unsigned width, unsigned height, struct dino_zink_context *share,
                         int double_buffer)
{
   if (!width || !height || width > INT_MAX || height > INT_MAX) return NULL;
   struct dino_zink_context *ctx = calloc(1, sizeof(*ctx));
   if (!ctx) return NULL;
   if (share) {
      ctx->screen = share->screen;
      p_atomic_inc(&ctx->screen->refs);
   } else {
      ctx->screen = calloc(1, sizeof(*ctx->screen));
      if (!ctx->screen) { free(ctx); return NULL; }
      ctx->screen->fscreen.screen = zink_create_screen(NULL, NULL);
      if (!ctx->screen->fscreen.screen) { free(ctx->screen); free(ctx); return NULL; }
      ctx->screen->fscreen.get_param = get_param;
      ctx->screen->refs = 1;
   }
   ctx->width = width;
   ctx->height = height;
   ctx->double_buffer = double_buffer != 0;
   ctx->visual.color_format = PIPE_FORMAT_R8G8B8A8_UNORM;
   ctx->visual.depth_stencil_format = PIPE_FORMAT_Z24_UNORM_S8_UINT;
   ctx->visual.buffer_mask = ST_ATTACHMENT_FRONT_LEFT_MASK | ST_ATTACHMENT_DEPTH_STENCIL_MASK;
   if (ctx->double_buffer) ctx->visual.buffer_mask |= ST_ATTACHMENT_BACK_LEFT_MASK;
   ctx->drawable.fscreen = &ctx->screen->fscreen;
   ctx->drawable.visual = &ctx->visual;
   ctx->drawable.validate = validate;
   ctx->drawable.flush_front = flush_front;
   ctx->drawable.ID = p_atomic_inc_return(&next_drawable_id);
   p_atomic_set(&ctx->drawable.stamp, 1);
   struct st_context_attribs attrs = {0};
   attrs.profile = API_OPENGL_CORE;
   attrs.major = 4;
   attrs.minor = 1;
   attrs.visual = ctx->visual;
   enum st_context_error error;
   ctx->st = st_api_create_context(&ctx->screen->fscreen, &attrs, &error, share ? share->st : NULL);
   if (!ctx->st) { dino_zink_destroy(ctx); return NULL; }
   return ctx;
}

DZ_EXPORT int dino_zink_make_current(struct dino_zink_context *ctx)
{
   /* Each native GL entrypoint verifies the Mesa context. Rebinding the same
    * frontend on every call needlessly validates/refcounts its framebuffers.
    * Drawable stamp changes are still handled by Mesa's draw validation.
    */
   if (ctx && st_api_get_current() == ctx->st) return 1;
   return ctx ? st_api_make_current(ctx->st, &ctx->drawable, &ctx->drawable)
              : st_api_make_current(NULL, NULL, NULL);
}

DZ_EXPORT void dino_zink_destroy(struct dino_zink_context *ctx)
{
   if (!ctx) return;
   if (ctx->st) {
      finish(ctx);
      if (st_api_get_current() == ctx->st) dino_zink_make_current(NULL);
      st_destroy_context(ctx->st);
   }
   st_api_destroy_drawable(&ctx->drawable);
   for (unsigned i = 0; i < ST_ATTACHMENT_COUNT; ++i)
      pipe_resource_reference(&ctx->attachments[i], NULL);
   if (p_atomic_dec_zero(&ctx->screen->refs)) {
      st_screen_destroy(&ctx->screen->fscreen);
      ctx->screen->fscreen.screen->destroy(ctx->screen->fscreen.screen);
      free(ctx->screen);
   }
   free(ctx);
}

DZ_EXPORT int dino_zink_resize(struct dino_zink_context *ctx, unsigned width, unsigned height)
{
   if (!ctx || !width || !height || width > INT_MAX || height > INT_MAX ||
       st_api_get_current() != ctx->st) return 0;
   if (ctx->width == width && ctx->height == height) return 1;
   finish(ctx);
   for (unsigned i = 0; i < ST_ATTACHMENT_COUNT; ++i)
      pipe_resource_reference(&ctx->attachments[i], NULL);
   ctx->width = width;
   ctx->height = height;
   p_atomic_inc(&ctx->drawable.stamp);
   return 1;
}

DZ_EXPORT int dino_zink_swap(struct dino_zink_context *ctx)
{
   if (!ctx || st_api_get_current() != ctx->st) return 0;
   finish(ctx);
   if (ctx->double_buffer) {
      struct pipe_resource *front = ctx->attachments[ST_ATTACHMENT_FRONT_LEFT];
      ctx->attachments[ST_ATTACHMENT_FRONT_LEFT] = ctx->attachments[ST_ATTACHMENT_BACK_LEFT];
      ctx->attachments[ST_ATTACHMENT_BACK_LEFT] = front;
      p_atomic_inc(&ctx->drawable.stamp);
   }
   return 1;
}

DZ_EXPORT int dino_zink_present_iosurface(struct dino_zink_context *ctx, IOSurfaceRef surface)
{
   if (!ctx || !surface || IOSurfaceGetPlaneCount(surface) ||
       IOSurfaceGetWidth(surface) != ctx->width || IOSurfaceGetHeight(surface) != ctx->height ||
       IOSurfaceGetBytesPerElement(surface) != 4) return 0;
   uint32_t format = IOSurfaceGetPixelFormat(surface);
   if (format != 0x52474241 /* RGBA */ && format != 0x42475241 /* BGRA */) return 0;
   size_t row = (size_t)ctx->width * 4;
   if (row > SIZE_MAX / ctx->height) return 0;
   size_t size = row * ctx->height, stride = IOSurfaceGetBytesPerRow(surface);
   if (stride < row || stride > SIZE_MAX / ctx->height ||
       IOSurfaceGetAllocSize(surface) < stride * ctx->height) return 0;
   unsigned char *pixels = malloc(size);
   if (!pixels) return 0;
   if (!dino_zink_readback(ctx, pixels, size, row)) { free(pixels); return 0; }
   if (IOSurfaceLock(surface, 0, NULL) != kIOReturnSuccess) { free(pixels); return 0; }
   unsigned char *base = IOSurfaceGetBaseAddress(surface);
   if (base) {
      for (unsigned y = 0; y < ctx->height; ++y) {
         unsigned char *dst = base + y * stride, *src = pixels + y * row;
         if (format == 0x52474241) memcpy(dst, src, row);
         else for (unsigned x = 0; x < ctx->width; ++x) {
            dst[x * 4] = src[x * 4 + 2]; dst[x * 4 + 1] = src[x * 4 + 1];
            dst[x * 4 + 2] = src[x * 4]; dst[x * 4 + 3] = src[x * 4 + 3];
         }
      }
   }
   int ok = IOSurfaceUnlock(surface, 0, NULL) == kIOReturnSuccess && base;
   free(pixels);
   return ok;
}

DZ_EXPORT dino_zink_proc dino_zink_get_proc_address(const char *name)
{
   return name && strncmp(name, "gl", 2) == 0 ? _mesa_glapi_get_proc_address(name) : NULL;
}

static int readback(struct dino_zink_context *ctx, void *pixels,
                     size_t size, size_t stride, bool top_first)
{
   if (!ctx || !pixels || st_api_get_current() != ctx->st ||
       stride < (size_t)ctx->width * 4 || stride > SIZE_MAX / ctx->height ||
       size < stride * ctx->height ||
       (!top_first && (stride % 4 || stride / 4 > INT_MAX))) return 0;
   /* Mesa's readback path validates drawable state and synchronizes Zink's
    * transfer. Raw texture_map on this frontend returned stale data on NVK.
    * Preserve the application's pack state and read framebuffer binding. */
   void (*get)(GLenum, GLint *) = (void *)_mesa_glapi_get_proc_address("glGetIntegerv");
   void (*bindfb)(GLenum, GLuint) = (void *)_mesa_glapi_get_proc_address("glBindFramebuffer");
   void (*bindbuf)(GLenum, GLuint) = (void *)_mesa_glapi_get_proc_address("glBindBuffer");
   void (*store)(GLenum, GLint) = (void *)_mesa_glapi_get_proc_address("glPixelStorei");
   void (*readbuf)(GLenum) = (void *)_mesa_glapi_get_proc_address("glReadBuffer");
   void (*read)(GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, void *) =
      (void *)_mesa_glapi_get_proc_address("glReadPixels");
   size_t row = (size_t)ctx->width * 4;
   if (row > SIZE_MAX / ctx->height) return 0;
   unsigned char *map = top_first ? malloc(row * ctx->height) : pixels;
   if (!map) return 0;
   const GLenum pack_names[] = {GL_PACK_ALIGNMENT, GL_PACK_ROW_LENGTH, GL_PACK_SKIP_ROWS,
                                GL_PACK_SKIP_PIXELS, GL_PACK_IMAGE_HEIGHT, GL_PACK_SKIP_IMAGES};
   GLint saved_pack[6], saved_fb, saved_pbo, saved_read;
   get(GL_READ_FRAMEBUFFER_BINDING, &saved_fb);
   get(GL_PIXEL_PACK_BUFFER_BINDING, &saved_pbo);
   for (unsigned i = 0; i < 6; ++i) get(pack_names[i], &saved_pack[i]);
   bindfb(GL_READ_FRAMEBUFFER, 0);
   get(GL_READ_BUFFER, &saved_read);
   readbuf(ctx->double_buffer ? GL_BACK : GL_FRONT);
   bindbuf(GL_PIXEL_PACK_BUFFER, 0);
   for (unsigned i = 0; i < 6; ++i) store(pack_names[i], i ? 0 : 1);
   if (!top_first) store(GL_PACK_ROW_LENGTH, stride / 4);
   read(0, 0, ctx->width, ctx->height, GL_RGBA, GL_UNSIGNED_BYTE, map);
   for (unsigned i = 0; i < 6; ++i) store(pack_names[i], saved_pack[i]);
   bindbuf(GL_PIXEL_PACK_BUFFER, saved_pbo);
   readbuf(saved_read);
   bindfb(GL_READ_FRAMEBUFFER, saved_fb);
   if (top_first) {
      for (unsigned y = 0; y < ctx->height; ++y)
         memcpy((unsigned char *)pixels + y * stride,
                map + (ctx->height - 1 - y) * row, row);
      free(map);
   }
   return 1;
}

DZ_EXPORT int dino_zink_readback(struct dino_zink_context *ctx, void *pixels,
                                 size_t size, size_t stride)
{
   return readback(ctx, pixels, size, stride, true);
}

DZ_EXPORT int dino_zink_readback_bottom_up(struct dino_zink_context *ctx, void *pixels,
                                           size_t size, size_t stride)
{
   return readback(ctx, pixels, size, stride, false);
}
