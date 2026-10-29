# Wine/NVK validation tools

These probes distinguish native Vulkan, Windows Vulkan, and D3D11 through DXVK.
They do not replace actual game testing or establish an FPS improvement.

`d3d12_probe.cpp` and `d3d12_probe.hlsl` additionally exercise the optional
vkd3d-proton candidate. Compile the HLSL entry points `cs`, `vs` and `ps` with
Microsoft DXC targeting `cs_6_0`, `vs_6_0` and `ps_6_0`, producing `cs.dxil`,
`vs.dxil` and `ps.dxil` in one private shader directory. Build the probe with:

```sh
/absolute/llvm-mingw/bin/x86_64-w64-mingw32-clang++ \
  -std=c++17 -O2 -static tools/wine-nvk/d3d12_probe.cpp \
  -ld3d12 -ldxgi -ldxguid -lole32 -luser32 -lgdi32 \
  -o /absolute/tests/d3d12-probe.exe
```

Initialize a separate prefix as below, then use the candidate helper's
`install-d3d12 ROOT PREFIX` command. Set
`WINEDLLOVERRIDES='d3d11,dxgi,d3d12,d3d12core=n;mscoree,mshtml='` and
`VKD3D_CONFIG=nodxr`, preserving the scoped native provider and cache paths.
Pass `--shaders 'Z:\absolute\tests\shaders'` to the probe for device creation,
DXIL compute, a root UAV, fence completion and 1,024 checked readback words.
Add `--window --frames 120` for DXIL vertex/pixel rendering, five pixel readbacks,
presentation and resize. GPU fence waits are bounded to ten seconds. This is a
correctness test with deliberate synchronization/readback overhead.

