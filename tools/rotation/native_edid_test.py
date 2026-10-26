#!/usr/bin/env python3
"""Exercise the optional duplicate-EDID repair without changing unique monitors."""
from test_support import FB, method, run

methods = '\n'.join(method(FB, name) for name in [
    'static bool nvrmEdidSerialString(', 'void NVRMNVDAFramebuffer::takeEdid('])
fixture = r'''
#include <cassert>
#include <cstdio>
#include <cstdint>
#include <cstring>
#include <initializer_list>
using NvU8=uint8_t;using NvU16=uint16_t;using NvU32=uint32_t;
#define FBLOG(...) ((void)0)
static void nvu_copy(void *p,const void *q,size_t n){memcpy(p,q,n);}
static void nvrmEdidPanelSizeMm(const NvU8 *,NvU16,NvU16 *,NvU16 *){}
struct nvrm_dpy_rec{NvU32 handle=0,edidSize=0;NvU8 edid[256]{};};
static nvrm_dpy_rec gDpy[4];static int gNDpy=0;
struct NVRMNVDAFramebuffer{
 NvU8 fEdid[256]{};NvU16 fEdidSize=0,fEdidMmW=0,fEdidMmH=0;
 unsigned fDisplay=1,fIndex=0;bool fRotationEnabled=true;
 void takeEdid(const NvU8 *,NvU32);
};
@@METHODS@@
static void make(NvU8 *p,const char *serial){
 memset(p,0,256);p[8]=0xac;p[9]=0x10;p[10]=0x97;p[11]=0xa0;p[12]=1;
 p[54+3]=0xff;memset(p+54+5,' ',13);memcpy(p+54+5,serial,strlen(serial));
 unsigned sum=0;for(unsigned i=0;i<127;++i)sum+=p[i];p[127]=(NvU8)(0-sum);p[128]=0x5a;
}
int main(){
 NvU8 input[256];make(input,"monitor-a");NVRMNVDAFramebuffer a;
 a.takeEdid(input,127);assert(a.fEdidSize==127&&!memcmp(a.fEdid,input,127));
 a.takeEdid(input,256);assert(!memcmp(a.fEdid,input,256));
 gNDpy=2;gDpy[0].handle=1;gDpy[0].edidSize=256;memcpy(gDpy[0].edid,input,256);
 gDpy[1].handle=2;gDpy[1].edidSize=256;make(gDpy[1].edid,"monitor-b");
 NVRMNVDAFramebuffer b;b.fDisplay=2;b.fIndex=1;
 a.takeEdid(input,256);b.takeEdid(gDpy[1].edid,256);
 assert(memcmp(a.fEdid+12,b.fEdid+12,4)!=0);
 for(auto *f:{&a,&b}){
  unsigned sum=0;for(unsigned i=0;i<128;++i)sum+=f->fEdid[i];assert(!(sum&255));
  assert(f->fEdid[128]==0x5a); // extension block untouched
 }
 NVRMNVDAFramebuffer disabled;disabled.fRotationEnabled=false;disabled.takeEdid(input,256);
 assert(!memcmp(disabled.fEdid,input,256));
 // Distinct numeric serials (the four-monitor report) must not be rewritten.
 input[12]=2;a.takeEdid(input,256);assert(!memcmp(a.fEdid,input,256));
 // Missing serial strings cannot invent a stable monitor identity.
 make(input,"");a.takeEdid(input,256);assert(!memcmp(a.fEdid,input,256));
 puts("PASS: production duplicate-EDID repair; unique numeric serials/disabled path untouched, distinct strings, short/missing descriptors, checksum and extension preservation");
}
'''
run(fixture.replace('@@METHODS@@', methods))
