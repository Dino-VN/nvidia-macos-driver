#!/usr/bin/env python3
"""Retain the fork's repairs while accepting the reviewed upstream 2.6.3 changes.

Functional fixtures cover new mode/audio, shader and surface interfaces. These
comparisons protect the existing fork behavior against the pre-merge checkpoint.
"""
import re
import subprocess
from test_support import ROOT, FB, method

BASE = "55f9263e2a62fc7b84b1d4ffead29c426bc98a40"

def historical(path):
    return subprocess.check_output(["git", "show", BASE + ":" + path], cwd=ROOT)

def same_methods(path, signatures):
    before = historical(path).decode()
    after = (ROOT / path).read_text()
    for signature in signatures:
        assert method(before, signature) == method(after, signature), (path, signature)

# These runtime/build sources were not touched by upstream 2.6.3. Protect the
# Minecraft/Wine ABI, rollback tools and release optimization settings together.
for path in subprocess.check_output(["git", "ls-tree", "-r", "--name-only", BASE,
                                     "nvk", "runtime", "build"], cwd=ROOT, text=True).splitlines():
    assert (ROOT / path).read_bytes() == historical(path), path
assert (ROOT / "translator/wrapper/src/uniform_cbuf.rs").read_bytes() == historical("translator/wrapper/src/uniform_cbuf.rs")

fb_path = "kexts/NVRMFB/fb/nvrm-fb.cpp"
old = historical(fb_path).decode()
for name in ["cursorInit", "cursorFire", "cursorApply", "scheduleCall",
             "setCursorState", "setCursorImageLocked", "publishCursorGeometry",
             "vramGrant", "vramRelease", "getApertureRange", "getVRAMRange", "headOff",
             "notifyConnectionChanged", "connectNotifyFire", "configureRotation",
             "configureDisplayIdentity", "configureControllerIdentity", "requestProbe",
             "getCurrentDisplayMode", "setDetailedTimings", "dtIsCurrent", "publishRotatedSizes",
             "edidModeFor", "addKmsRefreshModes"]:
    signature = "NVRMNVDAFramebuffer::" + name + "("
    assert method(FB, signature) == method(old, signature), name

# Audio adds two notification removals and its worker to cleanup; the cursor's
# separate accepted-work drain must remain byte-for-byte intact.
stop = method(FB, "NVRMNVDAFramebuffer::stop(")
for line in ["    if (fAudioReady) { fAudioReady->remove(); fAudioReady = nullptr; }\n",
             "    if (fCodecReady) { fCodecReady->remove(); fCodecReady = nullptr; }\n"]:
    assert stop.count(line) == 1
    stop = stop.replace(line, "")
assert stop.replace("&fConnectNotify, &fAudioCall}", "&fConnectNotify}") == method(old, "NVRMNVDAFramebuffer::stop(")
for name in ["applyMode", "flipToMemory"]:
    signature = "NVRMNVDAFramebuffer::" + name + "("
    assert ''.join(method(FB, signature).replace("(NvU16)", "").split()) == ''.join(method(old, signature).split()), name
power = method(FB, "NVRMNVDAFramebuffer::setHeadPower(")
assert power.replace("{ fHeadSlept = false; publishDisplayAudioProperties(); }", "fHeadSlept = false;") == method(old, "NVRMNVDAFramebuffer::setHeadPower(")
init = method(FB, "NVRMNVDAFramebuffer::kapiInit(")
assert init.count("validateInitialDviMode();") == 1
assert init.index("validateInitialDviMode();") < init.index("fBootW = fW")
assert "nvrmKmsRasterValid" in init
assert "fNewIdOnce" not in FB
assert not re.search(r"\bthread_call_cancel_wait\s*\(", FB)
assert "THREAD_CALL_PRIORITY_KERNEL, THREAD_CALL_OPTIONS_ONCE" in FB
assert "while (OSAddAtomic(0, &fCursorOutstanding)) IOSleep(1);" in FB

same_methods("kexts/NVRM/accel/nvrm-accel.cpp", ["static bool nvAccelRestoreParkedForDirty(", "static bool fbPublished("])
same_methods("plugin/NVMTLDevice.m", ["static bool nvmtl_is_sandboxed(", "static bool nvmtl_is_chromium_gpu_process(",
    "static bool nvmtl_can_register_decoder(", "static void nvmtl_nvdec_register(",
    "static void nvmtl_nvdec_hevc_register(", "static void nvmtl_angle_allow_nvidia("])
same_methods("plugin/NVMTLEventSync.m", ["static void nvmtl_gpu_uses_adjust(", "static void nvmtl_gpu_uses_raise(",
    "static void nvmtl_gpu_uses_lower(", "static void nvmtl_prepare_submission_copies("])
same_methods("plugin/nvmtl_vk.c", ["uint32_t nvmtl_spirv_stencil_emu("])
same_methods("plugin/NVMTLObjects.m", ["static unsigned nvmtl_mip_autofill_bpp(", "static void nvmtl_mip_autofill("])
assert not (ROOT / "plugin/NVMTLRotationInline.m").exists()
print("PASS: retained Tahoe rotation/current IDs, cursor serialization/drain, DVI, parked backing, decoder/ANGLE defaults, strict stencil, badge mips, GL completion/copies and native runtimes; reviewed audio/raster changes allowed")
