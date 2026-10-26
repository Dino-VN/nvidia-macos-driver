#include "bridge.mm"
#include <cassert>

static int submits, waits, destroyed_semaphores;
static VkResult injected=VK_SUCCESS;
static VkResult fake_submit(VkQueue,uint32_t count,const VkSubmitInfo *infos,VkFence) {
   assert(count==1);
   if (infos->waitSemaphoreCount) assert(infos->pWaitSemaphores && infos->pWaitDstStageMask);
   submits++; return injected;
}
static VkResult fake_idle(VkQueue) { waits++;return VK_SUCCESS; }
static VkResult fake_semaphore(VkDevice,const VkSemaphoreCreateInfo *,const VkAllocationCallbacks *,VkSemaphore *out) {
   *out=(VkSemaphore)(uintptr_t)0x44;return VK_SUCCESS;
}
static void fake_destroy_semaphore(VkDevice,VkSemaphore,const VkAllocationCallbacks *) { destroyed_semaphores++; }
static PFN_vkVoidFunction fake_gdpa(VkDevice,const char *name) {
   if (!strcmp(name,"vkQueueSubmit")) return (PFN_vkVoidFunction)fake_submit;
   if (!strcmp(name,"vkQueueWaitIdle")) return (PFN_vkVoidFunction)fake_idle;
   if (!strcmp(name,"vkCreateSemaphore")) return (PFN_vkVoidFunction)fake_semaphore;
   if (!strcmp(name,"vkDestroySemaphore")) return (PFN_vkVoidFunction)fake_destroy_semaphore;
   return nullptr;
}
static PFN_vkVoidFunction fake_gipa(VkInstance,const char *) { return nullptr; }
static VkResult throw_oom() { throw std::bad_alloc(); }
static VkResult throw_error() { throw std::runtime_error("injected"); }

int main() { @autoreleasepool {
   std::call_once(backend_once,[]{});backend_gipa=fake_gipa;backend_gdpa=fake_gdpa;
   uint32_t count=0;int out=99;
   assert(enumerate(std::vector<int>{1,2},&count,&out)==VK_INCOMPLETE && count==0 && out==99);
   count=1;assert(enumerate(std::vector<int>{1,2},&count,&out)==VK_INCOMPLETE && count==1 && out==1);
   assert(enumerate(std::vector<int>{1,2},&count,(int *)nullptr)==VK_SUCCESS && count==2);
   puts("PASS bounded enumeration and zero-capacity writes");

   auto i=std::make_shared<Instance>();i->raw=(VkInstance)(uintptr_t)1;
   VkPhysicalDevice p=(VkPhysicalDevice)(uintptr_t)2;
   auto s=std::make_shared<Surface>();
   VkSurfaceKHR surface=(VkSurfaceKHR)(uintptr_t)3;
   physicals[p]=i;surfaces[surface]=s;
   VkPhysicalDeviceSurfaceInfo2KHR info{VK_STRUCTURE_TYPE_PHYSICAL_DEVICE_SURFACE_INFO_2_KHR};info.surface=surface;
   VkSurfaceFormat2KHR format{VK_STRUCTURE_TYPE_SURFACE_FORMAT_2_KHR};format.surfaceFormat.format=VK_FORMAT_UNDEFINED;
   count=0;assert(surface_formats2(p,&info,&count,&format)==VK_INCOMPLETE && !count && format.surfaceFormat.format==VK_FORMAT_UNDEFINED);
   count=1;assert(surface_formats2(p,&info,&count,&format)==VK_INCOMPLETE && count==1 && format.surfaceFormat.format==VK_FORMAT_B8G8R8A8_SRGB);
   puts("PASS surface-formats2 preserves caller bounds");

   auto d=std::make_shared<Device>();d->raw=(VkDevice)(uintptr_t)4;d->copy_queue=(VkQueue)(uintptr_t)5;d->swapchain=true;
   auto c=std::make_shared<Chain>();c->dev=d;c->surface=s;c->images.resize(2);c->handle=(VkSwapchainKHR)(uintptr_t)6;
   devices[d->raw]=d;chains[c->handle]=c;
   uint32_t index=99;VkSemaphore semaphore=(VkSemaphore)(uintptr_t)7;
   assert(acquire_image(d->raw,c->handle,0,semaphore,VK_NULL_HANDLE,&index)==VK_SUCCESS && index==0 && submits==1);
   assert(acquire_image(d->raw,c->handle,0,semaphore,VK_NULL_HANDLE,&index)==VK_SUCCESS && index==1 && submits==2);
   assert(acquire_image(d->raw,c->handle,0,semaphore,VK_NULL_HANDLE,&index)==VK_NOT_READY && submits==2);
   assert(acquire_image(d->raw,c->handle,1000,semaphore,VK_NULL_HANDLE,&index)==VK_TIMEOUT && submits==2);
   puts("PASS acquire reservations, immediate exhaustion and bounded timeout");
   c->images[0].acquired=false;injected=VK_ERROR_OUT_OF_DEVICE_MEMORY;
   assert(acquire_image(d->raw,c->handle,0,semaphore,VK_NULL_HANDLE,&index)==injected && !c->images[0].acquired);
   injected=VK_SUCCESS;c->retired=true;
   assert(acquire_image(d->raw,c->handle,UINT64_MAX,semaphore,VK_NULL_HANDLE,&index)==VK_ERROR_OUT_OF_DATE_KHR);
   assert(acquire_image(d->raw,c->handle,0,VK_NULL_HANDLE,VK_NULL_HANDLE,&index)==VK_ERROR_INITIALIZATION_FAILED);
   puts("PASS failed submission rolls back acquisition; retired chains unblock");

   auto q=std::make_shared<Queue>();q->raw=(VkQueue)(uintptr_t)8;q->dev=d;queues[q->raw]=q;
   VkSwapchainKHR absent=(VkSwapchainKHR)(uintptr_t)99;uint32_t zero=0;
   VkPresentInfoKHR present{VK_STRUCTURE_TYPE_PRESENT_INFO_KHR};present.swapchainCount=1;present.pSwapchains=&absent;present.pImageIndices=&zero;
   submits=waits=destroyed_semaphores=0;
   assert(queue_present(q->raw,&present)==VK_ERROR_OUT_OF_DATE_KHR && submits==2 && waits==1 && destroyed_semaphores==1);
   injected=VK_ERROR_OUT_OF_DEVICE_MEMORY;submits=waits=destroyed_semaphores=0;
   assert(queue_present(q->raw,&present)==injected && submits==1 && waits==0 && destroyed_semaphores==1);
   injected=VK_SUCCESS;
   puts("PASS rejected presents consume queued handoff once; failed submissions unwind");
   assert(vkGetInstanceProcAddr(VK_NULL_HANDLE,"vkCreateSwapchainKHR")==nullptr);
   assert(vkGetDeviceProcAddr(d->raw,"vkCreateInstance")==nullptr);
   d->swapchain=false;assert(vkGetDeviceProcAddr(d->raw,"vkCreateSwapchainKHR")==nullptr);
   assert(ApiGuard<throw_oom>::call()==VK_ERROR_OUT_OF_HOST_MEMORY);
   assert(ApiGuard<throw_error>::call()==VK_ERROR_UNKNOWN);
   puts("PASS command scope, extension gating and C ABI exception containment");
   puts("HOST CHECKS PASSED; bridge submission functions were mocked");
} }
