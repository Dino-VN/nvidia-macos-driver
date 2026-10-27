# Wine / CrossOver native NVK

This runtime lets compatible x64 Wine builds send Vulkan directly to this
driver's native NVK renderer. For D3D11 games, the included DXVK DLLs translate
D3D11 to Vulkan first:

| Provider | Game rendering path |
|---|---|
| DXVK + MoltenVK | D3D11 → DXVK → Vulkan → MoltenVK → Metal → NVMTL → NVK → NVIDIA GPU |
| DXVK + native NVK | D3D11 → DXVK → Wine's Vulkan bridge → native NVK → NVIDIA GPU |

It removes MoltenVK's Vulkan-to-Metal conversion and NVMTL's Metal/AIR-to-SPIR-V
translation from game rendering. Wine, DXVK and NVK shader compilation remain.
Finished frames are copied on the GPU into a Metal drawable for macOS presentation;
this is not zero-copy, but it does not read back/upload pixels through the CPU.
Fewer translation stages can reduce conversion overhead. A controlled FPS gain
over MoltenVK has **not** been measured.

## Requirements

- This fork's driver and a matching Wine/NVK runtime, on Intel macOS **15.5+** or
  **Tahoe 26**, with a supported NVIDIA GPU.
- An **x64 Windows D3D11** game and a compatible macOS Wine Vulkan bridge. D3D12,
  32-bit games, HDR and cross-process external GPU-handle sharing are not supported
  by this integration.
- The matched, repaired DXVK **3.1.1** `d3d11.dll` / `dxgi.dll` pair supplied with
  the runtime. Stock 3.1.1 can crash when a game requests an unsupported shared texture.

**Verified:** ZZZ gameplay on RTX 2060 SUPER / Tahoe 26.7.1 using YAAGL's Wine
11.0-1 build, including characters, scenery, UI and FPS overlay. Windows Vulkan
readback/presentation and D3D11 depth/blend/shared-texture probes also pass.
Genshin Impact, Honkai: Star Rail, commercial CrossOver releases, other Wine builds
and physical Sequoia hardware have **not** been qualified.

## YAAGL: ZZZ, Genshin Impact and Honkai: Star Rail

