#!/bin/bash
# Sign a staged distribution package, then refresh its installer manifest.
# Compatible with macOS's /bin/bash 3.2; signing uses the ad hoc identity.
set -euo pipefail

usage() {
  echo "Usage: bash build/sign_package.sh /path/to/pkgroot"
  echo "Run on macOS after copying the final artifacts into the package."
}

die() { echo "STOP: $*" >&2; exit 1; }

case "${1:-}" in -h|--help) usage; exit 0;; esac
[ "$#" -eq 1 ] || { usage >&2; exit 2; }
[ "$(uname -s)" = Darwin ] || die "signing requires macOS"
for tool in codesign shasum find mktemp chmod mv rm dirname; do
  command -v "$tool" >/dev/null || die "required tool is missing: $tool"
done

package_root=$(cd -P "$1" && pwd) || die "package directory does not exist: $1"
case "$package_root" in /|/System/Volumes/Data) die "use a staged package, not the installed system";; esac
[ ! -L "$package_root/SHA256SUMS" ] || die "SHA256SUMS must not be a symlink"

# Check every signing target before changing any signatures. Resolving parents
# also prevents package directory links from sending codesign outside the stage.
require_file() {
  [ -f "$1" ] && [ ! -L "$1" ] || die "missing regular package file: $1"
  local parent
  parent=$(cd -P "$(dirname "$1")" && pwd) || die "cannot resolve package path: $1"
  case "$parent/" in "$package_root/"*) ;; *) die "package file resolves outside the stage: $1";; esac
}

require_bundle() {
  [ -d "$1" ] && [ ! -L "$1" ] || die "missing regular bundle directory: $1"
  require_file "$1/Contents/Info.plist"
  require_file "$1/Contents/MacOS/$2"
}

require_file "$package_root/install.sh"
translator="$package_root/Library/GPUBundles/nvmtl/libnvmtl_translate.dylib"
plugin="$package_root/Library/GPUBundles/NVMTLDriver.bundle"
framebuffer="$package_root/Library/Extensions/NVRMFB.kext"
accel15="$package_root/Library/NullMoth/kexts/15/NVAccel.kext"
accel26="$package_root/Library/NullMoth/kexts/26/NVAccel.kext"
require_file "$translator"
require_bundle "$plugin" NVMTLDriver
require_bundle "$framebuffer" NVRMFB
require_bundle "$accel15" NVAccel
require_bundle "$accel26" NVAccel

libraries_list=""; files_list=""; manifest_tmp=""
cleanup() {
  [ -z "$libraries_list" ] || rm -f "$libraries_list"
  [ -z "$files_list" ] || rm -f "$files_list"
  [ -z "$manifest_tmp" ] || rm -f "$manifest_tmp"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

libraries_list=$(mktemp -t nullmoth-sign-libraries.XXXXXX)
find "$plugin" -type f -name '*.dylib' -print0 > "$libraries_list"
while IFS= read -r -d '' library; do
  require_file "$library"
done < "$libraries_list"

sign_and_verify() {
  printf 'Signing %s\n' "${1#"$package_root/"}"
  codesign --force --sign - "$1"
  codesign --verify --deep --strict --verbose=2 "$1"
}

# Sign nested libraries before sealing the enclosing plugin. find does not
# follow symlinks, so a link to the canonical translator is left intact.
sign_and_verify "$translator"
while IFS= read -r -d '' library; do
  sign_and_verify "$library"
done < "$libraries_list"
for bundle in "$plugin" "$framebuffer" "$accel15" "$accel26"; do
  sign_and_verify "$bundle"
done

# Build and check the candidate before replacing the old manifest. Keep the
# candidate on the package's filesystem so the final rename is atomic.
files_list=$(mktemp -t nullmoth-sign-files.XXXXXX)
manifest_tmp=$(mktemp "$package_root/.SHA256SUMS.sign.XXXXXX")
(
  cd "$package_root"
  find . -type f ! -path './SHA256SUMS' \
    ! -path "./${manifest_tmp##*/}" -print0 > "$files_list"
  while IFS= read -r -d '' package_file; do
    shasum -a 256 "$package_file"
  done < "$files_list"
) > "$manifest_tmp"
(
  cd "$package_root"
  shasum -a 256 -c "$manifest_tmp" --quiet
)
chmod 644 "$manifest_tmp"
mv -f "$manifest_tmp" "$package_root/SHA256SUMS"
manifest_tmp=""

echo "Package signatures verified; SHA256SUMS refreshed. Ready to archive."
