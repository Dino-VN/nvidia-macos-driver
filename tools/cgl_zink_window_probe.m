/* SPDX-License-Identifier: MIT */
#import <Cocoa/Cocoa.h>
#import <IOSurface/IOSurface.h>
#import <objc/message.h>
#import <objc/runtime.h>
#import <dispatch/dispatch.h>
#include <OpenGL/gl3.h>
#include <dlfcn.h>
#include "dino_cgl.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int check_appkit_presentation(CGLContextObj ctx, GLint width, GLint height,
                                     unsigned expected_alpha)
{
   CGLError (*get_surface)(CGLContextObj, unsigned *, unsigned *, unsigned *) =
      dlsym(RTLD_DEFAULT, "CGLGetSurface");
   Class surface_class = NSClassFromString(@"NSCGLSurface");
   SEL lookup = NSSelectorFromString(@"surfaceWithID:");
   unsigned connection = 0, window = 0, surface_id = 0;
   if (!get_surface || ![surface_class respondsToSelector:lookup] ||
       get_surface(ctx, &connection, &window, &surface_id) || !surface_id) {
      fprintf(stderr, "Cannot find the AppKit drawable surface\n"); return 0;
   }
   id surface = ((id (*)(id, SEL, uint64_t))objc_msgSend)(surface_class, lookup, surface_id);
   Ivar wrapper_ivar = class_getInstanceVariable(surface_class, "_surface");
   Ivar map_ivar = class_getInstanceVariable(surface_class, "_surfacesToImageQueueBufferIDs");
   Ivar active_ivar = class_getInstanceVariable(surface_class, "_activeImageQueueBufferIDs");
   if (!surface || !wrapper_ivar || !map_ivar || !active_ivar) {
      fprintf(stderr, "AppKit surface inspection is unavailable\n"); return 0;
   }
   id wrapper = object_getIvar(surface, wrapper_ivar);
   Ivar context_ivar = class_getInstanceVariable(object_getClass(wrapper), "_context");
   CGLContextObj helper = NULL;
   if (wrapper && context_ivar)
      memcpy(&helper, (char *)(__bridge void *)wrapper + ivar_getOffset(context_ivar), sizeof(helper));
   if (!helper) { fprintf(stderr, "AppKit has no presentation copy context\n"); return 0; }
   CGLContextObj saved = CGLGetCurrentContext();
   CGLError set_error = CGLSetCurrentContext(helper);
   const char *renderer = set_error ? NULL : (const char *)glGetString(GL_RENDERER);
   bool native = renderer && !strstr(renderer, "zink");
   printf("appkit_copy_renderer=%s\n", renderer ? renderer : "(null)");
   CGLError restore_error = CGLSetCurrentContext(saved);
   if (!native || restore_error) {
      fprintf(stderr, "AppKit's presentation copy context must stay native\n"); return 0;
   }
   /* Inspect buffers AppKit actually registered and successfully inserted.
    * Reading GL_FRONT alone cannot detect a failed image queue publication. */
   NSMapTable *buffers = object_getIvar(surface, map_ivar);
   NSHashTable *active = object_getIvar(surface, active_ivar);
   for (id object in buffers.keyEnumerator) {
      NSNumber *buffer_id = [buffers objectForKey:object];
      IOSurfaceRef image = (__bridge IOSurfaceRef)object;
      if (![active containsObject:buffer_id] || IOSurfaceGetWidth(image) != (size_t)width ||
          IOSurfaceGetHeight(image) != (size_t)height || IOSurfaceGetBytesPerElement(image) != 4 ||
          IOSurfaceGetPixelFormat(image) != 0x42475241 || IOSurfaceGetPlaneCount(image) > 1)
         continue;
      if (IOSurfaceLock(image, kIOSurfaceLockReadOnly, NULL) != kIOReturnSuccess) continue;
      const unsigned char *pixels = IOSurfaceGetBaseAddress(image);
      size_t row = IOSurfaceGetBytesPerRow(image), red = 0, green = 0, blue = 0, alpha = 0;
      if (pixels && row >= (size_t)width * 4) {
         for (GLint y = 0; y < height; ++y) for (GLint x = 0; x < width; ++x) {
            const unsigned char *p = pixels + (size_t)y * row + (size_t)x * 4;
            red += p[2] > 240 && p[1] < 8 && p[0] < 8;
            green += p[1] > 240 && p[2] < 8 && p[0] < 8;
            blue += p[0] > 240 && p[1] < 8 && p[2] < 8;
            alpha += p[3] == expected_alpha;
         }
      }
      IOSurfaceUnlock(image, kIOSurfaceLockReadOnly, NULL);
      size_t total = (size_t)width * height;
      if (red > total / 8 && green > total / 8 && blue >= 16 && alpha == total) {
         printf("appkit_queued_surface=%u buffer=%llu size=%dx%d red=%zu green=%zu blue=%zu\n",
                IOSurfaceGetID(image), buffer_id.unsignedLongLongValue, width, height, red, green, blue);
         return 1;
      }
   }
   fprintf(stderr, "AppKit has no queued IOSurface containing the presented frame\n");
   return 0;
}

