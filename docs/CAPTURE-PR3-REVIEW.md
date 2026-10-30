# IOSurface capture copy and import reuse

Review of [PR #3](https://github.com/HighDelay/nvidia-macos-driver-nvk/pull/3),
head `f854c6886c2ac23e63c56da59e9bd6e05b2dd0c3`, against fork `bdce1a8`.
The PR contains three commits based on `050f191`; the only textual merge
conflict was the changelog. Preserve the newer Zink and upstream 2.6.4 work.

## Retained and strengthened

Released IOSurface wrappers can hand their completed family-VRAM or imported
host-page buffers to the next wrapper of the same surface/plane. The cache
retains the IOSurface, preventing object/ID reuse while an entry exists. A new
wrapper still creates its own correctly typed image; host-page mappings are
checked against their current address and size before use. Existing command
buffer resource retention and uncertain-work handling are unchanged.

The idle cache has a combined **128 MiB** byte budget and 64-entry limit.
Oversized imports are released immediately; pressure evicts the oldest parked
entry. Entries cannot be taken after 250 ms idle or two seconds total age,
even if the asynchronous sweeper has not run. GPU import/free operations run
outside the cache mutex. Initialization and new hit counters are synchronized.
Family reuse depends on the fork's stable parked-VRAM backing; a future change
that replaces that backing must invalidate imports or identify its generation.

`NVMTL_VRAM_KEEP=0` disables cross-wrapper reuse. `NVMTL_VRAM_KEEP_MB` sets the
idle byte budget (0 disables it; valid range 0–4096 MiB). The existing
`NVMTL_HOST_PAGES_MB` limit independently bounds pinned host pages, including
those currently owned by live textures. These controls do not change the GPU's
advertised VRAM or the lifetime of resources still in flight.

420v/420f NV12 planes commonly start 64 bytes inside an import page. Import the
page containing the plane and carry the texel-aligned offset into the GPU copy.
Use one span calculation for uploads and readbacks so their cache entries agree.
Check pitch, image extent, offset, integer overflow and the allocation end before
importing; never round an import above that end or below the owned mapping.
Unsupported/partial-page spans retain the existing CPU fallback. The helper
handles supported texel sizes and arbitrary image dimensions, including P010;
there is no 1080p-only path.

## Pending-tag proposal excluded

Do not change `NVMTLVramAt:pN` from three words to four with the same magic.
Native Minecraft/Wine and Zink also publish the three-word seed/generation tag;
a length change would prevent the readers from recognizing each other's
completed writes. The PR's pending bit and four-millisecond per-reader polling
also introduce another cross-process ordering protocol, outside the retained
kernel marks, overlapping-writer counts and deferred-publication rules.

Keep the existing tag, WindowServer conditional completion policy and kernel
page-off synchronization. This merge neither adds a polling delay nor claims
to remove the page-off wait identified in the PR. A future event-based capture
handoff needs explicit ownership, overlapping writes, error recovery and mixed
runtime-version tests rather than a shared boolean.

## OBS applicability

The changes apply to shared driver operations, without a Discord process-name
check. WindowServer can reuse BGRA surface imports for OBS capture too. A Metal
client that consumes or produces compatible video planes can use the repaired
GPU upload/readback path.

OBS uses several different paths. At inspected OBS source
`65c320b46e1af5c7a555161aea6182cdf7a8c524`, its
[ScreenCaptureKit callback](https://github.com/obsproject/obs-studio/blob/65c320b46e1af5c7a555161aea6182cdf7a8c524/plugins/mac-capture/mac-sck-common.m)
locks the CVPixelBuffer before retrieving its IOSurface. Its
[screen source](https://github.com/obsproject/obs-studio/blob/65c320b46e1af5c7a555161aea6182cdf7a8c524/plugins/mac-capture/mac-sck-video-capture.m)
selects BGRA for ordinary SDR capture, and its
[macOS OpenGL backend](https://github.com/obsproject/obs-studio/blob/65c320b46e1af5c7a555161aea6182cdf7a8c524/libobs-opengl/gl-cocoa.m)
imports/rebinds those surfaces through `CGLTexImageIOSurface2D`.
Consequently, NV12 improvements are not proof of an OBS screen-source speedup,
and a later Metal-texture reader cannot eliminate that earlier CVPixelBuffer lock.

This changes no encoder, codec registration, VideoToolbox service or OBS
backend. It does not add NVENC support to a client that cannot already use the
driver's encoder. OBS's OpenGL/IOSurface behavior with the optional native Zink
GLD also needs separate application testing; the Metal tests below do not
qualify that interoperability. Do not force a different OBS renderer or encoder
as part of installing these capture changes.

## Validation and limits

RTX 2060 SUPER, 8 GiB BAR1, x86_64 Tahoe 26.7.1 / 25G241:

- Eleven host suites pass, including production cache code under ASan/UBSan,
  10,000 concurrent cache transfers, host-page accounting, allocation boundaries,
  14,336 span/offset checks, publication overlap, pending-writer lifetime,
  submission resource retention and the all-app ANGLE policy.
- Local release and diagnostic plugins compile at `-O2`, minimum macOS 15.0,
  and pass signature checks. Their 333 compiler warnings match an independently
  compiled pre-merge baseline; no new warning diagnostic was introduced.
- `bench_capture_surfaces` verifies active pixels in both directions for BGRA,
  420v, 420f and P010 at 1920×1080, 2560×1440, 3840×2160 and padded 1000×750.
  Rewrapping after writer destruction preserves the completed GPU pixels without
  a CPU overwrite. Planar row-padding guards remain intact. Default, reuse-disabled, explicit CPU
  fallback and private-BGRA runs pass; the pre-merge baseline is a control.
  The release binary passes the same 16 format/size combinations.
- The NV12 compute-wrapper probe passes all 12 combinations of four dimensions
  and one command buffer, two command buffers, or two command queues.
- All 22 `bench_surface_order` runs pass: 100 frames each with family sharing
  and private fallback, covering same/different command buffers, aliases,
  partial updates, CPU overwrite, abandoned work and cross-queue events.

The local wrapper-only timing exercise did not establish a consistent CPU-time
gain. The PR author's Discord timings describe their test, not a measurement
of this merged build. No FPS, recording-throughput or encoding gain is claimed.
No full live Discord share, OBS recording, new WindowServer session, Sequoia
boot, low-BAR1 or other-GPU test has been performed with this build. The plugin
was loaded into isolated test processes; the installed driver was not replaced.
No kernel, translator, native-runtime or Zink implementation changes are needed.

Local logs and producing inputs: `out/pr3-capture-20261030/`. No release was
prepared or published; the driver's existing release hold remains in effect.
