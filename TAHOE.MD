# Building the Tahoe driver with the retained icon fixes

This guide targets upstream **1.15.0 at `56bc4f9`**, plus PRs **#171, #136, #147 and #131**. Our working PR #79 Dock icon fixes and PR #112 System Settings glyph fix are preserved. Upstream 1.15.0 already contains equivalent implementations of both icon fixes, so the merge keeps one implementation of each. Their implementation code was compared with the previously tested fork and remains unchanged.

| Component | Purpose | Build output |
|---|---|---|
| `NVMTLDriver` | Retained icon rendering, PR #171 Vulkan features, PR #136 MSAA sample positions, and optional PR #147 surface scheduling | `out/plugin-<commit>-release/NVMTLDriver` |
| `libnvmtl_translate.dylib` | Retained Settings glyph fix and PR #171 shader translation repairs | `out/translator/x86_64-apple-darwin/release/libnvmtl_translate.dylib` |
| `NVAccel.kext` | Tahoe accelerator built from the same source as NVRMFB, keeping their VRAM interface compatible | `out/tahoe/NVAccel.kext` |
| `NVRMFB.kext/Contents/Info.plist` | PR #131: restrict the framebuffer claim to NVIDIA display-class PCI devices | `kexts/NVRMFB/fb/Info.plist` |

None of the four additional PRs changes the main `NVRM.kext` binary. PR #171 needs the plugin and translator rebuilt; PRs #136 and #147 need the plugin rebuilt. PR #131 changes framebuffer bundle metadata and requires reinstalling that bundle and refreshing the Auxiliary Kernel Collection, rather than recompiling its binary. The kexts in this Tahoe test workflow do not require code signing; signing would not grant kext loading approval.

The upstream merge itself also updates `NVRM`, `NVRMFB`, `NVAccel`, and the NVK runtime after 1.14.7. A complete build of this merged tree needs those components from the same source snapshot. The commands below cover the plugin, translator and accelerator; they do not build the main RM binary, framebuffer binary or NVK. Replacing only those outputs and the framebuffer plist in the official 1.14.7 package is a partial rebuild and does not include every upstream change. The NVK build uses Mesa `17ca6174` with this checkout's `nvk/nvk-macos.patch`, as described in the [upstream build instructions](https://github.com/nullmoth/nvidia-macos-driver#build-from-source).

PR #136 was adapted to preserve upstream's standard sample-position fallback when programmable positions are unavailable, while treating 1x rendering as a fixed center. PR #131 preserves the modern framebuffer's `NVRMBootFB` personality; its test compares the NVIDIA claim in both plist copies without requiring the entire files to be identical.

PR #147 remains **off by default**. To test it in a particular application, launch that application's executable with `NVMTL_SCHEDULE_AFTER_SURFACE_WRITES=1` in its environment. It delays the scheduled notification for command buffers that write shared surfaces until completion. This is a process environment variable, not a boot argument or an `nvrm610.conf` setting.

Run the build commands in **macOS Terminal**. The plugin and translator can be built on a working Sequoia installation for use on Tahoe. The translator command below explicitly targets Intel macOS, including when the build machine uses Apple silicon. The newly merged 1.15.0 tree still needs fresh package builds and hardware validation.

Safari and Messages Dock icons were reported missing their foregrounds with the official 1.14.0 package even after clearing the rendered-icon caches. The user confirmed that this fork's retained fixes resolve that issue on their RTX 2060 Super Hackintosh. That result applies to the previously tested build; the new merged build still needs macOS and GPU validation.

The merge keeps specialized-name linking, linked stages for pixel-sampler variants, swizzled sampled views and the buffer-offset repair for CoreImage resize helpers. It also keeps upstream's HDR storage-texture handling and newer stage-output repair. The fallback for missing NVIDIA Darwin build metadata remains in `build/accel_build.sh`.

## 1. Use the committed merge

The plugin build script requires a clean Git working tree. Use the merged commit in your macOS checkout and check its identity before building:

```bash
git log -1 --oneline
git status --short
```

If transferring through GitHub, the merge must first be pushed to the fork. Pulling before that still retrieves the previous published commit. The clone and pull commands below assume the merged commit is available there.

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
```

Expect an **x86_64 Mach-O bundle**. This produces the plugin executable, rather than an entire `.bundle` directory or installer.

If compilation fails, inspect the full compiler output:

```bash
cat "$plugin_out/NVMTLDriver.err"
```

PRs #79, #136, #147 and #171 affect the plugin; PRs #112 and #171 affect the translator. Build both for this verification. These PRs do not themselves change Mesa, but current upstream main includes an NVK connection-pool repair beyond the released 1.14.7 runtime.

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

Set the library's install name and inspect the output:

```bash
translator_out="$HOME/nvmtl-build/LIVE/out/translator/x86_64-apple-darwin/release/libnvmtl_translate.dylib"

