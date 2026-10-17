# OpenGL performance experiment on the 2.3.0 fork

This build selects the OpenGL changes from [pengubow's `opengl-perf` branch](https://github.com/pengubow/nvidia-macos-driver/commits/1706681662e1f8b0278b985ed3e742bf0d64d418/), based on upstream 2.1.0, and applies them to this fork's tested 2.3.0 base. It does not merge upstream 2.3.1.

## Imported changes

| Source commit | Change |
| --- | --- |
| `6ed805f` | Translate Minecraft's zero-offset integer-vector uniform loads and constant-selected texture/sampler pairs; reuse the translator's existing buffer-address table. |
| `8b5d622` | Exclude the bindless heap from stage buffer masks, reuse address-table descriptors with dynamic offsets, implement provoking-vertex/restart selectors, and create texture-buffer format views. |
| `a0265a5` | Track render buffer bindings in arrays; cache recent resource-set entries; copy pipeline descriptors before inspecting getters so GL's blit cache keeps working. |
| `05de7b5` | Reuse descriptor sets for matching texel-buffer layouts, including Sodium's terrain shaders. |
| `6e25f60` | Apply depth bias requested through Metal/OpenGL. |
| `c1da272` | Honor supported per-instance vertex divisors, including nonzero base instances. |
| `1706681` | Retry failed sampler translation for mixed argument buffers and sampler arrays. |

The `f482da2` benchmark tools are included too. The branch's general build scripts are unnecessary for this workflow. Its framebuffer-fetch repair is already in 2.3.0; the fork keeps that version, including its existing split limit.

Apple's GL renderer normally emulates last-vertex flat shading by rewriting index buffers. The imported profile adjustment enables the native selector only when the Vulkan device supports it and the renderer's NVIDIA capability bytes match the recognized profile. An unfamiliar profile keeps the existing renderer path. This is a process-local data change, not a modification to Apple's files on disk.

## Additional repairs

- Resource-phi folding requires the selector's single literal store to dominate its loads, and the selected resource to dominate the merge. Initialized, escaped and cyclic selector storage remains untouched. Shaders without phis skip the extra CFG analysis.
- The recent-resource cache stores the actual retained set member. Adding or removing a different but equal object cannot leave a dangling cached address or update the wrong residency count.
- Every new render encoder resets primitive restart, provoking vertex and depth bias. Depth bias uses Vulkan 1.3's dynamic enable; its zero default keeps the ordinary rasterization path disabled. The pipeline assembles its dynamic states in one bounded array.
- Reusing a pre-existing address table requires its block member to start at byte zero, as well as its existing element/stride checks. An incompatible table keeps the existing descriptor path.
- The benchmark checks shader linking, input counts, GL errors and readback errors, and reports an image checksum.

The changes retain parked-VRAM restoration, WindowServer's Dock completion wait, strict stencil detection, Chromium's GPU default and release `-O2`. The package uses the same tested 2.3.0 NVRM, NVRMFB, NVAccel and NVK binaries. Only the Metal plugin and AIR-to-SPIR-V translator need rebuilding.

## Checks and limits

`tools/test_opengl_perf.py` compiles the production descriptor-cache, resource-set and encoder-state code. It checks offset-only reuse, address-table page rollover, texel/image layout changes, direct-buffer changes, descriptor retirement, equal-object lifetime, reset defaults and all 128 combinations of optional dynamic pipeline states.

`tools/test_resource_phi_fold.py` runs the production pass and SPIR-V IR with eight control-flow cases. It omits unused `Ctx` fields so the checks can run when the native unit suite's unpublished fixtures are absent. The two imported Minecraft shader fixtures also run through the real translator, address lowering and SPIR-V Tools validation in the wrapper tests.

The broader test run exposed five pre-existing wide-load census failures, reproduced against `7f3c751`. The census counted only scalar loads aligned to four bytes, missing correctly preserved eight-byte alignment; it now counts scalar words by type. Staging-test mocks were also updated for the current `lipo` argument order and parent-traversal rejection policy. These changes affect tests only.

The full native test suite still needs unpublished `validation/fixtures/public` inputs. Two wrapper tests also require external Core Animation captures. The available fixture tests and CPU harnesses cannot establish frame rate or rule out hardware-specific regressions.

### Hardware comparison

Before installing this experiment, a short offscreen `glbench 500 5` run on RTX 2060 Super / Tahoe 26.7.1 with the existing fork produced:

| Case | Mean frame time | Image checksum |
| --- | --- | --- |
| Smooth varying | 20.9 ms | `21a707f9ed81a2f9` |
| Flat varying | 16.5 ms | `4854f974f5ae3d0d` |

Both returned `GL_NO_ERROR`. This is a short baseline, not Minecraft FPS or a measured improvement. The same installed NVK reports Vulkan 1.4.363, native last-vertex provoking support and the dynamic depth-bias command.

Build and repeat the benchmark after installation, with similar background activity:

```sh
xcrun clang -O2 tools/glbench/glbench.c -framework OpenGL -o /tmp/glbench
/tmp/glbench 500 5
/tmp/glbench 500 5 flat
```

Use several runs and compare the image checksums as well as timings. Also test Minecraft with the same world, location, settings and mods; Terminal erase/backspace; fresh Dock previews; Chromium WebGL; and a known Vulkan workload. Candidate hardware results remain pending until the staged package is installed.
