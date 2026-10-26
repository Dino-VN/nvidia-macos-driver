#import <Foundation/Foundation.h>
#import <CoreGraphics/CoreGraphics.h>
#import <IOKit/IOKitLib.h>
#include <crt_externs.h>
#include <mach-o/dyld.h>
#include <spawn.h>
#include <sys/wait.h>
#include <unistd.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <limits.h>
#include <signal.h>
#include <math.h>
#include <chrono>
#include "../../kexts/NVRMFB/fb/nvrm-rotation.h"
#include "resolution.h"

static io_service_t framebuffer(CGDirectDisplayID display)
{
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
    io_service_t entry = CGDisplayIOServicePort(display);
#pragma clang diagnostic pop
    if (!entry) return IO_OBJECT_NULL;
    IOObjectRetain(entry);
    for (unsigned i = 0; i < 12; ++i) {
        if (IOObjectConformsTo(entry, "NVRMNVDAFramebuffer")) return entry;
        io_registry_entry_t parent = IO_OBJECT_NULL;
        kern_return_t status = IORegistryEntryGetParentEntry(entry, kIOServicePlane, &parent);
        IOObjectRelease(entry);
        if (status != KERN_SUCCESS) return IO_OBJECT_NULL;
        entry = parent;
    }
    IOObjectRelease(entry);
    return IO_OBJECT_NULL;
}

static NSDictionary *properties(io_service_t entry)
{
    CFMutableDictionaryRef value = nullptr;
    if (IORegistryEntryCreateCFProperties(entry, &value, kCFAllocatorDefault, 0) != KERN_SUCCESS)
        return @{};
    return CFBridgingRelease(value);
}

static bool enabled(NSDictionary *p)
{
    id marker = p[@"NVRMRotationEnabled"], probe = p[@"IOFBProbeOptions"];
    return [marker isKindOfClass:NSNumber.class] && [marker boolValue] &&
           [p[@"NVRMRotationImplementationVersion"] unsignedIntValue] == NM_ROTATION_IMPLEMENTATION_VERSION &&
           [probe isKindOfClass:NSNumber.class] && ([probe unsignedIntValue] & kNVRMSetTransform);
}

static uint64_t entryID(io_service_t entry)
{
    uint64_t id = 0;
    IORegistryEntryGetRegistryEntryID(entry, &id);
    return id;
}

static bool framebufferPathMatches(io_service_t entry, io_string_t path, uint64_t *resolvedID)
{
    path[0] = 0;
    *resolvedID = 0;
    if (IORegistryEntryGetPath(entry, kIOServicePlane, path) != KERN_SUCCESS) return false;
    io_registry_entry_t resolved = IORegistryEntryFromPath(kIOMainPortDefault, path);
    if (!resolved) return false;
    *resolvedID = entryID(resolved);
    IOObjectRelease(resolved);
    return *resolvedID != 0 && *resolvedID == entryID(entry);
}

