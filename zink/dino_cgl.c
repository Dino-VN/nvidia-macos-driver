/* SPDX-License-Identifier: MIT */
#include "dino_cgl.h"
#include "dino_zink.h"
#include <OpenGL/gl3.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/sysctl.h>

#define EXPORT __attribute__((visibility("default")))
#define PREFIX_BYTES 0x1e80
#define MAX_ENTRIES 512
struct dino_cgl_bridge {
   CGLContextObj context;
   void *engine;
   struct dino_zink_context *zink;
   unsigned width, height;
   void *original[PREFIX_BYTES / sizeof(void *)];
   dino_zink_proc procs[MAX_ENTRIES];
   GLuint present_texture, present_fbo;
   unsigned char *present_pixels;
   size_t present_capacity;
   unsigned present_width, present_height;
   void *driver;
   void **engine_back;
   void *apple_back[(PREFIX_BYTES - 8) / sizeof(void *)];
   bool automatic;
   bool resize_pending;
   GLint native_x, native_y;
   struct dino_cgl_bridge *next;
};
struct dispatch_entry { const char *name; size_t offset; void *adapter, *stub; };
static pthread_mutex_t bridges_lock = PTHREAD_MUTEX_INITIALIZER;
static struct dino_cgl_bridge *bridges;
static _Atomic unsigned generation;
static _Thread_local unsigned thread_generation;
static _Thread_local struct dino_cgl_bridge *thread_bridge;
static _Thread_local const char *last_error;
static int materialize(struct dino_cgl_bridge *b);

__attribute__((noinline)) static int fail(const char *error) { last_error = error; return 0; }
EXPORT const char *dino_cgl_last_error(void) { return last_error ? last_error : "none"; }

static struct dino_cgl_bridge *find_bridge(CGLContextObj context)
{
   struct dino_cgl_bridge *b;
   for (b = bridges; b && b->context != context; b = b->next) {}
   return b;
}

static void *original_noncurrent(void *engine, size_t offset)
{
   void *proc = NULL;
   CGLContextObj current = CGLGetCurrentContext();
   if (current && *(void **)current == engine) return NULL;
   pthread_mutex_lock(&bridges_lock);
   for (struct dino_cgl_bridge *b = bridges; b; b = b->next)
      if (b->automatic && b->engine == engine && b->context != current) {
         proc = b->apple_back[(offset - 8) / 8]; break;
      }
   pthread_mutex_unlock(&bridges_lock);
   return proc == (void *)1 ? NULL : proc;
}

/* CGL and NSOpenGLContext call the public viewport dispatch during native
 * surface updates, sometimes before the context becomes current. Restrict
 * drawable sizing to those observed callers, preserving application viewports. */
static int native_viewport(void *engine, void *caller, GLint x, GLint y,
                           GLsizei width, GLsizei height)
{
   Dl_info info;
   if (!dladdr(caller, &info) || !info.dli_sname) return 0;
   if (strcmp(info.dli_sname, "CGLSetSurface") &&
       strcmp(info.dli_sname, "-[NSOpenGLContext(NSOpenGLContextInternal) _updateOpenGLViewport]")) return 0;
   pthread_mutex_lock(&bridges_lock);
   struct dino_cgl_bridge *b;
   for (b = bridges; b && b->engine != engine; b = b->next) {}
   pthread_mutex_unlock(&bridges_lock);
   if (!b || !b->automatic) return 0;
   void (*apple)(void *, GLint, GLint, GLsizei, GLsizei) = b->apple_back[(0xa80 - 8) / 8];
   apple(engine, x, y, width, height);
   if (width > 0 && height > 0) {
      b->width = width; b->height = height;
      b->native_x = x; b->native_y = y;
      b->resize_pending = true;
      if (b->zink && b->context == CGLGetCurrentContext()) {
         if (!dino_zink_make_current(b->zink) ||
             !dino_zink_resize(b->zink, width, height)) {
            fail("Cannot resize native Zink drawable"); return 1;
         }
         b->resize_pending = false;
         void (*mesa)(GLint, GLint, GLsizei, GLsizei) =
            (void *)dino_zink_get_proc_address("glViewport");
         mesa(x, y, width, height);
      }
   }
   return 1;
}