static int draw_frame(CGLContextObj ctx, GLint width, GLint height,
                      const char *(*error)(void))
{
   /* A viewport is application state; it must not shrink the native drawable. */
   glViewport(0, 0, width / 2, height / 2);
   static unsigned frame;
   bool alternate = (++frame % 2) == 0;
   /* Games can leave zero alpha in an opaque window's default framebuffer. */
   glClearColor(alternate ? 0 : 1, alternate ? 1 : 0, 0, 0); glClear(GL_COLOR_BUFFER_BIT);
   glEnable(GL_SCISSOR_TEST);
   glScissor(width / 4, height / 4, width / 2, height / 2);
   glClearColor(alternate ? 1 : 0, alternate ? 0 : 1, 0, 0); glClear(GL_COLOR_BUFFER_BIT);
   glScissor(width - 8, height - 8, 8, 8);
   glClearColor(0, 0, 1, 0); glClear(GL_COLOR_BUFFER_BIT);
   glDisable(GL_SCISSOR_TEST);
   unsigned char edge[4] = {0};
   glReadBuffer(GL_BACK);
   glReadPixels(width - 2, height - 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, edge);
   if (glGetError() || edge[2] < 240 || edge[0] > 8 || edge[1] > 8) {
      fprintf(stderr, "Zink drawable extent failed at %dx%d: %u,%u,%u\n",
              width, height, edge[0], edge[1], edge[2]); return 0;
   }
   if (CGLFlushDrawable(ctx) != kCGLNoError || strcmp(error(), "none")) {
      fprintf(stderr, "swap failed at %dx%d: %s\n", width, height, error()); return 0;
   }
   /* Presentation must not force opacity into the application's GL state. */
   GLfloat clear[4] = {0}; glGetFloatv(GL_COLOR_CLEAR_VALUE, clear);
   if (clear[3] != 0) { fprintf(stderr, "presentation changed clear alpha\n"); return 0; }
   printf("presented_frame=%dx%d\n", width, height);
   return 1;
}

