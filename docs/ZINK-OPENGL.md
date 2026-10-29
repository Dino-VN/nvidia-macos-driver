# Zink on NVK and native CGL

Zink now builds as `libdino_zink.dylib`, using Mesa's Gallium OpenGL state
tracker directly on NVK. The standalone probe renders through this library.
`libdino_cgl.dylib` now connects real CGL contexts and OpenGL.framework calls
to Zink, including native drawable presentation. The GLD proxy automatically attaches core and legacy CGL contexts when selected by
NVAccel's `IOGLBundleName`. The explicit API remains available for development.
Native GLD is experimental and bound to x86_64 macOS build 25G241. Its normal
loader/rendering path has been tested with a process-local bundle lookup
substitution. Local RLCraft 1.12.2 testing also reaches its native main-menu
pixels through LWJGL 2; a fresh installation/reboot and general game compatibility
remain untested.

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
or zero-copy rendering into the native drawable yet. Native CGL can use the GPU
IOSurface copy described below. Release a
context before moving it between threads; destroy it only when no other thread
uses it. These are Mesa contexts, not interchangeable with `CGLContextObj`.

## GPU presentation and OpenGL 2.1 compatibility (2026-10-29)

Native presentation first tries two reusable IOSurfaces. Zink imports their
page-aligned system memory through `VK_EXT_external_memory_host`, blits RGBA to
BGRA with the required row orientation on the GPU, then issues an image-to-buffer
GPU transfer directly into those pages. Apple GL imports the surface as a
rectangle texture and blits it to the native drawable. This path does not map
the render target, copy pixels with `memcpy`, or upload a CPU texture each frame.

Opaque native surfaces use alpha 1 in the presentation image, even when the
game clears alpha to 0 or masks alpha writes. This follows `kCGLCPSurfaceOpacity`,
since macOS may allocate alpha bits even when the application requests none.
Zink clears the scratch image to opaque and blits only RGB on the GPU. The
application's framebuffer alpha and GL state remain unchanged; a transparent
native surface retains application alpha. RGBX drawables also force opaque
presentation, accounting for Vulkan's underlying RGBA storage.

NVK's fence completes before Apple reads the surface. An Apple GL fence completes
before the same slot is written again. Resize and teardown drain outstanding
work before releasing imports. Frames are presented on their own swap call;
there is no intentional extra frame of latency. Unsupported host-memory or
native texture imports fall back to the CPU path. `DINO_ZINK_PRESENT=cpu` forces
that fallback; `DINO_ZINK_PRESENT=gpu` requires the GPU path and reports failure
when it cannot be initialized.

The transfer pages are shared with Apple without a CPU copy. Rendering still uses
separate GPU images, with a GPU blit/copy into the surface. This is not zero-copy
rendering or direct scanout. The shipped NVK image-format query does not support
host-allocation handles for images, although its buffer import works; it cannot
currently import an IOSurface as a linear render target through this API.

The existing standalone probe checks GPU BGRA bytes, both row orientations,
both slots, padding, rejection of a pending slot, and preservation of read
FBO/PBO/pixel-pack state when `DINO_ZINK_REQUIRE_GPU=1` is set. Native window
checks with `DINO_ZINK_PRESENT=gpu` cover repeated frames, 128x128 -> 64x96 ->
192x160 resizing, a surface update without a current context, and final native
red/green/blue pixels. These checks passed on the RTX 2060 and build 25G241.
The native window probe accepts `--legacy`, `--no-alpha` and `--transparent`.
It clears application alpha to 0 and verifies native alpha 255 for opaque windows
and alpha 0 for transparent windows. Both GPU and CPU paths are checked.
`DINO_ZINK_RGBX=1` runs the standalone copy checks using a no-alpha framebuffer
and zero-alpha draws, verifying RGBX readback and presentation alpha 1.

The new `dino_zink_create_drawable_profile` API requests OpenGL 2.1 compatibility
for legacy CGL pixel formats. Its fixed-function state, display lists and
ARB/EXT aliases are needed by LWJGL 2 / Minecraft 1.12.2 RLCraft. The dispatch
generator now reads the SDK's core, legacy and extension declarations together,
checks the actual public symbol slots, and handles Apple's pointer-sized ARB
shader handles. Unsupported/empty SDK symbols are recorded in its local map;
an SDK declaration alone does not establish extension support.

The legacy probe covers immediate-mode drawing, matrices, display lists,
multitexture, ARB VBO/client arrays, EXT framebuffer objects, pointer-sized ARB
shader handles and shared contexts. A separate local shared-context teardown
test passed three times: noncurrent destruction defers native textures, fences
and surface references until the surviving peer can safely release them.

The RLCraft reproduction loaded the compatibility runtime and rendered its
loading screen while its window stayed gray. The opaque copy fix makes
readback from the actual Apple front buffer contain
loading-screen and main-menu text/artwork, with 185 mods loaded and alpha 255
throughout. Front-buffer pixels alone did not establish visible presentation:
AppKit's own legacy surface-copy context was also being routed to Zink, and
`NSIOAccelSurface.frontBuffer` returned nil, so no image entered CAImageQueue.

