# Zink on NVK and native CGL

Zink now builds as `libdino_zink.dylib`, using Mesa's Gallium OpenGL state
tracker directly on NVK. The standalone probe renders through this library.
`libdino_cgl.dylib` now connects real CGL contexts and OpenGL.framework calls
to Zink, including native drawable presentation. The new GLD proxy automatically attaches core CGL contexts when selected by
NVAccel's `IOGLBundleName`. The explicit API remains available for development.
Native GLD is experimental and bound to x86_64 macOS build 25G241. Its normal
loader/rendering path has been tested with a process-local bundle lookup
substitution; a fresh installation/reboot and general games remain untested.

## Build and run

Use a separate Mesa source tree at `17ca6174`, the same baseline as NVK. The
Zink build needs Meson, Ninja, Python with Mako, a C/C++ compiler, and Mesa's
normal build tools. It does not build another Vulkan ICD or require MoltenVK.
Keep the NVK source, build directory, patch, and installed dylib separate.

```sh
bash build/build_zink.sh /path/to/mesa-17ca6174 /path/to/zink-build /path/to/zink-out
/path/to/zink-out/zink_probe /path/to/zink-out/libdino_zink.dylib /Library/GPUBundles/nvmtl/nvk_icd.json /path/to/triangle.ppm
/path/to/zink-out/cgl_renderer_probe
/path/to/zink-out/cgl_renderer_probe --require-zink
```

The last command succeeds only when **Apple CGL itself** selects Zink on NVK. A passing
standalone probe does not establish native CGL support. `VK_DRIVER_FILES` selects
the NVK ICD in the probe before Vulkan initialization. The library never changes
environment variables. Set `ZINK_VULKAN_RUNTIME` at build time to change the
Vulkan loader's rpath from `/Library/GPUBundles/nvmtl`.

`build/prepare_zink.py` checks and applies `zink/mesa-zink-nvk.patch`, then copies
the standalone frontend into the supplied Mesa source tree. Repeating this
operation recognizes the applied patch. A mismatched patch fails before copying
the frontend. Mesa's normal MoltenVK build remains available when
`moltenvk-dir` is supplied; NVK builds omit the MoltenVK private APIs and the
MoltenVK-specific portability instance flag.

The public interface is `zink/dino_zink.h`. Create a context, make it current,
resolve Mesa GL functions with `dino_zink_get_proc_address`, and render.
Contexts currently request OpenGL 4.1 core, single-buffer RGBA8, and depth/stencil.
Mesa may report a newer supported version. Resize requires the context current.
Readback returns RGBA8 with the top row first. IOSurface presentation copies to
same-size, nonplanar RGBA/BGRA surfaces and respects row padding. The caller must
submit that surface to its compositor. `dino_zink_create_shared` shares GL objects;
`dino_zink_create_drawable` additionally selects double buffering for CGL.
There is no direct WindowServer hookup in the standalone frontend, multisampling,
or zero-copy presentation yet. Release a
context before moving it between threads; destroy it only when no other thread
uses it. These are Mesa contexts, not interchangeable with `CGLContextObj`.

## Validation on 2026-10-28

Tested on macOS 26.7.1 (25G241), x86_64, NVIDIA GeForce RTX 2060 / TU106-A,
using the already installed NVK ICD. The standalone renderer reports:

```text
GL_VENDOR=Mesa
GL_RENDERER=zink Vulkan 1.4(NVIDIA GeForce RTX 2060 (NVK TU106-A) (MESA_NVK))
GL_VERSION=4.6 (Core Profile) Mesa 26.3.0-devel
```

The probe checks GLSL 4.10 shader compilation/linking, triangle and background
pixels, resize from 64x64 to 32x24, image orientation, short output buffers,
readback without a current context, preservation of read FBO/PBO and pixel-pack
state, and padded BGRA IOSurface pixel contents. It does not test games, native
CGL selection, WindowServer presentation, or performance. Readback is deliberately
CPU-based; no speed improvement over the existing Metal path has been measured.

The CGL probe reports `0x01027f00`, accelerated, and
`NVIDIA GeForce RTX 2060 (NVMTL over NVIDIA GeForce RTX 2060 (NVK TU106-A))`,
with OpenGL `4.1 Metal - 90.5`. It also enumerates the software renderer
`0x01020400`. Mask with `0x00ffff00` when comparing to the `0x00020400` software
renderer family, because renderer IDs can include other bits.

## Automatic native GLD

Build the CGL adapter first, then run:

```sh
bash build/build_gld_bridge.sh /path/to/zink-out /path/to/gld-build
```

