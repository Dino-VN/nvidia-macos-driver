# Display rotation tools

See [Display rotation](../../docs/DISPLAY-ROTATION.md) for configuration, per-display
GPU presentation, CPU fallback, hardware results and validation limits.

`build.py --output <new-directory> --package-base <matching-pkgroot>` builds NVRMFB,
the timed per-display controller and sanitized geometry/pixel checks. It does not
install, sign, stage or change rotation. Also build the matching Tahoe accelerator
and release plugin. Preserve official release versions/dependencies in packaging.

Run the generated `protocol-test`, `copy-test`, `cursor-map-test`,
`source-probe-test`, `resolution-test` and `physical-plane-test` binaries.
Host checks execute production methods with OS/GPU doubles:

- `enablement_test.py`, `state_test.py`, `portrait_contract_test.py`: defaults,
  opt-outs, normalized transforms, native mode metadata and mode/teardown guards.
- `copy_integration_test.py`, `gpu_framebuffer_test.py`: actual GPU/CPU presenter
  guards, exact pixels, per-display destinations and concurrent mode changes.
- `gpu_kernel_test.py`: actual metadata/presenter, head/owner/cookie checks and
  bounded handoff. Its negative control must fail when the wait is removed.
- `gpu_producer_test.py`: actual producer, imports outside completion monitors,
  resource retention, two independent output pools for a shared source, and a
  Standard display alongside another rotating display.
- `gpu_state_test.cpp`, `multidisplay_test.cpp`: source/ticket/output ownership,
  mixed resolutions/angles, reverse completions, reconnect and nonce exhaustion.
- `normal_path_test.py`, `gpu_retention_test.py`: unchanged normal rendering,
  cursor, OpenGL/Minecraft, shader and MoltenVK behavior outside rotation hooks.
- `source_probe_kernel_test.py`: bounded root-only capture and reader lifetime.

The raw-buffer `gpu_inline_probe.c` checks the actual compute helper on a GPU
without rotating a display or instantiating a compositor device. These tests and
pixel cases through 8K do not qualify multi-monitor hardware or performance.

`nv-rotate --list` reads display state. Select one display with
`nv-rotate --display <ID> --set 90 --seconds 15`; it starts an independent restore
before changing the transform and requires matching rotation-capable components.
`source_probe.py` explicitly arms, saves or discards one private diagnostic frame.
