/* SPDX-License-Identifier: MIT
 * Diagnostic bundle only. It deliberately reports no usable GLD renderer.
 */
#include "gld_abi.h"
#include <os/log.h>

int nvk_gld_trace(const char *name, uintptr_t a0, uintptr_t a1, uintptr_t a2,
                    uintptr_t a3, uintptr_t a4, uintptr_t a5)
{
   os_log_error(OS_LOG_DEFAULT,
      "NVKZinkGLDriver diagnostic %{public}s args=%{public}lx,%{public}lx,%{public}lx,%{public}lx,%{public}lx,%{public}lx; ABI incomplete",
      name, a0, a1, a2, a3, a4, a5);
   /* Nonzero failure for GLD error-returning entries. Return conventions for
    * other entries are unknown; this bundle must not advertise readiness. */
   return 10000;
}

__attribute__((visibility("default"))) int
gldGetVersion(uint32_t *major, uint32_t *minor, uint32_t *third, uint32_t *driver)
{
   nvk_gld_trace("gldGetVersion", (uintptr_t)major, (uintptr_t)minor,
                  (uintptr_t)third, (uintptr_t)driver, 0, 0);
   /* Match AMD's not-initialized path: return false without dereferencing. */
   return 0;
}

__attribute__((visibility("default"))) const char *
gldGetDeviceString(void *device, uint32_t selector)
{
   nvk_gld_trace("gldGetDeviceString", (uintptr_t)device, selector, 0, 0, 0, 0);
   return NULL;
}
