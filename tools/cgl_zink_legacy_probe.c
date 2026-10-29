/* SPDX-License-Identifier: MIT */
#include "nvk_cgl.h"
#include <OpenGL/gl.h>
#include <OpenGL/glext.h>
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int (*attach)(CGLContextObj, unsigned, unsigned);
static int (*detach)(CGLContextObj);
static int (*resize_ctx)(CGLContextObj, unsigned, unsigned);
static const char *(*last_error)(void);
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s (%s)\n", __LINE__, #x, last_error ? last_error() : "Apple CGL"); exit(1); } } while (0)

static CGLContextObj create(int core, CGLContextObj share)
{
   CGLPixelFormatAttribute attrs[] = {kCGLPFAOpenGLProfile,
      (CGLPixelFormatAttribute)(core ? kCGLOGLPVersion_GL4_Core : kCGLOGLPVersion_Legacy), 0};
   CGLPixelFormatObj format = NULL; CGLContextObj ctx = NULL; GLint count = 0;
   CHECK(CGLChoosePixelFormat(attrs, &format, &count) == kCGLNoError && format);
   CHECK(CGLCreateContext(format, share, &ctx) == kCGLNoError && ctx);
   CGLDestroyPixelFormat(format);
   return ctx;
}

static void triangle(void)
{
   glBegin(GL_TRIANGLES);
   glVertex2f(-.8f, -.8f); glVertex2f(.8f, -.8f); glVertex2f(0, .8f);
   glEnd();
}

static void expect_pixel(unsigned char red, unsigned char green, unsigned char blue)
{
   unsigned char pixel[4] = {0};
   glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
   CHECK(abs(pixel[0] - red) <= 1 && abs(pixel[1] - green) <= 1 &&
         abs(pixel[2] - blue) <= 1 && pixel[3] == 255);
   CHECK(glGetError() == GL_NO_ERROR);
}

static void fixed_function_test(void)
{
   glViewport(0, 0, 64, 64);
   glMatrixMode(GL_PROJECTION); glLoadIdentity(); glOrtho(-1, 1, -1, 1, -1, 1);
   glMatrixMode(GL_MODELVIEW); glLoadIdentity();
   glClearColor(1, 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT);
   glColor4f(0, 1, 0, 1); triangle(); expect_pixel(0, 255, 0);
   GLuint list = glGenLists(1); CHECK(list);
   glNewList(list, GL_COMPILE); glColor4ub(0, 0, 255, 255); triangle(); glEndList();
   CHECK(glIsList(list));
   glPushMatrix(); glTranslatef(.1f, 0, 0); glCallList(list); glPopMatrix();
   expect_pixel(0, 0, 255);
   glDeleteLists(list, 1); CHECK(!glIsList(list));
   puts("PASS: legacy matrices, immediate triangles and display lists");
}

static GLuint texture_test(void)
{
   GLuint texture; glGenTextures(1, &texture);
   glActiveTextureARB(GL_TEXTURE0_ARB); glBindTexture(GL_TEXTURE_2D, texture);
   const unsigned char texels[4] = {32, 96, 160, 255};
   glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 1, 1, 0, GL_RGBA, GL_UNSIGNED_BYTE, texels);
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
   glEnable(GL_TEXTURE_2D); glTexEnvi(GL_TEXTURE_ENV, GL_TEXTURE_ENV_MODE, GL_REPLACE);
   glBegin(GL_TRIANGLES);
   glMultiTexCoord2fARB(GL_TEXTURE0_ARB, .5f, .5f); glVertex2f(-.8f, -.8f);
   glMultiTexCoord2fARB(GL_TEXTURE0_ARB, .5f, .5f); glVertex2f(.8f, -.8f);
   glMultiTexCoord2fARB(GL_TEXTURE0_ARB, .5f, .5f); glVertex2f(0, .8f);
   glEnd(); expect_pixel(32, 96, 160);
   glDisable(GL_TEXTURE_2D);
   puts("PASS: textures, texture environment and ARB multitexture coordinates");
   return texture;
}