install_name_tool -id @rpath/libnvmtl_translate.dylib "$translator_out"
codesign --force --sign - "$translator_out"
file "$translator_out"
```

Expect an **x86_64 Mach-O dynamic library**. WindowServer requires an ad-hoc signature on this userland library. Sign it after setting its install name; the staging helper preserves the finalized bytes. The build uses the Rust sources directly; Apple's private AIR fixtures are not required to build the release library. The full translator test suite does reference unpublished `validation/fixtures`, so a missing-fixture test failure is distinct from a release-library build failure.

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

To build both Sequoia and Tahoe accelerators from this same checkout, upstream 1.14 adds:

```bash
bash build/accel_build_all.sh kexts/NVRM out/accel
```

This produces `out/accel/15/NVAccel.kext` and `out/accel/26/NVAccel.kext`. It calls this fork's `accel_build.sh`, including the metadata fallback. The script clears each OS-specific output directory before building; use a directory reserved for generated output.

## 7. Stage the Tahoe PR outputs in an upstream package

Extract an upstream prebuilt driver archive into a separate directory. Use its unmodified `pkgroot` as the base; the helper verifies its existing `SHA256SUMS` before copying anything. Run on macOS with Python 3 and Apple's command line tools installed:

```bash
cd "$HOME/nvmtl-build/LIVE"
python3 build/stage_package.py "/path/to/upstream/pkgroot" \
  "$HOME/nvmtl-build/tahoe-package/pkgroot"
```

The output directory must be new and outside the input package. The helper creates its parent directories and publishes the output only after all copies and checksum checks succeed. The upstream package and original build outputs remain intact.

By default, this stages the Tahoe PR changes using these exact paths in the checkout:

| Built artifact | Destination relative to the output `pkgroot` |
|---|---|
| `out/plugin-<current-commit>-release/NVMTLDriver` | `Library/GPUBundles/NVMTLDriver.bundle/Contents/MacOS/NVMTLDriver` |
| `out/translator/x86_64-apple-darwin/release/libnvmtl_translate.dylib` | `Library/GPUBundles/nvmtl/libnvmtl_translate.dylib` and the plugin's separate translator copy, if present |
| `kexts/NVRMFB/fb/Info.plist` | `Library/Extensions/NVRMFB.kext/Contents/Info.plist` |

The loader prefers a translator beside the plugin executable. The helper updates that separate copy, or preserves its relative symlink to the canonical `nvmtl` translator, so an older copy cannot take precedence. Plugin resources, the prebuilt NVRM/NVRMAGDC/framebuffer binaries, NVK, firmware, and the Sequoia accelerator are retained from the base package.

The four PRs do not require rebuilding NVAccel. If you also built the Tahoe accelerator in section 6 and have a compatible prebuilt framebuffer, include it explicitly:

```bash
python3 build/stage_package.py "/path/to/upstream/pkgroot" \
  "$HOME/nvmtl-build/tahoe-package/pkgroot" \
  --accel-26 out/tahoe/NVAccel.kext
```

This replaces `Library/NullMoth/kexts/26/NVAccel.kext` and refreshes its nested `SHA256SUMS`. With `accel_build_all.sh`, the corresponding input is `out/accel/26/NVAccel.kext`. Both prebuilt OS variants must be present because upstream's installer requires them; this helper updates only the Tahoe accelerator when requested.

For outputs in other locations, use `--plugin /path/to/NVMTLDriver`, `--translator /path/to/libnvmtl_translate.dylib`, and optionally `--framebuffer-plist /path/to/Info.plist`. The helper checks that replacement binaries contain x86_64 code. It copies finalized binaries byte-for-byte and performs no signing or install-name edits. Complete the translator build steps in section 5 first.

The package's upstream `install.sh`, `uninstall.sh`, supporting tools, and `VERSION` are preserved. The helper makes the two scripts executable, regenerates the root `SHA256SUMS` over the final package, and verifies every generated checksum. These are packaging checks; they do not establish compatibility between a newer source build and an older prebuilt framebuffer or NVK. This stages the Tahoe PR outputs, not every component changed by the upstream merge described at the top of this guide.

This workflow uses the SIP and Secure Boot settings in [README.md](README.md#wiring-into-an-existing-opencore-setup). [Apple documents unsigned development kexts](https://developer.apple.com/library/archive/documentation/Security/Conceptual/System_Integrity_Protection_Guide/KernelExtensions/KernelExtensions.html) with the relevant SIP restrictions disabled. A correct package checksum is separate from kernel approval and loading.

Install the resulting package **while running Tahoe**:

```bash
cd "$HOME/nvmtl-build/tahoe-package/pkgroot"
shasum -a 256 -c SHA256SUMS --quiet
sudo bash ./install.sh
```

After the installer reports success, reboot. It selects the Tahoe accelerator and rebuilds the Auxiliary Kernel Collection. Verify after reboot:

```bash
kmutil showloaded --list-only | grep nullmoth
```

Expect `NVRM`, `NVRMFB`, `NVAccel`, and `NVRMAGDC`. The preserved uninstaller is available as `sudo bash ./uninstall.sh` from the same package directory. Use these tools on the installed OS, not in Recovery against another mounted volume.

For distribution, create the archive outside `pkgroot`:

```bash
tar -czf "$HOME/nvmtl-build/nullmoth-tahoe-custom.tar.gz" \
  -C "$HOME/nvmtl-build/tahoe-package" pkgroot
