#!/bin/bash
# SPDX-License-Identifier: MIT
set -euo pipefail
[ "$#" = 1 ] || { echo 'usage: build_gld_probe.sh OUTPUT_DIRECTORY' >&2; exit 2; }
REPO=$(cd "$(dirname "$0")/.." && pwd)
BUNDLE="$1/NVKZinkGLDriver.bundle"
mkdir -p "$BUNDLE/Contents/MacOS"
clang -arch x86_64 -bundle -std=c11 -Wall -Wextra -Werror -fvisibility=hidden \
  "$REPO/zink/gld_trace.c" "$REPO/zink/gld_trace.S" -o "$BUNDLE/Contents/MacOS/NVKZinkGLDriver"
cat > "$BUNDLE/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>NVKZinkGLDriver</string>
<key>CFBundleIdentifier</key><string>com.highdelay.NVKZinkGLDriver</string>
<key>CFBundleName</key><string>NVKZinkGLDriver</string>
<key>CFBundlePackageType</key><string>BNDL</string>
<key>CFBundleVersion</key><string>0.0.1</string>
<key>NVKZinkDiagnosticOnly</key><true/>
</dict></plist>
PLIST
codesign --force --sign - "$BUNDLE"
echo "Diagnostic only; no usable GLD renderer: $BUNDLE"