The production `DinoZinkGLDriver.bundle` forwards 131 GLD exports to Apple's
installed AppleMetalOpenGLRenderer. It wraps context creation/destruction and
checks the OS build during version negotiation. Apple continues owning device,
pixel-format and native drawable handling. No Apple binary is copied or modified.
The generator uses only the names in the local export list; forwarding stubs use
ABI-neutral tail calls, preserving register and stack arguments.

Caller-side and runtime observations establish that the fifth argument of
`gldCreateContext` points at GLI+`0x8e0`. GLI+`0xb2c8` points at CGL+8, while
GLI+`0xb2d0` points at the saved **public** GL dispatch table. The GLD creation
wrapper provides a private table for `gliInitDispatchTable` to populate and
leaves Zink adapters in CGL's saved table. CGL restores those adapters before
returning the context to the application. Mesa is initialized on its first GL
call. This bypasses GLEngine's GL state tracking while keeping its native
presentation context available. This is distinct from the incompatible HAL
`gldPopulateContextDispatch` table examined below.

CGL calls viewport/scissor dispatch functions with an explicit GLI context during
surface setup, sometimes before that context is current. Noncurrent native setup
calls use Apple's original functions. `CGLSetSurface` and AppKit's
`-[NSOpenGLContext(NSOpenGLContextInternal) _updateOpenGLViewport]` viewport
updates set the Zink drawable dimensions. Updates while the context is not
current are applied when the context next becomes current. Both callers were
observed in local LLDB traces on 25G241. An application
changing its viewport alone does not change the drawable dimensions. Automatic
registrations do not retain their CGL context; GLD destruction releases Mesa and
restores the original dispatch pointers.

`libGFXShared::gfxInitializeLibrary` reads `IOGLBundleName` and uses
`gpu_bundle_find_trusted`. This macOS build searches `/Library/GPUBundles` before
`/System/Library/Extensions`, with `KernelExtensionManagement` trust checks.
The combined native package selects `DinoZinkGLDriver` in both the active and
cached macOS 26 NVAccel personalities, installs the plugin in the first directory,
and verifies trusted lookup after copying. No System snapshot is needed. The
macOS 15 cached accelerator keeps its original selection; the native installer
refuses any OS build other than 25G241.

REA loader evidence: `ev_4eb41b1d403c7968c9483a941e25bc766330cf0f3fbc17c385574557e526a6fa`.
Its extracted-cache import labels are incomplete; local live LLDB disassembly and
runtime memory establish the actual lookup names and paths. All Apple analysis
artifacts remain outside the repository and package.

Tests load the production plugin through the normal gfx loader by substituting
only its lookup path in the test process. The unchanged `cgl_renderer_probe
--require-zink` succeeds without loading an adapter or calling an attachment API.
The `--system` modes of the graphics/window probes omit application attachment.
Sharing, shaders, pixels, thread migration, context retain count and automatic
destruction pass. The native window probe also passes 128x128 → 64x96 →
192x160 resizing, including an update before makeCurrent, viewport changes that
leave drawable size intact, and red/green/blue pixels in the original native
drawable beyond its old extent. Native installer fixtures pass complete setup,
wrong-build rejection, trusted-lookup failure, first-install cleanup, and late
kernel-collection failure with restoration of the previous driver/plugin/runtime,
firmware, cached personalities and kernel collection. Privileged commands and
runtime qualification are mocked in those installer fixtures.
Registry selection after installation and reboot, game
compatibility, other OS builds/GPUs, legacy GL on Zink, multisampled/float/sRGB
buffers, pbuffer/IOSurface texture APIs, GPU-only presentation and performance
remain unqualified. Legacy contexts use the original Apple renderer.

## Native CGL adapter

```sh
bash build/build_cgl_zink.sh /path/to/zink-out /path/to/cgl-build
/path/to/zink-out/cgl_zink_probe /path/to/zink-out/libdino_cgl.dylib /Library/GPUBundles/nvmtl/nvk_icd.json
/path/to/zink-out/cgl_zink_window_probe /path/to/zink-out/libdino_cgl.dylib /Library/GPUBundles/nvmtl/nvk_icd.json
```

Create a normal 4.1 core CGL/NSOpenGLContext, make it current, and call
`dino_cgl_attach(context, width, height)` before allocating application GL objects.
Ordinary GL core entrypoints linked from OpenGL.framework then call Mesa through
adapters that remove Apple's hidden GLI-context argument. CGL context identity,
locking, retain counts and existing drawable association remain native. The
renderer ID continues describing the existing CGL carrier, so verify Zink using
the GL renderer string and actual pixels instead of treating its ID as a newly
registered GLD renderer.

