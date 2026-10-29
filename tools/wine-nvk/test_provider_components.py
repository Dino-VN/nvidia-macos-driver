#!/usr/bin/env python3
"""Verify pinned DLSS extraction/provenance without compiling a driver component."""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile

repo = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("provider", repo / "nvk/wine-macos/provider.py")
provider = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provider)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--nvapi-archive", type=Path, required=True)
parser.add_argument("--nvapi-source", type=Path, required=True)
parser.add_argument("--ngx-archive", type=Path, required=True)
parser.add_argument("--work", type=Path, required=True)
args = parser.parse_args()
args.work.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory(prefix="component-check-", dir=args.work) as temporary:
    root = Path(temporary)
    (root / "LICENSES").mkdir()
    metadata, paths = provider.add_dlss(root, args.nvapi_archive, args.nvapi_source, args.ngx_archive)
    assert metadata["nvapi_version"] == "0.9.2"
    record = json.loads((root / "DLSS-BUILD.json").read_text())
    assert record["ngx"]["modified"] is False
    assert "nvngx_dlss.dll" not in [p.name for p in root.rglob("*")]
    for name, expected in provider.DLSS_FILES.items():
        assert hashlib.sha256((root / "dlss/x64" / name).read_bytes()).hexdigest() == expected
    for name, expected in record["files"].items():
        assert provider.digest(root / name) == expected
    assert all((root / p).is_file() and not (root / p).is_symlink() for p in paths)
    assert "NVIDIA Driver License Agreement" in (root / "LICENSES/NVIDIA-NGX-driver-license.txt").read_text()
    bad = root / "bad.tar.gz"
    bad.write_bytes(b"invalid")
    try:
        provider.add_dlss(root, bad, args.nvapi_source, args.ngx_archive)
    except ValueError:
        pass
    else:
        raise AssertionError("Unpinned archive was accepted")
print("PASS pinned extraction, DLL hashes, licenses/provenance, no feature-DLL redistribution, tamper rejection")
