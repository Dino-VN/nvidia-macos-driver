# Retained fork changes for upstream merges

## Merge policy

Keep the fork's Tahoe fixes, existing performance optimizations, OpenGL/Minecraft changes and
MoltenVK optimizations when merging upstream. This policy was confirmed on 2026-10-17.

Before each merge:

1. Fetch the requested upstream revision and inspect its changes since the previous merge.
2. Check for both textual conflicts and changes to the behavior listed below. A clean Git merge
   does not establish compatibility.
3. Check whether upstream has already implemented each fix. Use its implementation when it fully
   covers the retained behavior; keep any remaining fork-specific repair. Avoid applying equivalent
   fixes twice, and inspect overlapping code before resolving a conflict.
4. Build the affected components and check their behavior, resource lifetime and synchronization.
   Record which fork changes upstream now covers, what remains local and the validation limits.

The current upstream base is **2.3.5 at `8b120f3`**, integrated on 2026-10-18. The previous upstream
merge was `7f3c751`, based on 2.3.0 at `5f812c4`. The commit list below records the OpenGL/MoltenVK
additions between those merges; earlier retained fixes remain part of this policy.

## Upstream 2.3.5 integration

- The only textual conflict was `CHANGELOG.md`; both the fork additions and upstream release history are kept.
  The release plugin build also exposed a declaration of `nvtrace` colliding with the retained OpenGL
  call-site macro. Guard that declaration when the macro is already defined; keep the macro's argument-cost saving.
- NVRM and NVRMFB source remain identical to upstream. Keep its display-aware BAR1 budget, scanout lifetime,
  plugin-write cookies, capture ordering, refresh-derived flip waits, hardware-vblank retries and startup changes.
  Do not restore the retired experimental framebuffer policies.
- Upstream still lacks the fork's parked-backing reactivation and unconditional WindowServer submit-and-wait
  completion wait. Keep both. Restore the same parked allocation before upstream's dirty mark records its
  allocation cookie. Kernel-gated capture publication complements the Dock wait; it is not treated as proof
  that every offscreen consumer can safely use scheduling-only completion.
- Keep all ten OpenGL/Minecraft and MoltenVK commits below, strict stencil detection, Chromium's enabled default
  and release `-O2`. The new upstream remote release helper also uses `-O2`; the existing local build script
  retains its settings. Translator and native NVK sources are unchanged by this upstream update.
- Package against the official **2.3.5** RM/framebuffer and installer, with the rebuilt fork plugin and matching
  Tahoe accelerator. Reuse the fork translator built from the unchanged source. The prior 2.3.0 package is not
  the matching base for this merge.

The merged release plugin compiles for x86_64 with macOS 15.0 as its minimum and `-O2`; the Tahoe accelerator
also compiles. No runtime/GPU regression tests or boot of this combined build have been performed yet. Earlier
Minecraft results below, and the reported successful ReBAR-off boot before this integration, do not validate it.

The upstream boot guard is retained as provided. A previously identified source-level ordering concern remains:
NVRM checks the stored failure count, then increments it; later components read the incremented count against
the same limit. This is not a hardware-reproduced failure. A working boot alone does not cover the retry path.

## Earlier Tahoe and performance fixes to retain

- Tahoe icon rendering and System Settings/CoreImage glyph repairs.
- Parked-VRAM backing restoration before ordinary surface dirty updates, including the repair
  introduced by `eb6544b`.
- WindowServer's GPU completion wait for fresh Dock window snapshots.
- Strict detection of the dedicated stencil-export push-constant block.
- Chromium, Edge and Electron acceleration enabled by default, with the existing application opt-out.
- Submission upload-discovery caching, copy-backing deduplication and release plugin `-O2`.
- Upstream framebuffer handling, framebuffer-resource allocation, scanout lifetime and GPU mapping.
  The experimental framebuffer policies and borrowed-scanout extension remain retired.
- Upstream's general Terminal framebuffer-fetch repair and event-driven flip/submission waits.

See [TAHOE.MD](../TAHOE.MD) for their implementation history and build/staging procedure.

## OpenGL/Minecraft and MoltenVK commits to retain

### Newer `perf` follow-up on 2.3.5

The follow-up adapts `8e88b38`, `e13b339` and `153fe3c` from pengubow's `perf` branch at
`153fe3c464aea4c76750720351134b4afb473d5b` into one fork commit. Its build scripts are not imported;
the older OpenGL changes and `0695972` declaration repair are already covered by this fork.

Retain these behaviors when reviewing an equivalent upstream implementation:

