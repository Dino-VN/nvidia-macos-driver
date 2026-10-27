#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#define VK_NO_PROTOTYPES
#define VK_USE_PLATFORM_WIN32_KHR
#include <vulkan/vulkan.h>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

static void check(VkResult r,const char *where) {
    if (r!=VK_SUCCESS) throw std::runtime_error(std::string(where)+": "+std::to_string(r));
}
static void require(bool value,const char *message) { if (!value) throw std::runtime_error(message); }
static void pump() { MSG msg;while (PeekMessageW(&msg,nullptr,0,0,PM_REMOVE)) {TranslateMessage(&msg);DispatchMessageW(&msg);} }
static void delay(unsigned ms) { for (unsigned i=0;i<ms;i+=10) {pump();Sleep(10);} }
template<class T> static T function(PFN_vkVoidFunction ptr,const char *name) {
    if (!ptr) throw std::runtime_error(std::string("Missing ")+name);return reinterpret_cast<T>(ptr);
}
struct Api {
    PFN_vkGetInstanceProcAddr gipa{};PFN_vkGetDeviceProcAddr gdpa{};
    VkInstance instance{};VkPhysicalDevice physical{};VkDevice device{};VkQueue queue{};uint32_t family{};
    VkPhysicalDeviceMemoryProperties memory{};
#define INSTANCE_COMMON(X) X(DestroyInstance) X(EnumeratePhysicalDevices) X(GetPhysicalDeviceProperties) \
    X(GetPhysicalDeviceFeatures2) X(GetPhysicalDeviceMemoryProperties) X(GetPhysicalDeviceQueueFamilyProperties) \
    X(EnumerateDeviceExtensionProperties) X(CreateDevice)
#define INSTANCE_WSI(X) X(CreateWin32SurfaceKHR) X(DestroySurfaceKHR) \
    X(GetPhysicalDeviceSurfaceSupportKHR) X(GetPhysicalDeviceSurfaceCapabilitiesKHR) X(GetPhysicalDeviceSurfaceFormatsKHR)
#define DEVICE_FUNCTIONS(X) X(DestroyDevice) X(GetDeviceQueue) X(DeviceWaitIdle) X(CreateBuffer) X(DestroyBuffer) \
    X(GetBufferMemoryRequirements) X(AllocateMemory) X(FreeMemory) X(BindBufferMemory) X(MapMemory) X(UnmapMemory) \
    X(CreateCommandPool) X(DestroyCommandPool) X(AllocateCommandBuffers) X(ResetCommandPool) X(BeginCommandBuffer) \
    X(EndCommandBuffer) X(CmdFillBuffer) X(CmdPipelineBarrier) X(CmdClearColorImage) X(QueueSubmit) X(QueueSubmit2) \
    X(CreateFence) X(DestroyFence) X(WaitForFences) X(ResetFences) X(CreateSemaphore) X(DestroySemaphore) \
    X(CreateSwapchainKHR) X(DestroySwapchainKHR) X(GetSwapchainImagesKHR) X(AcquireNextImageKHR) X(QueuePresentKHR)
#define DECL(name) PFN_vk##name name{};
    INSTANCE_COMMON(DECL) INSTANCE_WSI(DECL) DEVICE_FUNCTIONS(DECL)
#undef DECL
    void init(bool windowed) {
        HMODULE library=LoadLibraryW(L"vulkan-1.dll");require(library!=nullptr,"Cannot load vulkan-1.dll");
        char path[32768]{};GetModuleFileNameA(library,path,sizeof path);printf("VULKAN_DLL %s\n",path);
        gipa=reinterpret_cast<PFN_vkGetInstanceProcAddr>(GetProcAddress(library,"vkGetInstanceProcAddr"));require(gipa,"Missing gipa");
#define GLOBAL(name) function<PFN_vk##name>(gipa(VK_NULL_HANDLE,"vk" #name),"vk" #name)
        uint32_t version=VK_API_VERSION_1_0;
        if (auto fn=(PFN_vkEnumerateInstanceVersion)gipa(VK_NULL_HANDLE,"vkEnumerateInstanceVersion")) check(fn(&version),"version");
        printf("INSTANCE_API %u.%u.%u\n",VK_API_VERSION_MAJOR(version),VK_API_VERSION_MINOR(version),VK_API_VERSION_PATCH(version));
        require(version>=VK_API_VERSION_1_3,"Vulkan 1.3 required for this probe");
        uint32_t count=0;check(GLOBAL(EnumerateInstanceExtensionProperties)(nullptr,&count,nullptr),"instance extensions");
        std::vector<VkExtensionProperties> extensions(count);check(GLOBAL(EnumerateInstanceExtensionProperties)(nullptr,&count,extensions.data()),"instance extensions");
        for (auto &e:extensions) printf("INSTANCE_EXTENSION %s\n",e.extensionName);
        const char *names[]={VK_KHR_SURFACE_EXTENSION_NAME,VK_KHR_WIN32_SURFACE_EXTENSION_NAME};
        VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO};app.apiVersion=std::min(version,VK_API_VERSION_1_4);app.pApplicationName="Wine native NVK probe";
        VkInstanceCreateInfo ici{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};ici.pApplicationInfo=&app;
        if (windowed) {ici.enabledExtensionCount=2;ici.ppEnabledExtensionNames=names;}
        check(GLOBAL(CreateInstance)(&ici,nullptr,&instance),"create instance");
#define LOAD(name) name=function<PFN_vk##name>(gipa(instance,"vk" #name),"vk" #name);
        INSTANCE_COMMON(LOAD)
        if (windowed) {INSTANCE_WSI(LOAD)}
#undef LOAD
        check(EnumeratePhysicalDevices(instance,&count,nullptr),"device count");require(count>0,"No Vulkan GPU");
        std::vector<VkPhysicalDevice> physicals(count);check(EnumeratePhysicalDevices(instance,&count,physicals.data()),"devices");
        for (auto p:physicals) {
            VkPhysicalDeviceProperties props{};GetPhysicalDeviceProperties(p,&props);
            printf("GPU %s vendor=0x%x device=0x%x api=%u.%u.%u push_constants=%u\n",props.deviceName,props.vendorID,props.deviceID,
                VK_API_VERSION_MAJOR(props.apiVersion),VK_API_VERSION_MINOR(props.apiVersion),VK_API_VERSION_PATCH(props.apiVersion),props.limits.maxPushConstantsSize);
            if (props.vendorID==0x10de) physical=p;
        }
        require(physical,"No NVIDIA Vulkan device");GetPhysicalDeviceMemoryProperties(physical,&memory);
        check(EnumerateDeviceExtensionProperties(physical,nullptr,&count,nullptr),"device extensions");extensions.resize(count);
        check(EnumerateDeviceExtensionProperties(physical,nullptr,&count,extensions.data()),"device extensions");
        for (auto &e:extensions) printf("DEVICE_EXTENSION %s\n",e.extensionName);
        VkPhysicalDeviceFeatures2 features{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2};
        VkPhysicalDeviceVulkan12Features f12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
        VkPhysicalDeviceVulkan13Features f13{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES};features.pNext=&f12;f12.pNext=&f13;
        GetPhysicalDeviceFeatures2(physical,&features);
        printf("FEATURES descriptorIndexing=%u scalarBlockLayout=%u timelineSemaphore=%u bufferDeviceAddress=%u synchronization2=%u dynamicRendering=%u\n",
            f12.descriptorIndexing,f12.scalarBlockLayout,f12.timelineSemaphore,f12.bufferDeviceAddress,f13.synchronization2,f13.dynamicRendering);
        require(f13.synchronization2,"Synchronization2 required for alias qualification");
        GetPhysicalDeviceQueueFamilyProperties(physical,&count,nullptr);std::vector<VkQueueFamilyProperties> queues(count);
        GetPhysicalDeviceQueueFamilyProperties(physical,&count,queues.data());family=UINT32_MAX;
        for (uint32_t i=0;i<count;++i) if ((queues[i].queueFlags&3)==3 && queues[i].queueCount) {family=i;break;}
        require(family!=UINT32_MAX,"No graphics/compute queue");
        float priority=1;VkDeviceQueueCreateInfo qci{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};qci.queueFamilyIndex=family;qci.queueCount=1;qci.pQueuePriorities=&priority;
        VkPhysicalDeviceSynchronization2Features sync{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SYNCHRONIZATION_2_FEATURES};sync.synchronization2=VK_TRUE;
        const char *deviceExtensions[]={VK_KHR_SYNCHRONIZATION_2_EXTENSION_NAME,VK_KHR_SWAPCHAIN_EXTENSION_NAME};
        VkDeviceCreateInfo dci{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};dci.pNext=&sync;dci.queueCreateInfoCount=1;dci.pQueueCreateInfos=&qci;
        dci.enabledExtensionCount=windowed?2:1;dci.ppEnabledExtensionNames=deviceExtensions;
        check(CreateDevice(physical,&dci,nullptr,&device),"create device");
        gdpa=function<PFN_vkGetDeviceProcAddr>(gipa(instance,"vkGetDeviceProcAddr"),"gdpa");
#define LOAD(name) name=function<PFN_vk##name>(gdpa(device,"vk" #name),"vk" #name);
        // WSI function pointers are unavailable on a headless device.
        if (windowed) {DEVICE_FUNCTIONS(LOAD)}
        else {
            LOAD(DestroyDevice) LOAD(GetDeviceQueue) LOAD(DeviceWaitIdle) LOAD(CreateBuffer) LOAD(DestroyBuffer)
            LOAD(GetBufferMemoryRequirements) LOAD(AllocateMemory) LOAD(FreeMemory) LOAD(BindBufferMemory) LOAD(MapMemory) LOAD(UnmapMemory)
            LOAD(CreateCommandPool) LOAD(DestroyCommandPool) LOAD(AllocateCommandBuffers) LOAD(ResetCommandPool) LOAD(BeginCommandBuffer)
            LOAD(EndCommandBuffer) LOAD(CmdFillBuffer) LOAD(CmdPipelineBarrier) LOAD(QueueSubmit) LOAD(QueueSubmit2)
            LOAD(CreateFence) LOAD(DestroyFence) LOAD(WaitForFences) LOAD(ResetFences)
        }
#undef LOAD
        GetDeviceQueue(device,family,0,&queue);
    }
    uint32_t memoryType(uint32_t bits) {
        for (uint32_t i=0;i<memory.memoryTypeCount;++i) if ((bits&(1u<<i)) &&
            (memory.memoryTypes[i].propertyFlags&6)==6) return i;
        throw std::runtime_error("No coherent host-visible memory");
    }
    void fill() {
        VkBufferCreateInfo b{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};b.size=4096;b.usage=VK_BUFFER_USAGE_TRANSFER_DST_BIT;
        VkBuffer buffer{};check(CreateBuffer(device,&b,nullptr,&buffer),"buffer");VkMemoryRequirements req{};GetBufferMemoryRequirements(device,buffer,&req);
        VkMemoryAllocateInfo ma{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};ma.allocationSize=req.size;ma.memoryTypeIndex=memoryType(req.memoryTypeBits);
        VkDeviceMemory allocation{};check(AllocateMemory(device,&ma,nullptr,&allocation),"memory");check(BindBufferMemory(device,buffer,allocation,0),"bind");
        VkCommandPoolCreateInfo pc{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};pc.queueFamilyIndex=family;VkCommandPool pool{};check(CreateCommandPool(device,&pc,nullptr,&pool),"pool");
        VkCommandBufferAllocateInfo ca{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};ca.commandPool=pool;ca.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;ca.commandBufferCount=1;
        VkCommandBuffer cb{};check(AllocateCommandBuffers(device,&ca,&cb),"commands");VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};check(BeginCommandBuffer(cb,&begin),"begin");
        CmdFillBuffer(cb,buffer,0,4096,0x4e564b57);
        VkMemoryBarrier barrier{VK_STRUCTURE_TYPE_MEMORY_BARRIER};barrier.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;barrier.dstAccessMask=VK_ACCESS_HOST_READ_BIT;
        CmdPipelineBarrier(cb,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&barrier,0,nullptr,0,nullptr);check(EndCommandBuffer(cb),"end");
        VkFenceCreateInfo fi{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};VkFence fence{};check(CreateFence(device,&fi,nullptr,&fence),"fence");
        VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO};si.commandBufferCount=1;si.pCommandBuffers=&cb;check(QueueSubmit(queue,1,&si,fence),"fill submit");
        check(WaitForFences(device,1,&fence,VK_TRUE,5000000000ull),"fill completion");void *mapped{};check(MapMemory(device,allocation,0,4096,0,&mapped),"map");
        bool good=true;for (unsigned i=0;i<1024;++i) if (((uint32_t *)mapped)[i]!=0x4e564b57) good=false;
        UnmapMemory(device,allocation);require(good,"GPU readback mismatch");
        DestroyFence(device,fence,nullptr);DestroyCommandPool(device,pool,nullptr);DestroyBuffer(device,buffer,nullptr);FreeMemory(device,allocation,nullptr);
        puts("PASS GPU fill/readback: 1024 words");
    }
};
struct Window {
    HWND hwnd{};VkSurfaceKHR surface{};VkSwapchainKHR chain{};std::vector<VkImage> images;std::vector<bool> initialized;
    void create(Api &a,unsigned index) {
        hwnd=CreateWindowExW(0,L"NVKWineProbe",index?L"NVK Wine second surface":L"NVK Wine changing frames",WS_OVERLAPPEDWINDOW|WS_VISIBLE,
            120+index*300,140+index*80,640,360,nullptr,nullptr,GetModuleHandleW(nullptr),nullptr);
        require(hwnd,"CreateWindow failed");
        VkWin32SurfaceCreateInfoKHR ci{VK_STRUCTURE_TYPE_WIN32_SURFACE_CREATE_INFO_KHR};ci.hinstance=GetModuleHandleW(nullptr);ci.hwnd=hwnd;
        check(a.CreateWin32SurfaceKHR(a.instance,&ci,nullptr,&surface),"Win32 surface");
        VkBool32 supported=0;check(a.GetPhysicalDeviceSurfaceSupportKHR(a.physical,a.family,surface,&supported),"surface support");require(supported,"Queue cannot present");
    }
    void recreate(Api &a,unsigned imageCount,bool immediate) {
        check(a.DeviceWaitIdle(a.device),"recreate idle");VkSurfaceCapabilitiesKHR caps{};
        check(a.GetPhysicalDeviceSurfaceCapabilitiesKHR(a.physical,surface,&caps),"surface caps");
        uint32_t count=0;check(a.GetPhysicalDeviceSurfaceFormatsKHR(a.physical,surface,&count,nullptr),"formats");
        std::vector<VkSurfaceFormatKHR> formats(count);check(a.GetPhysicalDeviceSurfaceFormatsKHR(a.physical,surface,&count,formats.data()),"formats");
        require(std::any_of(formats.begin(),formats.end(),[](auto &f){return f.format==VK_FORMAT_B8G8R8A8_UNORM && f.colorSpace==VK_COLOR_SPACE_SRGB_NONLINEAR_KHR;}),"No BGRA UNORM surface format");
        VkSwapchainCreateInfoKHR sc{VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR};sc.surface=surface;sc.minImageCount=imageCount;
        sc.imageFormat=VK_FORMAT_B8G8R8A8_UNORM;sc.imageColorSpace=VK_COLOR_SPACE_SRGB_NONLINEAR_KHR;sc.imageExtent=caps.currentExtent;
        if (sc.imageExtent.width==UINT32_MAX) {RECT rect;GetClientRect(hwnd,&rect);sc.imageExtent={(uint32_t)(rect.right-rect.left),(uint32_t)(rect.bottom-rect.top)};}
        sc.imageArrayLayers=1;sc.imageUsage=VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT|VK_IMAGE_USAGE_TRANSFER_DST_BIT;
        sc.imageSharingMode=VK_SHARING_MODE_EXCLUSIVE;sc.preTransform=VK_SURFACE_TRANSFORM_IDENTITY_BIT_KHR;
        sc.compositeAlpha=VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;sc.presentMode=immediate?VK_PRESENT_MODE_IMMEDIATE_KHR:VK_PRESENT_MODE_FIFO_KHR;sc.clipped=VK_TRUE;sc.oldSwapchain=chain;
        VkSwapchainKHR next{};check(a.CreateSwapchainKHR(a.device,&sc,nullptr,&next),"swapchain");if(chain)a.DestroySwapchainKHR(a.device,chain,nullptr);chain=next;
        check(a.GetSwapchainImagesKHR(a.device,chain,&count,nullptr),"image count");images.resize(count);initialized.assign(count,false);
        check(a.GetSwapchainImagesKHR(a.device,chain,&count,images.data()),"images");
        printf("SWAPCHAIN hwnd=%p extent=%ux%u images=%u mode=%s\n",hwnd,sc.imageExtent.width,sc.imageExtent.height,count,immediate?"immediate":"fifo");
    }
    void destroy(Api &a) {a.DestroySwapchainKHR(a.device,chain,nullptr);a.DestroySurfaceKHR(a.instance,surface,nullptr);DestroyWindow(hwnd);}
};
int main(int argc,char **argv) {
    setvbuf(stdout,nullptr,_IONBF,0);
    try {
        bool windowed=false,immediate=false;unsigned imageCount=3,frames=120,windowCount=1;
        for (int i=1;i<argc;++i) {
            if (!strcmp(argv[i],"--window")) windowed=true;
            else if (!strcmp(argv[i],"--immediate")) immediate=true;
            else if (!strcmp(argv[i],"--two-surfaces")) windowCount=2;
            else if (!strcmp(argv[i],"--images") && i+1<argc) imageCount=atoi(argv[++i]);
            else if (!strcmp(argv[i],"--frames") && i+1<argc) frames=atoi(argv[++i]);
            else throw std::runtime_error("Unknown argument");
        }
        require(imageCount>=2 && imageCount<=8 && frames>=6 && frames<=2000,"Invalid counts");
        Api a;a.init(windowed);a.fill();
        if (windowed) {
            WNDCLASSW wc{};wc.lpfnWndProc=DefWindowProcW;wc.hInstance=GetModuleHandleW(nullptr);wc.lpszClassName=L"NVKWineProbe";
            require(RegisterClassW(&wc),"RegisterClass failed");std::vector<Window> windows(windowCount);
            for (unsigned i=0;i<windowCount;++i) windows[i].create(a,i);
            delay(200);for(auto &w:windows)w.recreate(a,imageCount,immediate);
            VkCommandPoolCreateInfo pc{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};pc.queueFamilyIndex=a.family;pc.flags=VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;
            VkCommandPool pool{};check(a.CreateCommandPool(a.device,&pc,nullptr,&pool),"present pool");
            VkCommandBufferAllocateInfo ca{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};ca.commandPool=pool;ca.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;ca.commandBufferCount=1;
            VkCommandBuffer cb{};check(a.AllocateCommandBuffers(a.device,&ca,&cb),"present command");
            VkFenceCreateInfo fi{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};VkFence fence{};check(a.CreateFence(a.device,&fi,nullptr,&fence),"present fence");
            VkSemaphoreCreateInfo sci{VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO};std::vector<VkSemaphore> acquired(windowCount);VkSemaphore rendered{};
            for (auto &semaphore:acquired)check(a.CreateSemaphore(a.device,&sci,nullptr,&semaphore),"acquire semaphore");
            check(a.CreateSemaphore(a.device,&sci,nullptr,&rendered),"render semaphore");
            auto submit2KHR=(PFN_vkQueueSubmit2KHR)a.gdpa(a.device,"vkQueueSubmit2KHR");
            for (unsigned frame=0;frame<frames;++frame) {
                pump();
                if (frame==frames/3) {SetWindowPos(windows[0].hwnd,nullptr,0,0,800,450,SWP_NOMOVE|SWP_NOZORDER);delay(200);windows[0].recreate(a,imageCount,immediate);puts("PASS resize/recreation");}
                if (frame==2*frames/3) {ShowWindow(windows[0].hwnd,SW_MINIMIZE);delay(200);ShowWindow(windows[0].hwnd,SW_RESTORE);delay(200);windows[0].recreate(a,imageCount,immediate);puts("PASS minimize/restore/recreation");}
                std::vector<uint32_t> indices(windowCount);std::vector<VkSwapchainKHR> chains;std::vector<VkPipelineStageFlags> stages(windowCount,VK_PIPELINE_STAGE_TRANSFER_BIT);
                check(a.ResetCommandPool(a.device,pool,0),"reset pool");VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};check(a.BeginCommandBuffer(cb,&begin),"begin frame");
                for (unsigned j=0;j<windowCount;++j) {
                    auto &w=windows[j];check(a.AcquireNextImageKHR(a.device,w.chain,1000000000ull,acquired[j],VK_NULL_HANDLE,&indices[j]),"acquire");chains.push_back(w.chain);
                    VkImageMemoryBarrier b{VK_STRUCTURE_TYPE_IMAGE_MEMORY_BARRIER};b.oldLayout=w.initialized[indices[j]]?VK_IMAGE_LAYOUT_PRESENT_SRC_KHR:VK_IMAGE_LAYOUT_UNDEFINED;
                    b.newLayout=VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;b.dstAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;b.srcQueueFamilyIndex=b.dstQueueFamilyIndex=VK_QUEUE_FAMILY_IGNORED;
                    b.image=w.images[indices[j]];b.subresourceRange={VK_IMAGE_ASPECT_COLOR_BIT,0,1,0,1};
                    a.CmdPipelineBarrier(cb,VK_PIPELINE_STAGE_ALL_COMMANDS_BIT,VK_PIPELINE_STAGE_TRANSFER_BIT,0,0,nullptr,0,nullptr,1,&b);
                    float t=(frame%60)/59.f;VkClearColorValue color{{j?1.f-t:t,0.15f,j?t:1.f-t,1.f}};
                    a.CmdClearColorImage(cb,b.image,VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL,&color,1,&b.subresourceRange);
                    b.oldLayout=VK_IMAGE_LAYOUT_TRANSFER_DST_OPTIMAL;b.newLayout=VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;b.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;b.dstAccessMask=0;
                    a.CmdPipelineBarrier(cb,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_BOTTOM_OF_PIPE_BIT,0,0,nullptr,0,nullptr,1,&b);w.initialized[indices[j]]=true;
                }
                check(a.EndCommandBuffer(cb),"end frame");
                if (frame%3==0) {
                    VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO};si.waitSemaphoreCount=windowCount;si.pWaitSemaphores=acquired.data();si.pWaitDstStageMask=stages.data();
                    si.commandBufferCount=1;si.pCommandBuffers=&cb;si.signalSemaphoreCount=1;si.pSignalSemaphores=&rendered;check(a.QueueSubmit(a.queue,1,&si,fence),"submit");
                } else {
                    std::vector<VkSemaphoreSubmitInfo> waits(windowCount);for(unsigned j=0;j<windowCount;++j){waits[j]={VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO};waits[j].semaphore=acquired[j];waits[j].stageMask=VK_PIPELINE_STAGE_2_TRANSFER_BIT;}
                    VkSemaphoreSubmitInfo signal{VK_STRUCTURE_TYPE_SEMAPHORE_SUBMIT_INFO};signal.semaphore=rendered;signal.stageMask=VK_PIPELINE_STAGE_2_ALL_COMMANDS_BIT;
                    VkCommandBufferSubmitInfo command{VK_STRUCTURE_TYPE_COMMAND_BUFFER_SUBMIT_INFO};command.commandBuffer=cb;
                    VkSubmitInfo2 si{VK_STRUCTURE_TYPE_SUBMIT_INFO_2};si.waitSemaphoreInfoCount=windowCount;si.pWaitSemaphoreInfos=waits.data();si.commandBufferInfoCount=1;si.pCommandBufferInfos=&command;si.signalSemaphoreInfoCount=1;si.pSignalSemaphoreInfos=&signal;
                    if (frame%3==2 && submit2KHR) check(submit2KHR(a.queue,1,&si,fence),"submit2KHR");else check(a.QueueSubmit2(a.queue,1,&si,fence),"submit2");
                }
                VkPresentInfoKHR pi{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};pi.waitSemaphoreCount=1;pi.pWaitSemaphores=&rendered;pi.swapchainCount=windowCount;pi.pSwapchains=chains.data();pi.pImageIndices=indices.data();
                check(a.QueuePresentKHR(a.queue,&pi),"present");check(a.WaitForFences(a.device,1,&fence,VK_TRUE,5000000000ull),"render completion");check(a.ResetFences(a.device,1,&fence),"reset fence");
            }
            check(a.DeviceWaitIdle(a.device),"final idle");for(auto &w:windows)w.destroy(a);
            a.DestroyFence(a.device,fence,nullptr);a.DestroyCommandPool(a.device,pool,nullptr);for(auto semaphore:acquired)a.DestroySemaphore(a.device,semaphore,nullptr);a.DestroySemaphore(a.device,rendered,nullptr);
            printf("PASS presents=%u surfaces=%u images=%u submit_routes=legacy,core2,khr2-if-available\n",frames*windowCount,windowCount,imageCount);
        }
        a.DestroyDevice(a.device,nullptr);a.DestroyInstance(a.instance,nullptr);puts("RESULT PASS");return 0;
    } catch (const std::exception &e) {fprintf(stderr,"RESULT FAIL: %s\n",e.what());return 1;}
}
