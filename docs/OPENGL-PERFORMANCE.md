# OpenGL performance changes

For future upstream merges, retain these changes and the later MoltenVK/NVMTL optimization as
described in [Fork merge notes](FORK-MERGE-NOTES.md). Check for equivalent upstream implementations
and overlapping changes before resolving conflicts.

## Newer `perf` changes on 2.3.5

The follow-up selects these additions from [pengubow's `perf` branch](https://github.com/pengubow/nvidia-macos-driver/commits/153fe3c464aea4c76750720351134b4afb473d5b/). Its earlier OpenGL work is already present.

| Source commit | Selected behavior |
| --- | --- |
| [8e88b38](https://github.com/pengubow/nvidia-macos-driver/commit/8e88b38dda889ceba33e7e6fe6f192386a09b4e9) | Coalesce cursor moves outside WindowServer's cursor call, update the cursor surface only when needed, and correct GL VSync timing from the window display's refresh period. |
| [e13b339](https://github.com/pengubow/nvidia-macos-driver/commit/e13b33933606ad909bc59bf6ea59b3cd34aa4053) | Route eligible argument-buffer texture arrays through the heap while retaining texel-buffer bindings. |
| [153fe3c](https://github.com/pengubow/nvidia-macos-driver/commit/153fe3c464aea4c76750720351134b4afb473d5b) | Track committed resource uses, preserve sampler tokens, handle embedded texture/texel-buffer fields, fix 3D/array mipmaps and improve reflection/function-constant handling. |

The fork adds checks for the private GL method signature and ivar sizes, serializes installation and publishes
its fallback before the replacement can run. Invalid, stale or overflowing timing data uses AppKit's original
wait. A spanning window follows its centre display; display lookup is cached for one second. The correction
has no fixed 75 Hz target and can be disabled with `NVMTL_NO_GL_VBLANK_FIX=1` in an application's environment.
It changes GL's AppKit wait, not Metal drawable acquisition or MoltenVK's presentation ceiling.

Committed resource tracking reuses the sealed resource snapshot instead of creating another list per command
buffer. A fence whose completion is uncertain keeps its resources busy and retained. Array plans are bounded
by the backend's actual slot counts, while heap-routed fields allocate no per-draw plans. Mesh/object functions
keep their existing deferred constant specialization. Cursor completion state is synchronized with queued moves.

The plugin, translator and framebuffer compile for x86_64 with a macOS 15.0 minimum; release plugin code
uses `-O2`. Retained fixes and future merge rules are in [Fork merge notes](FORK-MERGE-NOTES.md).

### Audit repairs

The follow-up audit found three edge cases shared with the source branch:

- Address-table pointers must stay in `StorageBuffer` while ordinary buffer pointers become physical.
  Track supported pointer chains/copies before changing any types. If a table pointer reaches a helper,
  phi, select, pointer-valued store or return, refuse lowering so the caller can use its descriptor fallback
  or report an unsupported pipeline. The Uniform-table path can also refuse that fallback. This prevents
  mismatched function arguments; it does not add helper-pointer support.
- Stage descriptor bindings contain one descriptor each. Non-heap arrays larger than one, runtime arrays
  and arrays with specialized lengths are refused before shader-module creation. A constant array of one
  fits the layout, and its texel-buffer element now selects a buffer view correctly. Working sampled-image
  heap arrays in set 2 remain supported; arrays inside ordinary buffer blocks are unaffected. Supporting
  larger non-heap arrays requires matching layout, descriptor-write and binding-plan changes.
- Keep the cursor worker at normal kernel priority with `THREAD_CALL_OPTIONS_ONCE`. During stop, use
  exported `thread_call_cancel`, then wait for the outstanding cursor-work count without holding display/state
  locks. Count before enqueue, undo duplicate enqueues, and retire each count on cancellation or callback exit;
  this also covers callbacks dispatched but not yet entered. Free the call after draining. The initially used
  `thread_call_cancel_wait` is not exported to kexts and failed kernel-collection linking. A cursor update also
  rechecks stopping after acquiring the display gate.

`tools/test_opengl_audit_repairs.py` checks the production descriptor parser with address/undefined-behavior
sanitizers, the real address-lowering code, and a concurrent model of the cursor stop block. With
`--validator /path/to/spirv-val`, it also validates the helper input and safe lowered shaders for Vulkan 1.2.
The model covers queued, dispatched and running retain accounting; it cannot establish kernel shutdown safety on hardware.
These repairs require rebuilding the plugin, translator and framebuffer. Earlier hardware results below
describe the previous build, not runtime validation of these repairs.

### Follow-up checks on RTX 2060 Super / Tahoe 26.7.1

- Installed hashes match the staged builds, and loaded kext UUIDs match. Minecraft and WindowServer load
  the new plugin and translator. Minecraft reports OpenGL 4.1 over NVMTL/NVK, with VSync off.
- A 30-second gameplay capture recorded no additional allocation failures, surface timeouts, flip refusals
  or dropped flips. Parking/reuse counters were active since boot (nine parks and three reuses); none changed
  during this capture, so it does not isolate the parked-backing repair's execution or speedup.
- The asynchronous framebuffer cursor path logged successful updates. A separate process confirmed the
  private AppKit layout is recognized and the replacement `synchronize` method is installed. Minecraft's
  VSync-off sample did not enter that wait, so this is not a VSync-on pacing measurement.
- Five alternating runs per build of the 500-draw, 80-frame offscreen OpenGL workload measured the same
  rounded median, **2.8 ms/frame**, for the parent and this candidate. Every image matched the reference and
  GL returned no error. This workload does not establish a Minecraft FPS gain.
- Smooth/flat OpenGL readbacks, all nine sampler-state cases, and normalized-sampler MoltenVK and native
  Vulkan readbacks match their references; both Vulkan paths report zero wrong bytes. These short checks
  establish correctness for those workloads, not unchanged performance for every Vulkan application.
- Eight CPU regression harnesses pass, including committed resource accounting, alias/backing-buffer
  lifetime and uncertain-fence quarantine. The submission fixture now declares the new bookkeeping field.
- The user initially reported 90–120 FPS versus 150–200 previously. A later fullscreen screenshot showed
  202 FPS with a 209 average. Profiling/test workloads can affect live FPS, and the initial WindowServer
  sample also showed shader compilation. These observations do not identify the cause of the earlier dip.

Mode changes, sleep/wake, multiple displays, VSync-on pacing and the broader metadata/texture edge cases
still need hardware/application coverage. These results apply to this RTX 2060 Super, not every GPU.

## Original 2.3.0 experiment

The original experiment selected the OpenGL changes from [pengubow's `opengl-perf` branch](https://github.com/pengubow/nvidia-macos-driver/commits/1706681662e1f8b0278b985ed3e742bf0d64d418/), based on upstream 2.1.0, and applied them to this fork's 2.3.0 base. Those initial imports did not merge upstream 2.3.1.

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

Use several runs and compare the image checksums as well as timings. Also test Minecraft with the same world, location, settings and mods; Terminal erase/backspace; fresh Dock previews; Chromium WebGL; and a known Vulkan workload.

The candidate was subsequently installed on RTX 2060 Super / Tahoe 26.7.1. Repeated offscreen checks
produced 2–3 ms/frame with matching smooth/flat checksums and `GL_NO_ERROR`. The short original
baseline and background activity limit the comparison. A user screenshot showed Minecraft OpenGL
at 149 FPS at 854×480; no matched before/after gameplay comparison was made. The later shared
NVMTL cache optimization and its separate MoltenVK results are recorded in the merge notes.
