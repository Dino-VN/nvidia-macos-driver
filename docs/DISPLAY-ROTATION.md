# Display rotation on Tahoe

Standard, 90°, 180° and 270° are available in System Settings → Displays → Rotation
on macOS Tahoe (Darwin 25). Rotation is enabled by default. `nvrmrotation=0`
disables it at the next boot. An explicit false `NVRMRotationEnabled` framebuffer
property also disables it; the boot argument takes precedence. Other macOS
versions retain their existing behavior.

Build and install matching **NVRMFB, Tahoe NVAccel and NVMTLDriver**. The mode/copy
interface is version 10, the per-display GPU protocol is 12, and the framebuffer
implementation marker is `NVRMRotationImplementationVersion=12`. These versions
are checked independently. Older accelerator/framebuffer pairs cannot enable the
renamed rotation interface. Preserve the official package's bundle versions and
dependencies when replacing components.

## Presentation and cursor alignment

IOFramebuffer rotates cursor coordinates and its bitmap independently of the
desktop. The driver normalizes rotation requests to those low-bit cursor rules
and preserves native physical timings, resolution enumeration and pitch. There
is no fixed 1080p mode, filtering or rescaling in the pixel correction.

For 90°/270°, `kDisplayModeAcceleratorBackedFlag` lets the tested Tahoe compositor
produce a complete portrait desktop in a physical-sized BGRA surface. That image
has the opposite direction to the cursor, so the presenter reverses its pixels
by 180° to align them. Logical 180° uses the same exact permutation. Standard
uses the normal presentation path and does not allocate rotation outputs.

WindowServer appends a compute pass to its existing producer queue. It reads the
original shared VRAM and writes a dedicated output, preserving every BGRA/alpha
bit. There is no additional IOFramebuffer, import worker or rendering service.
Surface creation/import happens outside the command-buffer and pool monitors,
before pending GPU marks. Other applications do not run this rotation hook.

A result becomes eligible after its GPU fence and normal surface publication.
The source-ready mark must clear before publication so a page-off holding the
surface lock can progress. The presenter bridges the gap to the completed
rotation result with a metadata wait capped at 1 ms, releasing its metadata
mutex while asleep. The completion path does not acquire the family lock. Only
an exact registered pending job can wait; unknown, stale or cancelled jobs do not.
Command buffers with rotation work also wait for completion when their caller
uses `commitAndWaitUntilSubmitted`.

An accepted GPU output uses the framebuffer's existing allocation-cookie,
duplicated-memory pin and flip-latch checks. Missing or refused results use the
checked CPU copy into that display's owned scanout, including GPU readback when
needed. Busy flips keep the prior image. Mode/epoch/head/owner, geometry, format,
pitch, bounds, layout and non-overlap guards reject invalid work.

## Multiple displays

Rotation jobs are addressed to an explicit display index. Each display has its
own source records, mode, ticket sequence, current/previous output exclusions and
three GPU output buffers. Different native resolutions and rotation angles can
coexist, and a Standard display does not disable another display's rotation.

A shared IOSurface can be registered on multiple displays without selecting the
first match globally. One write invalidates every consumer, while completion and
presentation remain scoped to the ticket's display. Outputs cannot alias another
display's source, reserved buffer or scanout. Replacing a framebuffer invalidates
only its source records and rejects late mode queries/completions from the old
owner. Existing in-flight and scanout lifetime guards remain in force.

The implementation covers independent displays; physical testing with multiple
working monitors is still pending. Shared-source routing tests do not qualify
arbitrary mirroring/scaling combinations. Accepted quarter turns still require
exact full source/destination rectangles and no scaling. HDR and other pixel
formats remain unqualified.

A test boot retained an unplugged DVI display as the unopened first framebuffer.
Rotation requests reached the active second framebuffer but its transform did
not advance. Rebooting with only the active monitor connected cleared that
condition. This shared-controller/hotplug case remains unresolved; per-display
GPU routing does not claim to repair the monitor's DVI no-signal problem. The
upstream connection and display-enumeration behavior is retained.

## Cost and validation

The user confirmed sharp, aligned 180°, 90° and 270° on an RTX 2060 Super with
8 GiB BAR1 and Tahoe 26.7.1. Native landscape/portrait remained 1920×1080 or
1080×1920 at 75 Hz. After the handoff repair, two 15-second trials presented
322 of 324 completed GPU jobs. They also made 1,069 CPU copies. These are
activity-dependent presentation counters, not an FPS/latency benchmark, and
CPU fallback still accounts for substantial work. One source-GPU wait timeout
and one metadata timeout occurred in the 180° trial; the 90° trial had neither.
No geometry, output/backing, flip, IOP failure/blank or flip-latch timeout counters
rose. The final per-display routing changes still need hardware validation.

Actual GPU compute checks passed 18 padded raw-buffer cases through 8K with zero
pixel, source or padding mismatches. Host checks exercise the actual producer,
GPU presenter and framebuffer methods, completion ordering, stale ownership,
source publication, CPU fallback and mode/teardown races. Multi-display checks
cover shared sources, mixed resolutions/angles, reverse-order completions,
independent output pools, Standard plus rotated displays and 5,000 presentations.
These checks do not establish hardware support on other GPUs or at those sizes.
Sleep/wake, hotplug, multiple displays and long-running stability need testing.

GPU outputs add up to three native-sized allocations per rotating display.
Allocation refusal keeps the CPU fallback. Higher resolutions, refresh rates or
more rotated displays increase GPU/CPU memory traffic. CPU copies into active
scanout can tear; a new frame at every refresh is not guaranteed.

Each display has a nonwrapping 24-bit ticket sequence. After 16,777,215 successful
BEGIN requests on that display (about 62 hours at 75 requests/second), it uses
CPU fallback until reboot. Another display does not consume that sequence.
Source/output caches are bounded per display and retained for the boot.

## Build and check

```sh
python3 tools/rotation/build.py --output out/rotation-fb --package-base ~/Downloads/pkgroot
NM_TAHOE=1 bash build/accel_build.sh kexts/NVRM out/rotation-accel-26
```

Build the release plugin with the fork's normal build script too. Use new output
directories and install all matching components through the package workflow;
building does not update installed files or a package. The main RM, native NVK,
translator and codecs do not need changes for rotation.

The controller selects a specific display. Its independent restoration process
starts before changing orientation and preserves pixel resolution, density and
refresh. It checks the applied framebuffer transform because CoreDisplay's angle
can lag behind a direct probe. It never changes another display to perform a
trial. No timer can restore a machine whose OS is unresponsive.

```sh
out/rotation-fb/nv-rotate --list
out/rotation-fb/nv-rotate --display <display-ID> --set 90 --seconds 15
```

`sudo sysctl debug.nvaccel_rotation_gpu_on=0` returns GPU rotation to CPU fallback.
`NVMTL_ROTATION_GPU=0` disables the producer hook for that process. Setting
`debug.nvaccel_rotation_gpu_wait_us=0` disables the short handoff wait for an A/B
check; other values are clamped to 0–1000 µs.

Read-only `debug.nvaccel_rotation_gpu_*` counters distinguish completed jobs,
GPU flips, metadata waits/timeouts and missing/stale/refused results. Per-display
`_gpu_flips_h0` through `_h4` and `_copy_frames_h0` through `_h4` distinguish GPU
and CPU presentations by display index. The optional root-only source probe
captures one bounded frame for up to 20 seconds without changing orientation.
It can capture desktop content; keep captures private. It is unnecessary for
normal rotation and never relaxes presentation guards.
