# Display rotation tools

See [Display rotation](../../docs/DISPLAY-ROTATION.md) for the Tahoe default,
implementation, CPU-copy cost, hardware results and future GPU direction.
These tools contain the shared kernel-to-kernel copy definitions as well as the
controller and checks used to validate the implementation. Internal prototype
marker/property names are retained for compatibility with the tested build.

`build.py --output <new-directory> --package-base <matching-pkgroot>` builds the
framebuffer, timed controller and sanitized binary tests. It does not install,
sign, stage a package or change rotation. Build the matching Tahoe accelerator
with `NM_TAHOE=1 bash build/accel_build.sh kexts/NVRM <new-accel-directory>`.
Preserve release metadata when packaging; the source plist templates use `0.1`.

Run the generated `protocol-test`, `copy-test`, `cursor-map-test`,
`source-probe-test`, `resolution-test` and `physical-plane-test`. The separate
Python checks exercise production methods with host stubs:

- `enablement_test.py`: Tahoe defaults, opt-outs and matching accelerator/GPU guards.
- `normal_path_test.py`: retained production modes, cursor lifetime and GPU helpers.
- `state_test.py`: rotation snapshots and mode/teardown guards.
- `copy_integration_test.py`: GPU/page-off readiness, corrected pixels, stale requests and locking.
- `portrait_contract_test.py`: physical mode metadata and quarter-turn backing flags.
- `source_probe_kernel_test.py`: root-only capture, expiry, cancellation and retained reads.

The comparison tests use the published pre-rotation fork commit `6d71589`;
no unpublished prototype commit is needed. Binary pixel checks cover cases through
8K; this does not establish physical support or performance at those resolutions.

`nv-rotate --list` reads display state. A command such as
`nv-rotate --display <ID> --set 90 --seconds 15` starts an independent restoration
process before requesting rotation and checks that native pixel resolution,
density and refresh are preserved. It requires the matching framebuffer marker.
No controller can restore a machine whose OS has become unresponsive.

`source_probe.py` explicitly arms, saves or discards one root-only bounded source
capture. It never changes orientation. Captures can contain desktop content and
must remain private. They are not required for normal rotation.
