#!/usr/bin/env python3
"""Test the compiled provider's NGX/DLL/registry rollback in private Wine prefixes.

Run after building the final provider. Does not touch a user prefix or game.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--runtime", required=True, type=Path)
parser.add_argument("--wine", required=True, type=Path)
parser.add_argument("--work", required=True, type=Path)
args = parser.parse_args()
runtime = args.runtime.resolve(strict=True)
wine = args.wine.resolve(strict=True)
helper = runtime / "bin/nvk-runtime"
args.work.mkdir(parents=True, exist_ok=True)
work = Path(tempfile.mkdtemp(prefix="dlss-setup-", dir=args.work))
key = r"HKLM\SOFTWARE\NVIDIA Corporation\Global\NGXCore"
names = ["nvapi64.dll", "nvngx.dll", "_nvngx.dll"]
results = []

def command(argv, env=None, ok=True):
    p = subprocess.run([str(v) for v in argv], env=env, text=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=90)
    assert (p.returncode == 0) == ok, (argv, p.stdout, p.stderr[-2000:])
    return p.stdout

def setup(action, prefix, ok=True):
    return json.loads(command([helper, action, runtime, prefix, wine], ok=ok))

def environment(prefix):
    return {**os.environ, "WINEPREFIX": str(prefix), "DYLD_LIBRARY_PATH": str(runtime / "lib"),
            "WINEDEBUG": "-all", "WINEDLLOVERRIDES": "mscoree,mshtml=", "WINE_NVK_HUD": "0"}

def reg(prefix, *argv, ok=True):
    return command([wine, "reg.exe", *argv], environment(prefix), ok)

def original_files(system):
    for name in names:
        assert (system / name).read_bytes() == ("original " + name).encode()

caps = json.loads(command([helper, "check", runtime]))
assert caps["supports_dlss"] and caps["supports_d3d12"]
for kind in ["absent", "string", "dword"]:
    prefix = work / kind
    env = environment(prefix)
    try:
        command([wine, "wineboot", "--init"], env)
        system = prefix / "drive_c/windows/system32"
        for name in names:
            path = system / name
            if path.exists() or path.is_symlink():
                path.unlink()
            path.write_bytes(("original " + name).encode())
        if kind == "absent":
            # A fresh prefix may carry an unrelated Wine/DXMT registration.
            subprocess.run([str(wine), "reg.exe", "delete", key, "/v", "FullPath", "/f"], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        else:
            reg(prefix, "add", key, "/v", "FullPath", "/t", "REG_SZ" if kind == "string" else "REG_DWORD", "/d", r"C:\Original NGX" if kind == "string" else "42", "/f")
        setup("install-dlss", prefix)
        setup("install-dlss", prefix)
        assert r"C:\windows\system32" in reg(prefix, "query", key, "/v", "FullPath")
        for name in names:
            assert (system / name).read_bytes() == (runtime / "dlss/x64" / name).read_bytes()
        # Refuse a user registry edit before changing any installed DLL.
        reg(prefix, "add", key, "/v", "FullPath", "/t", "REG_SZ", "/d", r"C:\User changed", "/f")
        setup("restore", prefix, ok=False)
        assert (prefix / ".nvk-dlss-state.json").exists()
        reg(prefix, "add", key, "/v", "FullPath", "/t", "REG_SZ", "/d", r"C:\windows\system32", "/f")
        # Refuse a changed third DLL before restoring either other group.
        saved = (system / names[-1]).read_bytes()
        (system / names[-1]).write_bytes(b"user replacement")
        setup("restore", prefix, ok=False)
        assert (prefix / ".nvk-vkd3d-state.json").exists()
        (system / names[-1]).write_bytes(saved)
        setup("restore-dlss", prefix)
        original_files(system)
        assert (prefix / ".nvk-vkd3d-state.json").exists()
        if kind == "absent":
            reg(prefix, "query", key, "/v", "FullPath", ok=False)
        else:
            query = reg(prefix, "query", key, "/v", "FullPath")
            assert (r"C:\Original NGX" if kind == "string" else "REG_DWORD") in query
        setup("restore-dlss", prefix)
        setup("restore", prefix)
        assert not (prefix / ".nvk-vkd3d-state.json").exists()
        results.append(kind + ": repeat install, exact registry/DLL restore, tamper preflight, graphics preserved")
    finally:
        subprocess.run([str(wine.parent / "wineserver"), "-k"], env=env,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
report = {"result": "PASS", "work": str(work), "checks": results}
(args.work / "dlss-setup-results.json").write_text(json.dumps(report, indent=2) + "\n")
print(json.dumps(report, indent=2))
