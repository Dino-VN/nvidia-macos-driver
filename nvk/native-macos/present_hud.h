#pragma once
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstdint>
#include <cstring>
#include <memory>
#include <mutex>
#include <string>
#include <vector>

namespace nvkbridge_hud {
// Presentation pacing includes application stalls; this is not GPU time.
struct Timing {
   bool initialized{};
   double start{}, previous{};
   uint64_t frames{};
   bool frame(double now,double &fps,double &milliseconds) {
      if (!std::isfinite(now)) return false;
      if (!initialized || now<previous) {
         initialized=true;start=previous=now;frames=0;return false;
      }
      if (now==previous) return false;
      previous=now;frames++;
      double seconds=now-start;
      if (seconds<0.25) return false;
      fps=frames/seconds;milliseconds=seconds*1000.0/frames;
      start=now;frames=0;return true;
   }
};
inline bool enabled() {
   const char *value=getenv("WINE_NVK_HUD");
   if(!value)value=getenv("NVK_HUD");
   return value && (!strcmp(value,"1") || !strcmp(value,"fps") ||
      !strcmp(value,"fps,frametimes") || !strcmp(value,"all"));
}
// A compact bitmap avoids Cocoa callbacks from Wine's presentation thread.
// It is refreshed at most four times per second, then copied by the GPU.
struct Bitmap {
   uint32_t width{},height{};
   uint64_t version{};
   std::vector<uint32_t> pixels;
};
inline const uint8_t *glyph(char c) {
   static constexpr char names[]="0123456789.NVKFPSM/RAE- ";
   static constexpr uint8_t rows[][7]={
      {14,17,19,21,25,17,14},{4,12,4,4,4,4,14},{14,17,1,2,4,8,31},
      {30,1,1,14,1,1,30},{2,6,10,18,31,2,2},{31,16,16,30,1,1,30},
      {14,16,16,30,17,17,14},{31,1,2,4,8,8,8},{14,17,17,14,17,17,14},
      {14,17,17,15,1,1,14},{0,0,0,0,0,12,12},
      {17,25,21,19,17,17,17},{17,17,17,17,17,10,4},{17,18,20,24,20,18,17},
      {31,16,16,30,16,16,16},{30,17,17,30,16,16,16},{15,16,16,14,1,1,30},
      {17,27,21,21,17,17,17},{1,1,2,4,8,16,16},{30,17,17,30,20,18,17},
      {14,17,17,31,17,17,17},{31,16,16,30,16,16,31},{0,0,0,31,0,0,0},{0,0,0,0,0,0,0}
   };
   const char *found=strchr(names,c);return rows[found?found-names:sizeof(names)-2];
}
struct State {
   std::mutex mutex;
   Timing timing;
   std::string first="NVK -- FPS",second="-- MS/FRAME";
   uint64_t version=1;
   std::shared_ptr<const Bitmap> cached;
   void record(double now) {
      std::lock_guard<std::mutex> lock(mutex);double fps=0,ms=0;
      if(!timing.frame(now,fps,ms))return;
      char text[64];snprintf(text,sizeof text,"NVK %.1f FPS",fps);first=text;
      snprintf(text,sizeof text,"%.2f MS/FRAME",ms);second=text;++version;
   }
   std::shared_ptr<const Bitmap> bitmap(uint32_t width,uint32_t height) {
      std::lock_guard<std::mutex> lock(mutex);
      if(width<240 || height<76)return {};
      if(cached && cached->version==version)return cached;
      auto b=std::make_shared<Bitmap>();b->width=224;b->height=44;b->version=version;
      b->pixels.assign(b->width*b->height,0xff101010u);
      auto line=[&](const std::string &text,uint32_t y) {
         uint32_t x=6;
         for(char c:text) {
            if(x+10>b->width-6)break;
            auto rows=glyph(c);
            for(uint32_t gy=0;gy<7;++gy)for(uint32_t gx=0;gx<5;++gx)if(rows[gy]&(16u>>gx))
               for(uint32_t dy=0;dy<2;++dy)for(uint32_t dx=0;dx<2;++dx)
                  b->pixels[(y+gy*2+dy)*b->width+x+gx*2+dx]=0xffffffffu;
            x+=12;
         }
      };
      line(first,4);line(second,24);cached=b;return cached;
   }
};
}