static int printDisplays()
{
    CGDirectDisplayID displays[32]; uint32_t count = 0;
    if (CGGetOnlineDisplayList(32, displays, &count) != kCGErrorSuccess) return 2;
    NSMutableArray *rows = [NSMutableArray array];
    for (uint32_t i = 0; i < count; ++i) {
        CGDirectDisplayID id = displays[i];
        io_service_t fb = framebuffer(id);
        NSDictionary *p = fb ? properties(fb) : @{};
        CGRect bounds = CGDisplayBounds(id);
        NSMutableDictionary *row = [@{
            @"display_id": @(id), @"main": @(id == CGMainDisplayID()),
            @"width": @(CGDisplayPixelsWide(id)), @"height": @(CGDisplayPixelsHigh(id)),
            @"bounds_width": @(bounds.size.width), @"bounds_height": @(bounds.size.height),
            @"rotation": @(CGDisplayRotation(id)), @"nvrm_framebuffer": @(fb != IO_OBJECT_NULL),
            @"builtin": @(CGDisplayIsBuiltin(id)), @"active": @(CGDisplayIsActive(id)),
            @"online": @(CGDisplayIsOnline(id)), @"mirror_of": @(CGDisplayMirrorsDisplay(id)),
            @"bounds_x": @(bounds.origin.x), @"bounds_y": @(bounds.origin.y),
            @"rotation_enabled": @(enabled(p))
        } mutableCopy];
        for (NSString *key in @[@"IOFBTransform", @"IOFBProbeOptions", @"NVRMNativeRotationMask",
                                 @"NVRMRotationRequestedTransform", @"NVRMRotationPath", @"NVRMRotationImplementationVersion",
                                 @"IOFBDependentIndex"])
            if (p[key]) row[key] = p[key];
        if (fb && enabled(p))
            row[@"NVRMRotationActiveDegrees"] = @(nvrmRotationDegrees([p[@"IOFBTransform"] unsignedIntValue] & 0xffu));
        if (fb) {
            io_string_t path; uint64_t resolvedID = 0;
            const bool matched = framebufferPathMatches(fb, path, &resolvedID);
            row[@"registry_id"] = @(entryID(fb));
            row[@"framebuffer_path"] = @(path);
            row[@"framebuffer_path_registry_id"] = @(resolvedID);
            row[@"framebuffer_path_matches"] = @(matched);
            IOObjectRelease(fb);
        }
        CGDisplayModeRef mode = CGDisplayCopyDisplayMode(id);
        if (mode) {
            row[@"mode_width"] = @(CGDisplayModeGetWidth(mode));
            row[@"mode_height"] = @(CGDisplayModeGetHeight(mode));
            row[@"mode_pixel_width"] = @(CGDisplayModeGetPixelWidth(mode));
            row[@"mode_pixel_height"] = @(CGDisplayModeGetPixelHeight(mode));
            row[@"mode_refresh_hz"] = @(CGDisplayModeGetRefreshRate(mode));
            CGDisplayModeRelease(mode);
        }
        [rows addObject:row];
    }
    NSData *json = [NSJSONSerialization dataWithJSONObject:rows options:NSJSONWritingPrettyPrinted error:nil];
    fwrite(json.bytes, 1, json.length, stdout); putchar('\n');
    return 0;
}

static bool number(const char *s, unsigned long long limit, unsigned long long *value)
{
    if (!s || !s[0] || s[0] == '-') return false;
    char *end = nullptr; errno = 0;
    unsigned long long n = strtoull(s, &end, 0);
    if (errno || !end || *end || n > limit) return false;
    *value = n; return true;
}

static int printModes(CGDirectDisplayID display)
{
    NSDictionary *options = @{(__bridge NSString *)kCGDisplayShowDuplicateLowResolutionModes: @YES};
    CFArrayRef modes = CGDisplayCopyAllDisplayModes(display,(__bridge CFDictionaryRef)options);
    if (!modes) return 2;
    NSMutableArray *rows = [NSMutableArray array];
    for (CFIndex i=0; i<CFArrayGetCount(modes); ++i) {
        CGDisplayModeRef m = (CGDisplayModeRef)CFArrayGetValueAtIndex(modes,i);
        [rows addObject:@{@"width": @(CGDisplayModeGetWidth(m)), @"height": @(CGDisplayModeGetHeight(m)),
            @"pixel_width": @(CGDisplayModeGetPixelWidth(m)), @"pixel_height": @(CGDisplayModeGetPixelHeight(m)),
            @"refresh_hz": @(CGDisplayModeGetRefreshRate(m)), @"usable": @(CGDisplayModeIsUsableForDesktopGUI(m)),
            @"flags": @(CGDisplayModeGetIOFlags(m)), @"mode_id": @(CGDisplayModeGetIODisplayModeID(m))}];
    }
    CFRelease(modes);
    NSData *json = [NSJSONSerialization dataWithJSONObject:rows options:NSJSONWritingPrettyPrinted error:nil];
    fwrite(json.bytes,1,json.length,stdout); putchar('\n');
    return 0;
}

static bool resolution(CGDisplayModeRef mode, NMRotationResolution *out)
{
    if (!mode || !out) return false;
    const double hz = CGDisplayModeGetRefreshRate(mode);
    const size_t w=CGDisplayModeGetWidth(mode), h=CGDisplayModeGetHeight(mode);
    const size_t pw=CGDisplayModeGetPixelWidth(mode), ph=CGDisplayModeGetPixelHeight(mode);
    if (!isfinite(hz) || hz < 0 || hz > 1000 || w > UINT32_MAX || h > UINT32_MAX || pw > UINT32_MAX || ph > UINT32_MAX)
        return false;
    *out = {(uint32_t)w,(uint32_t)h,(uint32_t)pw,(uint32_t)ph,(uint32_t)llround(hz*1000)};
    return nmRotationResolutionValid(*out);
}