static void buffer_framebuffer_test(void)
{
   GLuint buffer;
   const GLfloat positions[] = {-.8f, -.8f, .8f, -.8f, 0, .8f};
   glGenBuffersARB(1, &buffer); glBindBufferARB(GL_ARRAY_BUFFER_ARB, buffer);
   glBufferDataARB(GL_ARRAY_BUFFER_ARB, sizeof(positions), NULL, GL_DYNAMIC_DRAW_ARB);
   void *mapped = glMapBufferARB(GL_ARRAY_BUFFER_ARB, GL_WRITE_ONLY_ARB); CHECK(mapped);
   memcpy(mapped, positions, sizeof(positions)); CHECK(glUnmapBufferARB(GL_ARRAY_BUFFER_ARB));
   GLfloat copied[6]; glGetBufferSubDataARB(GL_ARRAY_BUFFER_ARB, 0, sizeof(copied), copied);
   CHECK(!memcmp(copied, positions, sizeof(copied)));
   glClientActiveTextureARB(GL_TEXTURE0_ARB);
   glEnableClientState(GL_VERTEX_ARRAY); glVertexPointer(2, GL_FLOAT, 0, 0);
   glColor4ub(255, 128, 64, 255); glDrawArrays(GL_TRIANGLES, 0, 3);
   expect_pixel(255, 128, 64);
   GLuint fbo, renderbuffer;
   glGenFramebuffersEXT(1, &fbo); glBindFramebufferEXT(GL_FRAMEBUFFER_EXT, fbo);
   glGenRenderbuffersEXT(1, &renderbuffer); glBindRenderbufferEXT(GL_RENDERBUFFER_EXT, renderbuffer);
   glRenderbufferStorageEXT(GL_RENDERBUFFER_EXT, GL_RGBA8, 64, 64);
   glFramebufferRenderbufferEXT(GL_FRAMEBUFFER_EXT, GL_COLOR_ATTACHMENT0_EXT,
                               GL_RENDERBUFFER_EXT, renderbuffer);
   CHECK(glCheckFramebufferStatusEXT(GL_FRAMEBUFFER_EXT) == GL_FRAMEBUFFER_COMPLETE_EXT);
   glClearColor(0, 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT);
   glColor4ub(64, 128, 255, 255); glDrawArrays(GL_TRIANGLES, 0, 3);
   expect_pixel(64, 128, 255);
   glBindFramebufferEXT(GL_FRAMEBUFFER_EXT, 0);
   glDeleteFramebuffersEXT(1, &fbo); glDeleteRenderbuffersEXT(1, &renderbuffer);
   glDisableClientState(GL_VERTEX_ARRAY); glBindBufferARB(GL_ARRAY_BUFFER_ARB, 0);
   glDeleteBuffersARB(1, &buffer);
   CHECK(glGetError() == GL_NO_ERROR);
   puts("PASS: ARB mapped VBO/client arrays and EXT framebuffer/renderbuffer aliases");
}

static GLhandleARB shader(GLenum kind, const char *source)
{
   GLhandleARB object = glCreateShaderObjectARB(kind); CHECK(object);
   glShaderSourceARB(object, 1, &source, NULL); glCompileShaderARB(object);
   GLint compiled = 0; glGetObjectParameterivARB(object, GL_OBJECT_COMPILE_STATUS_ARB, &compiled);
   CHECK(compiled);
   return object;
}

