# DVI timing selection

Some DVI-to-HDMI displays are detected and have readable EDIDs but stay black
because their preferred timing fails NVIDIA's modeset validation.

On an RTX 2060 SUPER with an ITY V2422F, NVIDIA's indexed mode query accepted
1920×1080 at 60 Hz, but explicit validation rejected the returned public KAPI
mode as outside the EDID. The EDID's checksums and base detailed timing were
correct. Native indexed diagnostics showed YUV420 metadata on the 60/59.94 Hz
modes; the public KAPI conversion omits that metadata. The same display's
1920×1080 at 75.003 Hz mode had no YUV420 requirement and passed both validators.
This is consistent with metadata loss during conversion, rather than an absent
connector or unreadable EDID.

## Repair

For digital TMDS DVI-D/DVI-I only, explicitly validate the chosen startup timing
before sizing the boot raster and scanout. If it fails, search the enumerated
modes for a progressive timing with exactly the same visible resolution that
passes both indexed and explicit validation. Select the closest refresh rate;
keep an already-valid startup timing. No resolution, refresh rate or monitor name
is hardcoded. If no eligible timing exists or enumeration errors, keep the existing
startup path and its failure handling.

Apply the same explicit check to KAPI-generated DVI refresh modes and the EDID
timing-match shortcut. Otherwise a rejected timing could be offered again or
bypass explicit validation when macOS supplies its detailed timings.

The ordinary modeset retains NVIDIA's configuration, EDID and link-limit checks.
This does not force dual-link mode, synthesize a timing or disable validation.
HDMI, DisplayPort, internal panels and analog DVI-I keep their existing selection.
The repair uses the public function table only; it needs no diagnostic ioctl helper,
private NVIDIA structure offsets, additional RM dependency or RM metadata change.
Presentation, rotation, cursor lifetime and parked-VRAM behavior are unchanged.

## Validation

The user confirmed the ITY now displays an image alongside the HDMI VA2209 on
Tahoe 26.7.1. Boot logs show the fallback selected 1080p75 and both initial modesets
succeeded. That test used `nvfbcontrollers=0`; four-head independent rotation,
other DVI adapters, sleep/wake and other GPUs remain unqualified.

`python3 tools/test_dvi_modes.py` builds the production selector and extracts
the startup, EDID matching and refresh-publication methods for ASan/UBSan checks.
It covers the recorded timing rejection, native-resolution preservation, both
validators, nearest refresh, unchanged valid modes, enumeration errors/bounds,
other resolutions and HDMI/DP/LVDS/analog isolation. Use `--ogkm` or `OGKM` for
NVIDIA headers outside the default `~/ogkm615` directory.

Runtime properties are `NVRMDviModeSelectionVersion=1`,
`NVRMDviModeFallbackApplied` and, when used, `NVRMDviReplacementModeIndex`.
No new boot argument is required. Rebuild NVRMFB for this repair; the existing
matching accelerator and AGDC binaries remain suitable.
