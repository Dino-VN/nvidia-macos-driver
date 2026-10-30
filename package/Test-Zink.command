#!/bin/bash
# SPDX-License-Identifier: MIT
# Run only disposable probe processes; do not install or register any driver.
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd -P)
RUNTIME="$HERE/Library/GPUBundles/nvmtl/zink"
[ -d "$RUNTIME" ] || { echo 'Keep Test-Zink.command beside its Library folder.' >&2; exit 1; }
[ -d "$HERE/Library/GPUBundles/NVKZinkGLDriver.bundle" ] || { echo 'Native GLD bundle is missing.' >&2; exit 1; }
/usr/bin/xcode-select -p >/dev/null 2>&1 || { echo 'Install Apple Command Line Tools, then rerun this test.' >&2; exit 1; }
DEST=${1:-"$HOME/Desktop"}
[ -d "$DEST" ] || { echo 'Choose an existing output folder.' >&2; exit 1; }
DEST=$(cd "$DEST" && pwd -P)
OUT=$(mktemp -d "$DEST/NVIDIA-Zink-Test-$(date +%Y%m%d-%H%M%S).XXXXXX")
/usr/bin/sw_vers > "$OUT/macos.txt"
/usr/bin/uname -m > "$OUT/architecture.txt"
mkdir "$OUT/runtime-view"
for file in "$RUNTIME"/*; do ln -s "$file" "$OUT/runtime-view/$(basename "$file")"; done
ln -s "$HERE/Library/GPUBundles/NVKZinkGLDriver.bundle" "$OUT/runtime-view/NVKZinkGLDriver.bundle"
echo 'Testing native Zink in isolated processes; brief diagnostic windows will appear.'
echo 'This does not install anything or change the system OpenGL renderer.'
set +e
/usr/bin/python3 "$RUNTIME/zink-tests/test_zink_runtime.py" \
  --runtime "$OUT/runtime-view" --output "$OUT/checks" > "$OUT/test.log" 2>&1
STATUS=$?
set -e
cat "$OUT/test.log"
printf '%s\n' "$STATUS" > "$OUT/exit-status.txt"
# Runtime links are only a local test view, not part of the returned logs.
rm -f "$OUT/runtime-view/"*
rmdir "$OUT/runtime-view"
COPYFILE_DISABLE=1 /usr/bin/tar --exclude='.DS_Store' --exclude='._*' \
  -czf "$OUT.tar.gz" -C "$(dirname "$OUT")" "$(basename "$OUT")"
printf '\nSend these logs back:\n%s.tar.gz\n' "$OUT"
exit "$STATUS"
