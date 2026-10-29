# Native Zink OpenGL: PR #2 integration review

Reviewed against fork main `4a089a518187f4f8e3a18659ca324e080a9f419b`
and PR head `4872b8ce00ec9a46d55c30875c8dc0696c2ba840`.
[Original PR](https://github.com/HighDelay/nvidia-macos-driver-nvk/pull/2),
contributed by [Dino-VN](https://github.com/Dino-VN).

The intended behavior is **automatic native Zink/NVK rendering for OpenGL
applications and OpenGL Minecraft** after installing the Zink driver package.
No application attachment code, companion mod, `VK_DRIVER_FILES` override or
launch argument is required. The GLD proxy connects ordinary CGL contexts
before application GL objects are created. Internal Apple drawable-copy contexts
remain in their original driver; they do not execute the game's shaders.

## Changes made during review

- Resolve the README and package-builder conflicts by retaining the fork's
  current README and complete builder, then adding Zink separately. Keep both
  accelerator variants, firmware/version identity, Minecraft and Wine runtimes,
  all-app ANGLE Metal policy, Tahoe/rotation/cursor repairs and existing caches.
- Rename the renderer, CGL adapter, AppKit helper, public functions and generated
  wrappers to NVK/Zink names. The original contributor's MIT attribution remains.
- Load a private frontend and the exact verified native NVK renderer. Remove
  the GLD constructor's process-global Vulkan ICD environment override.
- Prefer GPU copies into the actual native drawable's VRAM, using the existing
  Minecraft handoff protocol: same-device import, completion fence, dirty
  notification, generation-tag publication, then drawable presentation.
  Keep scratch allocation per context and view/layer bindings per context.
  Match the real NVIDIA device rather than the system-default Metal GPU.
- Preserve GPU IOSurface/Apple presentation for CGL clients without an AppKit
  target and as an explicit comparison mode. CPU pixel transfer is an explicit
  diagnostic, never an automatic fallback. Apple OpenGL is not used to execute
  application shaders in any Zink presentation mode.
- Fix framebuffer invalidation after swap/resize. The cached make-current path
  otherwise allowed a clear to reach an obsolete attachment. Preserve the app's
  viewport and FBO/read/pixel-store state during resize and presentation.
- Replace opaque alpha initialization plus RGB-only copying with one RGBX
  sampler-view conversion blit. This supplies alpha 1 on the GPU and avoids
  reordering the scratch clear after its color copy.
- Repair a lost-wakeup race in Zink's unflushed-batch condition variable. Protect
  predicate updates/signals with the same mutex and recheck under that mutex.
  Retain the render worker and asynchronous submission rather than hiding the
  race with globally disabled threading.
- Repair Mesa's Darwin barrier fallback: it previously returned the serial
  result to every waiter, allowing repeated destruction of a queue-completion
  barrier. Return it once, after the other waiters stopped accessing the barrier.
- Cache one private Zink screen/device for the process. GL share groups remain
  separate unless CGL requests sharing. Context teardown drains GPU work and
  frees context resources; the private device/compiler cache survives until
  process cleanup. This also avoids the original renderer binary's unsafe
  Darwin disk-cache teardown barrier. Minecraft/Wine binaries are unchanged.
- Bound presentation completion waits; quarantine resources and stop the affected
  share group after uncertain GPU completion. Pin native drawables, surfaces,
  images and device state while queued work might still access them.
- Validate the exact Mesa source, native overlay and built-component hashes.
  Keep all Zink files in `nvmtl/zink`, preserve framework symlinks, exclude Finder
  metadata, retain version data and package with top-level `pkgroot/`.
- Use the normal `/Library/GPUBundles` GLD lookup path. Remove the obsolete
  writable-System-volume staging helper. Reject another OS build and retain
  installer rollback, trusted-lookup checking and the existing boot fallback.
- Preserve approved external kexts such as MacPorts macFUSE when rebuilding the
  auxiliary collection, using permanent source paths for preflight and live
  builds. Reject an unsafe/missing source before modifying installed files.

## Validation

The integration is tested on **RTX 2060 SUPER, Intel macOS 26.7.1 / 25G241**.
Builds use pinned Mesa `17ca6174dcc6cb22059ac343bc29f8af7800f42e`, a clean source
archive and the verified renderer from the fork's 2.6.4 package.

Final checks passed on 2026-10-30:

- 19 bounded GPU/CGL cases, including automatic core 3.2/4.1 and legacy selection,
  source-ICD isolation, two native windows, sharing, worker rendering, alpha,
  resize and rejected/uncertain publication. The native cases verify 107 frames.
- Another 12 automatic native runs verify 144 changing-color frames with normal
  command reordering enabled. No black/stale frames or timeouts occurred.
- 1,000 four-thread barrier generations and 100 queue-drain cycles. The same
  serial-return regression fails against the unmodified pinned Mesa barrier.
- 60 packaging/installer unit cases and four installer regression scripts.
  Packaged `Verify.command` also passes against the relocated runtime.
- Isolated Tahoe kernel linking through the real installer's `CHECK=1` path,
  retaining macFUSE from its permanent source. All 26 recorded installed files,
  including the active auxiliary collection, are unchanged after the check.

The local package records source/build hashes and exact test output. These
checks are not a physical installation or full-game qualification.

The tests cover core/legacy framework dispatch, GLSL and fixed-function drawing,
PBO/glyph/cubemap uploads, texture-buffer and uniform-buffer use, GL object
sharing, separate contexts, thread migration, native swaps and resize. Native
drawable tests verify **every copied pixel**, changing colors between frames,
including orientation, alpha, main/worker rendering and failed/uncertain handoff.
A separate diagnostic copy performs readback; gameplay does not run that observer.
A synchronization probe exercises the real Mesa barrier and queue implementation.

GLD lifecycle tests use a process-local lookup/executable shim, including
ordinary application context creation without `nvk_cgl_attach`. They do not
qualify macOS trusted-bundle registration, a reboot, sandboxed clients or actual
Minecraft gameplay. The original PR's RLCraft/185-mod observations and upload
microbenchmark are author-reported and were not reproduced in this review.
No FPS gain is claimed. Stereo/MSAA/float/pbuffer/fullscreen behavior, other
OS builds/GPUs and multiple identical NVIDIA cards remain unqualified.

Local builds and pushing this integration are authorized. **No release is
published or drafted as part of this work.**
