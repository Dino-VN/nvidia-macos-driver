#!/bin/bash
# SPDX-License-Identifier: MIT
set -euo pipefail
if [ "$#" -ne 3 ]; then
  echo "usage: build_zink.sh MESA_SOURCE BUILD_DIRECTORY OUTPUT_DIRECTORY" >&2
  exit 2
fi
REPO=$(cd "$(dirname "$0")/.." && pwd)
MESA_SOURCE=$(cd "$1" && pwd)
mkdir -p "$2" "$3"
ZINK_BUILD=$(cd "$2" && pwd)
ZINK_OUTPUT=$(cd "$3" && pwd)
case "$ZINK_BUILD" in "$MESA_SOURCE"|"$MESA_SOURCE/build263")
  echo "Use a separate Zink build directory." >&2; exit 2;;
esac
python3 "$REPO/build/prepare_zink.py" "$MESA_SOURCE"
args=(-Dbuildtype=release -Dgallium-drivers=zink -Dvulkan-drivers= -Dplatforms=
      -Degl=disabled -Dglx=disabled -Dgbm=disabled -Dglvnd=disabled
      -Dllvm=disabled -Dshared-glapi=disabled -Dvulkan-layers= -Dtools=
      -Dbuild-tests=false -Dexpat=disabled -Dzstd=disabled -Dlibunwind=disabled
      -Dlmsensors=disabled -Dvalgrind=disabled -Dxlib-lease=disabled
      -Dgallium-rusticl=false -Dspirv-tools=disabled -Dmoltenvk-dir=
      "-Dvulkan-loader-rpath=${ZINK_VULKAN_RUNTIME:-/Library/GPUBundles/nvmtl}")
if [ -f "$ZINK_BUILD/build.ninja" ]; then
  meson setup --reconfigure "$ZINK_BUILD" "$MESA_SOURCE" "${args[@]}"
else
  meson setup "$ZINK_BUILD" "$MESA_SOURCE" "${args[@]}"
fi
ninja -C "$ZINK_BUILD" src/gallium/targets/dino-zink/libdino_zink.dylib
cp "$ZINK_BUILD/src/gallium/targets/dino-zink/libdino_zink.dylib" "$ZINK_OUTPUT/"
cp "$REPO/zink/dino_zink.h" "$ZINK_OUTPUT/"
install_name_tool -id @rpath/libdino_zink.dylib "$ZINK_OUTPUT/libdino_zink.dylib"
codesign --force --sign - "$ZINK_OUTPUT/libdino_zink.dylib"
clang -arch x86_64 -std=c11 -Wall -Wextra -Werror \
  "$REPO/tools/zink_probe.c" -I"$REPO/zink" -framework IOSurface -framework CoreFoundation -o "$ZINK_OUTPUT/zink_probe"
clang -arch x86_64 -std=c11 -Wall -Wextra -Werror -Wno-deprecated-declarations \
  "$REPO/tools/cgl_renderer_probe.c" -framework OpenGL -o "$ZINK_OUTPUT/cgl_renderer_probe"
echo "Zink runtime and probes: $ZINK_OUTPUT"