static bool preserveResolution(CGDirectDisplayID display, uint64_t expectedID, unsigned degrees,
                               const NMRotationResolution &wanted)
{
    using clock = std::chrono::steady_clock;
    const auto deadline = clock::now() + std::chrono::milliseconds(3000);
    bool applied = false;
    while (clock::now() < deadline) {
        io_service_t fb = framebuffer(display);
        if (!fb || entryID(fb) != expectedID || !enabled(properties(fb))) {
            if (fb) IOObjectRelease(fb);
            return false;
        }
        const unsigned active = nvrmRotationDegrees([properties(fb)[@"IOFBTransform"] unsignedIntValue] & 0xffu);
        IOObjectRelease(fb);
        // CGDisplayRotation can retain the old angle after a direct framebuffer
        // probe, even after the physical output and cursor returned to Standard.
        // The applied framebuffer transform is authoritative; keep the independent
        // pixel resolution, density and refresh checks below unchanged.
        if (active != degrees) { usleep(100000); continue; }
        CGDisplayModeRef current = CGDisplayCopyDisplayMode(display);
        NMRotationResolution actual = {};
        const bool matched = resolution(current,&actual) && nmRotationResolutionMatches(wanted,actual);
        if (current) CGDisplayModeRelease(current);
        if (matched) return true;
        if (!applied) {
            NSDictionary *options = @{(__bridge NSString *)kCGDisplayShowDuplicateLowResolutionModes: @YES};
            CFArrayRef modes = CGDisplayCopyAllDisplayModes(display,(__bridge CFDictionaryRef)options);
            CGDisplayModeRef best = nullptr; unsigned bestDelta = UINT_MAX;
            if (modes) for (CFIndex i=0; i<CFArrayGetCount(modes); ++i) {
                CGDisplayModeRef candidate = (CGDisplayModeRef)CFArrayGetValueAtIndex(modes,i);
                NMRotationResolution candidateResolution = {};
                if (!CGDisplayModeIsUsableForDesktopGUI(candidate) || !resolution(candidate,&candidateResolution) ||
                    !nmRotationResolutionMatches(wanted,candidateResolution)) continue;
                const unsigned delta = wanted.milliHz > candidateResolution.milliHz ?
                    wanted.milliHz-candidateResolution.milliHz : candidateResolution.milliHz-wanted.milliHz;
                if (!best || delta < bestDelta) { best = candidate; bestDelta = delta; }
            }
            if (best) {
                printf("Preserving %ux%u pixels (%ux%u logical) at %.3f Hz.\n",wanted.pixelWidth,wanted.pixelHeight,
                    wanted.width,wanted.height,wanted.milliHz/1000.0); fflush(stdout);
                applied = CGDisplaySetDisplayMode(display,best,nullptr) == kCGErrorSuccess;
            }
            if (modes) CFRelease(modes);
        }
        usleep(100000);
    }
    fprintf(stderr,"Exact resolution/refresh was not confirmed after rotation; refusing the fallback.\n");
    return false;
}

static int restoreAfter(unsigned seconds, CGDirectDisplayID display, uint32_t original, uint64_t expectedID,
                        const NMRotationResolution *originalResolution)
{
    signal(SIGHUP, SIG_IGN);
    signal(SIGTTOU, SIG_IGN);
    sleep(seconds);
    io_service_t fb = framebuffer(display);
    if (!fb || entryID(fb) != expectedID || !enabled(properties(fb))) {
        if (fb) IOObjectRelease(fb);
        fprintf(stderr, "Restore target disappeared or changed; no other display was touched.\n");
        return 3;
    }
    IOReturn status = IOServiceRequestProbe(fb, kNVRMSetTransform | original << 16);
    IOObjectRelease(fb);
    printf("Automatic restore requested: %u degrees, status 0x%08x\n",
           nvrmRotationDegrees(original), status);
    fflush(stdout);
    return status == kIOReturnSuccess && (!originalResolution ||
        preserveResolution(display,expectedID,nvrmRotationDegrees(original),*originalResolution)) ? 0 : 3;
}

