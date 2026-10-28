#!/bin/bash
# SPDX-License-Identifier: MIT
set -euo pipefail
if [ "$#" -ne 2 ]; then
  echo "usage: build_cgl_zink.sh ZINK_OUTPUT CGL_BUILD_DIRECTORY" >&2; exit 2
fi
REPO=$(cd "$(dirname "$0")/.." && pwd)
ZINK_OUTPUT=$(cd "$1" && pwd)
mkdir -p "$2"
CGL_BUILD=$(cd "$2" && pwd)
python3 "$REPO/build/generate_cgl_dispatch.py" "$ZINK_OUTPUT/cgl_renderer_probe" "$CGL_BUILD"
CGL_OS_BUILD=$(sw_vers -buildVersion)
clang -arch x86_64 -mmacosx-version-min=15.5 -std=c11 -O2 -Wall -Wextra -Werror -Wno-deprecated-declarations \
  -fvisibility=hidden -DDINO_CGL_OS_BUILD=\""$CGL_OS_BUILD"\" \
  -I"$REPO/zink" -I"$CGL_BUILD" "$REPO/zink/dino_cgl.c" \
  -dynamiclib -L"$ZINK_OUTPUT" -ldino_zink -framework OpenGL \
  -Wl,-rpath,@loader_path -Wl,-rpath,/Library/GPUBundles/nvmtl \
  -install_name @rpath/libdino_cgl.dylib -o "$ZINK_OUTPUT/libdino_cgl.dylib"
codesign --force --sign - "$ZINK_OUTPUT/libdino_cgl.dylib"
cp "$REPO/zink/dino_cgl.h" "$ZINK_OUTPUT/"
printf '%s\n' "$CGL_OS_BUILD" > "$ZINK_OUTPUT/cgl-os-build.txt"
clang -arch x86_64 -mmacosx-version-min=15.5 -std=c11 -Wall -Wextra -Werror -Wno-deprecated-declarations \
  "$REPO/tools/cgl_zink_probe.c" -I"$REPO/zink" -framework OpenGL -o "$ZINK_OUTPUT/cgl_zink_probe"
clang -arch x86_64 -mmacosx-version-min=15.5 -fobjc-arc -Wall -Wextra -Werror -Wno-deprecated-declarations \
  "$REPO/tools/cgl_zink_window_probe.m" -I"$REPO/zink" -framework Cocoa -framework OpenGL \
  -o "$ZINK_OUTPUT/cgl_zink_window_probe"
echo "Native CGL adapters built for macOS $CGL_OS_BUILD: $ZINK_OUTPUT/libdino_cgl.dylib"
