# Driver, NVK, Zink and native OpenGL

This archive contains the complete driver payload, its matching NVIDIA firmware,
Vulkan loader and NVK, shader translator, video codecs, Zink renderer, native CGL
adapter and GLD plugin, verification tools, licenses and the installation/uninstallation scripts.
No separate runtime download or build tool is needed to install it.

Extract the archive and double-click `Install.command`, or run:

```sh
cd nvidia-zink-installer
./Install.command
```

The installer requests administrator access, checks OS/GPU compatibility and
payload integrity, tests the kernel collection, backs up the previous driver,
installs the complete payload and sets up the existing boot fallback. Follow its
restart instructions. OpenCore configuration and Recovery changes remain manual
prerequisites; the installer prints applicable requirements. The native package
requires Intel macOS 26.7.1, build **25G241**, with a supported NVIDIA GPU.
The installer refuses another build before changing driver files. Native GLD
is installed under `/Library/GPUBundles/DinoZinkGLDriver.bundle`, a standard
macOS GPU bundle search directory. It does not require a writable System volume
or disabling authenticated-root. The existing driver's OpenCore/SIP settings
still apply.

`Verify.command` checks all file hashes and runtime compatibility, then runs the
Zink and native CGL rendering tests against the runtime inside this archive. GPU
tests require the kernel driver already running. Verification does not install
files. Run `Uninstall.command` to use the existing uninstaller.

**Native CGL status:** the macOS 26 NVAccel personality selects `DinoZinkGLDriver`.
The plugin automatically connects core and legacy CGL contexts to Zink before application
GL objects are created. Applications use their normal OpenGL.framework calls;
they do not call `dino_cgl_attach`. NSOpenGLView/CGLFlushDrawable present to the
native drawable, and native surface changes resize the Zink drawable. Legacy
contexts use OpenGL compatibility for LWJGL 2 / Minecraft 1.12.2. Presentation
prefers a GPU copy into shared IOSurface memory, with CPU presentation as the
fallback when import is unavailable. Opaque windows present alpha 1 even if the
game leaves framebuffer alpha at 0; transparent windows retain their alpha.
AppKit's private surface-copy contexts stay in the native driver so their
IOSurface images reach the window's Core Animation queue.
See `Library/GPUBundles/nvmtl/ZINK-OPENGL.md`
for supported context/drawable behavior and validation limits.

Validation covers one RTX 2060 on macOS 26.7.1 (25G241): the normal macOS GLD
loader, the unchanged CGL renderer probe, GLSL drawing, pixels, native window
presentation, shrinking/growing windows, updates while a context is not current,
sharing, multiple contexts, thread migration and destruction. Installer fixtures
verify rollback on failed trusted bundle lookup and kernel-collection rebuild,
including restoration of the previous plugin and accelerator selection.
The loader tests substitute only the bundle lookup path inside the test process
so that no live installation is needed. Registration after installation and a
reboot remain untested, as do general games and other GPUs/OS builds. The plugin
is experimental. RLCraft 1.12.2 loading-screen and main-menu text/artwork (185
mods loaded) has been verified in its actual native front buffer, with opaque
alpha, through LWJGL 2. A controlled AppKit window also verifies nonnil
IOSurface publication, successful Core Animation queue insertion and visible
red/green/blue output after preserving the native surface-copy context. This
does not establish performance across modpacks or shaderpacks.
The user also confirmed visible content in the isolated RLCraft rerun with
the updated runtime.
The Darwin NVK overlay uses staging buffers and GPU copies for texture uploads.
A verified animated-atlas test improved from 1,178 ms to 49 ms for 2,048 small
updates; this is an upload benchmark, not a world FPS result. The user confirmed
that the world no longer stalls at zero FPS, but reported about 20 FPS. World
performance is still being checked.
The CGL runtime also routes LWJGL 2's direct Cocoa view operations to AppKit's
main thread after diagnosing a layer-tree mutation race. The Darwin NVK overlay
queues texture uploads up to 4 KiB on the existing render worker; other drivers
keep their default threshold. See `ZINK-OPENGL.md` for validation and limits.
AppKit viewport updates publish pending dimensions; Mesa attachment resizing
is deferred to the rendering thread. Validation covers growth and shrinkage
while GL remains current on a worker, including a screen-constrained 1920x955
drawable and actual queued IOSurface pixels. The LWJGL
hook also publishes dimensions from its bare `MacOSXOpenGLView`, which does not
emit the usual AppKit viewport callback. A paired test with the actual LWJGL 2
library previously read black edge pixels at 1280x720 and 1920x959; after this
change, both sizes and the subsequent shrink return the correct pixels.
The user confirmed that RLCraft now displays correctly when the window is
resized. Final world FPS has not yet been reported.
The earlier diagnostic GLD is excluded.

The current macOS 26 accelerator and driver components are recorded in
`PACKAGE-IDENTITY.json`. The macOS 15 accelerator remains from the verified base
payload. The original `BASELINE-IDENTITY.json` describes its earlier upstream
baseline; `PACKAGE-IDENTITY.json` and the regenerated manifests describe this
combined package.

To reproduce a package from already built outputs:

```sh
python3 build/package_zink.py --base /path/to/verified/pkgroot \
  --zink /path/to/zink-out --components /path/to/matching/Library \
  --stage /path/to/new/pkgroot --archive /path/to/new/driver-zink.tar.gz --native-gld
```

The component overlay is optional. When supplied, it must contain the same NVK
and Vulkan loader as the verified base, plus complete matching driver bundles.
The builder checks the firmware files referenced by the actual NVRM executable.
It records component hashes, excludes shader caches, uses relative ICD/rpath
resolution and regenerates all package checksums. Omitting `--native-gld` produces
an archive for explicit application attachment without registering a GLD plugin.
