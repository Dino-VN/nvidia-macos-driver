# Native OpenGL through Zink and NVK

This optional integration runs OpenGL shaders through Mesa Zink and the fork's
native NVK renderer. It is separate from Minecraft's native Vulkan bridge and
the Wine/DXVK/vkd3d runtime. Ordinary driver packages retain Apple's OpenGL
renderer unless built with the optional Zink GLD bundle.

## Rendering and presentation

| Path | Work submitted for an OpenGL application |
| --- | --- |
| Apple GL on this driver | OpenGL → Apple GL-on-Metal → Metal/NVMTL → NVK → NVIDIA GPU |
| Native Zink | OpenGL.framework dispatch → Mesa OpenGL/Zink → private NVK → NVIDIA GPU |

Zink removes the Apple GL-to-Metal and NVMTL Metal/AIR-to-SPIR-V stages from
application shader execution. Mesa still implements OpenGL, Zink generates
Vulkan work and NVK compiles GPU shaders. Apple's CGL carrier still owns native
context creation, pixel formats and drawable lifecycle; this is not a replacement
OpenGL.framework.

For an AppKit window, the default presentation mode copies on the GPU into the
actual CAMetalLayer drawable's IOSurface VRAM. It uses the same version-3
IOSurface import, completion fence, dirty notification and generation tag
protocol as the Minecraft native NVK runtime. It never shares a VkImage across
Vulkan devices. A GPU scratch image handles channel order and opaque alpha;
there is no game-frame CPU readback, CPU row conversion or CPU pixel upload.
Metal still allocates the drawable and macOS composites it. This is a GPU-copy
path, not zero-copy scan-out, and it still waits for GPU completion on the CPU.

Native presentation follows the context's CGL swap interval: `0` disables
CAMetalLayer display synchronization and a nonzero interval enables it. An
application's VSync toggle takes effect on subsequent frames, independently for
each context, including render-thread clients. Intervals greater than one do not
currently add multi-refresh pacing. With VSync off, render throughput can exceed
the monitor's refresh rate; GPU copy completion is still required before a frame
is published. The display's physical refresh rate does not change.

The private frontend and renderer live under
`/Library/GPUBundles/nvmtl/zink`. They do not change `VK_DRIVER_FILES`, the default
ICD, Minecraft's runtime, Wine's provider or their paired DXVK/vkd3d DLLs.

## Compatibility and limits

The native GLD/CGL adapter is tested on **x86_64 macOS 26.7.1, build
25G241**. It does not restrict activation to an exact macOS build number.
If Apple's private CGL layout and required exports remain compatible, an
installed runtime can continue selecting Zink after a macOS update without
rebuilding. The build recorded in the package is provenance, not an activation
whitelist. The user requested this policy and will test macOS updates.

A user reports that Minecraft continued launching with Zink after upgrading
from macOS 26.7.1 to 26.7.2 without rebuilding the CGL adapter. This records
Minecraft compatibility for that update; local diagnostics below use 25G241.

Apple's private ABI is still an assumption: a layout change can require an
adapter update and can break OpenGL before a clean fallback is possible. Existing
symbol/profile/device checks remain; they do not prove full layout compatibility.
The package currently selects only the **Tahoe/macOS 26 accelerator**. The
standalone Mesa/NVK binaries target macOS 15.5, but that does **not** establish
native CGL support on Sequoia or another major macOS release.

The adapter covers core 3.2/4.1 and legacy compatibility CGL contexts through the
entrypoints exposed by the current Apple SDK/framework. Mesa reporting OpenGL
4.6 does not give an application every 4.6 entrypoint through Apple's framework.
RGB/RGBA8 windows, opaque/transparent alpha, ordinary CGL swaps, resize, sharing
and thread migration have focused tests. Stereo, multisampled/float drawables,
pbuffers, full-screen transitions, sandboxed clients, other GPUs and multiple
identical NVIDIA cards are unqualified. An ambiguous Metal/NVK GPU match is
refused. Apps must obey CGL context ownership. The GLD attaches shared contexts
automatically; developer tests using explicit attachment must attach every
shared context before creating GL objects.

