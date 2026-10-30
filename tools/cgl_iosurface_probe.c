/* SPDX-License-Identifier: MIT
 * Exercise the texture import API used by OBS independently of screen capture.
 */
#include <OpenGL/OpenGL.h>
#include <OpenGL/CGLIOSurface.h>
#include <OpenGL/gl3.h>
#include <IOSurface/IOSurface.h>
#include <CoreVideo/CoreVideo.h>
#include <dlfcn.h>
#include <math.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define REQUIRE(test, message) do { if (!(test)) { fprintf(stderr,"FAIL: %s\n",message); exit(1); } } while (0)

static void import_pixels(CGLContextObj context, int half)
{
   const int width=32,height=24,element=half ? 8 : 4;
   int row=(int)IOSurfaceAlignProperty(kIOSurfaceBytesPerRow,(size_t)width*element);
   int bytes=(int)IOSurfaceAlignProperty(kIOSurfaceAllocSize,(size_t)row*height);
   int format=half ? kCVPixelFormatType_64RGBAHalf : kCVPixelFormatType_32BGRA;
   const CFStringRef keys[]={kIOSurfaceWidth,kIOSurfaceHeight,kIOSurfaceBytesPerElement,
      kIOSurfaceBytesPerRow,kIOSurfaceAllocSize,kIOSurfacePixelFormat};
   int values[]={width,height,element,row,bytes,format}; CFNumberRef numbers[6];
   for (unsigned i=0;i<6;++i) numbers[i]=CFNumberCreate(NULL,kCFNumberIntType,&values[i]);
   CFDictionaryRef properties=CFDictionaryCreate(NULL,(const void **)keys,(const void **)numbers,6,
      &kCFTypeDictionaryKeyCallBacks,&kCFTypeDictionaryValueCallBacks);
   IOSurfaceRef surface=IOSurfaceCreate(properties); CFRelease(properties);
   for (unsigned i=0;i<6;++i) CFRelease(numbers[i]);
   REQUIRE(surface,"Create diagnostic IOSurface");
   REQUIRE(!IOSurfaceLock(surface,0,NULL),"Lock diagnostic IOSurface");
   unsigned char *base=IOSurfaceGetBaseAddress(surface); REQUIRE(base,"Map diagnostic IOSurface");
   const uint16_t fp16[]={0x3800,0x3400,0x3000,0x3c00};
   const unsigned char bgra[]={32,64,128,255};
   for (int y=0;y<height;++y) for (int x=0;x<width;++x)
      memcpy(base+(size_t)y*row+x*element,half ? (const void *)fp16 : (const void *)bgra,element);
   REQUIRE(!IOSurfaceUnlock(surface,0,NULL),"Unlock diagnostic IOSurface");
   GLuint texture=0,fbo=0; glGenTextures(1,&texture); glBindTexture(GL_TEXTURE_RECTANGLE,texture);
   CGLError result=CGLTexImageIOSurface2D(context,GL_TEXTURE_RECTANGLE,half ? GL_RGBA16F : GL_RGBA8,
      width,height,half ? GL_RGBA : GL_BGRA,half ? GL_HALF_FLOAT : GL_UNSIGNED_INT_8_8_8_8_REV,surface,0);
   printf("%s import: CGL error %d (%s)\n",half ? "RGBA16F" : "BGRA8",result,CGLErrorString(result));
   REQUIRE(result==kCGLNoError,"CGLTexImageIOSurface2D must import capture textures");
   glGenFramebuffers(1,&fbo); glBindFramebuffer(GL_FRAMEBUFFER,fbo);
   glFramebufferTexture2D(GL_FRAMEBUFFER,GL_COLOR_ATTACHMENT0,GL_TEXTURE_RECTANGLE,texture,0);
   REQUIRE(glCheckFramebufferStatus(GL_FRAMEBUFFER)==GL_FRAMEBUFFER_COMPLETE,"Imported texture framebuffer");
   glReadBuffer(GL_COLOR_ATTACHMENT0); float pixel[4]; glReadPixels(3,5,1,1,GL_RGBA,GL_FLOAT,pixel);
   REQUIRE(glGetError()==GL_NO_ERROR,"Read imported texture");
   const float expected_half[]={0.5f,0.25f,0.125f,1.0f},expected_bgra[]={128/255.0f,64/255.0f,32/255.0f,1.0f};
   const float *expected=half ? expected_half : expected_bgra;
   for (unsigned i=0;i<4;++i) REQUIRE(fabsf(pixel[i]-expected[i])<0.005f,"Imported pixel values");
   printf("PASS: %s IOSurface import and pixels\n",half ? "RGBA16F" : "BGRA8");
   glBindFramebuffer(GL_FRAMEBUFFER,0);glDeleteFramebuffers(1,&fbo);glDeleteTextures(1,&texture);CFRelease(surface);
}

int main(int argc,char **argv)
{
   REQUIRE(argc>=2,"usage: cgl_iosurface_probe libnvk_cgl.dylib [nvk_icd.json] [--require-apple]");
   setvbuf(stdout,NULL,_IOLBF,0);
   REQUIRE(dlopen(argv[1],RTLD_NOW|RTLD_LOCAL),"Load tested CGL bridge");
   CGLPixelFormatAttribute attributes[]={kCGLPFAOpenGLProfile,(CGLPixelFormatAttribute)kCGLOGLPVersion_GL4_Core,0};
   CGLPixelFormatObj format=NULL;CGLContextObj context=NULL;GLint count=0;
   REQUIRE(!CGLChoosePixelFormat(attributes,&format,&count) && format,"Choose CGL pixel format");
   REQUIRE(!CGLCreateContext(format,NULL,&context),"Create CGL context");CGLDestroyPixelFormat(format);
   REQUIRE(!CGLSetCurrentContext(context),"Make CGL context current");
   const char *renderer=(const char *)glGetString(GL_RENDERER);REQUIRE(renderer,"Read GL renderer");
   printf("Renderer: %s\n",renderer);
   for (int i=2;i<argc;++i) if (!strcmp(argv[i],"--require-apple"))
      REQUIRE(!strstr(renderer,"zink"),"Opt-out must use Apple's complete GL context");
   import_pixels(context,0);import_pixels(context,1);
   REQUIRE(!CGLSetCurrentContext(NULL),"Clear context");CGLDestroyContext(context);
   return 0;
}
