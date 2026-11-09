# Browser video decoding

## Edge VP9 output buffers

Edge's GPU process crashed during VP9 playback, then disabled hardware rendering
for the rest of that browser session. The ANGLE Metal workaround was still
present: a fresh browser initialized ANGLE normally before playing the video.

The codec's private output pool copied the client's destination dictionary.
Chromium requested only `PixelFormatType`, so this pool produced heap-backed
CVPixelBuffers without IOSurfaces. Native tests had previously requested
IOSurface backing explicitly and therefore missed this browser contract.

The pool now retains the negotiated output attributes, including IOSurface
backing and Metal compatibility, while preserving client options and the
existing pool/conversion policy. ANGLE, sandbox settings, kernel code, Zink and
the other GPU codec selections are unchanged.

Validation on RTX 2060 SUPER / Tahoe 26.7.1:

- The original library fails the new minimal-attributes test with missing
  IOSurfaces. The corrected library passes all 48 sync/async VP8/VP9 sessions
  (360 frames), through 4K and VP9 10-bit, with exact libvpx-reference pixels.
- Edge **156.0.4314.58** played the supplied [YouTube VP9 test](https://www.youtube.com/watch?v=VhZtweWFtVI)
  at **3840×2160 / 60 fps** for 35 seconds, including looping. Media diagnostics
  selected `VideoToolboxVideoDecoder` with platform decoding enabled; ANGLE
  Metal, compositing, WebGL and WebGPU remained enabled, with zero GPU crashes.
- The player controls were deliberately revealed during the interactive run.
  Raw dropped-frame counts are recorded; this is not an isolated FPS benchmark.
- The original H.264/HEVC hardware encoders still pass their eight-frame smoke
  tests. Ada/Ampere/TU117 registration policy and codec packaging checks pass.

Run `tools/video/vt_codec_probe.m` with `--minimal-output` to reproduce the
browser-style destination dictionary. The probe checks IOSurface backing on
every returned frame. [Evidence and hashes](BROWSER-VIDEO-DECODING.json).

After updating, fully quit and reopen a browser that already fell back to
software rendering. Reloading the video alone does not reset that session's
failed GPU state. Other browser versions, codecs and applications need their
own playback qualification.

## Firefox and Zen H.264 capability reporting

On **2026-11-09**, the installed `v2.8-nvk` driver on **RTX 2060 / macOS
26.7.2 (25G332)** reproduced `H264 SWDEC` in fresh profiles of **Firefox
159.0.1** and **Zen 1.24.1b**. This table entry is not proof of software playback:
RDD logs report actual hardware use for successfully created H.264 sessions.
A headed Firefox test advanced video-only H.264 playback for about 2.5 seconds,
rendered nonblank pixels, and retained an accelerated WebRender window. Zen's
corresponding playback test was headless. These are short smoke tests, not
smoothness benchmarks or qualification of all browser rendering.

The first `VTIsHardwareDecodeSupported('avc1')` call captures the decoder
registry before its GPU filter loads NVMTLDriver. The driver is present after
that call, and a later H.264 query succeeds. Gecko caches the first result.
RDD decoder registration is already synchronous after driver configuration;
repeating that change does not repair a snapshot taken before plugin loading.
There is **no validated driver-only first-query repair** in these results.
Keep the stock browser sandbox and the existing codec bridge/descriptor repairs.

Use the cold probe in a fresh process, without Metal enumeration, driver
preloading or decoder registration before its first query:

```sh
mkdir -p out/vt-capability
xcrun clang -arch x86_64 -mmacosx-version-min=15.5 -fobjc-arc \
  -O2 -Wall -Wextra -Werror tools/video/vt_cold_capability_probe.m \
  -framework Foundation -framework CoreMedia -framework VideoToolbox \
  -o out/vt-capability/cold
out/vt-capability/cold --require-first-h264
```

Exit `1` means the first H.264 query was false, even if later queries succeed;
exit `2` indicates invalid arguments, a failed report, or an already-loaded
driver that invalidates the cold experiment. Without `--require-first-h264`,
a false hardware capability is reported normally rather than treated as failure.
The JSON explicitly marks playback and browser-sandbox testing as **not tested**.

For comparison only, build and run a **separate** process that enumerates Metal
before querying VideoToolbox:

```sh
xcrun clang -arch x86_64 -mmacosx-version-min=15.5 -fobjc-arc \
  -O2 -Wall -Wextra -Werror -DVT_CAPABILITY_PREWARM=1 \
  tools/video/vt_cold_capability_probe.m \
  -framework Foundation -framework CoreMedia -framework VideoToolbox \
  -framework Metal -o out/vt-capability/prewarmed-control
out/vt-capability/prewarmed-control --require-first-h264
python3 tools/test_cold_video_capability_probe.py
```

On the tested driver, the cold first query was false and the separate prewarmed
control's first query was true. Prewarming is a diagnostic control, **not a
browser workaround or evidence of automatic decoder discovery**. The unit tests
use process-local fake VT functions solely to check probe ordering and exit
semantics; they do not validate hardware or intercept the installed driver.

Firefox's Apple decoder eligibility separately excludes VP8, and RTX 20/Turing
has no AV1 hardware decoder. Preserve those negative hardware capabilities.
The available WebGL clear/readback tests passed, but no specific user-reported
OpenGL rendering failure was reproduced by this investigation.