The default `NVKZINK_PRESENT=auto` chooses direct native drawable presentation
when an AppKit view and matching NVIDIA drawable are available. Otherwise it
uses a GPU copy into shared IOSurface pages and Apple's presentation blit.
It never switches silently to CPU frame transfer. These modes are scoped to
the launched application:

| Value | Presentation |
| --- | --- |
| `auto` (default) | Native drawable when available; GPU IOSurface/Apple presentation for other CGL clients |
| `native` | Require the direct drawable VRAM copy; report unsupported targets as errors |
| `gpu` | Require shared host-page import plus Apple GL presentation; useful for comparison |
| `cpu` | Explicit readback/upload diagnostic; slow and not the normal rendering path |

For example, after installing the optional GLD package:

```sh
NVKZINK_PRESENT=native /path/to/application
```

Use the application's executable or launcher, rather than setting this for all
processes with `launchctl`. No boot argument or Minecraft companion mod selects
Zink. `NVKZINK_REQUIRE_GPU=1` makes the standalone probe reject missing GPU-copy
support; `NVKZINK_RGBX=1` tests alpha-less drawables. These names intentionally
survive the installed Metal plugin's filtering of internal `NVK_` variables.

### OBS display capture compatibility

OBS 33.0.1 needs two compatibility measures on the tested Intel Tahoe/NVIDIA
system. Its OpenGL capture textures fail to import through
`CGLTexImageIOSurface2D` while the context uses Zink. Its ScreenCaptureKit source
also requests RGBA16F frames, which fail to start with “The stream is nil” even
with Apple's OpenGL renderer. Separate diagnostics receive BGRA8 frames and
verify Apple's BGRA8/RGBA16F texture imports successfully.

After installing a driver build with this repair, quit OBS and enable its saved
compatibility setting:

```sh
defaults write com.obsproject.obs-studio NVKZinkCaptureCompatibility -bool true
```

Open OBS normally, add **macOS Screen Capture**, explicitly select the display,
and click **OK**. The setting keeps OBS's entire OpenGL context in Apple's
renderer and changes its RGBA16F capture request to **8-bit BGRA SDR**. It is
checked only for the `com.obsproject.obs-studio` application; other applications
continue to select Zink. OBS 33.0.1's moving desktop preview is user-confirmed on
RTX 2060 SUPER / Tahoe 26.7.1. HDR capture, encoding and streaming need separate
testing. This is a compatibility path, not native Zink IOSurface import support.

To turn the mode off, quit OBS and run:

```sh
defaults delete com.obsproject.obs-studio NVKZinkCaptureCompatibility
```

For a single launch, `NVKZINK_OBS_COMPAT=1 /Applications/OBS.app/Contents/MacOS/obs`
enables the same mode; `NVKZINK_OBS_COMPAT=0` overrides a saved setting for that
process. For other CGL interoperability diagnostics,
`NVKZINK_DISABLE=1 /path/to/application` keeps automatic contexts in Apple's
renderer for that process. It does not alter ScreenCaptureKit formats.

Copy/import failures do not publish partial frames. Uncertain completion stops
the affected share group and retains its GPU resources until process exit.
Normal context teardown drains accepted work before freeing imports. One private
Zink device and its compiler cache are reused for the process; contexts without
CGL sharing still have separate GL objects. The renderer
currently caches its scratch image but creates copy/import objects per native
frame; reducing that overhead and pipelining presentation remain future work.
No controlled application FPS improvement is claimed.

## Building locally