static struct dino_cgl_bridge *bridge_current(void *engine)
{
   unsigned current_generation = atomic_load(&generation);
   CGLContextObj context = CGLGetCurrentContext();
   if (thread_generation != current_generation || !thread_bridge ||
       thread_bridge->context != context || thread_bridge->engine != engine) {
      pthread_mutex_lock(&bridges_lock);
      thread_bridge = find_bridge(context);
      thread_generation = atomic_load(&generation);
      pthread_mutex_unlock(&bridges_lock);
   }
   if (!thread_bridge || thread_bridge->engine != engine ||
       (!thread_bridge->zink && !materialize(thread_bridge)) ||
       !dino_zink_make_current(thread_bridge->zink)) {
      fail("No attached Zink context current on this thread"); return NULL;
   }
   /* GLFW can resize a Cocoa window through a path that does not pass the
    * CGLSetSurface/NSOpenGLContext viewport callers above.  The native CGL
    * surface still exposes its backing dimensions through this public CGL
    * parameter, so check it at the frame boundary as a fallback. */
   if (thread_bridge->automatic) {
      GLint surface[2] = {0, 0};
      if (CGLGetParameter(thread_bridge->context, kCGLCPSurfaceBackingSize, surface) == kCGLNoError &&
          surface[0] > 0 && surface[1] > 0 &&
          ((unsigned)surface[0] != thread_bridge->width ||
           (unsigned)surface[1] != thread_bridge->height)) {
         thread_bridge->width = (unsigned)surface[0];
         thread_bridge->height = (unsigned)surface[1];
         thread_bridge->native_x = 0;
         thread_bridge->native_y = 0;
         thread_bridge->resize_pending = true;
      }
   }
   /* NSOpenGLContext can update a surface while another CGL context is current.
    * Mesa requires this drawable current before reallocating its buffers. */
   if (thread_bridge->resize_pending) {
      if (!dino_zink_resize(thread_bridge->zink, thread_bridge->width, thread_bridge->height)) {
         fail("Cannot resize native Zink drawable"); return NULL;
      }
      void (*viewport)(GLint, GLint, GLsizei, GLsizei) =
         (void *)dino_zink_get_proc_address("glViewport");
      viewport(thread_bridge->native_x, thread_bridge->native_y,
               thread_bridge->width, thread_bridge->height);
      thread_bridge->resize_pending = false;
   }
   return thread_bridge;
}

#include "cgl_dispatch.inc"
_Static_assert(sizeof(entries) / sizeof(entries[0]) <= MAX_ENTRIES, "adapter inventory too large");

static bool supported_os(void)
{
   char build[128]; size_t length = sizeof(build);
   return sysctlbyname("kern.osversion", build, &length, NULL, 0) == 0 &&
          strcmp(build, DINO_CGL_OS_BUILD) == 0;
}

static void use_original(struct dino_cgl_bridge *b)
{
   if (b->automatic) {
      b->original[0] = b->engine;
      memcpy(b->original + 1, b->apple_back, PREFIX_BYTES - 8);
   }
   memcpy(b->context, b->original, PREFIX_BYTES);
}

/* CGLFlushDrawable calls a distinct dispatch slot, not public glFlush. */
static void swap_drawable(void *engine)
{
   struct dino_cgl_bridge *b = bridge_current(engine);
   if (b) dino_cgl_present(b->context);
}

static void use_zink(struct dino_cgl_bridge *b)
{
   for (size_t i = 0; i < sizeof(entries) / sizeof(entries[0]); ++i)
      *(void **)((char *)b->context + entries[i].offset) = entries[i].adapter;
   *(void **)((char *)b->context + 0x1278) = (void *)swap_drawable;
}

/* GLD context creation runs before gliInitDispatchTable. On 25G241, GLI
 * +b2c8 points at CGL+8 and +b2d0 at the saved public dispatch table. Give
 * GLEngine a private table to populate, and leave adapters in the original
 * saved table for CGL's final restore. This is distinct from the HAL table.
 * The GLD proxy owns this registration and calls destroy during teardown. */
EXPORT int dino_cgl_prepare_gld(void *engine, void *driver)
{
   if (!supported_os() || !engine || !driver) return 0;
   if (*(unsigned char *)((char *)engine + 0xc6a6) != 1) return 0;
   CGLContextObj context = (CGLContextObj)((char *)*(void **)((char *)engine + 0xb2c8) - 8);
   void **back = *(void ***)((char *)engine + 0xb2d0);
   if (!context || !back) return 0;
   struct dino_cgl_bridge *b = calloc(1, sizeof(*b));
   if (!b) return 0;
   b->context = context; b->engine = engine; b->driver = driver;
   b->automatic = true; b->engine_back = back;
   memcpy(b->original, context, PREFIX_BYTES);
   /* Every nonzero private slot directs gliInitDispatchTable to write here. */
   for (size_t i = 0; i < sizeof(b->apple_back) / sizeof(b->apple_back[0]); ++i)
      b->apple_back[i] = (void *)1;
   for (size_t i = 0; i < sizeof(entries) / sizeof(entries[0]); ++i) {
      b->procs[i] = dino_zink_get_proc_address(entries[i].name);
      if (!b->procs[i]) { free(b); return 0; }
   }
   for (size_t i = 0; i < sizeof(entries) / sizeof(entries[0]); ++i) {
      back[(entries[i].offset - 8) / 8] = entries[i].adapter;
   }
   back[(0x1278 - 8) / 8] = (void *)swap_drawable;
   *(void ***)((char *)engine + 0xb2d0) = b->apple_back;
   pthread_mutex_lock(&bridges_lock);
   b->next = bridges; bridges = b;
   atomic_fetch_add(&generation, 1);
   pthread_mutex_unlock(&bridges_lock);
   return 1;
}

