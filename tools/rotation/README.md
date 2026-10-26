# Display rotation tools

See [Display rotation](../../docs/DISPLAY-ROTATION.md) for the current native
CoreDisplay path, multiple-display findings, matching builds and hardware limits.

`build.py --output <new-directory> --package-base <matching-pkgroot>` builds
NVRMFB, `nv-rotate`, `transform-test` and `resolution-test`. It does not install,
sign, stage or change a display. Also build the matching Tahoe accelerator and
release plugin to remove the superseded extra rotation pass.

The Python host checks execute production methods with OS/GPU doubles:

- `display_identity_test.py`: duplicated paths, indexed providers and selected-head lookup.
- `enablement_test.py`: Tahoe defaults/opt-outs, normalized probes and matching accelerator.
- `native_modes_test.py`: native/scaled modes, refresh, timing renumber/alias, bounds and independent heads.
- `native_cursor_test.py`: bitmap/hotspot/position, HiDPI, extreme inputs and serialized geometry.
- `native_attributes_test.py`: per-display scale entries, existing overrides and allocation/property failure.
- `native_edid_test.py`: duplicate numeric serials, descriptor bounds and checksum preservation.
- `native_retention_test.py`: retained cursor lifecycle, parking, decoder, OpenGL/MoltenVK and -O2 code.

`nv-rotate --list` is read-only. A timed `--display <ID> --set 90 --seconds 15`
trial changes that display and restores its original transform. Verify the
physical monitor, other displays, extended layout and refresh yourself; a correct
transform property alone does not establish correct output. The old copy/GPU
rotation pipeline, source probe and their tests are retired with their implementation.
