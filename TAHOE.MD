# Building the Tahoe fixes

This guide builds the three components needed for the Tahoe fixes in this fork:

| Component | Purpose | Build output |
|---|---|---|
| `NVMTLDriver` | PR #79: shader linking, sampler variants, and texture channel mapping for icon layers | `out/plugin-<commit>-release/NVMTLDriver` |
| `libnvmtl_translate.dylib` | PR #112: preserve buffer offsets in CoreImage resize helpers, restoring small System Settings icon glyphs | `out/translator/x86_64-apple-darwin/release/libnvmtl_translate.dylib` |
| `NVAccel.kext` | Tahoe accelerator rebuilt with the current VRAM interface, avoiding the ABI 1/2 mismatch that causes a black desktop | `out/tahoe/NVAccel.kext` |

The patched sources described here are based on **1.13.0**. Use the outputs with the matching **1.13.0 driver package and user-space libraries**. Rebuild from matching sources when moving to another driver version.

Run the build commands in **macOS Terminal**. The plugin and translator can be built on a working Sequoia installation for use on Tahoe. The translator command below explicitly targets Intel macOS, including when the build machine uses Apple silicon. macOS compilation and GPU testing have not been performed in this Windows workspace.

If the PR #79 plugin and rebuilt Tahoe accelerator already work on your machine, build and replace only the translator for PR #112. Rebuilding the plugin alone does not include this glyph fix.

## 1. Commit and transfer your changes

The plugin build script requires a clean Git working tree. If the fixes and this guide are still uncommitted on Windows, run these commands from your repository in PowerShell:

```powershell
git add -- TAHOE.MD plugin/NVMTLDevice.m plugin/NVMTLEmbedded.m plugin/NVMTLLibraryLoad.m plugin/NVMTLObjects.h plugin/NVMTLObjects.m translator/translator/src/native/emitter/mod.rs translator/translator/src/native/tests/buffers.rs
git commit -m "Apply Tahoe icon and glyph fixes and document builds"
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

The PR #79 author tested the plugin with **Command Line Tools 16.4 / macOS 15.5 SDK**. NVAccel also requires the macOS SDK's kernel headers and libraries.

The translator requires **Rust 1.87 or newer**. Install it through [rustup](https://rustup.rs/) if needed, then check:

```bash
rustc --version
cargo --version
```

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

PR #79 only changes the plugin. PR #112 also requires the translator build below. Neither patch requires rebuilding Mesa; keep the matching 1.13.0 NVK runtime.

## 5. Build the System Settings glyph-fix translator

PR #112 changes the Rust translator under `translator/translator/`. Build its C-compatible wrapper, which produces the dynamic library loaded by the plugin:

```bash
cd "$HOME/nvmtl-build/LIVE"
rustup target add x86_64-apple-darwin

cargo build --release \
  --manifest-path translator/wrapper/Cargo.toml \
  --target x86_64-apple-darwin \
  --target-dir out/translator
```

This direct Cargo command uses the translator in this checkout. The repository's `build/build_xlate.sh` defaults to a separate `~/nvmtl-build/bindless` tree and also expects release-check files outside this public checkout, so use the command above for this guide.

Set the library's install name, sign it, and verify the output:

```bash
translator_out="$HOME/nvmtl-build/LIVE/out/translator/x86_64-apple-darwin/release/libnvmtl_translate.dylib"

install_name_tool -id @rpath/libnvmtl_translate.dylib "$translator_out"
codesign --force --sign - "$translator_out"
file "$translator_out"
codesign --verify --verbose=2 "$translator_out"
```

Expect an **x86_64 Mach-O dynamic library** and successful signature verification. The build uses the Rust sources directly; Apple's private AIR fixtures are not required to build the release library. The full translator test suite does reference unpublished `validation/fixtures`, so a missing-fixture test failure is distinct from a release-library build failure.

## 6. Build NVAccel.kext for Tahoe

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

## 7. Package and install the matching components

These build commands do not install anything. In a copy of the matching extracted driver package, replace:

| Built artifact | Destination relative to the package's `pkgroot` |
|---|---|
| `out/plugin-<commit>-release/NVMTLDriver` | `Library/GPUBundles/NVMTLDriver.bundle/Contents/MacOS/NVMTLDriver` |
| `out/translator/x86_64-apple-darwin/release/libnvmtl_translate.dylib` | `Library/GPUBundles/nvmtl/libnvmtl_translate.dylib` |
| `out/tahoe/NVAccel.kext` | `Library/NullMoth/kexts/26/NVAccel.kext` |

Preserve the plugin bundle's other resources and the matching runtime libraries. Regenerate the package's `SHA256SUMS` after replacing the artifacts, then install the corrected package **while running Tahoe**. The installer selects the accelerator for the running OS, updates its cached copy, and rebuilds the Auxiliary Kernel Collection. Reboot after installation.

The loader prefers a translator library beside the plugin executable if one exists: `Library/GPUBundles/NVMTLDriver.bundle/Contents/MacOS/libnvmtl_translate.dylib`. If your package contains a separate copy there, replace it with the same rebuilt library too; a symlink to the canonical `nvmtl` library can keep pointing there. Otherwise that older copy would take precedence over the patched translator.

An NVAccel rebuild addresses the VRAM interface mismatch; PR #79's plugin rebuild addresses icon layers; PR #112's translator rebuild addresses the small Settings glyphs. Include the components needed by your installation. The plugin keys its shader cache by translator content, so the rebuilt library gets a new shader-cache identity after the process restarts.

After installing and rebooting, quit and reopen System Settings. If old rendered icons remain, run this as the desktop user to back up the IconServices and Dock caches:

```bash
cache_stamp="$(date +%Y%m%d-%H%M%S)"
user_cache="$(getconf DARWIN_USER_CACHE_DIR)"
if [ -n "$user_cache" ] && [ -d "$user_cache" ]; then
  for cache_name in com.apple.iconservices com.apple.dock.iconcache; do
    icon_cache="$user_cache/$cache_name"
    if [ -e "$icon_cache" ]; then
      mv "$icon_cache" "$icon_cache.bak-$cache_stamp"
    fi
  done
fi
system_icon_cache="/Library/Caches/com.apple.iconservices.store"
if [ -e "$system_icon_cache" ]; then
  sudo mv "$system_icon_cache" "$system_icon_cache.bak-$cache_stamp"
fi
```

Reboot after moving the caches so IconServices and the desktop regenerate their images with the new translator. The first redraw can take longer. These rendered-icon caches are separate from the translator's shader cache.

PR #112 reports restored System Settings sidebar glyphs on RTX 5070 Ti / macOS 26.6. Ghostty's incorrectly sized foreground remains outside these fixes. These patches are not a claim of complete Tahoe support.

## References

- [PR #79: Tahoe icon rendering fixes](https://github.com/nullmoth/nvidia-macos-driver/pull/79) — the patch applied here is revision `74c0dc30ab8e58139707fb603948329a1cede67f`.
- [PR #112: CoreImage resize and System Settings glyph fix](https://github.com/nullmoth/nvidia-macos-driver/pull/112) — the patch applied here is revision `a6c38cd52ee23e335e08af89824b72aca4f9fcdb`.
- [Issue #51: Tahoe NVAccel VRAM ABI mismatch](https://github.com/nullmoth/nvidia-macos-driver/issues/51).
- [Test build 2: matching 1.13.0 components and hardware results](https://github.com/modesttao/nvidia-macos-driver/releases/tag/icons-test2).
- [Apple: installing command-line developer tools](https://developer.apple.com/library/archive/technotes/tn2339/_index.html).
