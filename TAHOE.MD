# Building the Tahoe fixes

This guide builds the two components needed for the Tahoe fixes in this fork:

| Component | Purpose | Build output |
|---|---|---|
| `NVMTLDriver` | PR #79: shader linking, sampler variants, and texture channel mapping for icon layers | `out/plugin-<commit>-release/NVMTLDriver` |
| `NVAccel.kext` | Tahoe accelerator rebuilt with the current VRAM interface, avoiding the ABI 1/2 mismatch that causes a black desktop | `out/tahoe/NVAccel.kext` |

The patched sources described here are based on **1.13.0**. Use the outputs with the matching **1.13.0 driver package and user-space libraries**. Rebuild from matching sources when moving to another driver version.

Run the build commands in **macOS Terminal**. The plugin can be built on a working Sequoia installation for use on Tahoe. Compilation and GPU testing have not been performed in this Windows workspace.

## 1. Commit and transfer your changes

The plugin build script requires a clean Git working tree. If the fixes and this guide are still uncommitted on Windows, run these commands from your repository in PowerShell:

```powershell
git add -- TAHOE.MD plugin/NVMTLDevice.m plugin/NVMTLEmbedded.m plugin/NVMTLLibraryLoad.m plugin/NVMTLObjects.h plugin/NVMTLObjects.m
git commit -m "Apply upstream PR #79 Tahoe icon fixes and document builds"
git push origin main
```

Skip this step if those changes have already been committed and pushed.

## 2. Prepare the macOS toolchain

Check that Apple's compiler and macOS SDK are available:

```bash
xcrun clang --version
xcrun --show-sdk-path
```

If they are missing, install the Command Line Tools and wait for installation to finish:

```bash
xcode-select --install
```

The PR author tested the plugin with **Command Line Tools 16.4 / macOS 15.5 SDK**. NVAccel also requires the macOS SDK's kernel headers and libraries.

## 3. Prepare the checkout and Vulkan headers

`build/build_plugin.sh` expects the repository at `~/nvmtl-build/LIVE` and Vulkan headers at `~/Vulkan-Headers`.

For a fresh build checkout:

```bash
mkdir -p "$HOME/nvmtl-build"

git clone https://github.com/HighDelay/nvidia-macos-driver.git \
  "$HOME/nvmtl-build/LIVE"

git clone --depth 1 https://github.com/KhronosGroup/Vulkan-Headers.git \
  "$HOME/Vulkan-Headers"

cd "$HOME/nvmtl-build/LIVE"
```

If either checkout already exists, skip its clone command. To update an existing driver checkout:

```bash
cd "$HOME/nvmtl-build/LIVE"
git pull --ff-only
```

Exclude generated output locally so it does not cause the next plugin build to reject the working tree:

```bash
printf '\n/out/\n' >> .git/info/exclude
git status --short
```

`git status --short` should print nothing before building. Commit any intended source changes first.

## 4. Build the icon-fix plugin

From the repository root:

```bash
cd "$HOME/nvmtl-build/LIVE"
RELEASE=1 bash build/build_plugin.sh
```

A successful build prints `markers-missing 0` and the path to the executable. Verify the output in the same checkout:

```bash
plugin_out="$HOME/nvmtl-build/LIVE/out/plugin-$(git rev-parse --short HEAD)-release"

file "$plugin_out/NVMTLDriver"
codesign --verify --verbose=2 "$plugin_out/NVMTLDriver"
```

Expect an **x86_64 Mach-O bundle** and successful signature verification. This produces the plugin executable, rather than an entire `.bundle` directory or installer.

If compilation fails, inspect the full compiler output:

```bash
cat "$plugin_out/NVMTLDriver.err"
```

This icon patch does not require rebuilding the Rust translator or Mesa. Keep the matching 1.13.0 runtime libraries when packaging the new executable.

## 5. Build NVAccel.kext for Tahoe

NVAccel requires NVIDIA's **open-gpu-kernel-modules 610.57.04** source headers. The default location is `~/ogkm610`. If that checkout is not already present:

```bash
git clone --depth 1 --branch 610.57.04 \
  https://github.com/NVIDIA/open-gpu-kernel-modules.git \
  "$HOME/ogkm610"
```

Build from the driver repository root:

```bash
cd "$HOME/nvmtl-build/LIVE"
NM_TAHOE=1 bash build/accel_build.sh kexts/NVRM out/tahoe
```

If the NVIDIA source tree is elsewhere, specify it explicitly:

```bash
OGKM="/path/to/open-gpu-kernel-modules" \
NM_TAHOE=1 bash build/accel_build.sh kexts/NVRM out/tahoe
```

This fork's build script tolerates the absence of:

```text
src/nvidia/_out/Darwin_x86_64/compile_cmds.sh
```

With a fresh NVIDIA checkout it warns that it is compiling without NVIDIA's Darwin RM defines. The metadata fallback still requires the NVIDIA headers; it does not establish runtime compatibility by itself.

The result is:

```text
out/tahoe/NVAccel.kext
```

Check the executable's architecture:

```bash
file out/tahoe/NVAccel.kext/Contents/MacOS/NVAccel
```

It should report an x86_64 Mach-O binary. Compiler and linker diagnostics are saved separately:

```bash
cat out/tahoe/accel.err
cat out/tahoe/accelld.err
```

## 6. Package and install the matching components

These build commands do not install anything. In a copy of the matching extracted driver package, replace:

| Built artifact | Destination relative to the package's `pkgroot` |
|---|---|
| `out/plugin-<commit>-release/NVMTLDriver` | `Library/GPUBundles/NVMTLDriver.bundle/Contents/MacOS/NVMTLDriver` |
| `out/tahoe/NVAccel.kext` | `Library/NullMoth/kexts/26/NVAccel.kext` |

Preserve the plugin bundle's other resources and the matching runtime libraries. Regenerate the package's `SHA256SUMS` after replacing the artifacts, then install the corrected package **while running Tahoe**. The installer selects the accelerator for the running OS, updates its cached copy, and rebuilds the Auxiliary Kernel Collection. Reboot after installation.

An NVAccel rebuild addresses the VRAM interface mismatch; the plugin rebuild addresses the icon rendering problems. Both components are needed if both problems are present.

After installing and rebooting, run this as the desktop user to back up the Dock's old icon cache and regenerate it:

```bash
dock_cache="$(getconf DARWIN_USER_CACHE_DIR)com.apple.dock.iconcache"
if [ -f "$dock_cache" ]; then
  mv "$dock_cache" "$dock_cache.bak-$(date +%Y%m%d-%H%M%S)"
fi
killall Dock
```

The PR's reported remaining issues include Ghostty's incorrectly sized foreground and missing System Settings sidebar symbols. The icon fix is not a claim of complete Tahoe support.

## References

- [PR #79: Tahoe icon rendering fixes](https://github.com/nullmoth/nvidia-macos-driver/pull/79) — the patch applied here is revision `74c0dc30ab8e58139707fb603948329a1cede67f`.
- [Issue #51: Tahoe NVAccel VRAM ABI mismatch](https://github.com/nullmoth/nvidia-macos-driver/issues/51).
- [Test build 2: matching 1.13.0 components and hardware results](https://github.com/modesttao/nvidia-macos-driver/releases/tag/icons-test2).
- [Apple: installing command-line developer tools](https://developer.apple.com/library/archive/technotes/tn2339/_index.html).
