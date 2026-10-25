# Display rotation on Tahoe

The fork supports Standard, 90°, 180° and 270° in System Settings → Displays →
Rotation on macOS Tahoe. The option is enabled by default on Darwin 25 with the
matching Tahoe NVAccel. `nvrmrotation=0` disables it at the next boot. An explicit
false `NVRMRotationPrototype` framebuffer property also disables it; the boot
argument takes precedence. Other macOS versions keep the existing behavior.

Rebuild **both NVRMFB and Tahoe NVAccel** when packaging this change. A framebuffer
alone cannot rotate the desktop: the accelerator must advertise copy protocol 9
on the same GPU. The framebuffer reports implementation version 10. Those are
different version numbers by design. The `NVRMRotationPrototype*` registry names
are retained for compatibility with the tested implementation and controller.
Preserve the official package's bundle versions and dependencies when replacing
the two binaries. Rebuilding the source does not update installed files or a
package automatically.

## How it works

IOFramebuffer rotates cursor coordinates and the cursor bitmap independently of
the desktop. The driver normalizes the requested transform to those low-bit
cursor rules and leaves native physical timings, pitch and resolution enumeration
intact. There is no hardcoded 1080p mode.

For 90°/270°, the mode information also publishes
`kDisplayModeAcceleratorBackedFlag`. On the tested Tahoe compositor, this yields a
complete portrait desktop already laid out in a physical-sized BGRA surface.
Its direction is opposite to the cursor's, so the framebuffer applies an exact
180° pixel permutation to align them. For 180°, it applies that permutation to
the unrotated logical source. Standard retains the normal zero-copy presentation
path. No filtering or rescaling is performed by the copy.

The existing presentation thread waits for the source's GPU work, pages it off
when needed, then maps it for a CPU copy into the existing owned scanout. There
is no additional framebuffer, surface-import worker or userspace rendering
service. The display gate protects destination lifetime; epoch, mode sequence,
head, format, layout, dimensions, pitch, allocation bounds and non-overlap checks
reject stale or invalid copies. Quarter turns additionally require exact full
source/destination rectangles and no scaling. The read-only transaction layout
used for those checks is restricted to the Tahoe accelerator build.

## Costs and validation

Rotation still uses a **synchronous CPU copy**, including GPU-to-CPU synchronization
and readback when needed. Apps remain GPU accelerated. Higher resolutions,
refresh rates or multiple rotated displays increase bandwidth and CPU cost.
Copying into active scanout can tear; this implementation does not guarantee a
new frame at every refresh. BGRA is the supported copy format; HDR/other formats
and scaled transaction planes are not qualified.

The user confirmed 90°/270° output and cursor alignment on an RTX 2060 Super with
8 GiB BAR1, a 1920×1080 75 Hz display and Tahoe 26.7.1. The preceding 180° path
also worked on that setup. A whole-boot snapshot recorded 2,143 copied frames
and approximately 1.45 ms per successful frame in the copy-call timer, with a
12 ms maximum. That timer excludes GPU waits, page-off and CPU mapping; it is
not an end-to-end frame benchmark or a guarantee for another setup.

Host checks cover exact pixels and cursor-coordinate composition through 8K,
plane validation, source/destination bounds, GPU/page-off refusal, stale requests
and concurrent teardown. They do not establish hardware support at those sizes.
Other GPUs, BAR1 sizes, multiple displays, HDR, sleep/wake and hotplug still need
hardware testing.

## Timed checks and diagnostics

`tools/rotation/build.py` builds NVRMFB and a controller without installing,
signing or changing the display. For example:

```sh
python3 tools/rotation/build.py --output out/rotation-fb --package-base ~/Downloads/pkgroot
NM_TAHOE=1 bash build/accel_build.sh kexts/NVRM out/rotation-accel-26
```

Build into new output directories. Install the matching pair and refresh the
Auxiliary Kernel Collection through the normal package workflow. After reboot,
the controller can identify the display and perform a timed trial:

```sh
out/rotation-fb/nv-rotate --list
out/rotation-fb/nv-rotate --display <display-ID> --set 90 --seconds 15
```

The controller starts an independent restoration process before changing the
transform, preserves pixel resolution/density/refresh and rejects fallback
modes. The timer cannot restore a machine whose OS is unresponsive.

Read-only `debug.nvaccel_rotation_*` counters track accepted copies, skips,
geometry refusals and copy-call time. The optional source probe is root-only,
must be explicitly armed, and accepts one frame for up to 20 seconds. It never
changes rotation or displays its capture. `tools/rotation/source_probe.py`
supports arm/save/discard; saving also discards the kernel capture. The image
can contain desktop content, so keep diagnostic files private.

## GPU follow-up

A future GPU implementation should produce the corrected image inside the
existing compositor submission, then present a GPU-resident completed surface.
It must preserve source ownership, fence/completion ordering and mode-change
lifetime without waiting for an importing worker under display-family locks.
The earlier independent GPU importer deadlocked during a display transition;
do not reintroduce it. This remains a design direction, not an implemented
replacement for the working CPU path.
