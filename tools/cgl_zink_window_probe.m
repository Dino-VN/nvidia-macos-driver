/* SPDX-License-Identifier: MIT */
#import <Cocoa/Cocoa.h>
#include <OpenGL/gl3.h>
#include <dlfcn.h>
#include "dino_cgl.h"
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int draw_frame(CGLContextObj ctx, GLint width, GLint height,
                      const char *(*error)(void))
{
   /* A viewport is application state; it must not shrink the native drawable. */
   glViewport(0, 0, width / 2, height / 2);
   static unsigned frame;
   bool alternate = (++frame % 2) == 0;
   glClearColor(alternate ? 0 : 1, alternate ? 1 : 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT);
   glEnable(GL_SCISSOR_TEST);
   glScissor(width / 4, height / 4, width / 2, height / 2);
   glClearColor(alternate ? 1 : 0, alternate ? 0 : 1, 0, 1); glClear(GL_COLOR_BUFFER_BIT);
   glScissor(width - 8, height - 8, 8, 8);
   glClearColor(0, 0, 1, 1); glClear(GL_COLOR_BUFFER_BIT);
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
   printf("presented_frame=%dx%d\n", width, height);
   return 1;
}

int main(int argc, char **argv)
{
   int system = argc == 4 && !strcmp(argv[3], "--system");
   if (argc != 3 && !system) { fprintf(stderr, "usage: %s LIBDINO_CGL ICD_JSON [--system]\n", argv[0]); return 2; }
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
      NSOpenGLPixelFormatAttribute attrs[] = {NSOpenGLPFAOpenGLProfile,
         NSOpenGLProfileVersion4_1Core, NSOpenGLPFAColorSize, 24,
         NSOpenGLPFAAlphaSize, 8, NSOpenGLPFADoubleBuffer, 0};
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
      if (!system && !attach(ctx, 128, 128)) { fprintf(stderr, "%s\n", error()); return 1; }
      const char *renderer = (const char *)glGetString(GL_RENDERER);
      printf("native_window_renderer=%s\n", renderer ? renderer : "(null)");
      if (!renderer || !strstr(renderer, "zink") || !strstr(renderer, "NVK")) return 1;
      GLint double_buffer = 0; glGetIntegerv(GL_DOUBLEBUFFER, &double_buffer);
      if (!double_buffer) { fprintf(stderr, "Mesa drawable is not double buffered\n"); return 1; }
      if (!draw_frame(ctx, 128, 128, error)) return 1;
      if (!draw_frame(ctx, 128, 128, error) || !draw_frame(ctx, 128, 128, error)) return 1;
      GLint width = 128, height = 128;
      if (system) {
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
      puts(system ? "PASS: automatic CGL, shrink/grow, noncurrent surface update, native drawable pixels" :
                    "PASS: NSOpenGLView, framework calls, CGLFlushDrawable, native drawable pixels");
   }
   dlclose(lib);
   return 0;
}