```

The plugin and translator builds retain the icon and glyph fixes; building the accelerators together keeps the framebuffer interface consistent. The plugin keys its shader cache by translator content, so a changed library gets a new shader-cache identity after the process restarts. An identical translator binary does not invalidate cached images.

After installing, verify that the active files match the outputs you built. Each pair below should have the same SHA-256:

```bash
shasum -a 256 "$plugin_out/NVMTLDriver" \
  /Library/GPUBundles/NVMTLDriver.bundle/Contents/MacOS/NVMTLDriver
shasum -a 256 "$translator_out" \
  /Library/GPUBundles/nvmtl/libnvmtl_translate.dylib

bundled_translator=/Library/GPUBundles/NVMTLDriver.bundle/Contents/MacOS/libnvmtl_translate.dylib
if [ -e "$bundled_translator" ]; then
  shasum -a 256 "$translator_out" "$bundled_translator"
fi
```

For comparison, the plugin extracted from the official 1.14.0 package during this audit had SHA-256 `97dec4756bbf404dde6532e949237de9bafc8835e0640503b933001c753bb85b`. Its bundled translator had SHA-256 `808c76cfe0ab76cc28c5542b59ecdf9b49ad92e01741da66af2b8080baeec1ba`. These identify the audited binaries, not a known-good rendering result.

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

The official-package regression persisted after this cache reset, while the user confirmed the fork's retained fixes work. If it recurs with a later build, retain the installed component hashes and the OS build number with the reproduction to distinguish that build from the known-working fork.

PR #112 reports restored System Settings sidebar glyphs on RTX 5070 Ti / macOS 26.6. Ghostty's incorrectly sized foreground remains outside these fixes. These patches are not a claim of complete Tahoe support.

## References

- [Upstream 1.15.0 snapshot merged into this fork](https://github.com/nullmoth/nvidia-macos-driver/commit/56bc4f9ae3105df052eefd3ea094c782e56853c3).
- [Upstream 1.14.7 release](https://github.com/nullmoth/nvidia-macos-driver/releases/tag/v1.14.7).
- [PR #171: WoW Classic shader translation and Vulkan feature fixes](https://github.com/nullmoth/nvidia-macos-driver/pull/171) — revision `47e3e08192d36e6aef67cf433adb24c4dce9eddf`.
- [PR #136: MSAA without programmable 1x sample positions](https://github.com/nullmoth/nvidia-macos-driver/pull/136) — revision `a4d77592b2bca750a346f20475dce462cf120bd1`, adapted to retain upstream's default-position fallback.
- [PR #147: optional scheduled notification after surface writes](https://github.com/nullmoth/nvidia-macos-driver/pull/147) — revision `648df70fe27f302634045611ad5042fdc88764bc`.
- [PR #131: NVIDIA-only framebuffer claim](https://github.com/nullmoth/nvidia-macos-driver/pull/131) — revision `1f10026e780c104b90a3aa011ac93c2208bbd439`, with its plist-equality test adapted.
- [Upstream 1.14.2 release](https://github.com/nullmoth/nvidia-macos-driver/releases/tag/v1.14.2).
- [Upstream 1.14.1 release](https://github.com/nullmoth/nvidia-macos-driver/releases/tag/v1.14.1).
- [Upstream 1.14.0 release](https://github.com/nullmoth/nvidia-macos-driver/releases/tag/v1.14.0).
- [Build both accelerators from the same source](https://github.com/nullmoth/nvidia-macos-driver/commit/8c9429c8984f5c8f0c18fb9ffafbf81b299cd14d).
- [PR #79: Tahoe icon rendering fixes](https://github.com/nullmoth/nvidia-macos-driver/pull/79) — the patch applied here is revision `74c0dc30ab8e58139707fb603948329a1cede67f`.
- [PR #112: CoreImage resize and System Settings glyph fix](https://github.com/nullmoth/nvidia-macos-driver/pull/112) — the patch applied here is revision `a6c38cd52ee23e335e08af89824b72aca4f9fcdb`.
- [Issue #51: Tahoe NVAccel VRAM ABI mismatch](https://github.com/nullmoth/nvidia-macos-driver/issues/51).
- [Test build 2: matching 1.13.0 components and hardware results](https://github.com/modesttao/nvidia-macos-driver/releases/tag/icons-test2).
- [Apple: installing command-line developer tools](https://developer.apple.com/library/archive/technotes/tn2339/_index.html).
