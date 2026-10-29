#!/bin/bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
cd "$HERE"
/usr/bin/shasum -a 256 --strict -c SHA256SUMS --quiet
/bin/bash "$HERE/nullmoth-runtime-check.sh" "$HERE" "$(sw_vers -productVersion)"
RUNTIME="$HERE/Library/GPUBundles/nvmtl"
"$RUNTIME/zink_probe" "$RUNTIME/libdino_zink.dylib" "$RUNTIME/nvk_icd.json"
DINO_ZINK_RGBX=1 "$RUNTIME/zink_probe" "$RUNTIME/libdino_zink.dylib" "$RUNTIME/nvk_icd.json"
if [ "$(sw_vers -buildVersion)" = "$(cat "$RUNTIME/cgl-os-build.txt")" ]; then
  MODE=()
  if /usr/sbin/ioreg -r -c NVAccel -d 1 | /usr/bin/grep -q '"IOGLBundleName" = "DinoZinkGLDriver"'; then
    "$RUNTIME/cgl_renderer_probe" --require-zink
    MODE=(--system)
  fi
  "$RUNTIME/cgl_zink_probe" "$RUNTIME/libdino_cgl.dylib" "$RUNTIME/nvk_icd.json" ${MODE[@]+"${MODE[@]}"}
  "$RUNTIME/cgl_zink_legacy_probe" "$RUNTIME/libdino_cgl.dylib" "$RUNTIME/nvk_icd.json" ${MODE[@]+"${MODE[@]}"}
  "$RUNTIME/cgl_zink_window_probe" "$RUNTIME/libdino_cgl.dylib" "$RUNTIME/nvk_icd.json" ${MODE[@]+"${MODE[@]}"}
  "$RUNTIME/cgl_zink_window_probe" "$RUNTIME/libdino_cgl.dylib" "$RUNTIME/nvk_icd.json" ${MODE[@]+"${MODE[@]}"} --legacy --no-alpha --appkit-present
  if [ "${#MODE[@]}" -gt 0 ]; then
    "$RUNTIME/cgl_zink_window_probe" "$RUNTIME/libdino_cgl.dylib" "$RUNTIME/nvk_icd.json" "${MODE[@]}" --legacy --no-alpha --appkit-present --render-thread
  fi
  "$RUNTIME/cgl_zink_window_probe" "$RUNTIME/libdino_cgl.dylib" "$RUNTIME/nvk_icd.json" ${MODE[@]+"${MODE[@]}"} --legacy --transparent
else
  echo "Native CGL adapter requires a rebuild for this macOS build." >&2
  exit 1
fi
echo "Package verification passed."
