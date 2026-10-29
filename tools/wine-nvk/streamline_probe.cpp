// Exercise the game's unmodified public Streamline API outside the game.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#include <sl.h>
#include <cstdio>
#include <stdexcept>
using Microsoft::WRL::ComPtr;
static void check(HRESULT hr,const char *where){if(FAILED(hr))throw std::runtime_error(where);}
template<class T>static T symbol(HMODULE dll,const char *name){auto p=GetProcAddress(dll,name);if(!p)throw std::runtime_error(name);return reinterpret_cast<T>(p);}
static void log(sl::LogType,const char *message){printf("SL_LOG %s\n",message);}
static LONG WINAPI fatal(EXCEPTION_POINTERS *p){fprintf(stderr,"SL_EXCEPTION 0x%08lx\n",p->ExceptionRecord->ExceptionCode);return EXCEPTION_EXECUTE_HANDLER;}
int main(int argc,char **argv){
    setvbuf(stdout,nullptr,_IONBF,0);SetErrorMode(SEM_FAILCRITICALERRORS|SEM_NOGPFAULTERRORBOX);SetUnhandledExceptionFilter(fatal);
    try{
        if(argc!=2)throw std::runtime_error("Usage: streamline-probe.exe ABSOLUTE_WINDOWS_GAME_DIRECTORY");
        wchar_t directory[32768]{};if(!MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,argv[1],-1,directory,32768))throw std::runtime_error("Invalid UTF-8 plugin directory");
        if(wcslen(directory)>32000)throw std::runtime_error("Plugin path too long");
        wchar_t path[32768]{};swprintf(path,32768,L"%ls\\sl.interposer.dll",directory);
        HMODULE dll=LoadLibraryW(path);if(!dll)throw std::runtime_error("Load Streamline");
        const sl::Feature features[]={sl::kFeatureDLSS};const wchar_t *paths[]={directory};
        sl::Preferences p;p.featuresToLoad=features;p.numFeaturesToLoad=1;p.pathsToPlugins=paths;p.numPathsToPlugins=1;
        p.pathToLogsAndData=L"C:\\ngx-probe";p.logMessageCallback=log;p.logLevel=sl::LogLevel::eVerbose;
        p.flags=sl::PreferenceFlags::eDisableCLStateTracking|sl::PreferenceFlags::eUseFrameBasedResourceTagging;
        p.engine=sl::EngineType::eCustom;p.engineVersion="1.0";p.projectId="8a5cd3fa-5c17-4d8d-bb4e-d2cbd8cf8fe1";
        constexpr uint64_t version=(2ull<<48)|(11ull<<32)|(1ull<<16)|0xfedc;
        auto result=symbol<PFun_slInit *>(dll,"slInit")(p,version);printf("SL_INITIALIZE %u\n",unsigned(result));
        if(result!=sl::Result::eOk)return 2;
        ComPtr<IDXGIFactory4> factory;check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"DXGI factory");
        ComPtr<IDXGIAdapter1> adapter;check(factory->EnumAdapters1(0,&adapter),"adapter");
        DXGI_ADAPTER_DESC1 desc{};check(adapter->GetDesc1(&desc),"adapter desc");
        sl::AdapterInfo info;info.deviceLUID=reinterpret_cast<uint8_t *>(&desc.AdapterLuid);info.deviceLUIDSizeInBytes=sizeof desc.AdapterLuid;
        result=symbol<PFun_slIsFeatureSupported *>(dll,"slIsFeatureSupported")(sl::kFeatureDLSS,info);printf("SL_DLSS_SUPPORT %u\n",unsigned(result));
        sl::FeatureRequirements requirements;
        auto req=symbol<PFun_slGetFeatureRequirements *>(dll,"slGetFeatureRequirements")(sl::kFeatureDLSS,requirements);
        printf("SL_REQUIREMENTS result=%u os=%u.%u.%u required=%u.%u.%u driver=%u.%u.%u required=%u.%u.%u\n",unsigned(req),
          requirements.osVersionDetected.major,requirements.osVersionDetected.minor,requirements.osVersionDetected.build,
          requirements.osVersionRequired.major,requirements.osVersionRequired.minor,requirements.osVersionRequired.build,
          requirements.driverVersionDetected.major,requirements.driverVersionDetected.minor,requirements.driverVersionDetected.build,
          requirements.driverVersionRequired.major,requirements.driverVersionRequired.minor,requirements.driverVersionRequired.build);
        if(result==sl::Result::eOk){
            ComPtr<ID3D12Device> device;check(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)),"D3D12 device");
            result=symbol<PFun_slSetD3DDevice *>(dll,"slSetD3DDevice")(device.Get());printf("SL_SET_DEVICE %u\n",unsigned(result));
        }
        symbol<PFun_slShutdown *>(dll,"slShutdown")();return result==sl::Result::eOk?0:2;
    }catch(const std::exception &e){fprintf(stderr,"SL_PROBE_FAIL %s\n",e.what());return 1;}
}