`CGLFlushDrawable` invokes a separate adapter: read Zink's rendered buffer on the
CPU, upload into the original Apple's GL texture, blit into its native drawable,
then use Apple's existing swap path. The application's Mesa FBO, pixel store,
texture and buffer state is separate from presentation state. The adapter uses
the existing AppleMetal/NVMTL path for final presentation. `dino_cgl_resize` must
be called explicitly when drawable pixel dimensions change. Detach with the
context current before destroying it, and keep the adapter dylib loaded until
all contexts are detached. Shared CGL contexts must all be attached before GL
objects are used across them. Serialize attachment/detachment within each share
group, and obey CGL context thread ownership.

Local LLDB disassembly establishes the public `libGL` stub contract: the current
CGL context is read through `GS:0xf0`, its first pointer is a GLI context, and
`glGetString` calls the pointer at `CGL+0x3b0` with that hidden context prepended.
The CGL dispatch prefix ends at `0x1e80`; `CGLFlushDrawable` calls its distinct
slot at `0x1278`. The GLI share group pointer is at GLI context offset `0x5b00`.
These are observations on x86_64 macOS build 25G241, not a stable Apple API.
The library and generator refuse an unverified OS build. The generator recovers
all 478 core slots from that machine's public stubs; porting to another build
requires verifying the internal structure offsets and swap lifecycle first.
The generated local assembly is
research evidence and is excluded from installation artifacts.

REA/Hopper analysis of CGL creation is recorded as
`ev_019829e9362c3ee16019c8b0451281c47c4b41d3f742a583a9869903ba2076e0`.
LLDB runtime observation additionally confirmed native core context creation
calls `GLEngine::gliCreateContextWithShared` and Apple's `gldCreateContext` with
the driver state at GLI+`0x8e0`. A diagnostic `gldPopulateContextDispatch` trace
occurred during teardown after the first GL strings were already returned;
that hook cannot serve as a reliable pre-application attachment boundary.

Native tests on the RTX 2060 pass shader compilation/linking and triangle
pixels through actual framework entrypoints, float/stack/pointer arguments,
textures and fences, resize, independent context switching, and thread migration.
The NSOpenGLView test verifies green center and red corner pixels read from
the original native drawable after CGLFlushDrawable. Shared-object tests cover
texture visibility across attached CGL contexts. These tests do not qualify
unmodified games, all core functions, legacy/fixed-function profiles, pbuffer or
IOSurface texture-import APIs, multisampled/float/sRGB default drawables,
performance. Automatic drawable resizing is validated through the GLD window
probe above; explicit attachments continue using `dino_cgl_resize`.
This adapter is experimental.

### Minecraft buffer mapping fix

The first native package omitted `glMapBufferRange`, `glFlushMappedBufferRange`
and `glVertexAttribDivisor`: their SDK declarations lack the deprecation macro
that the generator originally required. Minecraft 26.3 failed during GUI vertex
upload with `GlBuffer$Direct.map: Failed to map buffer`, because buffer creation
used Mesa while the omitted mapping entry point used Apple's separate GL state.
The generator now accepts both declaration forms. The native CGL probe reproduces
the null mapping on the old library and passes with the fixed one, including
nonzero-offset unsynchronized writes, explicit flush, mapped readback and the
instance divisor. This is driver regression coverage, not general game qualification.

### Minecraft texture buffers, fonts, clouds and fog

Texture-buffer fetches read zero in vertex and fragment shaders with Zink's
automatic descriptor-buffer mode on the installed Darwin NVK runtime. This
broke shader-based PBO uploads, font atlases, cube-map panorama uploads and
Minecraft's buffer-driven cloud geometry. Direct CPU texture uploads worked.

The native NVK build now selects descriptor sets when descriptor mode is
automatic. Explicit `ZINK_DESCRIPTORS=db` remains an experimental override and
reproduces the failure. Shader-based PBO uploads remain enabled. The native
framework probe checks signed texture-buffer fetches/updates in both shader
stages, strided atlas uploads and untouched regions, grayscale glyph alpha,
all six cube-face uploads/samples, and Minecraft's 40-byte fog uniform range.
The descriptor-buffer control fails; the new default passes all checks.

Apple shares one untyped slot between shader and program deletion. The generator
now resolves the Mesa object type at this slot. The probe checks actual program
removal and cleanup without GL errors.

A Minecraft 26.3/Fabulously Optimized diagnostic run on RTX 2060 showed readable
text and visible clouds/fog in a captured world frame with Complementary
Reimagined r5.9.3. This validates the reported failures; it does not qualify every
shader pack or gameplay scenario.

