/* SPDX-License-Identifier: MIT */
#define _POSIX_C_SOURCE 200809L
#include "nvk_zink.h"
#include <OpenGL/gl3.h>
#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static void die(const char *message) { fprintf(stderr, "%s\n", message); exit(1); }
static IOSurfaceRef make_surface(unsigned width, unsigned height)
{
   CFMutableDictionaryRef dict = CFDictionaryCreateMutable(NULL, 0,
      &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
   const CFStringRef keys[] = {kIOSurfaceWidth, kIOSurfaceHeight, kIOSurfaceBytesPerElement,
                              kIOSurfaceBytesPerRow, kIOSurfacePixelFormat};
   int values[] = {(int)width, (int)height, 4, (int)width * 4 + 64, 0x42475241};
   for (unsigned i = 0; i < 5; ++i) {
      CFNumberRef n = CFNumberCreate(NULL, kCFNumberIntType, &values[i]);
      CFDictionarySetValue(dict, keys[i], n); CFRelease(n);
   }
   IOSurfaceRef surface = IOSurfaceCreate(dict); CFRelease(dict);
   return surface;
}
#define LOAD(type, name) __typeof__((type)0) name = (type)dlsym(library, #name); if (!name) die(dlerror())
#define GLPROC(ret, name, args) ret (*name) args = (void *)nvk_zink_get_proc_address(#name); if (!name) die(#name " unavailable")

int main(int argc, char **argv)
{
   if (argc < 2 || argc > 4) {
      fprintf(stderr, "usage: %s libnvk_zink.dylib [nvk_icd.json] [output.ppm]\n", argv[0]);
      return 2;
   }
   if (setenv("VK_DRIVER_FILES", argc >= 3 ? argv[2] : "/Library/GPUBundles/nvmtl/nvk_icd.json", 1)) die("setenv failed");
   void *library = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
   if (!library) die(dlerror());
   LOAD(struct nvk_zink_context *(*)(unsigned, unsigned), nvk_zink_create);
   LOAD(struct nvk_zink_context *(*)(unsigned, unsigned, struct nvk_zink_context *, int, int, int), nvk_zink_create_drawable_profile);
   LOAD(int (*)(struct nvk_zink_context *), nvk_zink_make_current);
   LOAD(void (*)(struct nvk_zink_context *), nvk_zink_destroy);
   LOAD(int (*)(struct nvk_zink_context *, unsigned, unsigned), nvk_zink_resize);
   LOAD(nvk_zink_proc (*)(const char *), nvk_zink_get_proc_address);
   LOAD(int (*)(struct nvk_zink_context *, void *, size_t, size_t), nvk_zink_readback);
   LOAD(int (*)(struct nvk_zink_context *, void *, size_t, size_t), nvk_zink_readback_bottom_up);
   LOAD(int (*)(struct nvk_zink_context *, IOSurfaceRef), nvk_zink_present_iosurface);
   LOAD(int (*)(struct nvk_zink_context *, unsigned, IOSurfaceRef), nvk_zink_present_import);
   LOAD(int (*)(struct nvk_zink_context *, unsigned, int, int), nvk_zink_present_begin);
   LOAD(int (*)(struct nvk_zink_context *, unsigned), nvk_zink_present_wait);
   LOAD(void (*)(struct nvk_zink_context *), nvk_zink_present_release);
   int require_gpu = getenv("NVKZINK_REQUIRE_GPU") != NULL;
   int rgbx = getenv("NVKZINK_RGBX") != NULL;
   struct nvk_zink_context *ctx = rgbx ? nvk_zink_create_drawable_profile(64, 64, NULL, 0, 0, 0) :
                                        nvk_zink_create(64, 64);
   if (!ctx || !nvk_zink_make_current(ctx)) die("Zink 4.1 context creation failed");
   GLPROC(const GLubyte *, glGetString, (GLenum));
   GLPROC(GLenum, glGetError, (void));
   GLPROC(void, glViewport, (GLint, GLint, GLsizei, GLsizei));
   GLPROC(void, glClearColor, (GLfloat, GLfloat, GLfloat, GLfloat));
   GLPROC(void, glClear, (GLbitfield));
   GLPROC(void, glReadPixels, (GLint, GLint, GLsizei, GLsizei, GLenum, GLenum, void *));
   GLPROC(void, glGetIntegerv, (GLenum, GLint *));
   GLPROC(void, glPixelStorei, (GLenum, GLint));
   GLPROC(void, glGenBuffers, (GLsizei, GLuint *));
   GLPROC(void, glBindBuffer, (GLenum, GLuint));
   GLPROC(void, glBufferData, (GLenum, GLsizeiptr, const void *, GLenum));
   GLPROC(void, glDeleteBuffers, (GLsizei, const GLuint *));
   GLPROC(void, glGenFramebuffers, (GLsizei, GLuint *));
   GLPROC(void, glBindFramebuffer, (GLenum, GLuint));
   GLPROC(void, glDeleteFramebuffers, (GLsizei, const GLuint *));
   GLPROC(GLuint, glCreateShader, (GLenum));
   GLPROC(void, glShaderSource, (GLuint, GLsizei, const GLchar *const *, const GLint *));
   GLPROC(void, glCompileShader, (GLuint));
   GLPROC(void, glGetShaderiv, (GLuint, GLenum, GLint *));
   GLPROC(void, glGetShaderInfoLog, (GLuint, GLsizei, GLsizei *, GLchar *));
   GLPROC(GLuint, glCreateProgram, (void));
   GLPROC(void, glAttachShader, (GLuint, GLuint));
   GLPROC(void, glLinkProgram, (GLuint));
   GLPROC(void, glGetProgramiv, (GLuint, GLenum, GLint *));
   GLPROC(void, glGetProgramInfoLog, (GLuint, GLsizei, GLsizei *, GLchar *));
   GLPROC(void, glUseProgram, (GLuint));
   GLPROC(void, glGenVertexArrays, (GLsizei, GLuint *));
   GLPROC(void, glBindVertexArray, (GLuint));
   GLPROC(void, glDrawArrays, (GLenum, GLint, GLsizei));
   GLPROC(void, glDeleteVertexArrays, (GLsizei, const GLuint *));
   GLPROC(void, glDeleteShader, (GLuint));
   GLPROC(void, glDeleteProgram, (GLuint));
   const char *renderer = (const char *)glGetString(GL_RENDERER);
   printf("GL_VENDOR=%s\nGL_RENDERER=%s\nGL_VERSION=%s\n", glGetString(GL_VENDOR), renderer, glGetString(GL_VERSION));
   if (!renderer || !strstr(renderer, "zink") || !strstr(renderer, "NVK")) die("Renderer is not Zink on NVK");
   const char *sources[] = {
      "#version 410 core\nconst vec2 p[3]=vec2[3](vec2(-.8,-.8),vec2(.8,-.8),vec2(0,.8)); void main(){gl_Position=vec4(p[gl_VertexID],0,1);}",
      rgbx ? "#version 410 core\nout vec4 color; void main(){color=vec4(0,1,0,0);}" :
             "#version 410 core\nout vec4 color; void main(){color=vec4(0,1,0,1);}"
   };
   GLuint shaders[2], program = glCreateProgram(), vao;
   for (int i = 0; i < 2; ++i) {
      shaders[i] = glCreateShader(i ? GL_FRAGMENT_SHADER : GL_VERTEX_SHADER);
      glShaderSource(shaders[i], 1, &sources[i], NULL);
      glCompileShader(shaders[i]);
      GLint ok; glGetShaderiv(shaders[i], GL_COMPILE_STATUS, &ok);
      if (!ok) { char log[4096]; glGetShaderInfoLog(shaders[i], sizeof(log), NULL, log); die(log); }
      glAttachShader(program, shaders[i]);
   }
   glLinkProgram(program);
   GLint ok; glGetProgramiv(program, GL_LINK_STATUS, &ok);
   if (!ok) { char log[4096]; glGetProgramInfoLog(program, sizeof(log), NULL, log); die(log); }
   glUseProgram(program);
   glGenVertexArrays(1, &vao); glBindVertexArray(vao);
   unsigned char pixels[64 * 64 * 4];
   for (unsigned pass = 0; pass < 2; ++pass) {
      unsigned width = pass ? 32 : 64, height = pass ? 24 : 64;
      if (!nvk_zink_resize(ctx, width, height)) die("resize failed");
      glViewport(0, 0, width, height);
      glClearColor(1, 0, 0, rgbx ? 0 : 1); glClear(GL_COLOR_BUFFER_BIT);
      glDrawArrays(GL_TRIANGLES, 0, 3);
      if (glGetError() != GL_NO_ERROR) die("OpenGL error after draw");
      GLuint pbo, fb;
      glGenBuffers(1, &pbo); glBindBuffer(GL_PIXEL_PACK_BUFFER, pbo);
      glBufferData(GL_PIXEL_PACK_BUFFER, 32, NULL, GL_STREAM_READ);
      glGenFramebuffers(1, &fb); glBindFramebuffer(GL_READ_FRAMEBUFFER, fb);
      glPixelStorei(GL_PACK_ALIGNMENT, 8); glPixelStorei(GL_PACK_ROW_LENGTH, width + 4);
      glPixelStorei(GL_PACK_SKIP_ROWS, 1); glPixelStorei(GL_PACK_SKIP_PIXELS, 2);
      if (nvk_zink_readback(ctx, pixels, 1, width * 4)) die("short output buffer accepted");
      if (!nvk_zink_readback(ctx, pixels, sizeof(pixels), width * 4)) die("readback failed");
      if (rgbx)
         for (unsigned i = 3; i < width * height * 4; i += 4)
            if (pixels[i] != 255) die("RGBX framebuffer must read opaque alpha");
      unsigned char bottom_rows[64 * (64 * 4 + 8)];
      size_t bottom_rows_stride = width * 4 + 8;
      memset(bottom_rows, 0xa5, sizeof(bottom_rows));
      if (nvk_zink_readback_bottom_up(ctx, bottom_rows, 1, bottom_rows_stride)) die("short bottom-up buffer accepted");
      if (nvk_zink_readback_bottom_up(ctx, bottom_rows, sizeof(bottom_rows), bottom_rows_stride + 1)) die("unaligned bottom-up stride accepted");
      if (!nvk_zink_readback_bottom_up(ctx, bottom_rows, sizeof(bottom_rows), bottom_rows_stride)) die("bottom-up readback failed");
      for (unsigned y = 0; y < height; ++y) {
         if (memcmp(bottom_rows + y * bottom_rows_stride, pixels + (height - 1 - y) * width * 4, width * 4))
            die("bottom-up image orientation changed");
         for (unsigned x = width * 4; x < bottom_rows_stride; ++x)
            if (bottom_rows[y * bottom_rows_stride + x] != 0xa5) die("bottom-up row padding changed");
      }
      GLint state;
      glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING, &state); if ((GLuint)state != pbo) die("pack buffer binding changed");
      glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &state); if ((GLuint)state != fb) die("read framebuffer binding changed");
      glGetIntegerv(GL_PACK_ALIGNMENT, &state); if (state != 8) die("pack alignment changed");
      glGetIntegerv(GL_PACK_ROW_LENGTH, &state); if ((unsigned)state != width + 4) die("pack row length changed");
      glGetIntegerv(GL_PACK_SKIP_ROWS, &state); if (state != 1) die("pack skip rows changed");
      glGetIntegerv(GL_PACK_SKIP_PIXELS, &state); if (state != 2) die("pack skip pixels changed");
      glBindFramebuffer(GL_READ_FRAMEBUFFER, 0); glDeleteFramebuffers(1, &fb);
      glBindBuffer(GL_PIXEL_PACK_BUFFER, 0); glDeleteBuffers(1, &pbo);
      glPixelStorei(GL_PACK_ALIGNMENT, 4); glPixelStorei(GL_PACK_ROW_LENGTH, 0);
      glPixelStorei(GL_PACK_SKIP_ROWS, 0); glPixelStorei(GL_PACK_SKIP_PIXELS, 0);
      unsigned char *center = pixels + ((height / 2) * width + width / 2) * 4;
      if (center[1] < 250 || center[0] > 5 || pixels[0] < 250 || pixels[1] > 5) {
         fprintf(stderr, "center=%u,%u,%u,%u corner=%u,%u,%u,%u\n", center[0], center[1], center[2], center[3],
                 pixels[0], pixels[1], pixels[2], pixels[3]);
         unsigned char glpixel[4] = {0};
         glReadPixels(width / 2, height / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, glpixel);
         fprintf(stderr, "glReadPixels center=%u,%u,%u,%u GL error=%x\n", glpixel[0], glpixel[1], glpixel[2], glpixel[3], glGetError());
         die("triangle pixel check failed");
      }
      unsigned char *top = pixels + ((height / 4) * width + width / 4) * 4;
      unsigned char *bottom = pixels + ((height * 3 / 4) * width + width / 4) * 4;
      if (top[0] < 250 || bottom[1] < 250) die("readback row orientation failed");
      IOSurfaceRef surface = make_surface(width, height);
      if (!surface) die("IOSurfaceCreate failed");
      if (IOSurfaceLock(surface, 0, NULL)) die("IOSurfaceLock failed");
      memset(IOSurfaceGetBaseAddress(surface), 0xa5, IOSurfaceGetAllocSize(surface));
      if (IOSurfaceUnlock(surface, 0, NULL)) die("IOSurfaceUnlock failed");
      if (!nvk_zink_present_iosurface(ctx, surface)) die("IOSurface present failed");
      if (IOSurfaceLock(surface, kIOSurfaceLockReadOnly, NULL)) die("IOSurface read lock failed");
      unsigned char *base = IOSurfaceGetBaseAddress(surface);
      size_t pitch = IOSurfaceGetBytesPerRow(surface);
      for (unsigned y = 0; y < height; ++y) {
         for (unsigned x = 0; x < width; ++x) {
            unsigned char *dst = base + y * pitch + x * 4, *src = pixels + (y * width + x) * 4;
            if (dst[0] != src[2] || dst[1] != src[1] || dst[2] != src[0] || dst[3] != src[3]) die("IOSurface BGRA mismatch");
         }
         if (base[y * pitch + width * 4] != 0xa5) die("IOSurface row padding overwritten");
      }
      if (IOSurfaceUnlock(surface, kIOSurfaceLockReadOnly, NULL)) die("IOSurface read unlock failed");
      if (require_gpu) {
         if (nvk_zink_present_import(ctx, 2, surface)) die("invalid GPU slot accepted");
         glGenFramebuffers(1, &fb); glBindFramebuffer(GL_READ_FRAMEBUFFER, fb);
         glGenBuffers(1, &pbo); glBindBuffer(GL_PIXEL_PACK_BUFFER, pbo);
         glPixelStorei(GL_PACK_SKIP_ROWS, 3);
         for (unsigned slot = 0; slot < 2; ++slot) {
            if (!nvk_zink_present_import(ctx, slot, surface)) die("GPU IOSurface import unavailable");
            if (IOSurfaceLock(surface, 0, NULL)) die("GPU IOSurface lock failed");
            if (!nvk_zink_present_begin(ctx, slot, slot != 0, 0)) die("GPU copy submission failed");
            if (nvk_zink_present_begin(ctx, slot, 0, 0)) die("pending GPU slot reused");
            if (!nvk_zink_present_wait(ctx, slot)) die("GPU copy wait failed");
            if (IOSurfaceUnlock(surface, 0, NULL)) die("GPU IOSurface unlock failed");
            if (IOSurfaceLock(surface, kIOSurfaceLockReadOnly, NULL)) die("GPU IOSurface read lock failed");
            base = IOSurfaceGetBaseAddress(surface);
            for (unsigned y = 0; y < height; ++y) {
               for (unsigned x = 0; x < width; ++x) {
                  unsigned sy = slot ? height - 1 - y : y;
                  unsigned char *dst = base + y * pitch + x * 4, *src = pixels + (sy * width + x) * 4;
                  if (dst[0] != src[2] || dst[1] != src[1] || dst[2] != src[0] || dst[3] != src[3])
                     die("GPU IOSurface color/orientation mismatch");
               }
               if (base[y * pitch + width * 4] != 0xa5) die("GPU IOSurface padding overwritten");
            }
            if (IOSurfaceUnlock(surface, kIOSurfaceLockReadOnly, NULL)) die("GPU IOSurface read unlock failed");
         }
         glGetIntegerv(GL_READ_FRAMEBUFFER_BINDING, &state); if ((GLuint)state != fb) die("GPU copy changed read FBO");
         glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING, &state); if ((GLuint)state != pbo) die("GPU copy changed pack PBO");
         glGetIntegerv(GL_PACK_SKIP_ROWS, &state); if (state != 3) die("GPU copy changed pack state");
         glBindFramebuffer(GL_READ_FRAMEBUFFER, 0); glDeleteFramebuffers(1, &fb);
         glBindBuffer(GL_PIXEL_PACK_BUFFER, 0); glDeleteBuffers(1, &pbo);
         glPixelStorei(GL_PACK_SKIP_ROWS, 0);
         nvk_zink_present_release(ctx);
         if (glGetError()) die("GPU presentation left GL error");
         puts("PASS: GPU copies, both slots/orientations, padding, pending reuse rejection, FBO/PBO/pack state");
      }
      CFRelease(surface);
      printf("PASS: GLSL triangle, resize, readback orientation/state, padded BGRA IOSurface, %ux%u\n", width, height);
      if (!pass && argc == 4) {
         FILE *f = fopen(argv[3], "wb"); if (!f) die("cannot open PPM output");
         fprintf(f, "P6\n64 64\n255\n");
         for (unsigned i = 0; i < 64 * 64; ++i)
            if (fwrite(pixels + i * 4, 1, 3, f) != 3) die("PPM write failed");
         if (fclose(f)) die("PPM close failed");
      }
   }
   glDeleteVertexArrays(1, &vao); glDeleteProgram(program);
   for (unsigned i = 0; i < 2; ++i) glDeleteShader(shaders[i]);
   if (!nvk_zink_make_current(NULL)) die("release failed");
   if (nvk_zink_readback(ctx, pixels, sizeof(pixels), 32 * 4)) die("readback without current context accepted");
   nvk_zink_destroy(ctx);
   dlclose(library);
   return 0;
}