static void arb_shader_test(void)
{
   GLhandleARB vs = shader(GL_VERTEX_SHADER_ARB,
      "#version 120\nvoid main(){gl_Position=gl_ModelViewProjectionMatrix*gl_Vertex;}");
   GLhandleARB fs = shader(GL_FRAGMENT_SHADER_ARB,
      "#version 120\nvoid main(){gl_FragColor=vec4(1,0,1,1);}");
   GLhandleARB program = glCreateProgramObjectARB(); CHECK(program);
   glAttachObjectARB(program, vs); glAttachObjectARB(program, fs); glLinkProgramARB(program);
   GLint linked = 0; glGetObjectParameterivARB(program, GL_OBJECT_LINK_STATUS_ARB, &linked); CHECK(linked);
   GLhandleARB attached[2] = {0}; GLsizei count = 0;
   glGetAttachedObjectsARB(program, 2, &count, attached);
   CHECK(count == 2 && ((attached[0] == vs && attached[1] == fs) ||
                        (attached[0] == fs && attached[1] == vs)));
   glUseProgramObjectARB(program); CHECK(glGetHandleARB(GL_PROGRAM_OBJECT_ARB) == program);
   triangle(); expect_pixel(255, 0, 255);
   glUseProgramObjectARB(NULL); glDeleteObjectARB(program); glDeleteObjectARB(vs); glDeleteObjectARB(fs);
   CHECK(glGetError() == GL_NO_ERROR);
   puts("PASS: ARB GLSL objects, object queries, attached pointer handles and deletion");
}

int main(int argc, char **argv)
{
   setvbuf(stdout, NULL, _IOLBF, 0);
   if (argc == 2 && !strcmp(argv[1], "--layout")) {
      for (int core = 0; core <= 1; ++core) {
         CGLContextObj ctx = create(core, NULL);
         CHECK(CGLSetCurrentContext(ctx) == kCGLNoError);
         char *engine = *(void **)ctx;
         printf("profile=%s context=%p engine=%p engine+c6a6=%u dispatch=%p back=%p GL=%s\n",
            core ? "core" : "legacy", (void *)ctx, (void *)engine,
            *(unsigned char *)(engine + 0xc6a6), *(void **)(engine + 0xb2c8),
            *(void **)(engine + 0xb2d0), glGetString(GL_VERSION));
         CGLSetCurrentContext(NULL); CGLDestroyContext(ctx);
      }
      return 0;
   }
   int system = argc == 4 && !strcmp(argv[3], "--system");
   if (argc != 3 && !system) {
      fprintf(stderr, "usage: %s LIBNVK_CGL ICD_JSON [--system] | --layout\n", argv[0]); return 2;
   }
   CHECK(setenv("VK_DRIVER_FILES", argv[2], 1) == 0);
   void *lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
   if (!lib) { fprintf(stderr, "%s\n", dlerror()); return 1; }
   attach = dlsym(lib, "nvk_cgl_attach"); detach = dlsym(lib, "nvk_cgl_detach");
   resize_ctx = dlsym(lib, "nvk_cgl_resize"); last_error = dlsym(lib, "nvk_cgl_last_error");
   CHECK(attach && detach && resize_ctx && last_error);
   CGLContextObj ctx = create(0, NULL); CHECK(CGLSetCurrentContext(ctx) == kCGLNoError);
   CHECK(system ? resize_ctx(ctx, 64, 64) : attach(ctx, 64, 64));
   printf("GL_VENDOR=%s\nGL_RENDERER=%s\nGL_VERSION=%s\n", glGetString(GL_VENDOR),
          glGetString(GL_RENDERER), glGetString(GL_VERSION));
   CHECK(strstr((const char *)glGetString(GL_RENDERER), "zink"));
   CHECK(strstr((const char *)glGetString(GL_RENDERER), "NVK"));
   CHECK(strstr((const char *)glGetString(GL_VERSION), "Compatibility"));
   fixed_function_test(); GLuint texture = texture_test();
   buffer_framebuffer_test(); arb_shader_test();
   CGLContextObj shared = create(0, ctx); CHECK(CGLSetCurrentContext(shared) == kCGLNoError);
   CHECK(system ? resize_ctx(shared, 8, 8) : attach(shared, 8, 8)); CHECK(glIsTexture(texture));
   CHECK(detach(shared)); CGLSetCurrentContext(ctx); CGLDestroyContext(shared);
   glDeleteTextures(1, &texture); CHECK(detach(ctx));
   CGLSetCurrentContext(NULL); CGLDestroyContext(ctx); dlclose(lib);
   puts("PASS: native legacy CGL dispatch and shared compatibility objects");
   return 0;
}