int main(int argc, char **argv)
{
   bool system = false, legacy = false, no_alpha = false, transparent = false, appkit = false, render_thread = false;
   if (argc < 3) { fprintf(stderr, "usage: %s LIBDINO_CGL ICD_JSON [--system] [--legacy] [--no-alpha] [--transparent] [--appkit-present] [--render-thread]\n", argv[0]); return 2; }
   for (int i = 3; i < argc; ++i) {
      if (!strcmp(argv[i], "--system")) system = true;
      else if (!strcmp(argv[i], "--legacy")) legacy = true;
      else if (!strcmp(argv[i], "--no-alpha")) no_alpha = true;
      else if (!strcmp(argv[i], "--transparent")) transparent = true;
      else if (!strcmp(argv[i], "--appkit-present")) appkit = true;
      else if (!strcmp(argv[i], "--render-thread")) render_thread = true;
      else { fprintf(stderr, "unknown option: %s\n", argv[i]); return 2; }
   }
   if (render_thread && !system) {
      fprintf(stderr, "--render-thread requires automatic --system attachment\n"); return 2;
   }
   setenv("VK_DRIVER_FILES", argv[2], 1);
   void *lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
   if (!lib) { fprintf(stderr, "%s\n", dlerror()); return 1; }
   int (*attach)(CGLContextObj, unsigned, unsigned) = dlsym(lib, "dino_cgl_attach");
   int (*detach)(CGLContextObj) = dlsym(lib, "dino_cgl_detach");
   const char *(*error)(void) = dlsym(lib, "dino_cgl_last_error");
   if (!attach || !detach || !error) return 1;
   @autoreleasepool {
      [NSApplication sharedApplication];
      [NSApp setActivationPolicy:NSApplicationActivationPolicyAccessory];
      [NSApp finishLaunching];
      NSOpenGLPixelFormatAttribute attrs[] = {NSOpenGLPFAOpenGLProfile,
         legacy ? NSOpenGLProfileVersionLegacy : NSOpenGLProfileVersion4_1Core,
         NSOpenGLPFAColorSize, 24, NSOpenGLPFADoubleBuffer,
         NSOpenGLPFAAlphaSize, 8, 0};
      if (no_alpha) attrs[5] = 0;
      NSOpenGLPixelFormat *format = [[NSOpenGLPixelFormat alloc] initWithAttributes:attrs];
      NSOpenGLView *view = [[NSOpenGLView alloc] initWithFrame:NSMakeRect(0, 0, 128, 128) pixelFormat:format];
      NSWindow *window = [[NSWindow alloc] initWithContentRect:NSMakeRect(100, 100, 128, 128)
         styleMask:NSWindowStyleMaskTitled | NSWindowStyleMaskResizable backing:NSBackingStoreBuffered defer:NO];
      [window setTitle:@"Zink native CGL validation"];
      [window setContentView:view]; [window orderFront:nil];
      [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.15]];
      NSOpenGLContext *nsctx = [view openGLContext];
      [nsctx makeCurrentContext]; [nsctx update];
      CGLContextObj ctx = [nsctx CGLContextObj];
      GLint opacity = transparent ? 0 : 1;
      if (CGLSetParameter(ctx, kCGLCPSurfaceOpacity, &opacity)) return 1;
      GLint native_alpha_bits = 0;
      CGLDescribePixelFormat(CGLGetPixelFormat(ctx), 0, kCGLPFAAlphaSize, &native_alpha_bits);
      printf("native_profile=%s alpha_bits=%d surface_opacity=%d\n", legacy ? "legacy" : "core", native_alpha_bits, opacity);
      if (!system && !attach(ctx, 128, 128)) { fprintf(stderr, "%s\n", error()); return 1; }
      const char *renderer = (const char *)glGetString(GL_RENDERER);
      printf("native_window_renderer=%s\n", renderer ? renderer : "(null)");
      if (!renderer || !strstr(renderer, "zink") || !strstr(renderer, "NVK")) return 1;
      GLint double_buffer = 0; glGetIntegerv(GL_DOUBLEBUFFER, &double_buffer);
      if (!double_buffer) { fprintf(stderr, "Mesa drawable is not double buffered\n"); return 1; }
      GLint width = 128, height = 128;
      if (render_thread) {
         /* Mirror LWJGL: AppKit resizes on main while this context remains
          * current on the render thread. Check actual backing pixels because
          * AppKit can constrain a requested window to the screen bounds. */
         [NSOpenGLContext clearCurrentContext];
         dispatch_semaphore_t ready = dispatch_semaphore_create(0), go = dispatch_semaphore_create(0);
         __block int good = 1;
         __block GLint actual_width = 128, actual_height = 128;
         static const GLint sizes[][2] = {{128,128}, {854,480}, {1920,960}, {854,480}};
         dispatch_async(dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0), ^{
            @autoreleasepool {
               [nsctx makeCurrentContext];
               for (unsigned i = 0; i < 4; ++i) {
                  dispatch_semaphore_wait(go, DISPATCH_TIME_FOREVER);
                  if (!draw_frame(ctx, actual_width, actual_height, error)) good = 0;
                  if (!i && !draw_frame(ctx, actual_width, actual_height, error)) good = 0;
                  if (i == 3) [NSOpenGLContext clearCurrentContext];
                  dispatch_semaphore_signal(ready);
               }
            }
         });
         for (unsigned i = 0; i < 4; ++i) {
            [window setContentSize:NSMakeSize(sizes[i][0], sizes[i][1])];
            [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.15]];
            [nsctx update];
            NSRect backing = [view convertRectToBacking:view.bounds];
            actual_width = backing.size.width; actual_height = backing.size.height;
            dispatch_semaphore_signal(go);
            dispatch_semaphore_wait(ready, DISPATCH_TIME_FOREVER);
         }
         if (!good) return 1;
         width = actual_width; height = actual_height;
         [nsctx makeCurrentContext];
      } else {
         if (!draw_frame(ctx, 128, 128, error)) return 1;
         if (!draw_frame(ctx, 128, 128, error) || !draw_frame(ctx, 128, 128, error)) return 1;
      }
      if (system && !render_thread) {
         [window setContentSize:NSMakeSize(64, 96)];
         [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.15]];
         [nsctx makeCurrentContext]; [nsctx update];
         if (!draw_frame(ctx, 64, 96, error)) return 1;
         [NSOpenGLContext clearCurrentContext];
         [window setContentSize:NSMakeSize(192, 160)];
         [[NSRunLoop currentRunLoop] runUntilDate:[NSDate dateWithTimeIntervalSinceNow:0.15]];
         /* Surface update precedes makeCurrent: no application resize API. */
         [nsctx update]; [nsctx makeCurrentContext];
         width = 192; height = 160;
         if (!draw_frame(ctx, width, height, error)) return 1;
      }
      unsigned expected_alpha = opacity || !native_alpha_bits ? 255 : 0;
      if (appkit && !check_appkit_presentation(ctx, width, height, expected_alpha)) return 1;
      // Detach restores the actual Apple context; read its presented pixels.
      if (!detach(ctx)) { fprintf(stderr, "%s\n", error()); return 1; }
      unsigned char center[4] = {0}, corner[4] = {0}, edge[4] = {0};
      glReadBuffer(GL_FRONT);
      glReadPixels(width / 2, height / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, center);
      glReadPixels(1, 1, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, corner);
      glReadPixels(width - 2, height - 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, edge);
      GLenum gl_error = glGetError();
      printf("presented_center=%u,%u,%u,%u corner=%u,%u,%u,%u edge=%u,%u,%u,%u error=%x\n",
         center[0], center[1], center[2], center[3], corner[0], corner[1], corner[2], corner[3],
         edge[0], edge[1], edge[2], edge[3], gl_error);
      [NSOpenGLContext clearCurrentContext];
      [window orderOut:nil];
      if (gl_error || center[1] < 240 || center[0] > 8 || corner[0] < 240 || corner[1] > 8 ||
          edge[2] < 240 || edge[0] > 8 || edge[1] > 8) return 1;
      if (center[3] != expected_alpha || corner[3] != expected_alpha || edge[3] != expected_alpha) {
         fprintf(stderr, "native presentation alpha must be %u\n", expected_alpha); return 1;
      }
      puts(system ? "PASS: automatic CGL, shrink/grow, noncurrent surface update, native drawable pixels" :
                    "PASS: NSOpenGLView, framework calls, CGLFlushDrawable, native drawable pixels");
   }
   dlclose(lib);
   return 0;
}
