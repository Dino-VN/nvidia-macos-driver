# Native NVK runtime for Wine and DXVK

[User setup: Wine, CrossOver and YAAGL](INSTALL.md). This page covers source,
packaging and validation. The launcher lives in [HighDelay/yaagl-nvk](https://github.com/HighDelay/yaagl-nvk)
and the repaired DXVK pair in [HighDelay/dxvk-nvk](https://github.com/HighDelay/dxvk-nvk/tree/nvk-3.1.1).

This package lets Windows D3D11 applications use the fork's native NVK renderer
through Wine and DXVK. The modified YAAGL launcher selects the package and keeps
its Wine prefix separate from the launcher's other backends.

```text
Windows D3D11 game → DXVK → Wine Vulkan → native NVK → NVIDIA GPU
```

DXVK still translates D3D11 and shaders to Vulkan/SPIR-V, and Wine still supplies
Windows compatibility. This route bypasses MoltenVK's Vulkan-to-Metal translation
and NVMTL's Metal/AIR-to-SPIR-V translation for game rendering. Metal supplies the
macOS display drawable. A GPU copy transfers completed frames into its IOSurface;
this is not zero-copy. Normal presentation does not read or upload pixels on the
CPU, but currently waits on the CPU for each presentation copy to finish.

## Requirements and current status

- Intel x86_64 macOS, with a compatible installed NVIDIA driver and matching NVK
  IOSurface import protocol. The bundled renderer targets macOS 15.5 or newer.
- Either the complete Wine/NVK package and YAAGL's `dxvk-nvk` backend, or the
  compact provider and a compatible external Wine installation.
- D3D11. This backend does not support D3D12.

On RTX 2060 SUPER / Tahoe 26.7.1, real Windows Vulkan GPU readback and window
presentation, two-window presentation, and a textured D3D11/DXVK probe passed.
The D3D11 probe completed 300 presents, 600 textured draws, depth/blend checks,
11 staging readbacks and a resize. ZZZ gameplay through YAAGL Wine 11.0-1 is
user-confirmed, including characters, scenery, UI and the FPS overlay.
Genshin Impact and Honkai: Star Rail share the new backend and D3D11 launch
handling, in global and CN builds. Their gameplay remains untested.
No controlled FPS comparison has been made.
Physical Sequoia testing, commercial CrossOver releases and other GPU families
remain unqualified.

## Setup with YAAGL

1. Keep `runtime/`, the custom YAAGL app and its `launcher-data/` directory
   together. `launcher-data/nvk-runtime` points to `../runtime`.
2. Open the supplied launcher and select **Settings → Wine → NVIDIA NVK + DXVK
   (local, experimental)**.
3. Let the launcher initialize its dedicated `wineprefix-nvk` prefix. It validates
   the runtime, initializes Wine, and installs the matched native x64
   `d3d11.dll` / `dxgi.dll` pair with a rollback journal.
4. Download ZZZ into the chosen game directory, then launch. The backend forces
   `-force-d3d11`; a saved D3D12 preference cannot override it.
5. Check the DXVK HUD and game launch logs. The underlying Vulkan device must
   identify NVIDIA/NVK, and loaded-image logs must show this package's
   `libnvk_wine.dylib` and `libnvk_renderer.dylib`.

The launcher sets `WINEDLLOVERRIDES=d3d11,dxgi=n` while preserving unrelated
overrides. It refuses conflicting DLLs in the game directory instead of replacing
them. ReShade is not enabled for this backend. Runtime validation, cache paths and
graphics settings are local to the launched processes.

The tested backend also defaults to `dxvk.enableDescriptorBuffer = False` and
logs `Binding model: Legacy`. The descriptor-buffer path rendered ZZZ scenery
but lost characters and HUD text; switching to descriptor sets restored both.
The FPS/frame-time/device HUD is enabled by default. ZZZ gameplay rendering is
user-confirmed; GI/HSR and sustained stability/performance remain unqualified.

DXVK may report an AMD PCI vendor to D3D11 applications as its normal NVIDIA/NVAPI
workaround. Check its Vulkan device/driver log and actual loaded libraries rather
than using that emulated vendor alone to identify the rendering GPU.

## Package and build

The source is in this driver repository. YAAGL integration is in
[YAAGL NVK](https://github.com/HighDelay/yaagl-nvk). DXVK and Wine
source are pinned as dependencies. Wine's binary code is unchanged. DXVK 3.1.1
needs the local shared-resource fallback repair below for ZZZ startup. Compiled
runtime archives belong in release assets.

The build needs Xcode command line tools, Python 3.12 or newer, Vulkan headers,
the matching private NVK renderer, the exact vendor archives below, and their
license/source records. Use an output directory that does not already exist.

```sh
python3 nvk/wine-macos/package.py \
  --output /absolute/new/nvk-wine-runtime \
  --renderer /absolute/minecraft-runtime/lib/libnvk_renderer.dylib \
  --headers /absolute/Vulkan-Headers/include \
  --wine-archive /absolute/wine-crossover-11.0-1-osx64-signed.tar.xz \
  --dxvk-archive /absolute/dxvk-3.1.1.tar.gz \
  --dxvk-source /absolute/dxvk-v3.1.1 \
  --mesa-license /absolute/Mesa-license.rst \
  --wine-cert-fragment /absolute/yaagl-wine-cert.inf.fragment
```

For YAAGL, the last argument is the existing launcher's Wine INF certificate
fragment, applied only to the private Wine package/prefix. Preserve its YAAGL
revision and hash. It does not install macOS certificates or modify `/etc/hosts`.
The frontend alone can be built with `build.py --output ... --renderer ...
--headers ...`; that output does not include Wine, DXVK or the setup helper.

| Dependency | Pinned identity |
|---|---|
| Wine archive | YAAGL `wine-crossover-11.0-1-signed`, SHA-256 `89fa7e90fb626523a90d5867a03c6be785d017176739c6320a3b86c7838c3a35` |
| DXVK | v3.1.1, commit `b1a1c99ab52b687cf950d62c88bc2fa316b41663` |
| DXVK archive | SHA-256 `40565b4a724aadc4433fa4e010b4b23916d9b1f1baeee64e17186db94f54e608` |
| YAAGL NVK integration | `eb42ac6f596b3b3686f3f8b58b9c46ed56937f01`, on base `4543cc5c5a66e8d1a702111fb095682019948fcb` |
| Repaired DXVK fork | `e1c9938a60e1fbdb89a265e1087b2395ca17933e`, branch `nvk-3.1.1` |

The Wine binary release does not identify its exact CrossOver patch revision.
Its archive hash and reference source are recorded; a fully reproducible Wine
source build remains unresolved. Keep that limitation explicit when preparing a
public bundle and provide the matching dependency source/license records.

The two private Wine loaders are re-signed with
`com.apple.security.get-task-allow` to satisfy their task-port exchange on the
tested Tahoe host. SDK retagging did not fix that exchange and is not used.
No boot arguments, global loader selection or installed CrossOver files change.

### Compact runtime for driver packages

After building the repaired full bundle below, extract its matched Vulkan/DXVK
libraries and rebuild the setup helper for use with an external Wine installation:

```sh
python3 nvk/wine-macos/provider.py \
  --base /absolute/repaired-runtime --output /absolute/new/wine-provider
```

This output contains no Wine installation or prefix. It carries the frontend,
private renderer, `libMoltenVK.dylib` alias, paired DXVK DLLs, setup helper,
licenses, source records, manifest and checksums. Use it with the existing package
stager's **`--wine-runtime /absolute/new/wine-provider`** option, alongside the
usual plugin/translator/kext and optional Minecraft arguments. The stager validates
it before and after copying to `Library/GPUBundles/nvmtl/wine`, and includes
`WINE-NVK.md` in the package. The existing installer/uninstaller manages it through
the ordinary nvmtl directory copy/removal; no system-wide provider selection changes.

`provider.py` copies the tested native libraries and DXVK DLLs byte-for-byte;
it does not rebuild NVK or qualify a different Wine/CrossOver version. Run the
setup fixtures on its rebuilt helper and retain a coherent renderer/driver pair.
Compiled bundles remain release assets rather than checked-in binaries.

## Integrity, logs and rollback

### DXVK shared-resource fallback repair

The stock DXVK 3.1.1 DLLs crash on the tested ZZZ startup when shared memory is
unavailable: a rejected sharing request still propagates its handle type into the
allocator, which calls the unavailable `vkGetMemoryWin32HandleKHR`. The local
patch keeps the allocation's default no-sharing handle type unless the image was
actually made shareable. It also refuses optional shared semaphore/keyed-mutex
creation when Win32 semaphore sharing is unavailable. Ordinary texture rendering
and DXVK's local-storage fallback remain available; external handles are not faked.

Apply [the DXVK patch](patches/dxvk-3.1.1-shared-fallback.patch) to the pinned DXVK
v3.1.1 checkout. Build its x64 `d3d11.dll` and `dxgi.dll` together with Meson/Ninja,
an x64 MinGW cross compiler, glslang and the pinned recursive DXVK submodules.
The local test used llvm-mingw 20261020, glslang 16.6.0, Meson 1.12.1 and Ninja
1.13.2, release optimization with debug symbols retained in the build directory.

```sh
git -C /absolute/dxvk-v3.1.1 apply /absolute/driver/nvk/wine-macos/patches/dxvk-3.1.1-shared-fallback.patch
meson setup /absolute/dxvk-build /absolute/dxvk-v3.1.1 \
  --cross-file /absolute/win64-cross-file.txt --buildtype release -Ddebug=true \
  -Denable_d3d8=false -Denable_d3d9=false -Denable_d3d10=false
ninja -C /absolute/dxvk-build
python3 nvk/wine-macos/replace-dxvk.py \
  --base /absolute/base-runtime --output /absolute/new/repaired-runtime \
  --dxvk-source /absolute/dxvk-v3.1.1 --dxvk-build /absolute/dxvk-build \
  --strip /absolute/llvm-mingw/bin/llvm-strip
```

The last command creates a new runtime, retains the base, strips only delivered
DLL debug sections, records source/submodules/compiler/options in `DXVK-BUILD.json`
and updates its runtime identity and checksums. Close the game and restore the
old prefix DLL journal before installing a different runtime identity.

The original DLLs reproduce an execute-at-null crash on the first shared texture.
The repaired pair passes eight GPU readbacks across feature levels 11.0/11.1 and
ordinary/shared/keyed/NT texture variants, while handle export remains refused.
The normal 300-present/600-draw test also passes. ZZZ then reached its menu/login
after enabling YAAGL's existing Steam Patch and timeout-fix options with the same
Wine 11.0-1 build. A preceding second crash was in `MHYPBase.dll`, separate from
the DXVK fault. ZZZ gameplay later rendered correctly with descriptor sets;
sustained stability and a performance comparison remain unqualified.

The patch changes DXVK code covered by its zlib license; preserve the DXVK license
and attribution when distributing it. The same repair is published on the
`nvk-3.1.1` branch of [HighDelay/dxvk-nvk](https://github.com/HighDelay/dxvk-nvk).
Use either that commit or the patch on v3.1.1, not both.

`nvk-wine-runtime.json` records the package identity and critical file hashes;
`BUILD.json` records source and build provenance; `SHA256SUMS` covers delivered
regular files. `LICENSES/` contains the component licenses. The native helper
checks hashes, architectures, signatures and the private provider alias:

```sh
/absolute/runtime/bin/nvk-runtime check /absolute/runtime
```

The Wine library lookup uses a scoped `DYLD_LIBRARY_PATH` and a package-local
`libMoltenVK.dylib` alias to `libnvk_wine.dylib`. Logs verify the actual library
loaded by the Windows process. The alias does not invoke the MoltenVK renderer.
General external-memory/semaphore sharing, HDR and unsupported WSI extensions
are not advertised. Private staged IOSurface import remains available internally.

Each game launch records `runtime.json` and DXVK logs beside the normal game log
in a `.nvk` directory. Startup library logs identify the provider; per-call Vulkan
tracing is confined to diagnostic probes. Prefixes, game data and account state
are excluded from release archives.

Close the game before changing runtime packages. Select another Wine distribution
to use its ordinary prefix again. To restore the two original DLLs in the NVK
prefix, run:

```sh
/absolute/runtime/bin/nvk-runtime restore /absolute/runtime /absolute/wineprefix-nvk
```

Rollback validates both originals before changing either file. It refuses to
overwrite unexpected user modifications. It does not require a valid runtime
manifest, reinstalling the driver, changing NVRAM or removing Minecraft's runtime.

Probe sources and rebuild commands are in [tools/wine-nvk](../../tools/wine-nvk/README.md).
