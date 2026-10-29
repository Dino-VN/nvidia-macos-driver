// Compile only this translation unit for x86_64-pc-windows-msvc. NGX returns
// an MSVC C++ interface whose overloaded virtuals must use the same ABI.
// The rest of the probe can use the ordinary LLVM-MinGW toolchain.
#include <nvsdk_ngx_params.h>
// MSVC's floating-point link marker; the executable uses LLVM-MinGW's CRT.
extern "C" { int _fltused=0; }
extern "C" unsigned nvk_ngx_get_i(NVSDK_NGX_Parameter *p,const char *key,int *value) {
   return p->Get(key,value);
}
extern "C" void nvk_ngx_set_i(NVSDK_NGX_Parameter *p,const char *key,int value) { p->Set(key,value); }
extern "C" void nvk_ngx_set_ui(NVSDK_NGX_Parameter *p,const char *key,unsigned value) { p->Set(key,value); }
extern "C" void nvk_ngx_set_f(NVSDK_NGX_Parameter *p,const char *key,float value) { p->Set(key,value); }
extern "C" void nvk_ngx_set_resource(NVSDK_NGX_Parameter *p,const char *key,ID3D12Resource *value) { p->Set(key,value); }