### Native bridge CPU overhead

GL entrypoints skip rebinding the Mesa frontend when the correct context is
already current. Presentation reuses its CPU buffer and Apple texture storage;
Mesa reads bottom-up directly into the upload buffer, eliminating two image
reversals and a temporary full-frame allocation. Top-first readback and IOSurface
APIs retain their behavior. Tests cover both orientations, padded rows, pack/FBO
state, context/thread changes and repeated presentation with native resize.

Warm 64x64 native dispatch runs measured state queries at 311–362 ns/call before
and 43–44 ns/call after; uniform/draw pairs measured 1,469–1,637 ns/pair before
and 271–276 ns/pair after (initial compilation excluded). These CPU timings are
not Minecraft FPS results. A 1920x1080 presentation benchmark remained roughly
14–15 ms/frame; the after run overlapped an active Minecraft test and cannot
establish a presentation speedup. Synchronous readback and Apple presentation
remain performance limits.

Use [the combined package builder](COMBINED-INSTALL.md) for one complete archive
with the matching kernel driver, firmware, NVK, Zink, native adapter and installer.

## GLD findings and the pasted plan

The supplied plan's constraints remain in effect: analyze Apple binaries locally,
never modify or redistribute them; explicitly label undocumented assumptions;
start with CPU readback; keep system installation repeatable; expect Apple's
framework path to expose at most its 4.1 API surface; defer an injected 4.6 shim
and zero-copy presentation.

The proposed **dispatch takeover cannot be used as written**. Both `otool`/
`llvm-objdump` disassembly and REA/Hopper show that
`gldPopulateContextDispatch` at `0xa799` writes internal callbacks:

| Table offset | AMD callback |
| --- | --- |
| `0x08` | `glrdATI_Hwl_DrawPixels` |
| `0x10` | `glrdATICopyPixels` |
| `0xa0` | `glrdAMD_BeginPrimitiveBuffer` |
| `0xa8` | `glrdAMD_EndPrimitiveBuffer` |
| `0xc0` | `glrdAMD_RenderVertexArray` |

These are internal rendering hooks, not Mesa's public `gl*` table. The table
pointer is stored at context offset `0x80`. `gldUpdateDispatch` stores its third
argument at `0x78` and manipulates dirty-state flags. Installing ordinary Mesa
entrypoints here would use incompatible arguments and state.

REA evidence for the dispatch function:
`ev_b5c719f258482b9f63beb2d5edfe09cfb736b5c40b586ff462151272e2c7a5d3`.
Initialization evidence:
`ev_72119bb69587a17fca1f43ffb0f5c23ac58278fea24d55d7d505e60d8c6bef52`.
These are static, provider-specific observations, not executed call traces.
Hopper's inferred integer signatures are not trusted as C prototypes.

The already extracted local `GLRendererFloat` and the on-disk
`AppleMetalOpenGLRenderer` both export `gldCreateContext`, `gldDestroyContext`,
`gldAttachDrawable`, and object lifecycle functions. The software renderer's
dispatch function also installs begin/end primitive and vertex-array rendering
callbacks at `0xa0`, `0xa8`, and `0xc0`. Its create-context code allocates and
initializes a large driver context. Therefore the AMD export list's lack of
`gldCreateContext` does not establish that GLEngine owns every driver context.
Symbol ownership can be split across driver and support libraries. The minimal
export list in the pasted plan is not a verified complete loading contract.

Other observed facts:

- `gldGetVersion` writes four 32-bit values: 4, 1, `0x11`, driver ID; returns
  1 after initialization, otherwise 0. The meaning of the third word is unknown.
- `gldInitializeLibrary` builds driver IO callbacks, forwards the six integer
  argument registers unchanged to `gpumInitializeIOData`, and adds two driver
  arguments on the stack. Those six caller argument meanings remain unknown.
- `gldCreateDevice` treats its first argument as an output pointer and writes
  byte 7 of its third argument before calling `gpumCreateDevice`.
- `gldChoosePixelFormat` forwards its first two arguments to
  `gpumChoosePixelFormat`, adding driver IO data and a sanitizer callback.
- `gldPresentFramebufferData` consumes a context and integer buffer selector.
  There is no directly passed IOSurface pointer in this implementation.
- AMD imports `gldCreateBuffer` and `gldReadFramebufferData` from supporting
  libraries. Absence from its exports does not prove object APIs exist only in
  initialization function tables, nor establish how contexts are owned.

