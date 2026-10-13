#!/usr/bin/env python3
"""Stage the Tahoe PR builds in a copy of an extracted upstream package.

Requires macOS, Python 3, and Apple's command line tools. The upstream input
and build outputs remain unchanged; the destination must not already exist.
"""
import argparse
import hashlib
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
PLUGIN = Path("Library/GPUBundles/NVMTLDriver.bundle")
RUNTIME = Path("Library/GPUBundles/nvmtl")
TRANSLATOR = RUNTIME / "libnvmtl_translate.dylib"
BUNDLED_TRANSLATOR = PLUGIN / "Contents/MacOS/libnvmtl_translate.dylib"
FRAMEBUFFER = Path("Library/Extensions/NVRMFB.kext")
ACCEL = {v: Path("Library/NullMoth/kexts") / v / "NVAccel.kext" for v in ("15", "26")}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def inside(path, root):
    return path == root or root in path.parents


def run(*args, check=True):
    result = subprocess.run([str(a) for a in args], capture_output=True, text=True)
    if check and result.returncode:
        raise ValueError("{} failed:\n{}{}".format(args[0], result.stdout, result.stderr))
    return result


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            checksum.update(chunk)
    return checksum.hexdigest()


def validate_links(root):
    # Resolve installed absolute paths against the staged package root. This
    # accepts the package's /Library/... runtime links without following them
    # into the live system or the source package.
    for entry in root.rglob("*"):
        if entry.is_symlink():
            current = entry
            seen = set()
            while current.is_symlink():
                require(current not in seen, "package symlink loop: " + str(entry))
                seen.add(current)
                target = Path(os.readlink(current))
                require(".." not in target.parts, "package symlink contains parent traversal: " + str(entry))
                current = (root / target.relative_to("/")) if target.is_absolute() else (current.parent / target)
            require(inside(current.resolve(strict=True), root), "package symlink escapes its root: " + str(entry))


def regular(path):
    require(path.is_file() and not path.is_symlink(), "missing regular file: " + str(path))


def bundle(path, executable):
    require(path.is_dir() and not path.is_symlink(), "missing bundle: " + str(path))
    regular(path / "Contents/Info.plist")
    regular(path / "Contents/MacOS" / executable)
    with (path / "Contents/Info.plist").open("rb") as stream:
        info = plistlib.load(stream)
    require(info.get("CFBundleExecutable") == executable, "unexpected bundle executable: " + str(path))


def manifest_name(name):
    if any(c in name for c in "\\\r\n"):
        return "\\", name.replace("\\", "\\\\").replace("\n", "\\n").replace("\r", "\\r")
    return "", name


def decode_name(name):
    # shasum/coreutils escape file names containing backslashes or newlines.
    require(re.fullmatch(r"(?:[^\\]|\\[\\nr])*", name) is not None, "invalid checksum filename escape")
    return re.sub(r"\\([\\nr])", lambda m: {"\\": "\\", "n": "\n", "r": "\r"}[m[1]], name)


def verify_manifest(root):
    manifest = root / "SHA256SUMS"
    regular(manifest)
    count = 0
    for row in manifest.read_text(encoding="utf-8").splitlines():
        if not row or row.startswith("#"):
            continue
        escaped = row.startswith("\\")
        match = re.fullmatch(r"([0-9a-fA-F]{64}) [ *](.+)", row[1:] if escaped else row)
        require(match is not None, "invalid checksum record in " + str(manifest))
        name = decode_name(match[2]) if escaped else match[2]
        relative = Path(name)
        require(not relative.is_absolute() and ".." not in relative.parts, "checksum path escapes package: " + name)
        target = root / relative
        require(inside(target.resolve(strict=True), root), "checksum target escapes package: " + name)
        require(digest(target) == match[1].lower(), "SHA256SUMS mismatch: " + name)
        count += 1
    require(count > 0, "empty checksum manifest: " + str(manifest))


def write_manifest(root):
    rows = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink() or path == root / "SHA256SUMS":
            continue
        prefix, name = manifest_name("./" + path.relative_to(root).as_posix())
        rows.append(prefix + digest(path) + "  " + name + "\n")
    manifest = root / "SHA256SUMS"
    require(not manifest.is_symlink(), "checksum manifest must not be a symlink: " + str(manifest))
    with manifest.open("w", encoding="utf-8", newline="\n") as stream:
        stream.writelines(rows)
    manifest.chmod(0o644)
    verify_manifest(root)


def replace_file(source, destination):
    # Unlink first: never write through a packaged symlink or shared hard link.
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    shutil.copy2(source, destination)