static int usage()
{
    fprintf(stderr, "Usage: nv-rotate --list\n"
                    "       nv-rotate --modes <display-ID>\n"
                    "       nv-rotate --display <decimal-or-hex-ID> --set <0|90|180|270> [--seconds <5..60>]\n"
                    "A timed trial preserves resolution/refresh and restores the original display mode automatically. Requires the rotation-capable framebuffer.\n");
    return 2;
}

int main(int argc, char **argv)
{
    @autoreleasepool {
        if (argc == 1 || (argc == 2 && !strcmp(argv[1], "--list"))) return printDisplays();
        if (argc == 3 && !strcmp(argv[1], "--modes")) {
            unsigned long long id = 0;
            if (!number(argv[2],UINT32_MAX,&id) || !id) return usage();
            return printModes((CGDirectDisplayID)id);
        }
        // Separate exec keeps Objective-C and IOKit out of a post-fork child.
        // Its process group differs from the parent, so Ctrl-C cannot cancel the restore timer.
        if ((argc == 6 || argc == 11) && !strcmp(argv[1], "--restore-after")) {
            unsigned long long delay, display, bits, expectedID;
            if (!number(argv[2], 60, &delay) || delay < 5 ||
                !number(argv[3], UINT32_MAX, &display) ||
                !number(argv[4], UINT32_MAX, &bits) ||
                !number(argv[5], UINT64_MAX, &expectedID) ||
                nvrmRotationDegrees((uint32_t)bits) == 0xffffffffu) return usage();
            NMRotationResolution saved = {};
            if (argc == 11) {
                uint32_t *fields[] = {&saved.width,&saved.height,&saved.pixelWidth,&saved.pixelHeight,&saved.milliHz};
                for (unsigned i=0; i<5; ++i) {
                    unsigned long long v=0;
                    if (!number(argv[6+i],UINT32_MAX,&v)) return usage();
                    *fields[i]=(uint32_t)v;
                }
                if (!nmRotationResolutionValid(saved)) return usage();
            }
            return restoreAfter((unsigned)delay, (CGDirectDisplayID)display, (uint32_t)bits, expectedID,argc==11?&saved:nullptr);
        }
        unsigned long long display = 0, degrees = UINT_MAX, seconds = 15;
        bool haveDisplay = false, haveAngle = false;
        for (int i = 1; i < argc; i += 2) {
            if (i + 1 >= argc) return usage();
            if (!strcmp(argv[i], "--display") && !haveDisplay) {
                if (!number(argv[i+1], UINT32_MAX, &display) || !display) return usage();
                haveDisplay = true;
            } else if (!strcmp(argv[i], "--set") && !haveAngle) {
                if (!number(argv[i+1], 270, &degrees)) return usage();
                haveAngle = true;
            } else if (!strcmp(argv[i], "--seconds")) {
                if (!number(argv[i+1], 60, &seconds) || seconds < 5) return usage();
            } else return usage();
        }
        uint32_t bits = 0;
        if (!haveDisplay || !haveAngle || !nvrmRotationBits((unsigned)degrees, &bits)) return usage();
        io_service_t fb = framebuffer((CGDirectDisplayID)display);
        if (!fb) { fprintf(stderr, "Selected display is not on the NVIDIA framebuffer.\n"); return 2; }
        NSDictionary *p = properties(fb);
        if (!enabled(p)) {
            IOObjectRelease(fb);
            fprintf(stderr, "Rotation is not active on this display; no rotation requested.\n");
            return 2;
        }
        io_string_t path; uint64_t resolvedID = 0;
        if (!framebufferPathMatches(fb, path, &resolvedID)) {
            fprintf(stderr, "Framebuffer path does not resolve to the selected head (selected %llu, resolved %llu). "
                "Install the display-identity repair before testing rotation. No rotation requested.\n",
                (unsigned long long)entryID(fb), (unsigned long long)resolvedID);
            IOObjectRelease(fb);
            return 2;
        }
        id transform = p[@"IOFBTransform"];
        uint64_t old = [transform isKindOfClass:NSNumber.class] ? [transform unsignedLongLongValue] : UINT64_MAX;
        // Underscan is preserved by IOFramebuffer::setTransform itself.
        uint64_t original = old & ~0x01000000ull;
        if (original > UINT32_MAX || nvrmRotationDegrees((uint32_t)original) == 0xffffffffu) {
            IOObjectRelease(fb); fprintf(stderr, "Cannot safely restore the current transform.\n"); return 2;
        }
        CGDisplayModeRef oldMode = CGDisplayCopyDisplayMode((CGDirectDisplayID)display);
        NMRotationResolution saved = {}, target = {};
        const bool haveMode = resolution(oldMode,&saved) &&
            nmRotationResolutionTarget(saved,nvrmRotationDegrees((uint32_t)original),(unsigned)degrees,&target);
        if (oldMode) CGDisplayModeRelease(oldMode);
        if (!haveMode) {
            IOObjectRelease(fb); fprintf(stderr,"Cannot safely preserve the current resolution/refresh.\n"); return 2;
        }
        char executable[PATH_MAX]; uint32_t capacity = sizeof executable;
        if (_NSGetExecutablePath(executable, &capacity)) { IOObjectRelease(fb); return 2; }
        NSString *delay = [NSString stringWithFormat:@"%llu", seconds];
        NSString *displayArg = [NSString stringWithFormat:@"%llu", display];
        NSString *bitsArg = [NSString stringWithFormat:@"%llu", original];
        NSString *idArg = [NSString stringWithFormat:@"%llu", (unsigned long long)entryID(fb)];
        NSString *wArg = [@(saved.width) stringValue], *hArg = [@(saved.height) stringValue];
        NSString *pwArg = [@(saved.pixelWidth) stringValue], *phArg = [@(saved.pixelHeight) stringValue];
        NSString *hzArg = [@(saved.milliHz) stringValue];
        char *childArgs[] = {executable, const_cast<char *>("--restore-after"),
            const_cast<char *>(delay.UTF8String), const_cast<char *>(displayArg.UTF8String),
            const_cast<char *>(bitsArg.UTF8String), const_cast<char *>(idArg.UTF8String),
            const_cast<char *>(wArg.UTF8String), const_cast<char *>(hArg.UTF8String),
            const_cast<char *>(pwArg.UTF8String), const_cast<char *>(phArg.UTF8String),
            const_cast<char *>(hzArg.UTF8String), nullptr};
        posix_spawnattr_t attributes;
        int setup = posix_spawnattr_init(&attributes);
        if (setup) { IOObjectRelease(fb); fprintf(stderr, "Cannot prepare restore timer: %s\n", strerror(setup)); return 2; }
        setup = posix_spawnattr_setflags(&attributes, POSIX_SPAWN_SETPGROUP);
        if (!setup) setup = posix_spawnattr_setpgroup(&attributes, 0);
        if (setup) {
            posix_spawnattr_destroy(&attributes); IOObjectRelease(fb);
            fprintf(stderr, "Cannot isolate restore timer: %s\n", strerror(setup)); return 2;
        }
        pid_t watchdog = -1;
        int spawned = posix_spawn(&watchdog, executable, nullptr, &attributes, childArgs, *_NSGetEnviron());
        posix_spawnattr_destroy(&attributes);
        if (spawned) { IOObjectRelease(fb); fprintf(stderr, "Cannot start restore timer: %s\n", strerror(spawned)); return 2; }
        IOReturn status = IOServiceRequestProbe(fb, kNVRMSetTransform | bits << 16);
        const uint64_t restoreID = entryID(fb);
        IOObjectRelease(fb);
        printf("Requested %llu degrees: status 0x%08x. Restoring in %llu seconds.\n", degrees, status, seconds);
        fflush(stdout);
        const bool native = status == kIOReturnSuccess && preserveResolution((CGDirectDisplayID)display,restoreID,(unsigned)degrees,target);
        if (!native) {
            // The detached timer is still armed even if the immediate restore fails.
            fb = framebuffer((CGDirectDisplayID)display);
            if (fb && entryID(fb) == restoreID) {
                IOServiceRequestProbe(fb,kNVRMSetTransform | (uint32_t)original << 16);
                IOObjectRelease(fb);
            } else if (fb) IOObjectRelease(fb);
        }
        int result = 0;
        while (waitpid(watchdog, &result, 0) < 0) if (errno != EINTR) return 3;
        printDisplays();
        return status == kIOReturnSuccess && native && WIFEXITED(result) ? WEXITSTATUS(result) : 3;
    }
}