static int materialize(struct dino_cgl_bridge *b)
{
   GLint double_buffer = 0;
   if (!b->automatic || b->context != CGLGetCurrentContext()) return 0;
   CGLDescribePixelFormat(CGLGetPixelFormat(b->context), 0, kCGLPFADoubleBuffer, &double_buffer);
   struct dino_zink_context *share = NULL;
   pthread_mutex_lock(&bridges_lock);
   for (struct dino_cgl_bridge *other = bridges; other; other = other->next)
      if (other != b && other->zink &&
          *(void **)((char *)other->engine + 0x5b00) ==
          *(void **)((char *)b->engine + 0x5b00)) share = other->zink;
   pthread_mutex_unlock(&bridges_lock);
   GLint viewport[4] = {0};
   use_original(b);
   glGetIntegerv(GL_VIEWPORT, viewport);
   use_zink(b);
   b->width = viewport[2] > 0 ? (unsigned)viewport[2] : 1;
   b->height = viewport[3] > 0 ? (unsigned)viewport[3] : 1;
   b->zink = dino_zink_create_drawable(b->width, b->height, share, double_buffer);
   if (!b->zink) return fail("Cannot create automatic Zink context");
   return 1;
}

EXPORT void dino_cgl_destroy_gld(void *driver)
{
   pthread_mutex_lock(&bridges_lock);
   struct dino_cgl_bridge **link = &bridges;
   while (*link && (*link)->driver != driver) link = &(*link)->next;
   struct dino_cgl_bridge *b = *link;
   if (b) { *link = b->next; atomic_fetch_add(&generation, 1); }
   pthread_mutex_unlock(&bridges_lock);
   if (!b) return;
   use_original(b);
   *(void ***)((char *)b->engine + 0xb2d0) = b->engine_back;
   /* GLEngine still owns its GL objects and releases the presentation objects
    * with the carrier context/share group. No native context retain is held. */
   dino_zink_destroy(b->zink);
   free(b);
}

EXPORT int dino_cgl_attach(CGLContextObj context, unsigned width, unsigned height)
{
   last_error = NULL;
   if (!supported_os()) return fail("CGL dispatch ABI requires rebuilding for this macOS build");
   if (!context || context != CGLGetCurrentContext() || !width || !height)
      return fail("Attach requires a current CGL context and nonzero dimensions");
   GLint profile = 0;
   if (CGLDescribePixelFormat(CGLGetPixelFormat(context), 0, kCGLPFAOpenGLProfile, &profile) ||
       profile != kCGLOGLPVersion_GL4_Core)
      return fail("Only GL 4.1 core CGL contexts are supported");
   if (CGLLockContext(context)) return fail("Cannot lock CGL context");
   pthread_mutex_lock(&bridges_lock);
   bool exists = find_bridge(context) != NULL;
   struct dino_zink_context *share = NULL;
   for (struct dino_cgl_bridge *other = bridges; other; other = other->next)
      if (other->context != context &&
          *(void **)((char *)other->engine + 0x5b00) ==
          *(void **)((char *)*(void **)context + 0x5b00)) share = other->zink;
   pthread_mutex_unlock(&bridges_lock);
   if (exists) { CGLUnlockContext(context); return fail("Context is already attached"); }
   struct dino_cgl_bridge *b = calloc(1, sizeof(*b));
   if (!b) { CGLUnlockContext(context); return fail("Out of memory"); }
   b->context = context; b->engine = *(void **)context;
   b->width = width; b->height = height;
   b->resize_pending = false;
   memcpy(b->original, context, PREFIX_BYTES);
   for (size_t i = 0; i < sizeof(entries) / sizeof(entries[0]); ++i) {
      b->procs[i] = dino_zink_get_proc_address(entries[i].name);
      if (!b->procs[i]) { free(b); CGLUnlockContext(context); return fail("Missing Mesa core entrypoint"); }
   }
   GLint double_buffer = 0;
   CGLDescribePixelFormat(CGLGetPixelFormat(context), 0, kCGLPFADoubleBuffer, &double_buffer);
   b->zink = dino_zink_create_drawable(width, height, share, double_buffer);
   if (!b->zink || !dino_zink_make_current(b->zink)) {
      dino_zink_destroy(b->zink); free(b); CGLUnlockContext(context);
      return fail("Cannot create Zink/NVK context");
   }
   CGLRetainContext(context);
   pthread_mutex_lock(&bridges_lock);
   b->next = bridges; bridges = b;
   atomic_fetch_add(&generation, 1);
   pthread_mutex_unlock(&bridges_lock);
   use_zink(b);
   CGLUnlockContext(context);
   return 1;
}