Automatic attachment now leaves contexts created by `NSIOAccelSurface` in the
native driver. The copy helper's native CGL texture imports and GL objects stay
together, while application core/legacy contexts use Zink. A controlled AppKit
window then returned a nonnil front-buffer IOSurface, successfully registered
and inserted its image into CAImageQueue, and visibly displayed red/green/blue
pixels. The native swap also selects framebuffer 0 for reads after the blit.
Mod/shader combinations beyond this RLCraft reproduction are not yet qualified.
The local RLCraft rerun loaded the updated library, and the user confirmed that
its window now displayed content. No installed system libraries were replaced
during this isolated test.

### Animated texture uploads on Darwin NVK

Sampling the RLCraft world at near-zero FPS found 2,923 of 2,979 client-thread
samples in `glTexSubImage2D`. NVK's host image copy repeatedly mapped/unmapped
GPU memory through NVRM and tiled the pixels on the CPU. The Darwin NVK overlay
now disables Zink's host-image-copy capability before resource creation, using
the existing staging-buffer and GPU buffer-to-image upload path. Other Vulkan
drivers retain their existing capability selection.

On the RTX 2060, a 2048x2048 atlas test with 2,048 strided 16x16 updates and
completion every 32 updates took 1,178 ms before this change and 49 ms afterward
(about 24 times faster). Full texture readback and a nonzero-mip update matched
every expected pixel. This measures texture upload throughput; it is not a
Minecraft world FPS measurement. Core/legacy dispatch, PBO and glyph uploads,
cube faces, and actual AppKit IOSurface queue publication also passed with the
updated backend. The user confirmed that the world no longer stalls at zero
FPS, but reported only about 20 FPS; higher world performance is still under test.

### LWJGL 2 view operations and AppKit

Two startup crashes were traced to LWJGL's Cocoa view operations running on its
client thread: one failed while releasing objects in `setView`, and another
reported a `CALayerArray` mutation during enumeration. `dino_appkit.m` now
marshals LWJGL's direct `setView:`, `update` and `clearDrawable` calls to AppKit's
main thread. GL current-context changes, rendering and swaps stay on the client
thread. Calls already on main and calls from other clients retain their original
path. The user confirmed visible loading and a working world with the test shim;
the same handling is integrated into the CGL runtime.

Native viewport updates publish pending drawable dimensions under the bridge
lock. The rendering thread consumes them and reallocates Mesa attachments;
AppKit never performs that reallocation from its own viewport update, even if
it makes the native context current on main. The window probe's `--render-thread`
mode keeps the GL context current on a worker while main grows/shrinks the view,
checks its actual constrained backing size (including 1920x955), and verifies
edge pixels and the queued AppKit IOSurface.

LWJGL 2's `MacOSXOpenGLView` is a bare `NSView` and does not emit the viewport
callback used by `NSOpenGLView`. Java could report `wasResized=true` and a new
1280x720 display while the bridge still used its original 854x480 drawable.
The LWJGL update hook now publishes the view dimensions after AppKit updates
the context, using backing pixels when the view requests a high-resolution
OpenGL surface. The rendering thread then applies the pending resize.

A paired Java 8 / LWJGL 2.9.4 test grew the same native view from 854x480 to
1280x720 and a constrained 1920x959, then shrank it to 854x480. Before this
change, both larger sizes returned black pixels at their new far edge on
every sampled frame. Afterward, all sizes returned the expected blue edge
pixels with no GL errors. The user then confirmed that RLCraft displayed
correctly after resizing with this final view-size publication. The final
world FPS after the upload optimization has not been reported.

### Threaded animated texture updates on Darwin NVK

The remaining world sample spent 616 of 2,530 client-thread samples in texture
updates. Mesa's default inline texture-upload limit is only 320 bytes, smaller
than a 16x16 RGBA animation tile. The Darwin NVK overlay raises this limit to
4 KiB for Zink's threaded context, copying qualifying upload bytes into the
existing command queue before returning to the game. Resource references and
upload ordering use the existing threaded-context path. Larger updates retain
their existing path, and other Vulkan drivers retain the default limit.

For the same 2,048 strided 16x16 updates with completion every 32 calls,
application-thread time inside the upload calls fell from 31.5 ms to 2.4 ms.
Total time including GPU completion stayed similar (62.5 ms versus 65.0 ms)
in this paired test. Full atlas/nonzero-mip readback had zero mismatches and
zero GL errors. This verifies reduced client-thread work, not a world FPS gain.

A freshly built Metal plugin also includes the existing bounded host-page
import cache. It passed the 12 IOSurface wrapper ordering/pixel cases and the
native AppKit publication probe with process-local bundle selection. The full
presentation timings were variable and did not establish a world FPS gain from
this cache alone.

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
CGL selection, WindowServer presentation, or performance. At that revision, readback was deliberately CPU-based; no speed improvement
over the existing Metal path had been measured.

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

At the frame boundary the automatic path also reads
`kCGLCPSurfaceBackingSize`. This catches Cocoa/GLFW window resizes that update
the native surface without reaching either observed viewport caller, then
reallocates the Zink drawable before the next presentation.

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
Registry selection after a fresh installation/reboot, general game compatibility,
other OS builds/GPUs, multisampled/float/sRGB buffers and application-facing
pbuffer/IOSurface texture APIs remain unqualified. Legacy GL and GPU presentation
validation on 2026-10-29 is described above. No Minecraft FPS gain has been measured.

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
installed renderer for the final native drawable blit and swap. Other OS builds require
fresh lifecycle and structure verification before lifting the build gate. A
proper independent HAL and rendering directly into a shared native surface remain future work.