Use [HighDelay/yaagl-nvk](https://github.com/HighDelay/yaagl-nvk) for these games.
Its packages contain launchers only. The driver supplies NVK and the patched
DXVK pair; first setup downloads/prepares the compatible Wine build separately.
The driver alone does not install the launcher or game.

1. Install this fork's driver and reboot.
2. Extract the YAAGL NVK package and use the desired game's supplied **Start** command.
3. Select **Settings → Wine → NVIDIA NVK + DXVK (local, experimental)**.
4. Install or select the game directory, then launch. This backend creates a
   separate `wineprefix-nvk`, selects D3D11, installs the matched DLLs and enables
   the FPS/frame-time/device overlay. Its packaged defaults enable YAAGL's existing
   Steam Patch and timeout fix; HSR retains its Jadeite launch handling.

All three games have launcher configurations, including global/CN variants.
**Only ZZZ gameplay is verified so far.** See [YAAGL's setup guide](https://github.com/HighDelay/yaagl-nvk/blob/main/docs/NVK.md).
YAAGL requires `/Library/GPUBundles/nvmtl/wine` for both Vulkan and DXVK. There
is no bundled renderer fallback or separate DXVK download. To update DXVK,
replace both DLLs in the driver runtime and regenerate its manifest/checksums.
YAAGL uses that installed pair. Wine downloads on first setup into the launcher's
private `launcher-data/wine-nvk` directory.

## Standalone Wine

Install a driver release that includes the Wine/NVK runtime, or extract a matching
standalone runtime. Driver packages install the compact provider at
`/Library/GPUBundles/nvmtl/wine`. It contains the libraries and DXVK pair, **not
Wine itself**. YAAGL downloads its Wine installation separately on first setup.
Close applications in the prefix before installing or restoring the DLL pair.

Choose a compatible Wine executable and create a dedicated 64-bit prefix:

```sh
nvk_runtime=/Library/GPUBundles/nvmtl/wine
nvk_wine=/absolute/path/to/wine
nvk_prefix="$HOME/Library/Application Support/Wine/NVK"
"$nvk_runtime/bin/nvk-runtime" check "$nvk_runtime"
env WINEPREFIX="$nvk_prefix" WINEARCH=win64 "$nvk_wine" wineboot.exe --init
"$nvk_runtime/bin/nvk-runtime" install "$nvk_runtime" "$nvk_prefix"
```

For the verified Wine build, you can use YAAGL's prepared
`launcher-data/wine-nvk/bin/wine` after first setup. Install any game prerequisites
in this same prefix. Launch a
D3D11 executable with the runtime selected **for this process only**:

```sh
cd /absolute/path/to/game
env WINEPREFIX="$nvk_prefix" \
  DYLD_LIBRARY_PATH="$nvk_runtime/lib" \
  WINEDLLOVERRIDES='d3d11,dxgi=n' \
  DXVK_CONFIG='dxvk.enableDescriptorBuffer = False' \
  DXVK_HUD='devinfo,fps,frametimes,scale=1.25' \
  DXVK_LOG_LEVEL=info DXVK_LOG_PATH="$nvk_prefix" \
  "$nvk_wine" ./Game.exe
```

Select the game's D3D11 renderer if it offers several backends. Append unrelated
DLL overrides to `WINEDLLOVERRIDES` if your game needs them. Remove game-local
`d3d11.dll` / `dxgi.dll` overrides from this test setup, or they may supersede the
matched system32 pair. Do not mix DXMT/D3DMetal/ReShade DLLs into this NVK setup.

Keep `dxvk.enableDescriptorBuffer = False`: the tested descriptor-buffer path
rendered scenery but lost ZZZ characters and HUD text; descriptor sets fixed both.
Use `DXVK_HUD=0` to hide the overlay. Do not export `DYLD_LIBRARY_PATH` globally or
replace Wine's/CrossOver's installed MoltenVK library.

## CrossOver — opt-in compatibility test

Commercial CrossOver is **not tested**. Its Wine version, library validation or
Vulkan loader may differ; these steps describe a scoped test, not guaranteed
compatibility with every release. If it still loads MoltenVK or rejects the
provider, use the verified YAAGL Wine package rather than modifying CrossOver.app.

1. Duplicate the game's **64-bit** bottle for the NVK test. Close its applications.
2. Select **Wine** as its graphics backend (or disable the DXVK/DXMT/D3DMetal
   toggles on older releases), so CrossOver does not install a different DLL pair.
3. From the bottle, use **Open Shell**. CodeWeavers documents this under
   [Bottle Commands](https://support.codeweavers.com/en_US/crossover-mac-user-guide).
   Keep that shell's CrossOver environment and use the actual bottle directory
   shown by CrossOver if your bottles are stored elsewhere.
4. In that shell, install the runtime DLLs and launch through CrossOver's Wine:

```sh
nvk_runtime=/Library/GPUBundles/nvmtl/wine
nvk_bottle='My Game NVK'
nvk_prefix="$HOME/Library/Application Support/CrossOver/Bottles/$nvk_bottle"
nvk_cx_wine='/Applications/CrossOver.app/Contents/SharedSupport/CrossOver/bin/wine'
"$nvk_runtime/bin/nvk-runtime" install "$nvk_runtime" "$nvk_prefix"
cd "$nvk_prefix/drive_c/path/to/game"
env WINEPREFIX="$nvk_prefix" \
  DYLD_LIBRARY_PATH="$nvk_runtime/lib" \
  WINEDLLOVERRIDES='d3d11,dxgi=n' \
  DXVK_CONFIG='dxvk.enableDescriptorBuffer = False' \
  DXVK_HUD='devinfo,fps,frametimes,scale=1.25' \
  DXVK_LOG_LEVEL=info DXVK_LOG_PATH="$nvk_prefix" \
  "$nvk_cx_wine" --bottle "$nvk_bottle" --cx-app ./Game.exe
```

Change the app path if CrossOver is installed elsewhere. Continue using this
scoped command for the NVK test; an ordinary GUI launch does not select this
provider automatically. No CrossOver installation files are replaced.

## Verify, update and restore

The DXVK HUD/log should identify **NVK / NVIDIA** and the log should say
`Binding model: Legacy`. A D3D11 app may see an emulated AMD PCI vendor because
of DXVK's normal NVAPI workaround; that alone does not identify the Vulkan GPU.
For provider diagnostics, add `DYLD_PRINT_LIBRARIES=1` to the same launch command
and capture stderr. The Windows process must load this runtime's
`libnvk_wine.dylib` and `libnvk_renderer.dylib`. Its local `libMoltenVK.dylib`
is an alias to the NVK frontend, not the MoltenVK renderer. A generic
`VK_ICD_FILENAMES` setting alone does not select it in the verified Wine build.

The helper validates hashes, signatures and architectures, then installs both
DLLs with an original-file backup and rollback journal. To switch runtime
versions that change the DLL pair, close the prefix's applications, restore first,
then install the new pair. An identical DLL pair can adopt a new provider identity
without replacing DLLs or losing its original-file backups:

```sh
"$nvk_runtime/bin/nvk-runtime" restore "$nvk_runtime" "$nvk_prefix"
```

Restore also works after the runtime was updated or its manifest became invalid.
Unexpected changes to installed DLLs or backups are refused before either DLL is
replaced. After restoring, use your normal Wine/CrossOver launch again. Minecraft's
runtime and the system's default Vulkan provider are independent of this setup.
