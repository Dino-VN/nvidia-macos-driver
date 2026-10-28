# Display rotation on Tahoe

Standard, 90°, 180° and 270° are available in System Settings → Displays → Rotation
on macOS Tahoe (Darwin 25). Rotation is enabled by default. `nvrmrotation=0` or an
explicit false `NVRMRotationEnabled` property disables it; the boot argument wins.
Other macOS versions keep the existing unrotated mode/scaler path.

## Current implementation

The local candidate adapts the rotation commit
[`0700c208`](https://github.com/nullmoth/nvidia-macos-driver/commit/0700c208dc4e1ea511d406f2e79e3796fcf9eb66)
from upstream PR 398. Its separate cross-process surface-busy/wait commit is excluded.
WindowServer rotates the desktop into the physical raster. The driver's normal
presentation path scans it out; there is no additional rotation compute pass,
CPU frame copy, output pool or framebuffer. The earlier 180° pixel correction
and its accelerator/plugin hooks are removed so the desktop is not rotated twice.

Enabled modes consistently report accelerator backing. During quarter turns,
self-scaled native timings and full 20-byte scale-resolution entries allow
CoreDisplay to generate rotated modes without marking them mirror-only. Native
resolution and refresh come from the display's timings, with no fixed 1080p size.
Up to 224 macOS timings are kept, reserving the remaining table for driver modes
and active aliases. Current timings are matched by raster, desktop size, transform,
pixel clock, totals and sync geometry when macOS renumbers their IDs.

Timing-list replacements now adopt the matching current ID and its descriptor
persistently. Reading the current mode has no side effects; different callers
receive the same answer until a mode or timing-list change. The previous ID stays
usable as an alias when the new table has room and has not reassigned it. If the
active timing is absent, it is retained; a reused ID gets an unused driver ID
starting at `0x20000` instead of shadowing another mode. A full table sacrifices
one extra NVKMS entry to retain the actual active timing, preserving every accepted
macOS entry. These bookkeeping changes do not perform a physical modeset.

The cursor bitmap, hotspot and position map into the same raster. Geometry and
hotspots are published under the cursor-state lock; coordinate arithmetic uses
64-bit intermediates and bounded output. The kernel-priority ONCE cursor worker,
accepted-work counter, exported cancellation and shutdown drain remain unchanged.
First-frame reconnect notification is deferred through the existing connection
worker, outside the presentation gate. Timing descriptions are copied to aligned
storage before reading their 64-bit fields.

A pre-existing or externally replaced `scale-resolutions` override is preserved.
The driver replaces/removes only its own published array. Unsupported reflections,
incomplete rotated desktops, invalid rasters and allocation limits remain refused.
The PR's duplicate numeric-EDID-serial repair applies only on the enabled path;
unique numeric serials and extension blocks remain unchanged.

## Multiple displays and identities

The four-monitor RTX 3070 report demonstrated wrong-monitor rotation and unwanted
mirroring, including 1080×1080 fallback modes. Its mixed-angle trial also entered
mirroring in the later snapshot, so the earlier extended snapshot was insufficient
to establish success. All four registry IDs/indices had the same IOService path.

Each NVRMDisplay provider now has a location from its existing index before the
framebuffer starts, such as `NVRMDisplay@0/NVRMFramebuffer` and
`NVRMDisplay@1/NVRMFramebuffer`. The controller reports the path and resolved
registry ID and refuses a selected path that resolves to another framebuffer.
Modes, transforms, cursor geometry and owned scale lists remain per instance.

The path repair and native mode handling are local candidates. The PR author
reports two working 2560×1440 displays on an RTX 4080 Super; that does not qualify
this adaptation or the four-monitor RTX 3070. Test each head and angle manually,
confirm the selected physical monitor, extended layout, native pixels/refresh,
cursor alignment and restoration, then test mixed angles. Laptop iGPU/dGPU routing
is a separate investigation. Mirroring/scaled desktops, HDR, hotplug, sleep/wake
and long-running behavior remain unqualified.

### Four-monitor controller repair

The next RTX 3070 report has distinct indexed paths and correct transform targeting,
but still enters mirroring. Independent controller tests were incomplete: late
registry edits cannot establish that an already cached controller was recreated,
and NVAccel/NVRMAGDC both used `IOFBDependentIndex` as their driver slot.

The coordinated test separates those roles. `NVRMDisplayIndex` keeps the stable
driver slot 0–3; both consumers prefer it and retain the old dependent-index fallback
for earlier framebuffer builds. Invalid explicit slots are refused without truncation
or fallback. GPU ownership is checked before accepting a slot. The optional Intel
panel still uses its existing slot 4.

With `NVRMIndependentControllers=true` in the test framebuffer personality, secondary
NVIDIA heads receive unique provider-registry IDs as controller IDs before the family
starts. Every NVIDIA head then has controller-local index zero. Head zero retains
its original group, allowing the optional Intel-panel bridge to join it as before.
The rotation rendering, cursor worker, scanout and parking paths are unchanged.

This mode defaults off in ordinary builds. Build with `--independent-controllers`
to enable it in a test package. `nvfbcontrollers=0` restores the existing shared
grouping; the boot argument overrides the property. Rotation-disabled and non-Tahoe
boots keep shared grouping. Install matching **NVRMFB, NVAccel and NVRMAGDC** together.
Production-method host checks cover all four slots, the Intel slot, ownership,
duplicate/invalid slots, legacy fallback and grouping opt-outs. The subsequent
four-monitor capture confirmed this coordinated repair was loaded but still
mirrored all heads. Separate manual Dell 180° and 270° captures reproduced the
failure after successful physical mode commits, during CoreDisplay layout
restoration; the HDMI display became mirror master. The 270° case also collapsed
to 1080×1080 bounds. Controller separation alone is not a confirmed repair.

The consistent-mode-ID change targets the query-dependent answer seen in those
captures. Host tests exercise the actual reporting and timing-table methods,
including successive renumbering, reused IDs, absent active modes, full tables
and four independent heads. Whether it prevents the affected desktop's mirroring
still requires hardware testing, with regression checks on the working
single-monitor and laptop/external configurations. It is not a proven diagnosis
of CoreDisplay's mirror decision.

## Build and validation

Install matching NVRMFB, Tahoe NVAccel and NVMTLDriver from this candidate. Runtime
markers are `NVRMRotationImplementationVersion=14` and
`NVAccelNativeRotationProtocol=1`. Nonzero rotation probes require a matching
accelerator on the same PCI device; restoring Standard remains independent of it.
The release package versions/dependencies stay 2.5.5. The signed translator,
main RM, NVK, codecs and firmware are reused unchanged. Kext signing is not required.

```sh
python3 tools/rotation/build.py --output out/native-rotation-fb --package-base ~/Downloads/pkgroot
NM_TAHOE=1 bash build/accel_build.sh kexts/NVRM out/native-rotation-accel
```

Also build the release plugin with the usual `-O2`, macOS 15 minimum and Intel
architecture. Building does not install or update a package. `transform-test` and
`resolution-test` are emitted by the framebuffer builder. Host checks run production
methods with OS/GPU doubles: `display_identity_test.py`, `enablement_test.py`,
`native_modes_test.py`, `native_cursor_test.py`, `native_attributes_test.py`,
`native_edid_test.py` and `native_retention_test.py`. They cover mode renumbering,
full-raster checks, cursor images/positions and concurrent geometry publication,
override ownership, duplicate EDIDs, head isolation and retained fork code.
These are not physical display or performance tests.

`controller_identity_test.py` additionally runs the actual controller publication,
accelerator notification and AGDC table scan against a four-head host fixture.
The timed controller's `--list` output includes stable driver slots, controller IDs,
local indices, split enablement and `NVRMDisplayIdentityVersion=1` for test captures.

```sh
out/native-rotation-fb/nv-rotate --list
out/native-rotation-fb/nv-rotate --display <display-ID> --set 90 --seconds 15
```

The timed controller preserves pixel density/refresh and starts an independent
restorer before changing the selected transform. Its exact-mode check may restore
a failed trial early. A timer cannot recover a frozen OS, and a successful return
alone does not prove the physical picture or unchanged extended layout. No source
pixel capture or old rotation GPU/CPU diagnostics are needed on this path.

The single-monitor RTX 2060 Super's earlier sharp 75 Hz rotation and GPU handoff
counters apply to the retired implementation. They do not establish correctness
or smoothness for this candidate.
