#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <dxgi1_2.h>
#include <wrl/client.h>
#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#include <stdexcept>
using Microsoft::WRL::ComPtr;

static void require(bool okay,const char *reason) { if (!okay) throw std::runtime_error(reason); }
static void check(HRESULT result,const char *reason) {
    if (FAILED(result)) { fprintf(stderr,"HRESULT 0x%08lx: %s\n",(unsigned long)result,reason);throw std::runtime_error(reason); }
}

int main() {
    setvbuf(stdout,nullptr,_IONBF,0);
    try {
        unsigned pixels=0,refused=0;
        for (D3D_FEATURE_LEVEL level : {D3D_FEATURE_LEVEL_11_1,D3D_FEATURE_LEVEL_11_0}) {
            ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> context;D3D_FEATURE_LEVEL actual{};
            check(D3D11CreateDevice(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,0,&level,1,D3D11_SDK_VERSION,&device,&actual,&context),"device");
            printf("DEVICE level=0x%x\n",actual);
            for (UINT flags : {0u,UINT(D3D11_RESOURCE_MISC_SHARED),
                    UINT(D3D11_RESOURCE_MISC_SHARED_KEYEDMUTEX),
                    UINT(D3D11_RESOURCE_MISC_SHARED_KEYEDMUTEX|D3D11_RESOURCE_MISC_SHARED_NTHANDLE)}) {
                D3D11_TEXTURE2D_DESC info{};info.Width=info.Height=16;info.MipLevels=info.ArraySize=1;
                info.Format=DXGI_FORMAT_B8G8R8A8_UNORM;info.SampleDesc.Count=1;info.Usage=D3D11_USAGE_DEFAULT;
                info.BindFlags=D3D11_BIND_RENDER_TARGET|D3D11_BIND_SHADER_RESOURCE;info.MiscFlags=flags;
                ComPtr<ID3D11Texture2D> texture;
                printf("CREATE flags=0x%x\n",flags);
                HRESULT result=device->CreateTexture2D(&info,nullptr,&texture);
                printf("CREATE_RESULT flags=0x%x hr=0x%08lx\n",flags,(unsigned long)result);
                if (FAILED(result)) { require(flags!=0,"ordinary texture was refused");++refused;continue; }
                require(texture!=nullptr,"successful create returned no texture");
                if (flags) {
                    ComPtr<IDXGIResource> resource;check(texture.As(&resource),"DXGI resource");
                    HANDLE handle=nullptr;result=resource->GetSharedHandle(&handle);
                    printf("GET_SHARED flags=0x%x hr=0x%08lx handle=%p\n",flags,(unsigned long)result,handle);
                    require(FAILED(result)&&(!handle||handle==INVALID_HANDLE_VALUE),"unsupported sharing returned a usable handle");
                    if (flags&D3D11_RESOURCE_MISC_SHARED_NTHANDLE) {
                        ComPtr<IDXGIResource1> resource1;check(texture.As(&resource1),"DXGI resource1");
                        handle=nullptr;result=resource1->CreateSharedHandle(nullptr,DXGI_SHARED_RESOURCE_READ|DXGI_SHARED_RESOURCE_WRITE,nullptr,&handle);
                        printf("CREATE_SHARED_NT hr=0x%08lx handle=%p\n",(unsigned long)result,handle);
                        require(FAILED(result)&&(!handle||handle==INVALID_HANDLE_VALUE),"unsupported NT sharing returned a usable handle");
                    }
                }
                ComPtr<ID3D11RenderTargetView> view;check(device->CreateRenderTargetView(texture.Get(),nullptr,&view),"RTV");
                const float color[]={0.25f,0.5f,0.75f,1.f};context->ClearRenderTargetView(view.Get(),color);
                info.Usage=D3D11_USAGE_STAGING;info.BindFlags=0;info.CPUAccessFlags=D3D11_CPU_ACCESS_READ;info.MiscFlags=0;
                ComPtr<ID3D11Texture2D> staging;check(device->CreateTexture2D(&info,nullptr,&staging),"staging");
                context->CopyResource(staging.Get(),texture.Get());D3D11_MAPPED_SUBRESOURCE map{};
                check(context->Map(staging.Get(),0,D3D11_MAP_READ,0,&map),"readback");
                auto pixel=(const unsigned char *)map.pData;
                bool okay=abs(int(pixel[0])-191)<=1&&abs(int(pixel[1])-128)<=1&&abs(int(pixel[2])-64)<=1&&pixel[3]==255;
                context->Unmap(staging.Get(),0);require(okay,"unshared fallback pixel mismatch");++pixels;
            }
            context->ClearState();context->Flush();
        }
        printf("RESULT PASS: pixel_checks=%u refused_shared_creates=%u; external handles remain unsupported\n",pixels,refused);
        return 0;
    } catch (const std::exception &e) { fprintf(stderr,"RESULT FAIL: %s\n",e.what());return 1; }
}