EXPORT int dino_cgl_resize(CGLContextObj context, unsigned width, unsigned height)
{
   if (!context || context != CGLGetCurrentContext()) return fail("Resize requires the context current");
   struct dino_cgl_bridge *b = bridge_current(*(void **)context);
   if (!b || !dino_zink_resize(b->zink, width, height)) return fail("Cannot resize Zink drawable");
   b->width = width; b->height = height;
   return 1;
}

EXPORT int dino_cgl_present(CGLContextObj context)
{
   last_error = NULL;
   if (!context || context != CGLGetCurrentContext()) return fail("Present requires the context current");
   struct dino_cgl_bridge *b = bridge_current(*(void **)context);
   if (!b) return 0;
   size_t row = (size_t)b->width * 4;
   if (row > SIZE_MAX / b->height) return fail("Drawable size overflow");
   size_t size = row * b->height;
   if (size > b->present_capacity) {
      unsigned char *pixels = realloc(b->present_pixels, size);
      if (!pixels) return fail("Out of memory during presentation");
      b->present_pixels = pixels; b->present_capacity = size;
   }
   int ok = dino_zink_readback_bottom_up(b->zink, b->present_pixels, size, row);
   if (!ok) return fail("Zink readback failed");
   /* Apple GL state is private to the presentation side. The application's
    * Mesa GL state is untouched, including its FBOs, pixel stores and buffers. */
   use_original(b);
   if (!b->present_texture) glGenTextures(1, &b->present_texture);
   if (!b->present_fbo) glGenFramebuffers(1, &b->present_fbo);
   glBindTexture(GL_TEXTURE_2D, b->present_texture);
   glPixelStorei(GL_UNPACK_ALIGNMENT, 1);
   if (b->present_width != b->width || b->present_height != b->height) {
      glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, b->width, b->height, 0,
                   GL_RGBA, GL_UNSIGNED_BYTE, b->present_pixels);
      b->present_width = b->width; b->present_height = b->height;
   } else {
      glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, b->width, b->height,
                      GL_RGBA, GL_UNSIGNED_BYTE, b->present_pixels);
   }
   glBindFramebuffer(GL_READ_FRAMEBUFFER, b->present_fbo);
   glFramebufferTexture2D(GL_READ_FRAMEBUFFER, GL_COLOR_ATTACHMENT0,
                          GL_TEXTURE_2D, b->present_texture, 0);
   glReadBuffer(GL_COLOR_ATTACHMENT0);
   glBindFramebuffer(GL_DRAW_FRAMEBUFFER, 0);
   GLint double_buffer = 0;
   glGetIntegerv(GL_DOUBLEBUFFER, &double_buffer);
   glDrawBuffer(double_buffer ? GL_BACK : GL_FRONT);
   glBlitFramebuffer(0, 0, b->width, b->height, 0, 0, b->width, b->height,
                      GL_COLOR_BUFFER_BIT, GL_NEAREST);
   GLenum error = glGetError();
   CGLError swap_error = CGLFlushDrawable(context);
   use_zink(b);
   if (error != GL_NO_ERROR || swap_error != kCGLNoError) return fail("Apple drawable upload or swap failed");
   return dino_zink_swap(b->zink);
}

EXPORT int dino_cgl_detach(CGLContextObj context)
{
   if (!context || context != CGLGetCurrentContext()) return fail("Detach requires the context current");
   if (CGLLockContext(context)) return fail("Cannot lock CGL context");
   pthread_mutex_lock(&bridges_lock);
   struct dino_cgl_bridge **link = &bridges;
   while (*link && (*link)->context != context) link = &(*link)->next;
   struct dino_cgl_bridge *b = *link;
   if (b) { *link = b->next; atomic_fetch_add(&generation, 1); }
   pthread_mutex_unlock(&bridges_lock);
   if (!b) { CGLUnlockContext(context); return fail("Context is not attached"); }
   use_original(b);
   bool automatic = b->automatic;
   if (automatic) *(void ***)((char *)b->engine + 0xb2d0) = b->engine_back;
   if (b->present_texture) glDeleteTextures(1, &b->present_texture);
   if (b->present_fbo) glDeleteFramebuffers(1, &b->present_fbo);
   dino_zink_destroy(b->zink);
   free(b->present_pixels);
   free(b);
   CGLUnlockContext(context);
   if (!automatic) CGLReleaseContext(context);
   return 1;
}
