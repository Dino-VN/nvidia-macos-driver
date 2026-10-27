/* Stable driver slots are independent of IOGraphics controller-local indices. */
#pragma once
#include <IOKit/IOService.h>
#include <libkern/c++/OSNumber.h>

#define NVRM_DISPLAY_INDEX_KEY "NVRMDisplayIndex"
#define NVRM_DISPLAY_IDENTITY_VERSION 1u
#define NVRM_LEGACY_CONTROLLER_ID 0x4E56524D00000001ull

// A malformed explicit slot is refused rather than falling back to
// controller-local index zero.
static inline bool nvrmFramebufferIndex(IOService *framebuffer, unsigned long long *index)
{
    if (!framebuffer || !index) return false;
    OSObject *value = framebuffer->copyProperty(NVRM_DISPLAY_INDEX_KEY);
    if (!value) value = framebuffer->copyProperty("IOFBDependentIndex");
    OSNumber *number = OSDynamicCast(OSNumber, value);
    const bool valid = number != nullptr;
    if (number) *index = number->unsigned64BitValue();
    OSSafeReleaseNULL(value);
    return valid;
}

static inline IOService *nvrmFramebufferPCIOwner(IOService *framebuffer)
{
    IOService *provider = framebuffer ? framebuffer->getProvider() : nullptr;
    for (unsigned hops = 0; provider && hops <= 8; ++hops) {
        if (provider->metaCast("IOPCIDevice")) return provider;
        provider = provider->getProvider();
    }
    return nullptr;
}
