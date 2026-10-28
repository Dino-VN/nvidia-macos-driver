#!/bin/bash
# SPDX-License-Identifier: MIT
# Stage only on an explicitly supplied, writable System-volume mount.
# Mounting, selecting the accelerator, and blessing a snapshot remain explicit.
set -euo pipefail
if [ "$#" != 2 ]; then
  echo 'usage: stage_gld_bundle.sh BUNDLE MOUNTED_SYSTEM_VOLUME' >&2; exit 2
fi
BUNDLE=$(cd "$1" && pwd)
SYSTEM_MOUNT=$(cd "$2" && pwd)
[ "$SYSTEM_MOUNT" != / ] || { echo 'Use a separate writable System-volume mount.' >&2; exit 2; }
[ -d "$SYSTEM_MOUNT/System/Library/Extensions" ] && [ -d "$SYSTEM_MOUNT/System/Library/CoreServices" ] || {
  echo 'Not a mounted macOS System volume.' >&2; exit 2;
}
[ -f "$BUNDLE/Contents/MacOS/DinoZinkGLDriver" ] || { echo 'GLD bundle missing.' >&2; exit 2; }
plutil -lint "$BUNDLE/Contents/Info.plist"
codesign --verify --strict "$BUNDLE"
lipo "$BUNDLE/Contents/MacOS/DinoZinkGLDriver" -verify_arch x86_64
DEST="$SYSTEM_MOUNT/System/Library/Extensions/DinoZinkGLDriver.bundle"
if [ -e "$DEST" ]; then
  BACKUP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/dino-gld-backup.XXXXXX")
  ditto "$DEST" "$BACKUP_ROOT/DinoZinkGLDriver.bundle"
  echo "Previous bundle backup: $BACKUP_ROOT/DinoZinkGLDriver.bundle"
fi
ditto "$BUNDLE" "$DEST"
chown -R root:wheel "$DEST"
chmod -R go-w "$DEST"
echo "Staged: $DEST"
echo 'The diagnostic bundle reports no usable renderer. IOGLBundleName and the boot snapshot have not been changed.'
