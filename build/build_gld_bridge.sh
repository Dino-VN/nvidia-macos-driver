#!/bin/bash
# SPDX-License-Identifier: MIT
set -euo pipefail
[ "$#" = 2 ] || { echo 'usage: build_gld_bridge.sh ZINK_OUTPUT BUILD_DIRECTORY' >&2; exit 2; }
REPO=$(cd "$(dirname "$0")/.." && pwd)
ZINK_OUTPUT=$(cd "$1" && pwd)
mkdir -p "$2"
GLD_BUILD=$(cd "$2" && pwd)
python3 "$REPO/build/generate_gld_forward.py" "$GLD_BUILD"
BUNDLE="$ZINK_OUTPUT/NVKZinkGLDriver.bundle"
mkdir -p "$BUNDLE/Contents/MacOS"
clang -arch x86_64 -mmacosx-version-min=15.5 -bundle -std=c11 -Wall -Wextra -Werror -fvisibility=hidden \
  -I"$REPO/zink" -I"$GLD_BUILD" "$REPO/zink/gld_bridge.c" "$GLD_BUILD/gld_forward.S" \
  -L"$ZINK_OUTPUT" -lnvk_cgl -Wl,-rpath,@loader_path/../../../nvmtl/zink \
  -Wl,-rpath,"$ZINK_OUTPUT" -o "$BUNDLE/Contents/MacOS/NVKZinkGLDriver"
cat > "$BUNDLE/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleExecutable</key><string>NVKZinkGLDriver</string>
<key>CFBundleIdentifier</key><string>com.highdelay.NVKZinkGLDriver</string>
<key>CFBundleName</key><string>NVKZinkGLDriver</string>
<key>CFBundlePackageType</key><string>BNDL</string>
<key>CFBundleVersion</key><string>0.1.0</string>
<key>NVKZinkExperimentalGLD</key><true/>
</dict></plist>
PLIST
# Record where these GLD exports were generated. Packaging checks the paired
# CGL provenance; neither value restricts the macOS build allowed to load it.
GLD_OS_BUILD=$(sw_vers -buildVersion)
/usr/libexec/PlistBuddy -c "Add :NVKZinkBuildOS string $GLD_OS_BUILD" "$BUNDLE/Contents/Info.plist"
codesign --force --sign - "$BUNDLE"
clang -arch x86_64 -mmacosx-version-min=15.5 -Wall -Wextra -Werror \
  "$REPO/tools/gld_bundle_probe.c" -o "$ZINK_OUTPUT/gld_bundle_probe"
codesign --force --sign - "$ZINK_OUTPUT/gld_bundle_probe"
python3 "$REPO/build/record_zink_runtime.py" "$ZINK_OUTPUT" gld
echo "Experimental GLD proxy built: $BUNDLE"
