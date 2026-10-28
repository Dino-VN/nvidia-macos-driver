/* SPDX-License-Identifier: MIT */
#include "dino_cgl.h"
#include <OpenGL/gl3.h>
#include <dlfcn.h>
#include <pthread.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static int (*attach)(CGLContextObj, unsigned, unsigned);
static int (*detach)(CGLContextObj);
static int (*resize_ctx)(CGLContextObj, unsigned, unsigned);
static const char *(*last_error)(void);
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s (%s)\n", __LINE__, #x, last_error()); exit(1); } } while (0)

static GLuint shader(GLenum kind, const char *source)
{
   GLuint object = glCreateShader(kind);
   glShaderSource(object, 1, &source, NULL);
   glCompileShader(object);
   GLint compiled = 0;
   glGetShaderiv(object, GL_COMPILE_STATUS, &compiled);
   CHECK(compiled);
   return object;
}

static void texture_upload_test(void)
{
   GLint old_program = 0;
   glGetIntegerv(GL_CURRENT_PROGRAM, &old_program);
   GLuint pbo, texture, cube;
   glGenBuffers(1, &pbo); glBindBuffer(GL_PIXEL_UNPACK_BUFFER, pbo);
   glBufferData(GL_PIXEL_UNPACK_BUFFER, 4096, NULL, GL_STREAM_DRAW);
   unsigned char *mapped = glMapBufferRange(GL_PIXEL_UNPACK_BUFFER, 256, 384,
      GL_MAP_WRITE_BIT | GL_MAP_UNSYNCHRONIZED_BIT);
   CHECK(mapped);
   memset(mapped, 0, 384);
   for (unsigned y = 0; y < 8; ++y)
      for (unsigned x = 0; x < 12; ++x) {
         unsigned char *p = mapped + (y * 12 + x) * 4;
         p[0] = 32 + x; p[1] = 64 + y; p[2] = 128; p[3] = 255;
      }
   CHECK(glUnmapBuffer(GL_PIXEL_UNPACK_BUFFER));
   glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0);
   glGenTextures(1, &texture); glBindTexture(GL_TEXTURE_2D, texture);
   unsigned char pixels[8 * 8 * 4] = {0};
   glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 8, 8, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
   glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
   glBindBuffer(GL_PIXEL_UNPACK_BUFFER, pbo);
   glPixelStorei(GL_UNPACK_ROW_LENGTH, 12);
   glPixelStorei(GL_UNPACK_SKIP_ROWS, 1); glPixelStorei(GL_UNPACK_SKIP_PIXELS, 2);
   glTexSubImage2D(GL_TEXTURE_2D, 0, 2, 1, 4, 3, GL_RGBA, GL_UNSIGNED_BYTE, (void *)256);
   glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0);
   glGetTexImage(GL_TEXTURE_2D, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
   for (unsigned y = 0; y < 8; ++y)
      for (unsigned x = 0; x < 8; ++x) {
         unsigned char *p = pixels + (y * 8 + x) * 4;
         if (x >= 2 && x < 6 && y >= 1 && y < 4)
            CHECK(p[0] == 32 + x && p[1] == 64 + y && p[2] == 128 && p[3] == 255);
         else CHECK(!p[0] && !p[1] && !p[2] && !p[3]);
      }
   glPixelStorei(GL_UNPACK_ROW_LENGTH, 0);
   glPixelStorei(GL_UNPACK_SKIP_ROWS, 0); glPixelStorei(GL_UNPACK_SKIP_PIXELS, 0);

   // A grayscale glyph upload must survive sampling and the alpha discard.
   unsigned char glyph[64] = {0};
   glTexImage2D(GL_TEXTURE_2D, 0, GL_R8, 8, 8, 0, GL_RED, GL_UNSIGNED_BYTE, glyph);
   glBindBuffer(GL_PIXEL_UNPACK_BUFFER, pbo);
   mapped = glMapBufferRange(GL_PIXEL_UNPACK_BUFFER, 256, 64,
      GL_MAP_WRITE_BIT | GL_MAP_UNSYNCHRONIZED_BIT);
   CHECK(mapped); memset(mapped, 255, 64); CHECK(glUnmapBuffer(GL_PIXEL_UNPACK_BUFFER));
   glPixelStorei(GL_UNPACK_ALIGNMENT, 1); glPixelStorei(GL_UNPACK_ROW_LENGTH, 8);
   glPixelStorei(GL_UNPACK_SKIP_ROWS, 1); glPixelStorei(GL_UNPACK_SKIP_PIXELS, 2);
   glTexSubImage2D(GL_TEXTURE_2D, 0, 2, 1, 4, 3, GL_RED, GL_UNSIGNED_BYTE, (void *)256);
   glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0);
   glPixelStorei(GL_UNPACK_ROW_LENGTH, 0);
   glPixelStorei(GL_UNPACK_SKIP_ROWS, 0); glPixelStorei(GL_UNPACK_SKIP_PIXELS, 0);
   GLuint vs = shader(GL_VERTEX_SHADER,
      "#version 410 core\nvoid main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}");
   GLuint fs = shader(GL_FRAGMENT_SHADER,
      "#version 410 core\nuniform sampler2D glyph;out vec4 c;void main(){c=texture(glyph,vec2(3.5/8,2.5/8)).rrrr;if(c.a<0.1)discard;}");
   GLuint program = glCreateProgram();
   glAttachShader(program, vs); glAttachShader(program, fs); glLinkProgram(program);
   GLint linked = 0; glGetProgramiv(program, GL_LINK_STATUS, &linked); CHECK(linked);
   glUseProgram(program); glUniform1i(glGetUniformLocation(program, "glyph"), 0);
   glClearColor(0, 0, 0, 0); glClear(GL_COLOR_BUFFER_BIT);
   glDrawArrays(GL_TRIANGLES, 0, 3);
   unsigned char pixel[4]; glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
   CHECK(pixel[0] == 255 && pixel[1] == 255 && pixel[2] == 255 && pixel[3] == 255);
   glUseProgram(old_program); glDeleteProgram(program); glDeleteShader(fs);

   glGenTextures(1, &cube); glBindTexture(GL_TEXTURE_CUBE_MAP, cube);
   glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MIN_FILTER, GL_NEAREST);
   glTexParameteri(GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAG_FILTER, GL_NEAREST);
   for (unsigned i = 0; i < 6; ++i) {
      memset(pixels, 0, sizeof(pixels));
      glTexImage2D(GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, 0, GL_RGBA8, 8, 8, 0,
         GL_RGBA, GL_UNSIGNED_BYTE, pixels);
   }
   for (unsigned i = 0; i < 6; ++i) {
      for (unsigned p = 0; p < 64; ++p) {
         pixels[p*4] = 32 + i*24; pixels[p*4+1] = 80;
         pixels[p*4+2] = 160; pixels[p*4+3] = 255;
      }
      glBindBuffer(GL_PIXEL_UNPACK_BUFFER, pbo);
      glBufferSubData(GL_PIXEL_UNPACK_BUFFER, 256, sizeof(pixels), pixels);
      glTexSubImage2D(GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, 0, 0, 0, 8, 8,
         GL_RGBA, GL_UNSIGNED_BYTE, (void *)256);
      glBindBuffer(GL_PIXEL_UNPACK_BUFFER, 0);
      memset(pixels, 0, sizeof(pixels));
      glGetTexImage(GL_TEXTURE_CUBE_MAP_POSITIVE_X + i, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
      for (unsigned p = 0; p < 64; ++p)
         CHECK(pixels[p*4] == 32 + i*24 && pixels[p*4+1] == 80 &&
               pixels[p*4+2] == 160 && pixels[p*4+3] == 255);
   }
   fs = shader(GL_FRAGMENT_SHADER,
      "#version 410 core\nuniform samplerCube panorama;uniform vec3 direction;out vec4 c;void main(){c=texture(panorama,direction);}");
   program = glCreateProgram();
   glAttachShader(program, vs); glAttachShader(program, fs); glLinkProgram(program);
   glGetProgramiv(program, GL_LINK_STATUS, &linked); CHECK(linked);
   glUseProgram(program); glUniform1i(glGetUniformLocation(program, "panorama"), 0);
   for (unsigned i = 0; i < 6; ++i) {
      float d[3] = {0}; d[i/2] = i%2 ? -1 : 1;
      glUniform3f(glGetUniformLocation(program, "direction"), d[0], d[1], d[2]);
      glDrawArrays(GL_TRIANGLES, 0, 3);
      glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
      CHECK(pixel[0] == 32 + i*24 && pixel[1] == 80 && pixel[2] == 160 && pixel[3] == 255);
   }
   CHECK(glGetError() == GL_NO_ERROR);
   glUseProgram(old_program); glDeleteProgram(program);
   glDeleteShader(vs); glDeleteShader(fs);
   glDeleteTextures(1, &texture); glDeleteTextures(1, &cube); glDeleteBuffers(1, &pbo);
   glPixelStorei(GL_UNPACK_ALIGNMENT, 4);
   puts("PASS: strided PBO subimages, grayscale glyph alpha and six cube-face uploads/sampling");
}

