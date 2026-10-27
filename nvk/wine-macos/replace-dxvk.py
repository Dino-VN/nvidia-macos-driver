#!/usr/bin/env python3
"""Create a new private runtime from a validated base and a local DXVK build."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
for name in ["base", "output", "dxvk-source", "dxvk-build", "strip"]:
    parser.add_argument("--" + name, type=Path, required=True)
args = parser.parse_args()
base, root = args.base.resolve(), args.output.resolve()
source, build = args.dxvk_source.resolve(), args.dxvk_build.resolve()
if root.exists():
    raise SystemExit("Output exists; use a new directory rather than replacing a running runtime")
subprocess.run([str(base / "bin/nvk-runtime"), "check", str(base)], check=True)
revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=source, text=True).strip()
source_base = "b1a1c99ab52b687cf950d62c88bc2fa316b41663"
subprocess.run(["git", "merge-base", "--is-ancestor", source_base, revision], cwd=source, check=True)
project_info = json.loads((build / "meson-info/intro-projectinfo.json").read_text())
if project_info["version"] != "3.1.1":
    raise SystemExit("This packaging recipe requires a build based on DXVK 3.1.1")
system_files = json.loads((build / "meson-info/intro-buildsystem_files.json").read_text())
if str(source / "meson.build") not in system_files:
    raise SystemExit("Meson output does not identify the requested DXVK source tree")
for component in ["d3d11", "dxgi"]:
    if not (build / "src" / component / (component + ".dll")).is_file():
        raise SystemExit("Build both DXVK DLLs before packaging")
root.parent.mkdir(parents=True, exist_ok=True)
clone = subprocess.run(["/bin/cp", "-cR", str(base), str(root)], capture_output=True)
if clone.returncode:
    if root.exists():
        shutil.rmtree(root)
    shutil.copytree(base, root, symlinks=True)

def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()

commands, dlls = [], {}
for component in ["d3d11", "dxgi"]:
    binary = build / "src" / component / (component + ".dll")
    relative = "dxvk/x64/" + component + ".dll"
    target = root / relative
    shutil.copyfile(binary, target)
    command = [str(args.strip.resolve()), "--strip-debug", str(target)]
    subprocess.run(command, check=True)
    commands.append(command)
    dlls[relative] = {"unstripped_sha256": digest(binary), "packaged_sha256": digest(target)}
diff = subprocess.check_output(["git", "diff", "--binary", source_base], cwd=source, text=True)
record = {"source_revision": revision, "source_base": source_base, "source_diff": diff,
          "source_diff_sha256": hashlib.sha256(diff.encode()).hexdigest(),
          "source_files": {name: digest(source / name) for name in
                           subprocess.check_output(["git", "diff", "--name-only", source_base], cwd=source, text=True).splitlines()},
          "submodules": subprocess.check_output(["git", "submodule", "status", "--recursive"], cwd=source, text=True),
          "meson_build_options": json.loads((build / "meson-info/intro-buildoptions.json").read_text()),
          "compiler_info": json.loads((build / "meson-info/intro-compilers.json").read_text()),
          "packaging_commands": commands, "dlls": dlls}
patch = root / "dxvk/source-changes.patch"
patch.write_text(diff)
shutil.copyfile(source / "LICENSE", root / "LICENSES/DXVK-zlib.txt")
(root / "DXVK-BUILD.json").write_text(json.dumps(record, indent=2) + "\n")
manifest = json.loads((root / "nvk-wine-runtime.json").read_text())
for relative in dlls:
    manifest["files"][relative] = digest(root / relative)
identity = hashlib.sha256(json.dumps(manifest["files"], sort_keys=True).encode()).hexdigest()[:12]
manifest["runtime_id"] = "nvk-wine-dxvk-3.1.1-" + identity
manifest["dxvk"] = {"version": "3.1.1+nvk-shared-fallback", "source_revision": revision,
                    "modified": bool(diff), "source_diff_sha256": record["source_diff_sha256"],
                    "base_archive_sha256": manifest["dxvk"].get("archive_sha256"),
                    "build_record": "DXVK-BUILD.json", "patch": "dxvk/source-changes.patch"}
manifest["validation"] = {"d3d11": "NOT RUN with custom DXVK", "shared_texture": "NOT RUN",
                          "zzz": "NOT RUN with custom DXVK", "gi": "NOT RUN", "hsr": "NOT RUN",
                          "inherited_native_libraries": "Byte-identical to validated base; see base BUILD.json"}
(root / "nvk-wine-runtime.json").write_text(json.dumps(manifest, indent=2) + "\n")
build_record = json.loads((root / "BUILD.json").read_text())
build_record["runtime_id"] = manifest["runtime_id"]
build_record["package_files"] = manifest["files"]
build_record["dxvk_build_record"] = "DXVK-BUILD.json"
build_record["validation"] = manifest["validation"]
build_record.setdefault("source_files", {})["nvk/wine-macos/replace-dxvk.py"] = digest(Path(__file__).resolve())
(root / "BUILD.json").write_text(json.dumps(build_record, indent=2) + "\n")
# Unchanged files retain their verified base hashes; only replaced/new files are
# rehashed. Copying keeps the immutable base available for comparison/rollback.
sums = {}
for line in (base / "SHA256SUMS").read_text().splitlines():
    sha, relative = line.split("  ", 1)
    sums[relative] = sha
for relative in [*dlls, "nvk-wine-runtime.json", "BUILD.json", "DXVK-BUILD.json",
                 "dxvk/source-changes.patch", "LICENSES/DXVK-zlib.txt"]:
    sums[relative] = digest(root / relative)
(root / "SHA256SUMS").write_text("".join(sha + "  " + relative + "\n" for relative, sha in sorted(sums.items())))
subprocess.run([str(root / "bin/nvk-runtime"), "check", str(root)], check=True)
print(json.dumps({"root": str(root), "runtime_id": manifest["runtime_id"], "dxvk": manifest["dxvk"]}, indent=2))
