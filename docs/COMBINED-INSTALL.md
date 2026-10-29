# Local native OpenGL test package

This is a complete fork driver package with an **optional Zink/NVK OpenGL
renderer**, built for Intel macOS **26.7.1 / 25G241**. It includes the existing
Minecraft and Wine runtimes. This local build has not been installed or
boot-tested by the integration review, and no GitHub release has been published.

Extract the archive to obtain `pkgroot/`. With the matching NVIDIA kernel driver
already running, double-click `Verify.command` to check hashes and run GPU/CGL
probes. Diagnostic windows briefly appear. The probes use package-local
libraries; passing them does not prove global GLD registration or a successful
reboot.

When ready to install, retain your previous working driver archive and run:

```sh
cd /path/to/pkgroot
sudo ./install.sh
```

Alternatively double-click `Install.command`. Follow its approval and reboot
instructions. The installer rejects another OS build, verifies payload and
kernel linking, backs up the previous driver and preserves its boot fallback.
It installs `NVKZinkGLDriver.bundle` in `/Library/GPUBundles` and selects it only
for the Tahoe accelerator. Existing OpenCore/SIP requirements still apply;
no System volume mounting or authenticated-root change is needed.

Normal OpenGL applications then use Zink without a companion mod. The default
`auto` presentation prefers direct GPU copies into native drawable VRAM, with a
GPU IOSurface/Apple presentation path for clients without an AppKit drawable.
CPU frame transfer requires the explicit `NVKZINK_PRESENT=cpu` diagnostic.
To require the new direct path for a particular app:

```sh
NVKZINK_PRESENT=native /path/to/application/executable
```

Check that `GL_RENDERER` contains **zink** and **NVK**. Minecraft's native Vulkan
bridge and Wine's runtime are independent and retain their existing setup.

For rollback, reinstall the previous complete driver package and reboot. The
normal installer removes the optional GLD bundle and restores the Apple OpenGL
selection from that package. `Uninstall.command` removes the NVIDIA driver
entirely; it is not a Zink-only toggle. Existing Recovery/boot removal guidance
from the driver README remains applicable if the desktop cannot start.

See `Library/GPUBundles/nvmtl/zink/ZINK-OPENGL.md` for build reproduction,
context/API limits, mode selection and validation details. Other OS builds,
GPUs, full games, sandboxed clients and a performance improvement remain
unqualified. Mesa's reported GL 4.6 version does not extend Apple's callable
framework API automatically.