- Recognized `NSCGLSurface` waits use the window display's period when image-queue timing would impose a
  slower rate. Keep method/ivar layout checks, valid timestamp/rate bounds, a fallback IMP published before
  replacing the method, serialized installation and the `NVMTL_NO_GL_VBLANK_FIX` opt-out. The correction is
  gated on the NVIDIA backend; it does not alter `CAMetalLayer` or Vulkan swapchain methods.
- Cursor movement is coalesced onto a retained/drained framebuffer thread call. Position-only moves leave the
  cursor image surface alone. Allocate the worker with `THREAD_CALL_PRIORITY_KERNEL` and
  `THREAD_CALL_OPTIONS_ONCE`: one invocation can run and one rerun can be pending, using the latest cursor
  state. A default high-priority call permits overlapping workers to accumulate behind the display gate.
  Stop must use `thread_call_cancel_wait` on this ONCE worker outside display/state locks, release a cancelled
  pending invocation's retain and free only after draining. Recheck stopping after taking the display gate;
  freeing a call alone does not wait for a running callback. Keep the shared display gate and cursor-state lock. This is a
  targeted change from upstream's framebuffer; BAR1 allocation, primary scanout and display modes stay upstream's.
- GL completion queries count committed command buffers, including texture owners and buffer-backed textures.
  Reuse the last sealed part's immutable resource snapshot instead of allocating another list. Unknown fence
  completion keeps the snapshot alive and its resources busy, matching the existing in-flight quarantine.
- Heap-route eligible argument-buffer texture arrays and keep texel buffers on texel-view bindings. Skip
  per-draw plan allocation for heap-routed fields, bound other arrays by the shared texture/sampler slot limits,
  and check field-offset arithmetic. Sampler-token fallback is bounded by persistent sampler slots.
- Stage layouts carry one descriptor per binding: preserve the explicit refusal of larger/runtime/specialized
  non-heap descriptor arrays until layout, writes and binding plans support them together. Recognize texel arrays
  of one. Keep set-2 sampled-image heap arrays and ordinary buffer-internal arrays working.
- Preflight shared address-table pointer uses before physical-buffer lowering. Clone logical pointer types for
  supported chains/copies independently of traversal order; refuse helper/control-flow/store/return escapes rather
  than emitting mismatched pointer types. Keep the existing controlled descriptor fallback/refusal behavior.
- Preserve mip layers for arrays/cubes and halve 3D depth at each mip. Retain AIR-derived reflection and required
  function-constant errors while allowing the existing deferred mesh/object specialization.

All prior Tahoe, parked-VRAM, Dock, stencil, Chromium, `-O2` and OpenGL/MoltenVK cache fixes remain required.
Native NVK, NVRM and NVAccel are unchanged by this follow-up. Rebuild the plugin, translator and **NVRMFB**
for a test package; the stock 2.3.5 framebuffer lacks the asynchronous cursor change. The current staging helper
replaces only the framebuffer plist: the rebuilt framebuffer binary must also be included and checksums refreshed.

The three components compile and booted on the RTX 2060 Super / Tahoe 26.7.1. Eight CPU regression
harnesses pass; OpenGL, sampler-state, normalized MoltenVK and native Vulkan readbacks match their
references. The 30-second gameplay capture added no allocation failures, surface timeouts or refused/dropped
flips. The isolated OpenGL comparison measured the same rounded 2.8 ms/frame median as the parent; it
does not establish a Minecraft FPS improvement. Keep the committed-use regression harness and the submission
fixture's bookkeeping declaration. VSync-on pacing, sleep/wake, mode changes and other GPUs remain unqualified.
Earlier results below apply to their original builds. See [OpenGL performance](OPENGL-PERFORMANCE.md)
for the source commits and validation limits.

Two subsequent whole-machine failures on 2026-10-18 panicked with the high-priority thread-call pool at
500 threads, 499 blocked. The cursor worker's default allocation permits that accumulation, but the panic
reports lack the blocked-thread stacks needed to attribute it conclusively. The serialization repair above
was rebuilt, staged and confirmed loaded on RTX 2060 Super / Tahoe 26.7.1 by its matching UUID and
installed/package executable hashes. Extended runtime validation is ongoing; loading successfully and
the earlier short gameplay capture do not establish stability. Similar upstream freeze reports have not
been matched to this panic signature.

### Earlier imports

These ten commits follow `7f3c751`. Preserve their behavior when resolving upstream conflicts;
the benchmark-only commit provides supporting tools.

