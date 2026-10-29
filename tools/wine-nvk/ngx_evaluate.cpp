// Bounded, offscreen DLSS SR smoke test. This is not an image-quality benchmark.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <wrl/client.h>
#define NGX_SNIPPET_BUILD 1
#include <nvsdk_ngx.h>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <initializer_list>
#include <stdexcept>
using Microsoft::WRL::ComPtr;
extern "C" void nvk_ngx_set_i(NVSDK_NGX_Parameter *,const char *,int);
extern "C" void nvk_ngx_set_ui(NVSDK_NGX_Parameter *,const char *,unsigned);
extern "C" void nvk_ngx_set_f(NVSDK_NGX_Parameter *,const char *,float);
extern "C" void nvk_ngx_set_resource(NVSDK_NGX_Parameter *,const char *,ID3D12Resource *);
static void check(HRESULT hr,const char *where) {
    if(FAILED(hr)){char s[160];snprintf(s,sizeof s,"%s: 0x%08lx",where,(unsigned long)hr);throw std::runtime_error(s);}
}
static void ngxCheck(NVSDK_NGX_Result value,const char *where) {
    printf("DLSS_%s 0x%08x\n",where,value);
    if(value!=NVSDK_NGX_Result_Success)throw std::runtime_error(where);
}
template<class T> static T symbol(HMODULE dll,const char *name) {
    auto p=GetProcAddress(dll,name);if(!p)throw std::runtime_error(name);return reinterpret_cast<T>(p);
}
static void transition(ID3D12GraphicsCommandList *list,ID3D12Resource *image,D3D12_RESOURCE_STATES from,D3D12_RESOURCE_STATES to) {
    D3D12_RESOURCE_BARRIER b{};b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition={image,D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES,from,to};list->ResourceBarrier(1,&b);
}
static ComPtr<ID3D12Resource> resource(ID3D12Device *device,const D3D12_RESOURCE_DESC &desc,D3D12_HEAP_TYPE type,D3D12_RESOURCE_STATES state) {
    D3D12_HEAP_PROPERTIES heap{};heap.Type=type;heap.CreationNodeMask=heap.VisibleNodeMask=1;
    ComPtr<ID3D12Resource> result;
    check(device->CreateCommittedResource(&heap,D3D12_HEAP_FLAG_NONE,&desc,state,nullptr,IID_PPV_ARGS(&result)),"resource allocation");return result;
}
static ComPtr<ID3D12Resource> texture(ID3D12Device *device,UINT width,UINT height,DXGI_FORMAT format,bool output=false) {
    D3D12_RESOURCE_DESC d{};d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D;d.Width=width;d.Height=height;
    d.DepthOrArraySize=d.MipLevels=d.SampleDesc.Count=1;d.Format=format;
    d.Flags=output?D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS:D3D12_RESOURCE_FLAG_ALLOW_RENDER_TARGET;
    return resource(device,d,D3D12_HEAP_TYPE_DEFAULT,output?D3D12_RESOURCE_STATE_UNORDERED_ACCESS:D3D12_RESOURCE_STATE_RENDER_TARGET);
}
static float half(std::uint16_t bits) {
    const unsigned e=(bits>>10)&31,m=bits&1023;
    if(e==31)return NAN;
    const float f=e?std::ldexp(float(1024+m),int(e)-25):std::ldexp(float(m),-24);
    return bits&0x8000?-f:f;
}
void nvk_ngx_evaluate(HMODULE dll,ID3D12Device *device,NVSDK_NGX_Parameter *p) {
    constexpr UINT iw=320,ih=180,ow=640,oh=360;
    D3D12_COMMAND_QUEUE_DESC q{};q.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
    ComPtr<ID3D12CommandQueue> queue;check(device->CreateCommandQueue(&q,IID_PPV_ARGS(&queue)),"DLSS queue");
    ComPtr<ID3D12CommandAllocator> allocator;check(device->CreateCommandAllocator(q.Type,IID_PPV_ARGS(&allocator)),"allocator");
    ComPtr<ID3D12GraphicsCommandList> list;check(device->CreateCommandList(0,q.Type,allocator.Get(),nullptr,IID_PPV_ARGS(&list)),"commands");
    ComPtr<ID3D12Fence> fence;check(device->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(&fence)),"fence");
    struct Event {HANDLE value=CreateEventW(nullptr,FALSE,FALSE,nullptr);~Event(){if(value)CloseHandle(value);}} event;
    if(!event.value)throw std::runtime_error("Fence event allocation");UINT64 seq=0;
    auto submit=[&] {
        check(list->Close(),"close commands");ID3D12CommandList *commands[]={list.Get()};queue->ExecuteCommandLists(1,commands);
        check(queue->Signal(fence.Get(),++seq),"signal");check(fence->SetEventOnCompletion(seq,event.value),"fence completion");
        if(WaitForSingleObject(event.value,10000)!=WAIT_OBJECT_0)throw std::runtime_error("DLSS GPU fence timed out");
        check(device->GetDeviceRemovedReason(),"device health");
    };
    auto reset=[&]{check(allocator->Reset(),"allocator reset");check(list->Reset(allocator.Get(),nullptr),"command reset");};
    nvk_ngx_set_ui(p,NVSDK_NGX_Parameter_CreationNodeMask,1);nvk_ngx_set_ui(p,NVSDK_NGX_Parameter_VisibilityNodeMask,1);
    nvk_ngx_set_ui(p,NVSDK_NGX_Parameter_Width,iw);nvk_ngx_set_ui(p,NVSDK_NGX_Parameter_Height,ih);
    nvk_ngx_set_ui(p,NVSDK_NGX_Parameter_OutWidth,ow);nvk_ngx_set_ui(p,NVSDK_NGX_Parameter_OutHeight,oh);
    nvk_ngx_set_i(p,NVSDK_NGX_Parameter_PerfQualityValue,NVSDK_NGX_PerfQuality_Value_MaxPerf);
    nvk_ngx_set_i(p,NVSDK_NGX_Parameter_DLSS_Feature_Create_Flags,NVSDK_NGX_DLSS_Feature_Flags_IsHDR|NVSDK_NGX_DLSS_Feature_Flags_MVLowRes);
    nvk_ngx_set_i(p,NVSDK_NGX_Parameter_DLSS_Enable_Output_Subrects,0);
    size_t scratchBytes=0;
    ngxCheck(symbol<decltype(&NVSDK_NGX_D3D12_GetScratchBufferSize)>(dll,"NVSDK_NGX_D3D12_GetScratchBufferSize")(NVSDK_NGX_Feature_SuperSampling,p,&scratchBytes),"SCRATCH_QUERY");
    // Current DLSS SR uses no application scratch allocation. Refuse an unknown
    // requirement instead of guessing the core DLL's scratch parameter ABI.
    printf("DLSS_SCRATCH_BYTES %zu\n",scratchBytes);
    if(scratchBytes)throw std::runtime_error("DLSS requires application scratch storage");
    NVSDK_NGX_Handle *feature=nullptr;
    ngxCheck(symbol<decltype(&NVSDK_NGX_D3D12_CreateFeature)>(dll,"NVSDK_NGX_D3D12_CreateFeature")(list.Get(),NVSDK_NGX_Feature_SuperSampling,p,&feature),"CREATE");
    if(!feature)throw std::runtime_error("DLSS returned no feature");submit();reset();
    auto color=texture(device,iw,ih,DXGI_FORMAT_R16G16B16A16_FLOAT);
    auto depth=texture(device,iw,ih,DXGI_FORMAT_R32_FLOAT);
    auto motion=texture(device,iw,ih,DXGI_FORMAT_R16G16_FLOAT);
    auto exposure=texture(device,1,1,DXGI_FORMAT_R32_FLOAT);
    auto output=texture(device,ow,oh,DXGI_FORMAT_R16G16B16A16_FLOAT,true);
    ID3D12Resource *inputs[]={color.Get(),depth.Get(),motion.Get(),exposure.Get()};
    D3D12_DESCRIPTOR_HEAP_DESC hd{};hd.Type=D3D12_DESCRIPTOR_HEAP_TYPE_RTV;hd.NumDescriptors=4;
    ComPtr<ID3D12DescriptorHeap> heap;check(device->CreateDescriptorHeap(&hd,IID_PPV_ARGS(&heap)),"RTV heap");
    auto handle=heap->GetCPUDescriptorHandleForHeapStart();const UINT stride=device->GetDescriptorHandleIncrementSize(hd.Type);
    const float clears[4][4]={{.25f,.5f,.75f,1},{.5f,0,0,0},{0,0,0,0},{1,0,0,0}};
    for(unsigned i=0;i<4;++i) {
        device->CreateRenderTargetView(inputs[i],nullptr,handle);list->ClearRenderTargetView(handle,clears[i],0,nullptr);
        if(i==0){const float right[]={.75f,.25f,.5f,1};D3D12_RECT rect{iw/2,0,iw,ih};list->ClearRenderTargetView(handle,right,1,&rect);}
        transition(list.Get(),inputs[i],D3D12_RESOURCE_STATE_RENDER_TARGET,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);handle.ptr+=stride;
    }
    nvk_ngx_set_resource(p,NVSDK_NGX_Parameter_Color,color.Get());nvk_ngx_set_resource(p,NVSDK_NGX_Parameter_Output,output.Get());
    nvk_ngx_set_resource(p,NVSDK_NGX_Parameter_Depth,depth.Get());nvk_ngx_set_resource(p,NVSDK_NGX_Parameter_MotionVectors,motion.Get());
    nvk_ngx_set_resource(p,NVSDK_NGX_Parameter_ExposureTexture,exposure.Get());
    nvk_ngx_set_f(p,NVSDK_NGX_Parameter_MV_Scale_X,1);nvk_ngx_set_f(p,NVSDK_NGX_Parameter_MV_Scale_Y,1);
    nvk_ngx_set_f(p,NVSDK_NGX_Parameter_Jitter_Offset_X,0);nvk_ngx_set_f(p,NVSDK_NGX_Parameter_Jitter_Offset_Y,0);
    nvk_ngx_set_f(p,NVSDK_NGX_Parameter_DLSS_Pre_Exposure,1);nvk_ngx_set_f(p,NVSDK_NGX_Parameter_DLSS_Exposure_Scale,1);
    nvk_ngx_set_f(p,NVSDK_NGX_Parameter_FrameTimeDeltaInMsec,16.667f);
    nvk_ngx_set_ui(p,NVSDK_NGX_Parameter_DLSS_Render_Subrect_Dimensions_Width,iw);
    nvk_ngx_set_ui(p,NVSDK_NGX_Parameter_DLSS_Render_Subrect_Dimensions_Height,ih);
    using Evaluate=NVSDK_NGX_Result (NVSDK_CONV *)(ID3D12GraphicsCommandList *,const NVSDK_NGX_Handle *,const NVSDK_NGX_Parameter *,void *);
    auto evaluate=symbol<Evaluate>(dll,"NVSDK_NGX_D3D12_EvaluateFeature");
    for(unsigned frame=0;frame<3;++frame) {
        nvk_ngx_set_i(p,NVSDK_NGX_Parameter_Reset,frame==0);
        ngxCheck(evaluate(list.Get(),feature,p,nullptr),"EVALUATE");submit();reset();
    }
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};UINT64 bytes=0;auto desc=output->GetDesc();
    device->GetCopyableFootprints(&desc,0,1,0,&footprint,nullptr,nullptr,&bytes);
    D3D12_RESOURCE_DESC bd{};bd.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER;bd.Width=bytes;
    bd.Height=bd.DepthOrArraySize=bd.MipLevels=bd.SampleDesc.Count=1;bd.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    auto readback=resource(device,bd,D3D12_HEAP_TYPE_READBACK,D3D12_RESOURCE_STATE_COPY_DEST);
    transition(list.Get(),output.Get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
    D3D12_TEXTURE_COPY_LOCATION src{},dst{};src.pResource=output.Get();src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
    dst.pResource=readback.Get();dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT;dst.PlacedFootprint=footprint;
    list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);submit();
    void *mapped=nullptr;D3D12_RANGE range{0,SIZE_T(bytes)};check(readback->Map(0,&range,&mapped),"DLSS readback");
    unsigned checked=0,bad=0;
    for(UINT y=oh/4;y<3*oh/4;y+=7)for(UINT x=ow/8;x<7*ow/8;x+=7) {
        if(x>ow/2-32&&x<ow/2+32)continue;
        const auto *pixel=reinterpret_cast<const std::uint16_t *>(static_cast<const unsigned char *>(mapped)+footprint.Offset+y*footprint.Footprint.RowPitch+x*8);
        const float *expected=clears[0];const float right[]={.75f,.25f,.5f};if(x>ow/2)expected=right;
        for(unsigned c=0;c<3;++c){const float value=half(pixel[c]);if(!std::isfinite(value)||fabsf(value-expected[c])>.15f)++bad;++checked;}
    }
    for(UINT x:{ow/4,3*ow/4}){
        auto pixel=reinterpret_cast<const std::uint16_t *>(static_cast<const unsigned char *>(mapped)+footprint.Offset+(oh/2)*footprint.Footprint.RowPitch+x*8);
        printf("DLSS_PIXEL x=%u rgb=%.4f,%.4f,%.4f\n",x,half(pixel[0]),half(pixel[1]),half(pixel[2]));
    }
    D3D12_RANGE noWrites{};readback->Unmap(0,&noWrites);
    ngxCheck(symbol<decltype(&NVSDK_NGX_D3D12_ReleaseFeature)>(dll,"NVSDK_NGX_D3D12_ReleaseFeature")(feature),"RELEASE");
    printf("DLSS_READBACK checked=%u mismatches=%u frames=3 input=%ux%u output=%ux%u\n",checked,bad,iw,ih,ow,oh);
    if(bad||!checked)throw std::runtime_error("DLSS SR readback mismatch");puts("RESULT DLSS_EVALUATION_PASS");
}
