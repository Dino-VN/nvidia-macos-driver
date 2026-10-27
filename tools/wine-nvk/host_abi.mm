#define VK_NO_PROTOTYPES
#define VK_USE_PLATFORM_METAL_EXT
#include <vulkan/vulkan.h>
#import <Foundation/Foundation.h>
#include <dlfcn.h>
#include <cstdio>
#include <stdexcept>
#include <string>
#include <vector>

static void checked(VkResult result, const char *name) {
    if (result != VK_SUCCESS) throw std::runtime_error(std::string(name)+": "+std::to_string(result));
}
template<class T> static T required(PFN_vkVoidFunction fn,const char *name) {
    if (!fn) throw std::runtime_error(std::string("Missing function: ")+name);
    return reinterpret_cast<T>(fn);
}
static NSString *owner(void *fn) {
    Dl_info info{};
    return fn && dladdr(fn,&info) && info.dli_fname ? @(info.dli_fname) : @"";
}
int main(int argc,char **argv) { @autoreleasepool {
    NSMutableDictionary *report=[NSMutableDictionary dictionary];
    int status=0;
    try {
        if (argc!=2) throw std::runtime_error("Usage: host-abi /absolute/libnvk_wine.dylib");
        void *library=dlopen(argv[1],RTLD_NOW|RTLD_LOCAL|RTLD_FIRST);
        if (!library) throw std::runtime_error(dlerror());
        auto gipa=reinterpret_cast<PFN_vkGetInstanceProcAddr>(dlsym(library,"vkGetInstanceProcAddr"));
        if (!gipa) throw std::runtime_error("Missing vkGetInstanceProcAddr export");
        report[@"entry_owner"]=owner((void *)gipa);
        NSMutableDictionary *exports=[NSMutableDictionary dictionary];
        for (const char *name:{"vkGetInstanceProcAddr","vkGetDeviceProcAddr","vkCreateMetalSurfaceEXT"}) {
            void *fn=dlsym(library,name);
            exports[@(name)]=@{@"available":@(fn!=nullptr),@"owner":owner(fn)};
        }
        report[@"direct_exports"]=exports;
#define GLOBAL(name) required<PFN_vk##name>(gipa(VK_NULL_HANDLE,"vk" #name),"vk" #name)
        uint32_t version=VK_API_VERSION_1_0;
        if (auto fn=(PFN_vkEnumerateInstanceVersion)gipa(VK_NULL_HANDLE,"vkEnumerateInstanceVersion")) checked(fn(&version),"instance version");
        report[@"instance_api"]=@(version);
        uint32_t count=0; checked(GLOBAL(EnumerateInstanceExtensionProperties)(nullptr,&count,nullptr),"instance extension count");
        std::vector<VkExtensionProperties> ie(count); checked(GLOBAL(EnumerateInstanceExtensionProperties)(nullptr,&count,ie.data()),"instance extensions");
        NSMutableArray *instanceExtensions=[NSMutableArray array];
        for (const auto &e:ie) [instanceExtensions addObject:@(e.extensionName)];
        report[@"instance_extensions"]=instanceExtensions;
        VkApplicationInfo app{VK_STRUCTURE_TYPE_APPLICATION_INFO}; app.pApplicationName="NVK Wine host qualification"; app.apiVersion=version;
        const char *extensions[]={VK_KHR_SURFACE_EXTENSION_NAME,VK_EXT_METAL_SURFACE_EXTENSION_NAME};
        VkInstanceCreateInfo ici{VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO};ici.pApplicationInfo=&app;ici.enabledExtensionCount=2;ici.ppEnabledExtensionNames=extensions;
        VkInstance instance{}; checked(GLOBAL(CreateInstance)(&ici,nullptr,&instance),"create instance");
#define IP(name) required<PFN_vk##name>(gipa(instance,"vk" #name),"vk" #name)
        auto metalSurface=gipa(instance,"vkCreateMetalSurfaceEXT");
        report[@"metal_surface_gipa_owner"]=owner((void *)metalSurface);
        report[@"direct_metal_matches_gipa"]=@((void *)metalSurface==dlsym(library,"vkCreateMetalSurfaceEXT"));
        checked(IP(EnumeratePhysicalDevices)(instance,&count,nullptr),"device count");
        std::vector<VkPhysicalDevice> physicals(count);checked(IP(EnumeratePhysicalDevices)(instance,&count,physicals.data()),"devices");
        NSMutableArray *deviceReports=[NSMutableArray array];bool verifiedNvidia=false;
        for (VkPhysicalDevice physical:physicals) {
            VkPhysicalDeviceProperties props{};IP(GetPhysicalDeviceProperties)(physical,&props);
            NSMutableDictionary *deviceReport=[@{@"name":@(props.deviceName),@"vendor_id":@(props.vendorID),@"device_id":@(props.deviceID),
                @"api_version":@(props.apiVersion),@"driver_version":@(props.driverVersion),@"max_push_constants":@(props.limits.maxPushConstantsSize)} mutableCopy];
            VkPhysicalDeviceFeatures2 f{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_FEATURES_2};
            VkPhysicalDeviceVulkan11Features f11{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_1_FEATURES};
            VkPhysicalDeviceVulkan12Features f12{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_2_FEATURES};
            VkPhysicalDeviceVulkan13Features f13{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_3_FEATURES};
            VkPhysicalDeviceVulkan14Features f14{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_VULKAN_1_4_FEATURES};
            VkPhysicalDeviceRobustness2FeaturesEXT robust{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_ROBUSTNESS_2_FEATURES_EXT};
            VkPhysicalDeviceTransformFeedbackFeaturesEXT tf{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_TRANSFORM_FEEDBACK_FEATURES_EXT};
            VkPhysicalDeviceDepthClipEnableFeaturesEXT clip{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_DEPTH_CLIP_ENABLE_FEATURES_EXT};
            f.pNext=&f11;f11.pNext=&f12;f12.pNext=&f13;
            if (props.apiVersion>=VK_API_VERSION_1_4) { f13.pNext=&f14; f14.pNext=&robust; } else f13.pNext=&robust;
            robust.pNext=&tf;tf.pNext=&clip;IP(GetPhysicalDeviceFeatures2)(physical,&f);
            deviceReport[@"features"]=@{@"shaderInt16":@(f.features.shaderInt16),@"shaderInt64":@(f.features.shaderInt64),
                @"descriptorIndexing":@(f12.descriptorIndexing),@"scalarBlockLayout":@(f12.scalarBlockLayout),
                @"timelineSemaphore":@(f12.timelineSemaphore),@"bufferDeviceAddress":@(f12.bufferDeviceAddress),
                @"dynamicRendering":@(f13.dynamicRendering),@"synchronization2":@(f13.synchronization2),
                @"maintenance5":@(f14.maintenance5),@"maintenance6":@(f14.maintenance6),
                @"robustBufferAccess2":@(robust.robustBufferAccess2),@"nullDescriptor":@(robust.nullDescriptor),
                @"transformFeedback":@(tf.transformFeedback),@"geometryStreams":@(tf.geometryStreams),@"depthClipEnable":@(clip.depthClipEnable)};
            checked(IP(EnumerateDeviceExtensionProperties)(physical,nullptr,&count,nullptr),"device extension count");
            std::vector<VkExtensionProperties> de(count);checked(IP(EnumerateDeviceExtensionProperties)(physical,nullptr,&count,de.data()),"device extensions");
            NSMutableArray *deviceExtensions=[NSMutableArray array];for (const auto &e:de) [deviceExtensions addObject:@(e.extensionName)];
            deviceReport[@"extensions"]=deviceExtensions;
            deviceReport[@"render_function_owner"]=owner((void *)IP(GetPhysicalDeviceProperties));
            if (props.vendorID==0x10de) {
                IP(GetPhysicalDeviceQueueFamilyProperties)(physical,&count,nullptr);std::vector<VkQueueFamilyProperties> families(count);
                IP(GetPhysicalDeviceQueueFamilyProperties)(physical,&count,families.data());uint32_t family=UINT32_MAX;
                for (uint32_t i=0;i<count;++i) if (families[i].queueFlags&VK_QUEUE_GRAPHICS_BIT) {family=i;break;}
                if (family==UINT32_MAX) throw std::runtime_error("No graphics queue");
                float priority=1;
                VkDeviceQueueCreateInfo qci{VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO};qci.queueFamilyIndex=family;qci.queueCount=1;qci.pQueuePriorities=&priority;
                VkDeviceCreateInfo dci{VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO};dci.queueCreateInfoCount=1;dci.pQueueCreateInfos=&qci;
                VkDevice device{};checked(IP(CreateDevice)(physical,&dci,nullptr,&device),"create device");
                auto gdpa=IP(GetDeviceProcAddr);
#define DP(name) required<PFN_vk##name>(gdpa(device,"vk" #name),"vk" #name)
                VkQueue queue{};DP(GetDeviceQueue)(device,family,0,&queue);
                VkBufferCreateInfo bci{VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO};bci.size=4096;bci.usage=VK_BUFFER_USAGE_TRANSFER_DST_BIT;
                VkBuffer buffer{};checked(DP(CreateBuffer)(device,&bci,nullptr,&buffer),"create buffer");
                VkMemoryRequirements req{};DP(GetBufferMemoryRequirements)(device,buffer,&req);
                VkPhysicalDeviceMemoryProperties mem{};IP(GetPhysicalDeviceMemoryProperties)(physical,&mem);uint32_t type=UINT32_MAX;
                for (uint32_t i=0;i<mem.memoryTypeCount;++i) if ((req.memoryTypeBits&(1u<<i)) &&
                    (mem.memoryTypes[i].propertyFlags&(VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT))==
                    (VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT|VK_MEMORY_PROPERTY_HOST_COHERENT_BIT)) {type=i;break;}
                if (type==UINT32_MAX) throw std::runtime_error("No coherent host-visible memory");
                VkMemoryAllocateInfo mai{VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO};mai.allocationSize=req.size;mai.memoryTypeIndex=type;
                VkDeviceMemory memory{};checked(DP(AllocateMemory)(device,&mai,nullptr,&memory),"allocate buffer");checked(DP(BindBufferMemory)(device,buffer,memory,0),"bind buffer");
                VkCommandPoolCreateInfo pci{VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO};pci.queueFamilyIndex=family;VkCommandPool pool{};checked(DP(CreateCommandPool)(device,&pci,nullptr,&pool),"create pool");
                VkCommandBufferAllocateInfo cai{VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO};cai.commandPool=pool;cai.level=VK_COMMAND_BUFFER_LEVEL_PRIMARY;cai.commandBufferCount=1;
                VkCommandBuffer command{};checked(DP(AllocateCommandBuffers)(device,&cai,&command),"allocate commands");
                VkCommandBufferBeginInfo begin{VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO};checked(DP(BeginCommandBuffer)(command,&begin),"begin");
                DP(CmdFillBuffer)(command,buffer,0,4096,0x6e766b31);
                VkMemoryBarrier barrier{VK_STRUCTURE_TYPE_MEMORY_BARRIER};barrier.srcAccessMask=VK_ACCESS_TRANSFER_WRITE_BIT;barrier.dstAccessMask=VK_ACCESS_HOST_READ_BIT;
                DP(CmdPipelineBarrier)(command,VK_PIPELINE_STAGE_TRANSFER_BIT,VK_PIPELINE_STAGE_HOST_BIT,0,1,&barrier,0,nullptr,0,nullptr);
                checked(DP(EndCommandBuffer)(command),"end");VkFenceCreateInfo fi{VK_STRUCTURE_TYPE_FENCE_CREATE_INFO};VkFence fence{};checked(DP(CreateFence)(device,&fi,nullptr,&fence),"fence");
                VkSubmitInfo si{VK_STRUCTURE_TYPE_SUBMIT_INFO};si.commandBufferCount=1;si.pCommandBuffers=&command;checked(DP(QueueSubmit)(queue,1,&si,fence),"submit");
                checked(DP(WaitForFences)(device,1,&fence,VK_TRUE,5000000000ull),"GPU completion");
                void *mapped=nullptr;checked(DP(MapMemory)(device,memory,0,4096,0,&mapped),"map");
                bool matched=true;for(unsigned i=0;i<1024;++i) if (((uint32_t *)mapped)[i]!=0x6e766b31) matched=false;
                DP(UnmapMemory)(device,memory);
                if (!matched) throw std::runtime_error("GPU fill readback mismatch");
                deviceReport[@"gpu_fill_checked_words"]=@1024;
                verifiedNvidia=true;
                deviceReport[@"submit_owner"]=owner((void *)DP(QueueSubmit));
                DP(DestroyFence)(device,fence,nullptr);DP(DestroyCommandPool)(device,pool,nullptr);
                DP(DestroyBuffer)(device,buffer,nullptr);DP(FreeMemory)(device,memory,nullptr);DP(DestroyDevice)(device,nullptr);
            }
            [deviceReports addObject:deviceReport];
        }
        if (!verifiedNvidia) throw std::runtime_error("No NVIDIA GPU completed the readback test");
        report[@"devices"]=deviceReports;report[@"result"]=@"PASS";
        IP(DestroyInstance)(instance,nullptr);
    } catch (const std::exception &e) { report[@"result"]=@"FAIL";report[@"error"]=@(e.what());status=1; }
    NSData *json=[NSJSONSerialization dataWithJSONObject:report options:NSJSONWritingPrettyPrinted|NSJSONWritingSortedKeys error:nil];
    fwrite(json.bytes,1,json.length,stdout);putchar('\n');return status;
} }