`zink/gld_abi.h` records only observed offsets and explicitly uncertain
prototypes. It must not be treated as a usable or complete ABI.
`tools/collect_gld_evidence.py NEW_DIRECTORY` records local binary hash, OS build,
imports, exports, dependencies, focused disassembly, and selected registry fields
without copying Apple binaries. An optional second argument selects another
locally supplied Apple GLD binary for comparison. Re-run after OS updates;
do not assume offsets remain stable. The pre-existing local software-renderer
extraction was inspected read-only; its original cache provenance was not
independently established.

GLEngine was also extracted locally from this machine's shared cache using
`ipsw dyld extract ... GLEngine --slide --stubs`. Focused disassembly of
`gliInitializeLibrary` shows a separate initialization contract with six
register arguments and a seventh stack argument; it retains an IO data pointer.
`gliCreateContext` validates an existing context before forwarding creation.
These observations do not recover the GLD registration contract or make Mesa
contexts compatible with GLEngine contexts. The extracted Apple binary stays
outside the repository and is not part of any build or distributable artifact.

## Earlier diagnostic bundle and registry research

```sh
bash build/build_gld_probe.sh /path/to/zink-out
log stream --predicate 'eventMessage CONTAINS "DinoZinkGLDriver"' --style compact
```

`DinoZinkGLDriver.bundle` exports the requested minimal hooks and logs the six
incoming x86_64 integer registers without dereferencing unknown structures.
Unknown stack and floating-point arguments are not captured. It reports no
usable GLD version and does not create devices or connect Zink to GLEngine.
Thus later rendering hooks should not be reached through normal selection.
This is a diagnostic artifact, not a working system OpenGL driver. Selecting it
can lose the currently working hardware GL renderer.

The live NVAccel registry has `IOGLBundleName=AppleMetalOpenGLRenderer` and
`IOAccelRevision=2`. Its source sets the GL bundle property only if absent, so a
personality value is preserved. Only NVAccel was available in the live
accelerator dump; a real active AMD/Intel accelerator comparison is still needed.
Presence of `IOAccelRevision`, statistics, or capability keys does not establish
which are mandatory for GLEngine.

`zink/NVAccel-Zink-personality.plist` is the exact **candidate** addition under
`IOKitPersonalities/NVAccel`: `IOGLBundleName` = `DinoZinkGLDriver` (without the
`.bundle` suffix, matching the existing registry convention). No guessed
revision/index/statistics properties are added. The candidate was not activated during diagnostic research. The combined native
package now applies this name with the working experimental proxy, not the diagnostic bundle. Only the verified macOS 26 package enables it; macOS 15 retains Apple selection.

## Earlier System-volume installation research (not needed by the native package)

SIP being off alone is insufficient: authenticated-root must also be disabled
(CSR bit `0x800`) and verified with `csrutil authenticated-root status`. If needed,
disable it in Recovery. Do not guess the System-volume device from the Data
volume or an APFS snapshot. Inspect `diskutil apfs list` and choose the actual
System volume for this macOS installation.

For an explicitly selected System volume such as `/dev/diskXsY`, the repeatable
staging sequence is:

```sh
sudo mkdir -p /Volumes/DinoSystem
sudo mount -t apfs -o nobrowse /dev/diskXsY /Volumes/DinoSystem
sudo bash package/stage_gld_bundle.sh /path/to/zink-out/DinoZinkGLDriver.bundle /Volumes/DinoSystem
```

The script verifies the bundle, preserves a previous bundle in a printed backup
directory, copies it into the supplied writable System mount, and fixes ownership.
It does not mount volumes, edit an accelerator, or select a boot snapshot.

After a usable GLD bridge is verified, add the candidate personality key to the
staged NVAccel kext, rebuild the appropriate accelerator/kernel collection with
the normal driver packaging workflow, and create the new boot snapshot:

```sh
sudo bless --folder /Volumes/DinoSystem/System/Library/CoreServices --bootefi --create-snapshot
```

Retain the original accelerator and bundle for rollback. Reboot and run the CGL
probe; a successful file copy or standalone Zink test does not confirm renderer
selection. OS updates can restore the sealed System volume and require staging
again. No System volume, installed bundle, accelerator property, kernel collection,
or boot snapshot was modified during this implementation.

## Remaining qualification

Verify a full installation/reboot, actual registry selection, unmodified games,
core-profile coverage beyond the probes, shared-context teardown/resource use,
and additional drawable formats. The production proxy depends on Apple's
installed renderer for final CPU-copy presentation. Other OS builds require
fresh lifecycle and structure verification before lifting the build gate. A
proper independent HAL and GPU-only presentation remain future work.
