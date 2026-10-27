#!/usr/bin/env python3
"""Extract a compact Wine/CrossOver provider from a validated Wine/NVK bundle.

Wine stays an application dependency. Only the matched Vulkan/DXVK libraries,
setup helper, license notices and provenance are included in the driver package.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[2]
CRITICAL = (
    "lib/libnvk_wine.dylib", "lib/libnvk_renderer.dylib",
    "bin/nvk-runtime", "dxvk/x64/d3d11.dll", "dxvk/x64/dxgi.dll",
)


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def build(base, output):
    base, output = base.resolve(strict=True), output.absolute()
    if output.exists() or output.is_symlink():
        raise ValueError("Output exists; choose a new directory")
    output = output.resolve()
    if base == output or base in output.parents:
        raise ValueError("Output must be outside the base runtime")
    subprocess.run([str(base / "bin/nvk-runtime"), "check", str(base)], check=True)
    source = json.loads((base / "nvk-wine-runtime.json").read_text())
    if source["dxvk"]["version"] != "3.1.1+nvk-shared-fallback":
        raise ValueError("Use the repaired DXVK 3.1.1 pair, not the stock release")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".wine-nvk-", dir=output.parent) as temporary:
        root = Path(temporary) / "provider"
        root.mkdir()
        paths = [*CRITICAL, "dxvk/source-changes.patch", "DXVK-BUILD.json"]
        licenses = base / "LICENSES"
        if not licenses.is_dir() or licenses.is_symlink():
            raise ValueError("The dependency license records are required")
        for name in ("frontend-PolyForm-Noncommercial-1.0.0.txt", "DXVK-zlib.txt", "Mesa-license.rst", "Wine-LGPL-2.1.txt"):
            if not (licenses / name).is_file():
                raise ValueError("Missing license: " + name)
        paths.extend(p.relative_to(base).as_posix() for p in sorted(licenses.glob("*")))
        for relative in paths:
            path = base / relative
            if not path.is_file() or path.is_symlink():
                raise ValueError("Missing regular runtime artifact: " + relative)
            if base not in path.resolve(strict=True).parents:
                raise ValueError("Runtime artifact resolves outside its root: " + relative)
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        # Provider-only manifests do not require a vendored Wine installation.
        # Build this helper rather than shipping an older bundle-only helper.
        helper = root / "bin/nvk-runtime"
        commands = [
            ["xcrun", "clang++", "-arch", "x86_64", "-mmacosx-version-min=15.0",
             "-std=c++17", "-fobjc-arc", "-O2", "-Wall", "-Wextra", "-Werror",
             str(REPO / "nvk/wine-macos/setup.mm"), "-framework", "Foundation", "-o", str(helper)],
            ["codesign", "--force", "--sign", "-", "--timestamp=none", str(helper)],
        ]
        for command in commands:
            subprocess.run(command, check=True)
        (root / "lib/libMoltenVK.dylib").symlink_to("libnvk_wine.dylib")
        shutil.copyfile(REPO / "nvk/wine-macos/INSTALL.md", root / "README.md")
        files = {p: digest(root / p) for p in paths}
        identity = hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()[:12]
        manifest = {
            "schema_version": 1, "kind": "provider", "runtime_id": "nvk-wine-provider-" + identity,
            "source_runtime_id": source["runtime_id"], "platform": source["platform"],
            "entry": {"path": CRITICAL[0], "sha256": files[CRITICAL[0]]},
            "renderer": {"path": CRITICAL[1], "sha256": files[CRITICAL[1]]},
            "files": files, "dxvk": source["dxvk"], "presentation": source["presentation"],
            "launch_defaults": {"DXVK_CONFIG": "dxvk.enableDescriptorBuffer = False",
                                "DXVK_HUD": "devinfo,fps,frametimes,scale=1.25",
                                "WINEDLLOVERRIDES": "d3d11,dxgi=n"},
            "validation": {"inherited_binaries": "Vulkan and DXVK binaries copied byte-for-byte from source_runtime_id",
                           "helper": "Rebuilt; run the setup/rollback tests on this output",
                           "external_wine_crossover": "Not qualified by packaging"},
        }
        (root / "nvk-wine-runtime.json").write_text(json.dumps(manifest, indent=2) + "\n")
        record = {
            "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=REPO, text=True).strip(),
            "source_runtime_id": source["runtime_id"], "source_manifest_sha256": digest(base / "nvk-wine-runtime.json"),
            "source_build_sha256": digest(base / "BUILD.json"),
            "source_files": {name: digest(REPO / name) for name in
                             ("nvk/wine-macos/setup.mm", "nvk/wine-macos/provider.py", "nvk/wine-macos/INSTALL.md")},
            "commands": commands, "files": files,
        }
        (root / "BUILD.json").write_text(json.dumps(record, indent=2) + "\n")
        with (root / "SHA256SUMS").open("w") as stream:
            for path in sorted(root.rglob("*")):
                if path.is_file() and not path.is_symlink() and path != root / "SHA256SUMS":
                    stream.write(digest(path) + "  " + path.relative_to(root).as_posix() + "\n")
        subprocess.run([str(helper), "check", str(root)], check=True)
        if output.exists() or output.is_symlink():
            raise ValueError("Output appeared while building; refusing to replace it")
        root.rename(output)
    return {"root": str(output), "runtime_id": manifest["runtime_id"], "bundled_wine": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, required=True, help="validated full Wine/NVK runtime with repaired DXVK")
    parser.add_argument("--output", type=Path, required=True, help="new compact provider directory")
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.base, args.output), indent=2))
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print("STOP: " + str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
