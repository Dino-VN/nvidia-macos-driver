#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_4.h>
#include <wrl/client.h>
#include <array>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iterator>
#include <stdexcept>
#include <string>
#include <vector>
using Microsoft::WRL::ComPtr;

static void need(bool value, const char *reason) { if (!value) throw std::runtime_error(reason); }
static void check(HRESULT hr, const char *where) {
    if (FAILED(hr)) { char text[256]; snprintf(text,sizeof text,"%s: 0x%08lx",where,(unsigned long)hr); throw std::runtime_error(text); }
}
static std::vector<char> shader(const std::string &path) {
    std::ifstream file(path, std::ios::binary); need(file.good(), "Cannot open DXIL shader");
    return {std::istreambuf_iterator<char>(file), std::istreambuf_iterator<char>()};
}
static void transition(ID3D12GraphicsCommandList *list, ID3D12Resource *resource,
                       D3D12_RESOURCE_STATES before, D3D12_RESOURCE_STATES after) {
    D3D12_RESOURCE_BARRIER b{}; b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition={resource,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,before,after};list->ResourceBarrier(1,&b);
}
static ComPtr<ID3D12Resource> buffer(ID3D12Device *device, UINT64 size, D3D12_HEAP_TYPE heap,
                                  D3D12_RESOURCE_STATES state, D3D12_RESOURCE_FLAGS flags=D3D12_RESOURCE_FLAG_NONE) {
    D3D12_HEAP_PROPERTIES properties{};properties.Type=heap;properties.CreationNodeMask=properties.VisibleNodeMask=1;
    D3D12_RESOURCE_DESC desc{};desc.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;desc.Width=size;
    desc.Height=desc.DepthOrArraySize=desc.MipLevels=1;desc.SampleDesc.Count=1;
    desc.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;desc.Flags=flags;
    ComPtr<ID3D12Resource> result;
    check(device->CreateCommittedResource(&properties,D3D12_HEAP_FLAG_NONE,&desc,state,nullptr,IID_PPV_ARGS(&result)),"buffer allocation");
    return result;
}
static ComPtr<ID3D12RootSignature> rootSignature(ID3D12Device *device, const D3D12_ROOT_SIGNATURE_DESC &desc) {
    ComPtr<ID3DBlob> blob,error;check(D3D12SerializeRootSignature(&desc,D3D_ROOT_SIGNATURE_VERSION_1,&blob,&error),"root signature serialization");
    ComPtr<ID3D12RootSignature> root;
    check(device->CreateRootSignature(0,blob->GetBufferPointer(),blob->GetBufferSize(),IID_PPV_ARGS(&root)),"root signature");return root;
}
int main(int argc,char **argv) {
    setvbuf(stdout,nullptr,_IONBF,0);
    HANDLE event=nullptr;HWND window=nullptr;
    try {
        bool windowed=false;unsigned frames=120;std::string directory=".";
        for(int i=1;i<argc;++i) {
            if(!strcmp(argv[i],"--window"))windowed=true;
            else if(!strcmp(argv[i],"--frames")&&i+1<argc)frames=std::stoul(argv[++i]);
            else if(!strcmp(argv[i],"--shaders")&&i+1<argc)directory=argv[++i];
            else throw std::runtime_error("Unknown argument");
        }
        need(frames>=30&&frames<=600,"Frame count must be 30..600");
        ComPtr<IDXGIFactory4> factory;check(CreateDXGIFactory1(IID_PPV_ARGS(&factory)),"DXGI factory");
        ComPtr<IDXGIAdapter1> adapter;check(factory->EnumAdapters1(0,&adapter),"adapter");
        DXGI_ADAPTER_DESC1 desc{};check(adapter->GetDesc1(&desc),"adapter description");
        char name[512]{};WideCharToMultiByte(CP_UTF8,0,desc.Description,-1,name,sizeof name,nullptr,nullptr);
        printf("ADAPTER %s\n",name);need(strstr(name,"NVK")&&strstr(name,"NVIDIA"),"Unexpected adapter");
        ComPtr<ID3D12Device> device;check(D3D12CreateDevice(adapter.Get(),D3D_FEATURE_LEVEL_11_0,IID_PPV_ARGS(&device)),"D3D12CreateDevice");
        for(const wchar_t *dll:{L"dxgi.dll",L"d3d12.dll",L"d3d12core.dll"}) {
            char path[32768]{};GetModuleFileNameA(GetModuleHandleW(dll),path,sizeof path);printf("NATIVE_DLL %s\n",path);
        }
        D3D12_FEATURE_DATA_SHADER_MODEL sm{D3D_SHADER_MODEL_6_0};
        check(device->CheckFeatureSupport(D3D12_FEATURE_SHADER_MODEL,&sm,sizeof sm),"shader model");
        need(sm.HighestShaderModel>=D3D_SHADER_MODEL_6_0,"Shader model 6.0 unavailable");
        printf("SHADER_MODEL 0x%x\n",sm.HighestShaderModel);
        D3D12_COMMAND_QUEUE_DESC q{};q.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
        ComPtr<ID3D12CommandQueue> queue;check(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)),"direct queue");
        ComPtr<ID3D12CommandAllocator> allocator;check(device->CreateCommandAllocator(q.Type,IID_PPV_ARGS(&allocator)),"allocator");
        ComPtr<ID3D12GraphicsCommandList> list;check(device->CreateCommandList(0,q.Type,allocator.Get(),nullptr,IID_PPV_ARGS(&list)),"command list");
        ComPtr<ID3D12Fence> fence;check(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"fence");
        event=CreateEventW(nullptr,FALSE,FALSE,nullptr);need(event,"Fence event");UINT64 sequence=0;
        auto submit=[&] {
            check(list->Close(),"close commands");ID3D12CommandList *commands[]={list.Get()};queue->ExecuteCommandLists(1,commands);
            check(queue->Signal(fence.Get(),++sequence),"queue signal");
            check(fence->SetEventOnCompletion(sequence,event),"fence event");
            need(WaitForSingleObject(event,10000)==WAIT_OBJECT_0,"GPU fence timed out");
            check(device->GetDeviceRemovedReason(),"device health");
        };
        auto reset=[&](ID3D12PipelineState *pipeline) {check(allocator->Reset(),"allocator reset");check(list->Reset(allocator.Get(),pipeline),"command reset");};
        const UINT seed=0x12345678;auto code=shader(directory+"/cs.dxil");
        D3D12_ROOT_PARAMETER params[2]{};params[0].ParameterType=D3D12_ROOT_PARAMETER_TYPE_UAV;
        params[1].ParameterType=D3D12_ROOT_PARAMETER_TYPE_32BIT_CONSTANTS;params[1].Constants.Num32BitValues=1;
        D3D12_ROOT_SIGNATURE_DESC rootDesc{};rootDesc.NumParameters=2;rootDesc.pParameters=params;
        auto computeRoot=rootSignature(device.Get(),rootDesc);
        D3D12_COMPUTE_PIPELINE_STATE_DESC cp{};cp.pRootSignature=computeRoot.Get();cp.CS={code.data(),code.size()};
        ComPtr<ID3D12PipelineState> compute;check(device->CreateComputePipelineState(&cp,IID_PPV_ARGS(&compute)),"DXIL compute pipeline");
        auto gpu=buffer(device.Get(),4096,D3D12_HEAP_TYPE_DEFAULT,D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS);
        auto readback=buffer(device.Get(),4096,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
        list->SetPipelineState(compute.Get());list->SetComputeRootSignature(computeRoot.Get());
        list->SetComputeRootUnorderedAccessView(0,gpu->GetGPUVirtualAddress());list->SetComputeRoot32BitConstant(1,seed,0);
        list->Dispatch(16,1,1);transition(list.Get(),gpu.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
        list->CopyResource(readback.Get(),gpu.Get());submit();
        void *mapped=nullptr;D3D12_RANGE range{0,4096};check(readback->Map(0,&range,&mapped),"compute readback");
        for(UINT i=0;i<1024;++i)need(static_cast<UINT *>(mapped)[i]==((i*1664525u+seed)^0x5a5aa5a5u),"DXIL compute pixel mismatch");
        D3D12_RANGE noWrites{};readback->Unmap(0,&noWrites);puts("PASS DXIL compute, root UAV, fence and 1024-word readback");
        if(windowed) {
            WNDCLASSW wc{};wc.lpfnWndProc=DefWindowProcW;wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"NVKD3D12Probe";
            need(RegisterClassW(&wc),"Window class");window=CreateWindowExW(0,wc.lpszClassName,L"D3D12 to native NVK: DXIL and presentation",WS_OVERLAPPEDWINDOW|WS_VISIBLE,180,180,720,450,nullptr,nullptr,wc.hInstance,nullptr);need(window,"Window creation");
            DXGI_SWAP_CHAIN_DESC1 sc{};sc.Width=640;sc.Height=360;sc.Format=DXGI_FORMAT_B8G8R8A8_UNORM;sc.SampleDesc.Count=1;
            sc.BufferUsage=DXGI_USAGE_RENDER_TARGET_OUTPUT;sc.BufferCount=3;sc.SwapEffect=DXGI_SWAP_EFFECT_FLIP_DISCARD;
            ComPtr<IDXGISwapChain1> original;check(factory->CreateSwapChainForHwnd(queue.Get(),window,&sc,nullptr,nullptr,&original),"D3D12 swapchain");
            ComPtr<IDXGISwapChain3> chain;check(original.As(&chain),"swapchain3");original.Reset();
            rootDesc={};auto graphicsRoot=rootSignature(device.Get(),rootDesc);
            auto vs=shader(directory+"/vs.dxil"),ps=shader(directory+"/ps.dxil");
            D3D12_GRAPHICS_PIPELINE_STATE_DESC gp{};gp.pRootSignature=graphicsRoot.Get();gp.VS={vs.data(),vs.size()};gp.PS={ps.data(),ps.size()};
            gp.RasterizerState.FillMode=D3D12_FILL_MODE_SOLID;gp.RasterizerState.CullMode=D3D12_CULL_MODE_NONE;gp.RasterizerState.DepthClipEnable=TRUE;
            auto &blend=gp.BlendState.RenderTarget[0];blend.SrcBlend=blend.SrcBlendAlpha=D3D12_BLEND_ONE;blend.DestBlend=blend.DestBlendAlpha=D3D12_BLEND_ZERO;
            blend.BlendOp=blend.BlendOpAlpha=D3D12_BLEND_OP_ADD;blend.RenderTargetWriteMask=D3D12_COLOR_WRITE_ENABLE_ALL;
            gp.DepthStencilState.DepthFunc=D3D12_COMPARISON_FUNC_ALWAYS;gp.DepthStencilState.FrontFace.StencilFunc=D3D12_COMPARISON_FUNC_ALWAYS;
            gp.DepthStencilState.FrontFace.StencilFailOp=gp.DepthStencilState.FrontFace.StencilDepthFailOp=gp.DepthStencilState.FrontFace.StencilPassOp=D3D12_STENCIL_OP_KEEP;
            gp.DepthStencilState.BackFace=gp.DepthStencilState.FrontFace;gp.SampleMask=~0u;gp.PrimitiveTopologyType=D3D12_PRIMITIVE_TOPOLOGY_TYPE_TRIANGLE;
            gp.NumRenderTargets=1;gp.RTVFormats[0]=sc.Format;gp.SampleDesc.Count=1;
            ComPtr<ID3D12PipelineState> graphics;check(device->CreateGraphicsPipelineState(&gp,IID_PPV_ARGS(&graphics)),"DXIL graphics pipeline");
            D3D12_DESCRIPTOR_HEAP_DESC heapDesc{};heapDesc.Type=D3D12_DESCRIPTOR_HEAP_TYPE_RTV;heapDesc.NumDescriptors=3;
            ComPtr<ID3D12DescriptorHeap> heap;check(device->CreateDescriptorHeap(&heapDesc,IID_PPV_ARGS(&heap)),"RTV heap");
            UINT stride=device->GetDescriptorHandleIncrementSize(heapDesc.Type);std::array<ComPtr<ID3D12Resource>,3> images;
            D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};UINT width=640,height=360;ComPtr<ID3D12Resource> pixels;
            auto imagesForSize=[&] {
                auto handle=heap->GetCPUDescriptorHandleForHeapStart();
                for(UINT i=0;i<3;++i) {check(chain->GetBuffer(i,IID_PPV_ARGS(&images[i])),"swapchain image");device->CreateRenderTargetView(images[i].Get(),nullptr,handle);handle.ptr+=stride;}
                auto info=images[0]->GetDesc();UINT64 bytes=0;device->GetCopyableFootprints(&info,0,1,0,&footprint,nullptr,nullptr,&bytes);
                pixels=buffer(device.Get(),bytes,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
            };imagesForSize();unsigned checks=0;
            for(unsigned frame=0;frame<frames;++frame) {
                MSG msg;while(PeekMessageW(&msg,nullptr,0,0,PM_REMOVE)){TranslateMessage(&msg);DispatchMessageW(&msg);}
                if(frame==frames/2) {
                    for(auto &image:images)image.Reset();pixels.Reset();width=800;height=450;
                    check(chain->ResizeBuffers(3,width,height,sc.Format,0),"D3D12 resize");imagesForSize();puts("PASS swapchain resize");
                }
                reset(graphics.Get());UINT index=chain->GetCurrentBackBufferIndex();auto *image=images[index].Get();
                transition(list.Get(),image,D3D12_RESOURCE_STATE_PRESENT,D3D12_RESOURCE_STATE_RENDER_TARGET);
                auto rtv=heap->GetCPUDescriptorHandleForHeapStart();rtv.ptr+=index*stride;
                const float clear[]={0.05f,0.10f,0.20f,1};list->ClearRenderTargetView(rtv,clear,0,nullptr);list->OMSetRenderTargets(1,&rtv,FALSE,nullptr);
                D3D12_VIEWPORT viewport{0,0,float(width),float(height),0,1};D3D12_RECT rect{0,0,LONG(width),LONG(height)};
                list->RSSetViewports(1,&viewport);list->RSSetScissorRects(1,&rect);list->SetGraphicsRootSignature(graphicsRoot.Get());
                list->IASetPrimitiveTopology(D3D_PRIMITIVE_TOPOLOGY_TRIANGLELIST);list->DrawInstanced(3,1,0,0);
                transition(list.Get(),image,D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_COPY_SOURCE);
                D3D12_TEXTURE_COPY_LOCATION src{};src.pResource=image;src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
                D3D12_TEXTURE_COPY_LOCATION dst{};dst.pResource=pixels.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dst.PlacedFootprint=footprint;
                list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);transition(list.Get(),image,D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_PRESENT);submit();
                if(frame%30==0||frame==frames-1) {
                    check(pixels->Map(0,nullptr,&mapped),"render readback");auto *corner=static_cast<unsigned char *>(mapped)+footprint.Offset;
                    auto *center=corner+(height/2)*footprint.Footprint.RowPitch+(width/2)*4;
                    int a[]={51,26,13},b[]={102,204,51};bool valid=true;
                    for(int c=0;c<3;++c)if(abs(corner[c]-a[c])>1||abs(center[c]-b[c])>1)valid=false;
                    if(!valid)fprintf(stderr,"PIXELS corner=%u,%u,%u center=%u,%u,%u\n",corner[0],corner[1],corner[2],center[0],center[1],center[2]);
                    pixels->Unmap(0,&noWrites);need(valid,"DXIL rendered pixel mismatch");++checks;
                }
                check(chain->Present(1,0),"present");
            }
            printf("PASS presents=%u render_readbacks=%u DXIL=cs,vs,ps resize=pass\n",frames,checks);
        }
        if(window)DestroyWindow(window);CloseHandle(event);puts("RESULT PASS");return 0;
    } catch(const std::exception &error) {
        fprintf(stderr,"RESULT FAIL: %s\n",error.what());if(window)DestroyWindow(window);if(event)CloseHandle(event);return 1;
    }
}
