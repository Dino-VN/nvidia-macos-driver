/* SPDX-License-Identifier: MIT
 * Test the real CGL adapter with a process-local OBS identity. No app bundle is
 * registered and no real OBS preferences or capture sessions are changed.
 */
#import <Cocoa/Cocoa.h>
#import <ScreenCaptureKit/ScreenCaptureKit.h>
#import <CoreVideo/CoreVideo.h>
#import <objc/runtime.h>
#include <OpenGL/gl3.h>
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>

static NSString *(*original_identifier)(id,SEL);
static NSString *obs_identifier(id bundle,SEL selector)
{
   return bundle == [NSBundle mainBundle] ? @"com.obsproject.obs-studio" : original_identifier(bundle,selector);
}
#define REQUIRE(test,message) do { if (!(test)) { fprintf(stderr,"FAIL: %s\n",message); return 1; } } while (0)

int main(int argc,char **argv)
{
   @autoreleasepool {
      REQUIRE(argc==4,"usage: obs_zink_policy_probe libnvk_cgl.dylib nvk_icd.json enabled|disabled");
      BOOL enabled=!strcmp(argv[3],"enabled");
      REQUIRE(enabled || !strcmp(argv[3],"disabled"),"Expected compatibility state");
      Method identifier=class_getInstanceMethod([NSBundle class],@selector(bundleIdentifier));
      original_identifier=(void *)method_getImplementation(identifier);
      method_setImplementation(identifier,(IMP)obs_identifier);
      REQUIRE(dlopen(argv[1],RTLD_NOW|RTLD_LOCAL),"Load tested CGL adapter");
      SCStreamConfiguration *configuration=[SCStreamConfiguration new];
      configuration.pixelFormat=kCVPixelFormatType_64RGBAHalf;
      REQUIRE(configuration.pixelFormat==(enabled ? kCVPixelFormatType_32BGRA : kCVPixelFormatType_64RGBAHalf),
              "OBS capture format follows compatibility policy");
      CGLPixelFormatAttribute attrs[]={kCGLPFAOpenGLProfile,(CGLPixelFormatAttribute)kCGLOGLPVersion_GL4_Core,0};
      CGLPixelFormatObj format=NULL;CGLContextObj context=NULL;GLint count=0;
      REQUIRE(!CGLChoosePixelFormat(attrs,&format,&count) && format,"Choose CGL pixel format");
      REQUIRE(!CGLCreateContext(format,NULL,&context),"Create CGL context");CGLDestroyPixelFormat(format);
      REQUIRE(!CGLSetCurrentContext(context),"Make context current");
      const char *renderer=(const char *)glGetString(GL_RENDERER);
      REQUIRE(renderer,"Read renderer");BOOL zink=strstr(renderer,"zink")!=NULL;
      REQUIRE(zink!=enabled,"OBS renderer follows compatibility policy");
      printf("PASS: OBS compatibility %s; format=%08x renderer=%s\n",enabled ? "enabled" : "disabled",
             (unsigned)configuration.pixelFormat,renderer);
      CGLSetCurrentContext(NULL);CGLDestroyContext(context);
      return 0;
   }
}