static CGLContextObj create(void)
{
   CGLPixelFormatAttribute attrs[] = {kCGLPFAOpenGLProfile,
      (CGLPixelFormatAttribute)kCGLOGLPVersion_GL4_Core, 0};
   CGLPixelFormatObj format = NULL; CGLContextObj ctx = NULL; GLint count = 0;
   CHECK(CGLChoosePixelFormat(attrs, &format, &count) == kCGLNoError && format);
   CHECK(CGLCreateContext(format, NULL, &ctx) == kCGLNoError && ctx);
   CGLDestroyPixelFormat(format);
   return ctx;
}

static void texture_buffer_fog_test(void)
{
   GLint old_program = 0; glGetIntegerv(GL_CURRENT_PROGRAM, &old_program);
   GLuint buffer, texture;
   glGenBuffers(1, &buffer); glBindBuffer(GL_TEXTURE_BUFFER, buffer);
   GLint values[16]; for (unsigned i = 0; i < 16; ++i) values[i] = 100 + i;
   glBufferData(GL_TEXTURE_BUFFER, sizeof(values), values, GL_STATIC_DRAW);
   glGenTextures(1, &texture); glBindTexture(GL_TEXTURE_BUFFER, texture);
   glTexBuffer(GL_TEXTURE_BUFFER, GL_R32I, buffer);
   GLuint vs = shader(GL_VERTEX_SHADER,
      "#version 410 core\nuniform isamplerBuffer data;out float v;void main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);v=float(texelFetch(data,3).x)/255;}");
   GLuint fs = shader(GL_FRAGMENT_SHADER,
      "#version 410 core\nuniform isamplerBuffer data;in float v;out vec4 c;void main(){c=vec4(v,float(texelFetch(data,5).x)/255,0,1);}");
   GLuint program = glCreateProgram();
   glAttachShader(program, vs); glAttachShader(program, fs); glLinkProgram(program);
   GLint linked; glGetProgramiv(program, GL_LINK_STATUS, &linked); CHECK(linked);
   glUseProgram(program); glUniform1i(glGetUniformLocation(program, "data"), 0);
   glDrawArrays(GL_TRIANGLES, 0, 3);
   unsigned char pixel[4]; glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
   CHECK(pixel[0] == 103 && pixel[1] == 105 && pixel[3] == 255);
   values[3] = 121; values[5] = 137;
   glBufferSubData(GL_TEXTURE_BUFFER, 0, sizeof(values), values);
   glDrawArrays(GL_TRIANGLES, 0, 3);
   glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
   CHECK(pixel[0] == 121 && pixel[1] == 137);
   glUseProgram(old_program); glDeleteProgram(program);
   CHECK(!glIsProgram(program));
   glDeleteShader(vs); glDeleteShader(fs);
   glDeleteTextures(1, &texture); glDeleteBuffers(1, &buffer);

   // Match Minecraft's 40-byte range containing the last fog/cloud parameter.
   GLfloat fog[10] = {0.8f, 0.2f, 0.4f, 1, 0, 1024, 172.8f, 192, 192, 512};
   glGenBuffers(1, &buffer); glBindBuffer(GL_UNIFORM_BUFFER, buffer);
   glBufferData(GL_UNIFORM_BUFFER, sizeof(fog), fog, GL_STATIC_DRAW);
   glBindBufferRange(GL_UNIFORM_BUFFER, 0, buffer, 0, sizeof(fog));
   vs = shader(GL_VERTEX_SHADER,
      "#version 410 core\nvoid main(){vec2 p[3]=vec2[3](vec2(-1,-1),vec2(3,-1),vec2(-1,3));gl_Position=vec4(p[gl_VertexID],0,1);}");
   fs = shader(GL_FRAGMENT_SHADER,
      "#version 410 core\nlayout(std140) uniform Fog{vec4 color;float envStart;float envEnd;float start;float end;float skyEnd;float cloudsEnd;};uniform float distance;out vec4 c;void main(){float f=clamp((distance-start)/(end-start),0,1);c=vec4(mix(vec3(0,1,0),color.rgb,f),cloudsEnd/512);}");
   program = glCreateProgram();
   glAttachShader(program, vs); glAttachShader(program, fs); glLinkProgram(program);
   glGetProgramiv(program, GL_LINK_STATUS, &linked); CHECK(linked);
   glUniformBlockBinding(program, glGetUniformBlockIndex(program, "Fog"), 0);
   glUseProgram(program);
   glUniform1f(glGetUniformLocation(program, "distance"), 0);
   glDrawArrays(GL_TRIANGLES, 0, 3);
   glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
   CHECK(pixel[0] == 0 && pixel[1] == 255 && pixel[2] == 0 && pixel[3] == 255);
   glUniform1f(glGetUniformLocation(program, "distance"), 200);
   glDrawArrays(GL_TRIANGLES, 0, 3);
   glReadPixels(32, 32, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
   CHECK(pixel[0] == 204 && pixel[1] == 51 && pixel[2] == 102 && pixel[3] == 255);
   glUseProgram(old_program); glDeleteProgram(program);
   glDeleteShader(vs); glDeleteShader(fs); glDeleteBuffers(1, &buffer);
   CHECK(glGetError() == GL_NO_ERROR);
   puts("PASS: vertex/fragment texture-buffer fetches, updates, program deletion and fog UBO range");
}

static void *thread_test(void *ptr)
{
   CGLContextObj ctx = ptr;
   CHECK(CGLSetCurrentContext(ctx) == kCGLNoError);
   CHECK(strstr((const char *)glGetString(GL_RENDERER), "zink"));
   glClearColor(0.0, 0.0, 1.0, 1.0); glClear(GL_COLOR_BUFFER_BIT);
   unsigned char pixel[4];
   glReadPixels(0, 0, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
   CHECK(pixel[2] > 240 && pixel[0] < 8);
   CGLSetCurrentContext(NULL);
   return NULL;
}

int main(int argc, char **argv)
{
   int system = argc == 4 && !strcmp(argv[3], "--system");
   if (argc != 3 && !system) { fprintf(stderr, "usage: %s LIBDINO_CGL ICD_JSON [--system]\n", argv[0]); return 2; }
   CHECK(setenv("VK_DRIVER_FILES", argv[2], 1) == 0);
   void *lib = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
   if (!lib) { fprintf(stderr, "%s\n", dlerror()); return 1; }
   attach = dlsym(lib, "dino_cgl_attach"); detach = dlsym(lib, "dino_cgl_detach");
   resize_ctx = dlsym(lib, "dino_cgl_resize"); last_error = dlsym(lib, "dino_cgl_last_error");
   if (!attach || !detach || !resize_ctx || !last_error) return 1;
   CGLContextObj a = create();
   CHECK(CGLSetCurrentContext(a) == kCGLNoError);
   CHECK(system ? resize_ctx(a, 64, 64) : attach(a, 64, 64));
   CHECK(!attach(a, 64, 64));
   printf("GL_VENDOR=%s\nGL_RENDERER=%s\nGL_VERSION=%s\n",
      glGetString(GL_VENDOR), glGetString(GL_RENDERER), glGetString(GL_VERSION));
   CHECK(strstr((const char *)glGetString(GL_RENDERER), "zink"));
   CHECK(strstr((const char *)glGetString(GL_RENDERER), "NVK"));
   GLuint vs = shader(GL_VERTEX_SHADER, "#version 410 core\nvoid main(){vec2 p[3]=vec2[3](vec2(-.8,-.8),vec2(.8,-.8),vec2(0,.8));gl_Position=vec4(p[gl_VertexID],0,1);}");
   GLuint fs = shader(GL_FRAGMENT_SHADER, "#version 410 core\nuniform vec4 color;out vec4 c;void main(){c=color;}");
   GLuint program = glCreateProgram();
   glAttachShader(program, vs); glAttachShader(program, fs); glLinkProgram(program);
   GLint linked = 0; glGetProgramiv(program, GL_LINK_STATUS, &linked); CHECK(linked);
   glUseProgram(program);
   glUniform4f(glGetUniformLocation(program, "color"), 0.0, 1.0, 0.0, 1.0);
   GLuint vao; glGenVertexArrays(1, &vao); glBindVertexArray(vao);
   glViewport(0, 0, 64, 64);
   glClearColor(1.0, 0.0, 0.0, 1.0); glClear(GL_COLOR_BUFFER_BIT);
   glDrawArrays(GL_TRIANGLES, 0, 3);
   unsigned char pixels[64*64*4];
   glReadPixels(0, 0, 64, 64, GL_RGBA, GL_UNSIGNED_BYTE, pixels);
   CHECK(pixels[(32*64+32)*4+1] > 240 && pixels[0] > 240);
   // Minecraft's staged vertex uploader maps buffers through the framework.
   GLuint upload; glGenBuffers(1, &upload); glBindBuffer(GL_ARRAY_BUFFER, upload);
   glBufferData(GL_ARRAY_BUFFER, 128, NULL, GL_STREAM_DRAW);
   unsigned char *mapped = glMapBufferRange(GL_ARRAY_BUFFER, 32, 64,
      GL_MAP_WRITE_BIT | GL_MAP_UNSYNCHRONIZED_BIT);
   CHECK(mapped);
   memset(mapped, 0x5a, 64); CHECK(glUnmapBuffer(GL_ARRAY_BUFFER));
   unsigned char written[64]; glGetBufferSubData(GL_ARRAY_BUFFER, 32, 64, written);
   for (unsigned i = 0; i < sizeof(written); ++i) CHECK(written[i] == 0x5a);
   mapped = glMapBufferRange(GL_ARRAY_BUFFER, 32, 64,
      GL_MAP_WRITE_BIT | GL_MAP_FLUSH_EXPLICIT_BIT);
   CHECK(mapped); memset(mapped, 0xa5, 64);
   glFlushMappedBufferRange(GL_ARRAY_BUFFER, 0, 64);
   CHECK(glUnmapBuffer(GL_ARRAY_BUFFER));
   mapped = glMapBufferRange(GL_ARRAY_BUFFER, 32, 64, GL_MAP_READ_BIT);
   CHECK(mapped);
   for (unsigned i = 0; i < 64; ++i) CHECK(mapped[i] == 0xa5);
   CHECK(glUnmapBuffer(GL_ARRAY_BUFFER));
   glDeleteBuffers(1, &upload);
   glVertexAttribDivisor(0, 3);
   GLint divisor = 0; glGetVertexAttribiv(0, GL_VERTEX_ATTRIB_ARRAY_DIVISOR, &divisor);
   CHECK(divisor == 3); glVertexAttribDivisor(0, 0);
   CHECK(glGetError() == GL_NO_ERROR);
   puts("PASS: framework buffer mapping, explicit flush, readback and instance divisor");
   texture_buffer_fog_test();
   texture_upload_test();
   GLuint tex; glGenTextures(1, &tex); glBindTexture(GL_TEXTURE_2D, tex);
   unsigned char texels[16] = {0};
   glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, 2, 2, 0, GL_RGBA, GL_UNSIGNED_BYTE, texels);
   GLsync fence = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
   CHECK(fence); glClientWaitSync(fence, GL_SYNC_FLUSH_COMMANDS_BIT, 1000000000); glDeleteSync(fence);
   CHECK(glGetError() == GL_NO_ERROR);
   // CGL sharing must preserve actual Mesa GL objects across the native contexts.
   CGLContextObj shared = NULL;
   CHECK(CGLCreateContext(CGLGetPixelFormat(a), a, &shared) == kCGLNoError && shared);
   CHECK(CGLSetCurrentContext(shared) == kCGLNoError);
   CHECK(system ? resize_ctx(shared, 8, 8) : attach(shared, 8, 8));
   CHECK(glIsTexture(tex));
   glBindTexture(GL_TEXTURE_2D, tex);
   GLint texture_width = 0; glGetTexLevelParameteriv(GL_TEXTURE_2D, 0, GL_TEXTURE_WIDTH, &texture_width);
   CHECK(texture_width == 2);
   CHECK(detach(shared)); CGLSetCurrentContext(a); CGLDestroyContext(shared);
   CHECK(resize_ctx(a, 32, 24)); glViewport(0, 0, 32, 24);
   glClearColor(1.0, 0.0, 0.0, 1.0); glClear(GL_COLOR_BUFFER_BIT);
   CGLContextObj b = create();
   CHECK(CGLSetCurrentContext(b) == kCGLNoError);
   CHECK(system ? resize_ctx(b, 16, 16) : attach(b, 16, 16));
   glClearColor(0.0, 1.0, 0.0, 1.0); glClear(GL_COLOR_BUFFER_BIT);
   CHECK(CGLSetCurrentContext(a) == kCGLNoError);
   unsigned char pixel[4]; glReadPixels(0, 0, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
   CHECK(pixel[0] > 240 && pixel[1] < 8);
   CHECK(CGLSetCurrentContext(b) == kCGLNoError);
   glReadPixels(0, 0, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
   CHECK(pixel[1] > 240 && pixel[0] < 8);
   CGLSetCurrentContext(NULL);
   pthread_t thread; CHECK(pthread_create(&thread, NULL, thread_test, b) == 0);
   CHECK(pthread_join(thread, NULL) == 0);
   CHECK(CGLSetCurrentContext(b) == kCGLNoError); CHECK(detach(b));
   CHECK(!strstr((const char *)glGetString(GL_RENDERER), "zink"));
   CGLSetCurrentContext(a);
   glDeleteTextures(1, &tex); glDeleteVertexArrays(1, &vao);
   glDeleteProgram(program); glDeleteShader(vs); glDeleteShader(fs);
   CHECK(detach(a)); CHECK(!detach(a));
   CHECK(!strstr((const char *)glGetString(GL_RENDERER), "zink"));
   CGLSetCurrentContext(NULL); CGLDestroyContext(a); CGLDestroyContext(b);
   if (system) {
      CGLContextObj automatic = create();
      CHECK(CGLGetContextRetainCount(automatic) == 1);
      CHECK(CGLSetCurrentContext(automatic) == kCGLNoError);
      CHECK(strstr((const char *)glGetString(GL_RENDERER), "zink"));
      glClearColor(0, 1, 0, 1); glClear(GL_COLOR_BUFFER_BIT);
      CGLSetCurrentContext(NULL);
      CHECK(CGLDestroyContext(automatic) == kCGLNoError);
   }
   puts("PASS: native framework GL dispatch, GLSL, pixels, stack/float/pointer arguments, resize, sharing, contexts, threads, detach");
   /* GL adapters must remain loaded until every attached context is detached. */
   dlclose(lib);
   return 0;
}