Use a separate, clean Mesa checkout at
[`17ca6174dcc6cb22059ac343bc29f8af7800f42e`](https://gitlab.freedesktop.org/mesa/mesa/-/commit/17ca6174dcc6cb22059ac343bc29f8af7800f42e).
Do not apply this overlay to the Mesa tree producing the installed NVMTL plugin.
The builder checks the source identity before applying its small Darwin/Zink
patch. Dispatch generation uses the local Apple symbols/slots and refuses
unrecognized conventions; it does not whitelist a particular OS build. It retains
descriptor sets for Darwin NVK, staging/GPU texture uploads
instead of host image copies, and bounded inline texture uploads on the render
worker. Other drivers retain their existing upload threshold.

Install Xcode command-line tools, Vulkan-Headers, Python, Meson, Ninja, Mako,
PyYAML, packaging and Bison 3.x. Bison 2.3 from macOS cannot parse this Mesa tree.
With this fork's driver already running and a matching verified NVK renderer:

```sh
python3 build/build_zink_vulkan.py /path/to/zink-out \
  --renderer /path/to/verified/pkgroot/Library/GPUBundles/nvmtl/libvulkan_nouveau.dylib
bash build/build_zink.sh /path/to/mesa /path/to/zink-build /path/to/zink-out
bash build/build_cgl_zink.sh /path/to/zink-out /path/to/cgl-build
bash build/build_gld_bridge.sh /path/to/zink-out /path/to/gld-build
python3 tools/test_zink_runtime.py --runtime /path/to/zink-out \
  --output /path/to/new/test-results
```

`VULKAN_HEADERS` can override the default `~/Vulkan-Headers/include`.
For a checkout extracted from the pinned mirror archive, set
`ZINK_MESA_ARCHIVE=/path/to/mesa-source.tar.gz`. The accepted archive SHA-256 is
`1328a4aaba2260c005ff46c88d572403f0b677cd87580050f4d1bfafe56388f0`;
its URL is `https://codeload.github.com/chaotic-cx/mesa-mirror/tar.gz/17ca6174dcc6cb22059ac343bc29f8af7800f42e`.
The builder checks extracted files against that archive. Source/build hashes,
Mesa identity and the private renderer pairing are recorded in `ZINK-BUILD.json`
and `NATIVE-BUILD.json`; packaging rejects stale or mismatched components.

The test script briefly opens diagnostic windows. It tests explicit CGL
attachment and the GLD lifecycle through a **process-local lookup shim**.
The shim substitutes the test bundle path/executable only in the probe process;
it does not install a driver or establish that macOS trusts a newly installed
bundle. Never use this shim for WindowServer or register it system-wide.
The native probe reads a separate diagnostic GPU buffer to verify pixels; that
readback is not part of gameplay presentation.

## Packaging and installation

Start with a checksum-verified **complete fork package**, including Minecraft,
Wine, both accelerator variants and matching firmware. The normal
`build/stage_package.py` retains responsibility for assembling that base.
Arbitrary overlays of installed `/Library` contents are rejected.

```sh
python3 build/package_zink.py --base /path/to/verified/pkgroot \
  --zink /path/to/zink-out --stage /path/to/new/pkgroot \
  --archive /path/to/new/nvidia-macos-driver-2.6.4-zink-nvk.tar.gz --native-gld
```

The archive has one top-level `pkgroot/`. It preserves existing runtimes and
version metadata, adds Zink in its own subdirectory and selects `NVKZinkGLDriver`
only for the Tahoe accelerator. `--native-gld` is the default. `--explicit-cgl-only` is a developer option
for attachment tests without system OpenGL selection.

Read the packaged [local installation guide](COMBINED-INSTALL.md) first. Run
`Verify.command` with the kernel driver already active, then install using
`Install.command` when ready for a boot test. The bundle uses the normal
`/Library/GPUBundles` search path; no System snapshot modification or
`authenticated-root` change is needed. The installer checks trusted bundle
lookup, preserves external kext sources such as macFUSE, and keeps rollback
and the existing boot fallback. A normal driver package can restore the Apple
OpenGL selection. Runtime GPU tests do not qualify registration or a reboot.

The current review and measured test coverage are in
[ZINK-PR2-REVIEW.md](ZINK-PR2-REVIEW.md). PR #2 was contributed by
[Dino-VN](https://github.com/Dino-VN); its original MIT attribution is retained.
Its RLCraft and upload-benchmark observations are author-reported and have not
been reproduced by this integration review.
