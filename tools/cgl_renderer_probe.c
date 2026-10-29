/* SPDX-License-Identifier: MIT */
#include <OpenGL/OpenGL.h>
#include <OpenGL/gl3.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

int main(int argc, char **argv)
{
   if (argc > 2 || (argc == 2 && strcmp(argv[1], "--require-zink"))) {
      fprintf(stderr, "usage: %s [--require-zink]\n", argv[0]); return 2;
   }
   CGLRendererInfoObj info = NULL;
   GLint count = 0;
   CGLError error = CGLQueryRendererInfo(~0u, &info, &count);
   if (error != kCGLNoError) { fprintf(stderr, "%s\n", CGLErrorString(error)); return 1; }
   for (GLint i = 0; i < count; ++i) {
      GLint id = 0, accelerated = 0, online = 0;
      CGLDescribeRenderer(info, i, kCGLRPRendererID, &id);
      CGLDescribeRenderer(info, i, kCGLRPAccelerated, &accelerated);
      CGLDescribeRenderer(info, i, kCGLRPOnline, &online);
      printf("renderer[%d]=0x%08x accelerated=%d online=%d%s\n", i, id, accelerated, online,
             (id & 0x00ffff00) == 0x00020400 ? " Apple Software Renderer" : "");
   }
   CGLDestroyRendererInfo(info);
   CGLPixelFormatAttribute attrs[] = {kCGLPFAOpenGLProfile,
      (CGLPixelFormatAttribute)kCGLOGLPVersion_GL4_Core, (CGLPixelFormatAttribute)0};
   CGLPixelFormatObj format = NULL;
   CGLContextObj context = NULL;
   error = CGLChoosePixelFormat(attrs, &format, &count);
   if (error == kCGLNoError && format) error = CGLCreateContext(format, NULL, &context);
   if (format) CGLDestroyPixelFormat(format);
   if (error != kCGLNoError || !context) { fprintf(stderr, "CGL context failed: %s\n", CGLErrorString(error)); return 1; }
   error = CGLSetCurrentContext(context);
   if (error != kCGLNoError) { CGLDestroyContext(context); return 1; }
   const char *renderer = (const char *)glGetString(GL_RENDERER);
   GLint id = 0;
   CGLGetParameter(context, kCGLCPCurrentRendererID, &id);
   printf("selected=0x%08x\nGL_VENDOR=%s\nGL_RENDERER=%s\nGL_VERSION=%s\n", id,
          glGetString(GL_VENDOR), renderer, glGetString(GL_VERSION));
   int status = argc == 2 && (!renderer || !strstr(renderer, "zink") || !strstr(renderer, "NVK"));
   CGLSetCurrentContext(NULL);
   CGLDestroyContext(context);
   return status;
}