Both modes passed on RTX 2060 SUPER / Tahoe 26.7.1 with vkd3d-proton 3.1,
DXC 1.9.2609 and YAAGL Wine 11.0-1. D3D11 and shared-resource probes also passed
with the candidate installed. ZZZ D3D12 gameplay and DLSS SR Quality were also user-confirmed on this setup.
Ray tracing and frame generation remain unqualified; see [status](../../nvk/wine-macos/README.md#d3d12-and-dlss).

Build from the driver repository root, with Xcode command line tools, Vulkan
headers, and an x86_64 llvm-mingw cross compiler. Keep outputs and temporary files
in a private test directory. The cross-compiled probes load Vulkan dynamically.

```sh
xcrun clang++ -arch x86_64 -mmacosx-version-min=15.0 \
  -std=c++17 -fobjc-arc -O2 -I /absolute/Vulkan-Headers/include \
  tools/wine-nvk/host_abi.mm -framework Foundation -o /absolute/tests/host-abi

/absolute/llvm-mingw/bin/x86_64-w64-mingw32-clang++ \
  -std=c++17 -O2 -static -I /absolute/Vulkan-Headers/include \
  tools/wine-nvk/win32_vulkan_probe.cpp -luser32 -lgdi32 \
  -o /absolute/tests/win32-vulkan-probe.exe

/absolute/llvm-mingw/bin/x86_64-w64-mingw32-clang++ \
  -std=c++17 -O2 -static tools/wine-nvk/d3d11_probe.cpp \
  -ld3d11 -ldxgi -ld3dcompiler -luser32 -lgdi32 -lole32 -luuid \
  -o /absolute/tests/d3d11-probe.exe
```

Run the native ABI probe with the exact Wine frontend path. It reports symbol
owners, direct/proc-address lookup coherence, device capabilities and an actual
GPU fill/readback of 1024 words:

```sh
/absolute/tests/host-abi /absolute/runtime/lib/libnvk_wine.dylib
```

For Windows probes, initialize a new dedicated prefix and set the same scoped
provider route used by the launcher. Use absolute paths throughout:

```sh
export WINEPREFIX=/absolute/tests/prefix
export WINEARCH=win64
export DYLD_LIBRARY_PATH=/absolute/runtime/lib
export DYLD_PRINT_LIBRARIES=1
export WINEDLLOVERRIDES='mscoree,mshtml='
export WINEDEBUG='+timestamp,+pid,+loaddll'
/absolute/runtime/wine/bin/wine /absolute/tests/win32-vulkan-probe.exe
/absolute/runtime/wine/bin/wine /absolute/tests/win32-vulkan-probe.exe \
  --window --images 3 --frames 120
/absolute/runtime/wine/bin/wine /absolute/tests/win32-vulkan-probe.exe \
  --window --images 4 --frames 120 --two-surfaces
```

Put `TMPDIR`, `MESA_SHADER_CACHE_DIR`, `XDG_CACHE_HOME`, `XDG_CONFIG_HOME` and
`XDG_DATA_HOME` in the same private test root if all mutable state must remain
there. Capture stdout/stderr and the exact runtime hashes for each run. Verify
that the Windows process loads both private NVK libraries. The window probe also
exercises resize, minimize/restore and legacy/core/KHR queue submission aliases.

Install the matched DXVK pair only after Wine has created the prefix:

```sh
/absolute/runtime/bin/nvk-runtime install /absolute/runtime "$WINEPREFIX"
export WINEDLLOVERRIDES='d3d11,dxgi=n;mscoree,mshtml='
export DXVK_LOG_PATH=/absolute/tests/dxvk-logs
export DXVK_LOG_LEVEL=info
export DXVK_HUD=devinfo,fps,frametimes
/absolute/runtime/wine/bin/wine /absolute/tests/d3d11-probe.exe
/absolute/runtime/bin/nvk-runtime restore /absolute/runtime "$WINEPREFIX"
```

Create the log directory first. The D3D11 probe verifies 300 presents, 600 textured
draws, depth rejection, alpha blending, 11 staging-readback pixel checks and resize.
Readback deliberately adds diagnostic cost. This is a correctness test.

## Host lifetime and setup checks

`d3d11_shared_probe.cpp` is a separate regression reproducer for DXVK's rejected
shared-resource path. Build it with the same command as `d3d11_probe.cpp`, replacing
the source/output name and omitting `-ld3dcompiler`. Run it with the same private
provider, prefix and native DLL pair. It tests feature levels 11.0/11.1, ordinary,
shared, keyed and NT texture flags, failed external-handle exports and eight GPU
pixel checks. The stock DXVK 3.1.1 pair crashes on its first shared texture on this
runtime; the local repair completes without pretending external sharing works.

The shared frontend's host fixture uses mocked Vulkan submissions. ASan/UBSan
checks cover bounds, acquisition timeouts, failed submissions, command scope,
direct exports, capability filtering and retention when completion is uncertain:

```sh
xcrun clang++ -arch x86_64 -mmacosx-version-min=15.0 \
  -std=c++17 -fobjc-arc -O1 -g -fsanitize=address,undefined \
  -fno-omit-frame-pointer -DNVKBRIDGE_WINE=1 \
  -I /absolute/Vulkan-Headers/include nvk/native-macos/host_test.mm \
  -framework Foundation -framework QuartzCore -framework Metal \
  -framework IOSurface -framework IOKit -o /absolute/tests/wine-host-test
ASAN_OPTIONS=detect_leaks=0 /absolute/tests/wine-host-test
python3 tools/wine-nvk/test_setup.py \
  --runtime /absolute/runtime --work /absolute/new/setup-tests
```

Leak detection is disabled for process-lifetime Objective-C/global objects.
The timeout fixture does not induce a real GPU fault. Setup tests use synthetic
prefix files and the real native helper: coherent install/rollback, partial
operation recovery, changed files, concurrency, path escape, tampering and
architecture rejection. These filesystem checks do not execute Wine.

Run actual Windows and D3D11 probes again after moving the complete runtime to a
path containing spaces. Inspect loaded-image paths for accidental dependencies
on the old root. Test gameplay separately, including warm-cache frame times,
scene transitions, repeat launch/shutdown and a sustained session.

## NGX/DLSS and HUD validation

`ngx_probe.cpp`, `ngx_evaluate.cpp` and `ngx_params_msvc.cpp` use NVIDIA's
unmodified [DLSS SDK headers](https://github.com/NVIDIA/DLSS). Compile the
parameter wrapper only with `clang++ --target=x86_64-pc-windows-msvc -O2
-fno-exceptions -fno-rtti -I SDK/include -c ngx_params_msvc.cpp`; NGX returns an
MSVC C++ interface, so the LLVM-MinGW overload-vtable ABI is not interchangeable.
Compile/link the other two sources and that object with LLVM-MinGW, `-std=c++17
-static -ld3d12 -ldxgi -ldxguid -luser32 -lole32`. Do not copy SDK headers into
this repository. Use `--project --evaluate` in a disposable prefix with the
matched NGX/NVAPI DLLs, the game's original feature DLL and native DLSS flags.
The probe uses a diagnostic project ID, not a registered game's identity.

The three-frame DLSS SR test passed 320×180 → 640×360 with 4,680 checked colour
values and no mismatches. It tests constant regions and an edge, not temporal
quality or a performance gain. `streamline_probe.cpp` separately checks the
game's public Streamline initialization and feature requirements; its plugin
path is supplied on the command line. Neither probe qualifies DLSSG.

The native Wine `host_test.mm` covers HUD pacing, cached bitmap rendering,
clipping, child flags and lifetime behavior; sanitizer checks passed on the
prototype. `smoke.mm` with `NVKBRIDGE_VERIFY_PIXELS=1`, `NVKBRIDGE_VERIFY_HUD=1`
and `WINE_NVK_HUD=fps,frametimes` validates the HUD and surrounding drawable
pixels using a separate test-only readback. 45 frames, resize and restore passed.
Normal presentation does not read the full game frame through the CPU.

Validate the compiled provider with its real installer:

```sh
python3 tools/wine-nvk/test_setup.py --runtime /absolute/provider --work /absolute/test-output
python3 tools/wine-nvk/test_dlss_setup.py --runtime /absolute/provider \
  --wine /absolute/prepared-wine/bin/wine --work /absolute/test-output
```

The second test creates private prefixes, verifies repeat installs, original
string/DWORD/absent registry values, tamper preflight and restoring NGX without
removing D3D12. Both tests pass against the compiled 2.6.4 Wine/NVK provider
on the Tahoe test host (19 setup checks and three real registry scenarios).
Component extraction can also be tested without compilation with
`test_provider_components.py` and the pinned input archives/source.
