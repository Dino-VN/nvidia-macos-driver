#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#define NGX_SNIPPET_BUILD 1
#include <nvsdk_ngx.h>
#include <initializer_list>
#include <cstdio>
#include <cstring>
#include <stdexcept>
using Microsoft::WRL::ComPtr;
extern "C" unsigned nvk_ngx_get_i(NVSDK_NGX_Parameter *,const char *,int *);
void nvk_ngx_evaluate(HMODULE,ID3D12Device *,NVSDK_NGX_Parameter *);
static void check(HRESULT hr,const char *where) {
   if (FAILED(hr)) { char message[160];snprintf(message,sizeof message,"%s: 0x%08lx",where,(unsigned long)hr);throw std::runtime_error(message); }
}
template<class T> static T symbol(HMODULE library,const char *name) {
   auto value=GetProcAddress(library,name);
   if (!value) throw std::runtime_error(name);
   return reinterpret_cast<T>(value);
}
static LONG WINAPI fatal(EXCEPTION_POINTERS *exception) {
   fprintf(stderr,"PROBE EXCEPTION 0x%08lx\n",exception->ExceptionRecord->ExceptionCode);return EXCEPTION_EXECUTE_HANDLER;
}
static void NVSDK_CONV ngx_log(const char *message,NVSDK_NGX_Logging_Level,NVSDK_NGX_Feature) {
   printf("NGX_LOG %s\n",message);
}
int main(int argc,char **argv) {
   setvbuf(stdout,nullptr,_IONBF,0);SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOGPFAULTERRORBOX);SetUnhandledExceptionFilter(fatal);
   try {
      HMODULE nvapi=LoadLibraryW(L"nvapi64.dll");
      if (!nvapi) {printf("NVAPI_LOAD_FAILED %lu\n",GetLastError());return 2;}
      auto query=symbol<void *(__cdecl *)(unsigned)>(nvapi,"nvapi_QueryInterface");
      auto initialize=reinterpret_cast<int (__cdecl *)()>(query(0x0150e828));
      if (!initialize) throw std::runtime_error("NvAPI_Initialize is missing");
      int status=initialize();printf("NVAPI_INITIALIZE %d\n",status);
      if (status) return 2;
      ComPtr<IDXGIFactory4> factory;check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"DXGI factory");
      ComPtr<IDXGIAdapter1> adapter;check(factory->EnumAdapters1(0,&adapter),"adapter");
      DXGI_ADAPTER_DESC1 props{};check(adapter->GetDesc1(&props),"adapter properties");
      char name[512]{};WideCharToMultiByte(CP_UTF8,0,props.Description,-1,name,sizeof name,nullptr,nullptr);
      printf("ADAPTER %s vendor=0x%x device=0x%x\n",name,props.VendorId,props.DeviceId);
      if (props.VendorId!=0x10de) throw std::runtime_error("Real NVIDIA vendor identification is required");
      HMODULE core=LoadLibraryW(L"_nvngx.dll");
      if(core) {
         wchar_t directory[32768]{};GetCurrentDirectoryW(32768,directory);const wchar_t *paths[]={directory};
         NVSDK_NGX_FeatureCommonInfo common{};common.PathListInfo={paths,1};
         common.LoggingInfo.LoggingCallback=ngx_log;common.LoggingInfo.MinimumLoggingLevel=NVSDK_NGX_LOGGING_LEVEL_VERBOSE;
         NVSDK_NGX_FeatureDiscoveryInfo discovery{};discovery.SDKVersion=NVSDK_NGX_Version_API;
         discovery.FeatureID=NVSDK_NGX_Feature_SuperSampling;discovery.ApplicationDataPath=L"C:\\ngx-probe";discovery.FeatureInfo=&common;
         discovery.Identifier.IdentifierType=NVSDK_NGX_Application_Identifier_Type_Project_Id;
         discovery.Identifier.v.ProjectDesc={"8a5cd3fa-5c17-4d8d-bb4e-d2cbd8cf8fe1",NVSDK_NGX_ENGINE_TYPE_CUSTOM,"1.0"};
         NVSDK_NGX_FeatureRequirement requirements{};
         auto queried=symbol<decltype(&NVSDK_NGX_D3D12_GetFeatureRequirements)>(core,"NVSDK_NGX_D3D12_GetFeatureRequirements")(adapter.Get(),&discovery,&requirements);
         printf("NGX_REQUIREMENTS result=0x%08x supported=0x%08x architecture=0x%x os=%s\n",queried,requirements.FeatureSupported,requirements.MinHWArchitecture,requirements.MinOSVersion);
      }
      ComPtr<ID3D12Device> device;check(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)),"D3D12 device");
      HMODULE ngx=LoadLibraryW(L"nvngx.dll");
      if (!ngx) {printf("NGX_LOAD_FAILED %lu\n",GetLastError());return 2;}
      for (const wchar_t *dll:{L"nvapi64.dll",L"nvngx.dll",L"_nvngx.dll",L"d3d12.dll",L"d3d12core.dll"}) {
         char path[32768]{};HMODULE module=GetModuleHandleW(dll);
         if(module){GetModuleFileNameA(module,path,sizeof path);printf("LOADED %s\n",path);}
      }
      auto init=symbol<decltype(&NVSDK_NGX_D3D12_Init)>(ngx,"NVSDK_NGX_D3D12_Init");
      // Diagnostic application ID only. Report an identity rejection instead
      // of impersonating a registered game or forcing a capability result.
      NVSDK_NGX_Result result;
      bool project=false,evaluate=false;
      for(int i=1;i<argc;++i){if(!strcmp(argv[i],"--project"))project=true;else if(!strcmp(argv[i],"--evaluate"))evaluate=true;else throw std::runtime_error("Unknown argument");}
      if(project) {
         // NVIDIA's Wine DLL exposes the core entry point, with the version
         // before common info (as in the standalone NGX core interface).
         using ProjectInit=NVSDK_NGX_Result (NVSDK_CONV *)(const char *,NVSDK_NGX_EngineType,const char *,const wchar_t *,ID3D12Device *,NVSDK_NGX_Version,const NVSDK_NGX_FeatureCommonInfo *);
         wchar_t directory[32768]{};GetCurrentDirectoryW(32768,directory);const wchar_t *paths[]={directory};
         NVSDK_NGX_FeatureCommonInfo common{};common.PathListInfo.Path=paths;common.PathListInfo.Length=1;
         common.LoggingInfo.LoggingCallback=ngx_log;common.LoggingInfo.MinimumLoggingLevel=NVSDK_NGX_LOGGING_LEVEL_VERBOSE;
         result=symbol<ProjectInit>(ngx,"NVSDK_NGX_D3D12_Init_ProjectID")("8a5cd3fa-5c17-4d8d-bb4e-d2cbd8cf8fe1",NVSDK_NGX_ENGINE_TYPE_CUSTOM,"1.0",L"C:\\ngx-probe",device.Get(),NVSDK_NGX_Version_API,&common);
      } else result=init(0,L"C:\\ngx-probe",device.Get(),NVSDK_NGX_Version_API);
      printf("NGX_D3D12_INITIALIZE 0x%08x\n",result);
      if (result!=NVSDK_NGX_Result_Success) return 2;
      auto caps=symbol<decltype(&NVSDK_NGX_D3D12_GetCapabilityParameters)>(ngx,"NVSDK_NGX_D3D12_GetCapabilityParameters");
      NVSDK_NGX_Parameter *parameters=nullptr;result=caps(&parameters);
      printf("NGX_CAPABILITY_QUERY 0x%08x\n",result);
      if (result!=NVSDK_NGX_Result_Success || !parameters) return 2;
      int available=0,needsDriver=0;
      auto availableResult=nvk_ngx_get_i(parameters,NVSDK_NGX_Parameter_SuperSampling_Available,&available);
      auto driverResult=nvk_ngx_get_i(parameters,NVSDK_NGX_Parameter_SuperSampling_NeedsUpdatedDriver,&needsDriver);
      printf("DLSS_AVAILABLE value=%d query=0x%08x needs_driver=%d query=0x%08x\n",available,availableResult,needsDriver,driverResult);
      for(const char *key:{NVSDK_NGX_Parameter_SuperSampling_FeatureInitResult,NVSDK_NGX_Parameter_SuperSampling_MinDriverVersionMajor,NVSDK_NGX_Parameter_SuperSampling_MinDriverVersionMinor}) {
         int value=0;auto status=nvk_ngx_get_i(parameters,key,&value);printf("NGX_PARAMETER %s value=0x%08x query=0x%08x\n",key,(unsigned)value,status);
      }
      if(evaluate&&availableResult==NVSDK_NGX_Result_Success&&available&&!needsDriver)nvk_ngx_evaluate(ngx,device.Get(),parameters);
      auto destroy=symbol<decltype(&NVSDK_NGX_D3D12_DestroyParameters)>(ngx,"NVSDK_NGX_D3D12_DestroyParameters");
      destroy(parameters);symbol<decltype(&NVSDK_NGX_D3D12_Shutdown1)>(ngx,"NVSDK_NGX_D3D12_Shutdown1")(device.Get());
      return availableResult==NVSDK_NGX_Result_Success && available && !needsDriver ? 0 : 2;
   } catch (const std::exception &error) {fprintf(stderr,"PROBE FAIL: %s\n",error.what());return 1;}
}