def stage(args):
    require(sys.platform == "darwin", "run this helper on macOS")
    base = args.base.resolve(strict=True)
    output = args.output.absolute()
    require(not output.exists() and not output.is_symlink(), "output already exists: " + str(output))
    output = output.resolve()
    require(not inside(output, base), "output must be outside the upstream package")
    require(base not in (Path("/"), Path("/System/Volumes/Data")), "use an extracted upstream pkgroot")

    for name in ("install.sh", "uninstall.sh", "VERSION", "Library/GPUBundles/nvmtl-allow.txt"):
        regular(base / name)
    for name in ("Library/GPUBundles/NVIDIAShared.bundle", "Users/Shared/nvfw"):
        require((base / name).is_dir(), "incomplete upstream package: " + name)
    bundle(base / PLUGIN, "NVMTLDriver")
    for name in ("NVRM", "NVRMAGDC", "NVRMFB"):
        bundle(base / "Library/Extensions" / (name + ".kext"), name)
    for path in ACCEL.values():
        bundle(base / path, "NVAccel")
    # Older upstream package builds keep the translator only beside the
    # plugin executable. Accept that layout; staging creates the canonical
    # nvmtl copy and refreshes the plugin copy below.
    canonical_translator = base / TRANSLATOR
    bundled_translator = base / BUNDLED_TRANSLATOR
    require(
        (canonical_translator.is_file() and not canonical_translator.is_symlink())
        or bundled_translator.is_file(),
        "missing packaged translator: " + str(TRANSLATOR),
    )
    regular(base / RUNTIME / "libvulkan_nouveau.dylib")
    validate_links(base)
    verify_manifest(base)

    # Defaults name one exact build, never whichever output directory is newest.
    commit = run("git", "-C", REPO, "rev-parse", "--short", "HEAD").stdout.strip()
    plugin = args.plugin or REPO / ("out/plugin-" + commit + "-release/NVMTLDriver")
    translator = args.translator or REPO / "out/translator/x86_64-apple-darwin/release/libnvmtl_translate.dylib"
    plist = args.framebuffer_plist or REPO / "kexts/NVRMFB/fb/Info.plist"
    for path in (plugin, translator, plist):
        regular(path)
    with plist.open("rb") as stream:
        require(plistlib.load(stream).get("CFBundleExecutable") == "NVRMFB", "not an NVRMFB Info.plist")
    replacements = [(plugin, PLUGIN / "Contents/MacOS/NVMTLDriver"), (translator, TRANSLATOR)]
    if args.accel_26:
        bundle(args.accel_26, "NVAccel")
        validate_links(args.accel_26.resolve())
        run("lipo", args.accel_26 / "Contents/MacOS/NVAccel", "-verify_arch", "x86_64")
    for source, _ in replacements:
        run("lipo", source, "-verify_arch", "x86_64")

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".nullmoth-stage-", dir=output.parent) as temporary:
        work = Path(temporary) / "pkgroot"
        shutil.copytree(base, work, symlinks=True)
        if args.accel_26:
            destination = work / ACCEL["26"]
            shutil.rmtree(destination)
            shutil.copytree(args.accel_26, destination, symlinks=True)
        replace_file(plist, work / FRAMEBUFFER / "Contents/Info.plist")
        for source, relative in replacements:
            replace_file(source, work / relative)

        # Copy finalized binaries byte-for-byte, including the translator copy
        # which the plugin prefers over the canonical runtime directory.
        bundled = work / BUNDLED_TRANSLATOR
        if bundled.is_symlink():
            require(bundled.resolve(strict=True) == (work / TRANSLATOR).resolve(),
                    "bundled translator link must point to the canonical nvmtl translator")
        elif bundled.exists():
            replace_file(work / TRANSLATOR, bundled)
        # install.sh requires both OS variants and selects 26 on Tahoe. Only
        # that optional replacement needs a new nested manifest; preserve 15.
        if args.accel_26:
            write_manifest(work / ACCEL["26"].parent)
        for name in ("install.sh", "uninstall.sh"):
            (work / name).chmod(0o755)
        validate_links(work)
        write_manifest(work)
        require(not output.exists() and not output.is_symlink(), "output appeared while staging; refusing to replace it")
        work.rename(output)
    print("Package ready: " + str(output))
    print("Updated: NVMTLDriver, translator, NVRMFB Info.plist" + (", Tahoe NVAccel" if args.accel_26 else ""))
    print("SHA256SUMS verified. Install on Tahoe using install.sh.")
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("base", type=Path, help="unmodified extracted upstream pkgroot")
    parser.add_argument("output", type=Path, help="new package directory outside the input")
    parser.add_argument("--plugin", type=Path, help="NVMTLDriver executable (default: current-commit release output)")
    parser.add_argument("--translator", type=Path, help="libnvmtl_translate.dylib (default: out/translator Intel release)")
    parser.add_argument("--framebuffer-plist", type=Path, help="NVRMFB Info.plist (default: this checkout's PR #131 plist)")
    parser.add_argument("--accel-26", type=Path, help="optional complete rebuilt Tahoe NVAccel.kext")
    try:
        stage(parser.parse_args())
    except (OSError, ValueError, RuntimeError, plistlib.InvalidFileException) as error:
        print("STOP: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
