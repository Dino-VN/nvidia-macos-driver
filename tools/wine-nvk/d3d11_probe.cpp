#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d11.h>
#include <dxgi.h>
#include <d3dcompiler.h>
#include <wrl/client.h>
#include <algorithm>
#include <cmath>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
using Microsoft::WRL::ComPtr;
static void check(HRESULT hr,const char *where) {
    if (FAILED(hr)) {char code[32];snprintf(code,sizeof code,"0x%08lx",(unsigned long)hr);throw std::runtime_error(std::string(where)+": "+code);}
}
static void require(bool condition,const char *message) {if (!condition)throw std::runtime_error(message);}
static void pump() {MSG msg;while(PeekMessageW(&msg,nullptr,0,0,PM_REMOVE)){TranslateMessage(&msg);DispatchMessageW(&msg);}}
static ComPtr<ID3DBlob> compile(const char *source,const char *entry,const char *target) {
    ComPtr<ID3DBlob> code,error;HRESULT hr=D3DCompile(source,strlen(source),"NVK D3D11 probe",nullptr,nullptr,entry,target,D3DCOMPILE_ENABLE_STRICTNESS,0,&code,&error);
    if(error)fprintf(stderr,"HLSL: %s\n",(char *)error->GetBufferPointer());check(hr,"D3DCompile");return code;
}
int main(int argc,char **argv) {
    setvbuf(stdout,nullptr,_IONBF,0);
    try {
        unsigned frames=300;bool immediate=false,indirect=false,indexed=false;
        for(int i=1;i<argc;++i){if(!strcmp(argv[i],"--frames")&&i+1<argc)frames=atoi(argv[++i]);else if(!strcmp(argv[i],"--immediate"))immediate=true;else if(!strcmp(argv[i],"--indirect"))indirect=true;else if(!strcmp(argv[i],"--indexed-indirect")){indirect=true;indexed=true;}else throw std::runtime_error("Unknown argument");}
        require(frames>=30&&frames<=3000,"Invalid frame count");
        WNDCLASSW wc{};wc.lpfnWndProc=DefWindowProcW;wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"NVKD3D11Probe";
        require(RegisterClassW(&wc),"RegisterClass failed");
        HWND window=CreateWindowExW(0,wc.lpszClassName,L"DXVK to native NVK: texture, depth and blending",WS_OVERLAPPEDWINDOW|WS_VISIBLE,
            180,180,800,500,nullptr,nullptr,wc.hInstance,nullptr);require(window,"CreateWindow failed");
        DXGI_SWAP_CHAIN_DESC sc{};sc.BufferDesc.Width=768;sc.BufferDesc.Height=432;sc.BufferDesc.Format=DXGI_FORMAT_B8G8R8A8_UNORM;
        sc.SampleDesc.Count=1;sc.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;sc.BufferCount=3;sc.OutputWindow=window;sc.Windowed=TRUE;sc.SwapEffect=DXGI_SWAP_EFFECT_FLIP_DISCARD;
        ComPtr<ID3D11Device> device;ComPtr<ID3D11DeviceContext> context;ComPtr<IDXGISwapChain> swapchain;
        D3D_FEATURE_LEVEL wanted=D3D_FEATURE_LEVEL_11_0,actual{};
        check(D3D11CreateDeviceAndSwapChain(nullptr,D3D_DRIVER_TYPE_HARDWARE,nullptr,0,&wanted,1,D3D11_SDK_VERSION,&sc,&swapchain,&device,&actual,&context),"D3D11 device/swapchain");
        printf("FEATURE_LEVEL 0x%x\n",actual);
        for(const wchar_t *name:{L"d3d11.dll",L"dxgi.dll"}){char path[32768]{};GetModuleFileNameA(GetModuleHandleW(name),path,sizeof path);printf("NATIVE_DLL %s\n",path);}
        ComPtr<IDXGIDevice> dxgiDevice;check(device.As(&dxgiDevice),"DXGI device");ComPtr<IDXGIAdapter> adapter;check(dxgiDevice->GetAdapter(&adapter),"adapter");
        DXGI_ADAPTER_DESC desc{};check(adapter->GetDesc(&desc),"adapter description");char name[512]{};WideCharToMultiByte(CP_UTF8,0,desc.Description,-1,name,sizeof name,nullptr,nullptr);
        printf("ADAPTER %s vendor=0x%x device=0x%x dedicated=%llu\n",name,desc.VendorId,desc.DeviceId,(unsigned long long)desc.DedicatedVideoMemory);
        // DXVK may intentionally report an AMD PCI ID when its NVIDIA/NVAPI
        // compatibility workaround is enabled. Its Vulkan log identifies the GPU.
        require(strstr(name,"NVIDIA") && strstr(name,"NVK"),"Unexpected adapter name");
        ComPtr<ID3D11Buffer> arguments,indexBuffer;
        if(indirect){
            const UINT values[]={3,1,0,0,0};D3D11_BUFFER_DESC info{};
            info.ByteWidth=indexed?20:16;info.Usage=D3D11_USAGE_DEFAULT;info.MiscFlags=D3D11_RESOURCE_MISC_DRAWINDIRECT_ARGS;
            D3D11_SUBRESOURCE_DATA data{values,0,0};check(device->CreateBuffer(&info,&data,&arguments),"indirect arguments");
            if(indexed){
                const unsigned short indices[]={0,1,2};info={};info.ByteWidth=sizeof indices;info.Usage=D3D11_USAGE_DEFAULT;info.BindFlags=D3D11_BIND_INDEX_BUFFER;
                data={indices,0,0};check(device->CreateBuffer(&info,&data,&indexBuffer),"index buffer");
                context->IASetIndexBuffer(indexBuffer.Get(),DXGI_FORMAT_R16_UINT,0);
            }
        }
        printf("DRAW_MODE %s\n",indexed?"indexed-indirect":indirect?"indirect":"direct");
        const char *hlsl=R"(
Texture2D tex : register(t0); SamplerState samp : register(s0);
struct Vertex { float4 pos : SV_Position; float2 uv : TEXCOORD0; };
Vertex vs(uint id : SV_VertexID) {
    float2 p[3]={float2(-0.75,-0.75),float2(0,0.75),float2(0.75,-0.75)};
    Vertex o; o.pos=float4(p[id],0.25,1);o.uv=float2(p[id].x*0.5+0.5,0.5-p[id].y*0.5);return o;
}
float4 ps(Vertex input) : SV_Target { return tex.Sample(samp,input.uv); }
)";
        auto vsCode=compile(hlsl,"vs","vs_5_0"),psCode=compile(hlsl,"ps","ps_5_0");
        ComPtr<ID3D11VertexShader> vs;ComPtr<ID3D11PixelShader> ps;
        check(device->CreateVertexShader(vsCode->GetBufferPointer(),vsCode->GetBufferSize(),nullptr,&vs),"vertex shader");
        check(device->CreatePixelShader(psCode->GetBufferPointer(),psCode->GetBufferSize(),nullptr,&ps),"pixel shader");
        D3D11_TEXTURE2D_DESC td{};td.Width=td.Height=td.MipLevels=td.ArraySize=1;td.Format=DXGI_FORMAT_R8G8B8A8_UNORM;td.SampleDesc.Count=1;td.Usage=D3D11_USAGE_IMMUTABLE;td.BindFlags=D3D11_BIND_SHADER_RESOURCE;
        const unsigned char rgba[]={230,60,25,128};D3D11_SUBRESOURCE_DATA data{rgba,4,4};ComPtr<ID3D11Texture2D> texture;check(device->CreateTexture2D(&td,&data,&texture),"texture");
        ComPtr<ID3D11ShaderResourceView> srv;check(device->CreateShaderResourceView(texture.Get(),nullptr,&srv),"texture view");
        D3D11_SAMPLER_DESC sd{};sd.Filter=D3D11_FILTER_MIN_MAG_MIP_POINT;sd.AddressU=sd.AddressV=sd.AddressW=D3D11_TEXTURE_ADDRESS_CLAMP;sd.MaxLOD=D3D11_FLOAT32_MAX;
        ComPtr<ID3D11SamplerState> sampler;check(device->CreateSamplerState(&sd,&sampler),"sampler");
        D3D11_BLEND_DESC bd{};auto &blend=bd.RenderTarget[0];blend.BlendEnable=TRUE;blend.SrcBlend=D3D11_BLEND_SRC_ALPHA;blend.DestBlend=D3D11_BLEND_INV_SRC_ALPHA;blend.BlendOp=D3D11_BLEND_OP_ADD;
        blend.SrcBlendAlpha=D3D11_BLEND_ONE;blend.DestBlendAlpha=D3D11_BLEND_ZERO;blend.BlendOpAlpha=D3D11_BLEND_OP_ADD;blend.RenderTargetWriteMask=D3D11_COLOR_WRITE_ENABLE_ALL;
        ComPtr<ID3D11BlendState> blendState;check(device->CreateBlendState(&bd,&blendState),"blend state");
        D3D11_DEPTH_STENCIL_DESC dd{};dd.DepthEnable=TRUE;dd.DepthWriteMask=D3D11_DEPTH_WRITE_MASK_ALL;dd.DepthFunc=D3D11_COMPARISON_LESS;
        ComPtr<ID3D11DepthStencilState> depthState;check(device->CreateDepthStencilState(&dd,&depthState),"depth state");
        D3D11_RASTERIZER_DESC rd{};rd.FillMode=D3D11_FILL_SOLID;rd.CullMode=D3D11_CULL_NONE;rd.DepthClipEnable=TRUE;
        ComPtr<ID3D11RasterizerState> rasterizer;check(device->CreateRasterizerState(&rd,&rasterizer),"rasterizer");
        ComPtr<ID3D11Texture2D> backbuffer,depth,staging;ComPtr<ID3D11RenderTargetView> rtv;ComPtr<ID3D11DepthStencilView> dsv;UINT width=0,height=0;
        auto views=[&]{
            check(swapchain->GetBuffer(0,IID_PPV_ARGS(&backbuffer)),"backbuffer");D3D11_TEXTURE2D_DESC info{};backbuffer->GetDesc(&info);width=info.Width;height=info.Height;
            check(device->CreateRenderTargetView(backbuffer.Get(),nullptr,&rtv),"RTV");
            info.Format=DXGI_FORMAT_D32_FLOAT;info.Usage=D3D11_USAGE_DEFAULT;info.BindFlags=D3D11_BIND_DEPTH_STENCIL;info.CPUAccessFlags=0;info.MiscFlags=0;
            check(device->CreateTexture2D(&info,nullptr,&depth),"depth texture");check(device->CreateDepthStencilView(depth.Get(),nullptr,&dsv),"DSV");
            info.Format=DXGI_FORMAT_B8G8R8A8_UNORM;info.Usage=D3D11_USAGE_STAGING;info.BindFlags=0;info.CPUAccessFlags=D3D11_CPU_ACCESS_READ;
            check(device->CreateTexture2D(&info,nullptr,&staging),"readback staging");printf("BACKBUFFER %ux%u\n",width,height);
        };views();unsigned verified=0;
        for(unsigned frame=0;frame<frames;++frame){
            pump();
            if(frame==frames/2){
                context->OMSetRenderTargets(0,nullptr,nullptr);rtv.Reset();dsv.Reset();backbuffer.Reset();depth.Reset();staging.Reset();
                check(swapchain->ResizeBuffers(3,960,540,DXGI_FORMAT_B8G8R8A8_UNORM,0),"ResizeBuffers");SetWindowPos(window,nullptr,0,0,960,580,SWP_NOMOVE|SWP_NOZORDER);views();puts("PASS swapchain resize/recreation");
            }
            float t=(frame%60)/59.f;const float clear[]={t,0.15f,1.f-t,1.f};context->ClearRenderTargetView(rtv.Get(),clear);context->ClearDepthStencilView(dsv.Get(),D3D11_CLEAR_DEPTH,1,0);
            ID3D11RenderTargetView *target=rtv.Get();context->OMSetRenderTargets(1,&target,dsv.Get());context->OMSetBlendState(blendState.Get(),nullptr,~0u);context->OMSetDepthStencilState(depthState.Get(),0);
            D3D11_VIEWPORT viewport{0,0,(float)width,(float)height,0,1};context->RSSetViewports(1,&viewport);context->RSSetState(rasterizer.Get());
            context->IASetPrimitiveTopology(D3D11_PRIMITIVE_TOPOLOGY_TRIANGLELIST);context->VSSetShader(vs.Get(),nullptr,0);context->PSSetShader(ps.Get(),nullptr,0);
            ID3D11ShaderResourceView *view=srv.Get();context->PSSetShaderResources(0,1,&view);ID3D11SamplerState *samp=sampler.Get();context->PSSetSamplers(0,1,&samp);
            for(unsigned draw=0;draw<2;++draw){ // Equal depth rejects the second blend.
                if(indexed)context->DrawIndexedInstancedIndirect(arguments.Get(),0);
                else if(indirect)context->DrawInstancedIndirect(arguments.Get(),0);
                else context->Draw(3,0);
            }
            if(frame%30==0||frame==frames-1){
                context->CopyResource(staging.Get(),backbuffer.Get());D3D11_MAPPED_SUBRESOURCE map{};check(context->Map(staging.Get(),0,D3D11_MAP_READ,0,&map),"readback");
                auto *corner=(unsigned char *)map.pData;auto *center=corner+(height/2)*map.RowPitch+(width/2)*4;
                int expectedCorner[]={int(lround((1.f-t)*255)),int(lround(.15f*255)),int(lround(t*255))};
                int expectedCenter[3];const int texBGR[]={25,60,230};bool good=true;
                for(unsigned k=0;k<3;++k){expectedCenter[k]=int(lround(texBGR[k]*(128.f/255.f)+expectedCorner[k]*(127.f/255.f)));if(abs(corner[k]-expectedCorner[k])>2||abs(center[k]-expectedCenter[k])>2)good=false;}
                if(!good)fprintf(stderr,"PIXEL MISMATCH frame=%u corner=%u,%u,%u center=%u,%u,%u expected_center=%d,%d,%d\n",frame,corner[0],corner[1],corner[2],center[0],center[1],center[2],expectedCenter[0],expectedCenter[1],expectedCenter[2]);
                context->Unmap(staging.Get(),0);require(good,"Texture/depth/blend/clear pixel check failed");++verified;
            }
            check(swapchain->Present(immediate?0:1,0),"Present");
        }
        context->ClearState();context->Flush();DestroyWindow(window);
        printf("PASS presents=%u pixel_checks=%u textured_draws=%u depth_rejects=%u blend=src_alpha resize=pass\n",frames,verified,frames*2,frames);puts("RESULT PASS");return 0;
    }catch(const std::exception &e){fprintf(stderr,"RESULT FAIL: %s\n",e.what());return 1;}
}