| Fork commit | Change |
| --- | --- |
| `ee4152f` | Minecraft OpenGL vertex shader translation. |
| `ff0f8d9` | OpenGL draw path, provoking vertex and texture-buffer views. |
| `34fd3e6` | OpenGL per-draw benchmark and path probe. |
| `16378da` | Remove per-draw allocations and retain the blit pipeline cache. |
| `fdbb5e1` | Reuse texel-buffer descriptor sets. |
| `fc13457` | Apply depth bias. |
| `c49edb2` | Honor per-instance vertex step rates. |
| `976d9ae` | Translate samplers and sampler arrays in mixed argument buffers. |
| `b0ba21d` | Harden resource caching, shader selection and render-state handling. |
| `d51bcd1` | Cache unchanged graphics bindings and sampler specialization keys. |

### OpenGL and translator requirements

- Retain the shader selection/dominance checks and zero-offset integer-vector load repair.
- Keep descriptor reuse sensitive to layout, buffer address, dynamic offset and table-page changes.
- Resource caches must keep the actual retained object alive, including when distinct objects compare equal.
- Reset primitive restart, provoking vertex and depth bias for each render encoder. Preserve the
  capability/profile checks and fallback for native last-vertex provoking behavior.
- Preserve supported instance divisors, texture-buffer format views and mixed argument-buffer samplers.

See [OpenGL performance](OPENGL-PERFORMANCE.md) for the selected source commits and test procedure.

### MoltenVK/NVMTL requirements from `d51bcd1`

- Cache graphics bindings per command recording and reset them for each new recording/event segment.
- Rebind when the pipeline, pipeline layout, descriptor sets, heap, set count or dynamic offsets/count change.
  Compute bindings use their separate bind point.
- Cache up to eight recent sampler-state keys per render encoder. Invalidate the active key when
  vertex/fragment sampler values or LOD clamps change, and preserve each pipeline's own variant lookup.
- Preserve resource retention, surface publication, completion waits and specialization refusal handling.

This commit changes NVMTL's submission path used by MoltenVK. It leaves the native NVK driver,
translator, kexts and framebuffer unchanged.

## Recorded results and limits

Hardware: RTX 2060 Super, 8 GiB BAR1, macOS Tahoe 26.7.1, 75 Hz display.

- Earlier OpenGL checks produced matching smooth/flat readback hashes and `GL_NO_ERROR` after installation.
  Short runs fell from roughly 16–21 ms/frame to 2–3 ms/frame. Background activity and the short baseline
  limit that comparison. A user screenshot showed Minecraft OpenGL at 149 FPS at 854×480; this was not a
  matched before/after gameplay test.
- For `d51bcd1`, five alternating runs per build of a normalized-sampler MoltenVK workload measured a median
  **5.3635 → 4.0128 ms/frame**, or **25.18% lower frame time**. The workload rendered 5,000 textured draws
  per frame into a 16×16 offscreen target for 40 measured frames. Readback matched the CPU reference.
  This result does not establish a Minecraft FPS increase or a native NVK performance improvement.
- Before staging, nine GPU state-transition cases and 23 surface publication/wrapper cases passed.
  OpenGL smooth/flat readbacks also matched between builds.
- After installation, Minecraft and WindowServer loaded the new plugin. A repeat 30-second sample during
  windowed play, with a 35-second counter capture, recorded no additional surface timeouts, allocation
  failures, flip refusals or drops. The surface-timeout counter stayed at nine; those earlier boot events
  remain unattributed. No explicit GPU fault/reset/device-lost messages appeared in the matching log interval.
- In that windowed sample, 3,214 of 5,067 render-thread samples (**63.43%**) were in drawable acquisition.
  The refresh-linked presentation ceiling remains unresolved: the earlier game test reached about 150 FPS
  at 75 Hz and 120 FPS at 60 Hz, and direct Metal reproduced the ceiling. Fullscreen switching is not
  required for the drawable wait. Sample percentages are not FPS measurements.
- An unnormalized-coordinate sampler test still fails through MoltenVK/NVMTL on both the older baseline
  and this candidate. Native NVK passes it. It was excluded from performance claims and remains unfixed.

All seven focused harnesses passed after the exact tested source was transferred into the fork:

```sh
python3 tools/test_render_sampler_cache.py
python3 tools/test_graphics_bindings.py
python3 tools/test_opengl_perf.py
python3 tools/test_surface_publication.py
python3 tools/test_submission_copies.py
python3 tools/test_resset_seal.py
python3 tools/test_resset_lifetime.py
```

The full translator suite still needs unpublished fixtures. These checks and one GPU's runtime results
do not establish behavior on every GPU or rule out regressions after a future merge.

Detailed local artifacts are under `out/vulkan-presentation-20261017-192317/`, including the repeat
capture in `windowed-20261017-202439/`. This document retains the summary if those artifacts are cleaned up.
