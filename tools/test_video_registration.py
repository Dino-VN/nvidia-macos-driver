#!/usr/bin/env python3
"""Check decoder registration policy and IOKit cleanup without opening a GPU."""
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "plugin/NVMTLDevice.m").read_text()
START = SOURCE.index("static bool nvmtl_is_decode_service(")
END = SOURCE.index("static void nvmtl_nvdec_register(", START)

HARNESS = r'''
#include <dispatch/dispatch.h>
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
typedef uint32_t io_service_t, io_connect_t;
typedef int IOReturn;
#define IO_OBJECT_NULL 0
#define kIOMainPortDefault 0
#define kIOReturnSuccess 0
#define kIOReturnNotFound 1
static int scenario, queries, opens, closes, releases, matches, logs;
static bool nvmtl_is_sandboxed(void) { queries++; return scenario != 0; }
static void nvlog(const char *fmt, ...) { logs++; }
#undef mach_task_self
static unsigned mach_task_self(void) { return 99; }
static void *IOServiceMatching(const char *name) {
    assert(!strcmp(name, "NVAccel")); return (void *)1;
}
static io_service_t IOServiceGetMatchingService(unsigned port, void *match) {
    assert(!port && match == (void *)1); matches++;
    return scenario == 2 ? 0 : 17;
}
static IOReturn IOServiceOpen(io_service_t service, unsigned task, uint32_t type,
                             io_connect_t *out) {
    assert(service == 17 && task == 99);
    assert(type == 0x4E560000u + (unsigned)opens++);
    assert(*out == 0);
    if ((scenario == 3 && type == 0x4E560000u) ||
        (scenario == 4 && type == 0x4E560001u)) return 2;
    if (scenario != 6) *out = type == 0x4E560000u ? 101 : 102;
    return 0;
}
static void IOServiceClose(io_connect_t port) {
    assert(port == 101 || port == 102); closes++;
}
static void IOObjectRelease(io_service_t service) { assert(service == 17); releases++; }
PRODUCTION
int main(int argc, char **argv) {
    scenario = atoi(argv[1]);
    const char *name = scenario == 1 ? "VTDecoderXPCService.arm64" : "Discord Helper";
    if (scenario == 7) name = "VTDecoderXPCServic";
    if (scenario == 8) name = NULL;
    bool expected = scenario == 0 || scenario == 1 || scenario == 5 || scenario >= 7;
    assert(nvmtl_can_register_decoder(name) == expected);
    assert(nvmtl_can_register_decoder(name) == expected); // both codec registrations share one check
    if (scenario <= 1) {
        assert(!opens && !closes && !matches && !releases && !logs);
        assert(queries == (scenario == 0 ? 2 : 0));
    } else {
        assert(matches == 1 && logs == 1);
        if (scenario == 2) assert(!opens && !closes && !releases);
        else if (scenario == 3) assert(opens == 1 && !closes && releases == 1);
        else if (scenario == 4) assert(opens == 2 && closes == 1 && releases == 1);
        else if (scenario == 6) assert(opens == 2 && !closes && releases == 1);
        else assert(opens == 2 && closes == 2 && releases == 1);
    }
    puts("PASS");
}
'''


def main():
    cases = (
        "unsandboxed client needs no bridge probe",
        "suffixed decode service bypasses the client restriction",
        "absent accelerator leaves decoding to the service",
        "denied control connection never opens the GPU connection",
        "denied GPU connection closes the successful control connection",
        "sandboxed GPU client registers after both bridge opens succeed",
        "success without connection handles is refused",
        "partial service name does not bypass the access check",
        "null process name still requires bridge access",
    )
    with tempfile.TemporaryDirectory(prefix="nvmtl-video-registration-") as tmp:
        src, exe = Path(tmp) / "test.m", Path(tmp) / "test"
        src.write_text(HARNESS.replace("PRODUCTION", SOURCE[START:END]))
        subprocess.run(["xcrun", "clang", "-fobjc-arc", "-O2", str(src),
                        "-framework", "Foundation", "-o", str(exe)], check=True)
        for index, case in enumerate(cases):
            subprocess.run([str(exe), str(index)], check=True, stdout=subprocess.DEVNULL)
            print("PASS", case)
    for codec, end in (("nvmtl_nvdec_register", "nvmtl_nvenc_register"),
                       ("nvmtl_nvdec_hevc_register", "// GH #175:")):
        body = SOURCE[SOURCE.index("static void " + codec + "(void)") :]
        body = body[:body.index(end)]
        assert "if (!nvmtl_can_register_decoder(me))" in body
        assert body.index('"WindowServer"') < body.index("nvmtl_can_register_decoder(me)")
        assert "NVMTL_NO_NVDEC" in body
    print("PASS both decoders retain disable/WindowServer guards and use the access check")


if __name__ == "__main__":
    main()
