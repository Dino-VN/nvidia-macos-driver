#!/usr/bin/env python3
"""Exercise staged signing and manifest failures with simulated macOS tools.

These tests check package handling, not Apple's actual signature or trust policy.
They also run on Windows using Git Bash when it is installed.
"""
import hashlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "build/sign_package.sh"
BASH = shutil.which("bash")
if not BASH and os.name == "nt":
    candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/bin/bash.exe"
    if candidate.is_file():
        BASH = str(candidate)


def shell_path(path):
    value = Path(path).resolve().as_posix()
    if os.name == "nt":
        return "/" + value[0].lower() + value[2:]
    return value


MOCK_TOOLS = r'''
import hashlib, json, os, re, sys
from pathlib import Path

tool, args = sys.argv[1], sys.argv[2:]
root = Path(os.environ["SIGN_PACKAGE_TEST_ROOT"])

def path(value):
    if os.name == "nt" and re.match(r"^/[a-zA-Z]/", value):
        value = value[1] + ":" + value[2:]
    return Path(value)

if tool == "uname":
    print(os.environ.get("FAKE_SYSTEM", "Darwin"))
elif tool == "codesign":
    target = path(args[-1])
    relative = target.relative_to(root).as_posix()
    operation = "verify" if "--verify" in args else "sign"
    with Path(os.environ["SIGN_PACKAGE_TEST_LOG"]).open("a", encoding="utf-8") as log:
        log.write(json.dumps([operation, relative]) + "\n")
    if os.environ.get("FAIL_" + operation.upper()) == relative:
        sys.exit(71)
    if operation == "sign":
        if target.is_dir():
            seal = target / "Contents/_CodeSignature/CodeResources"
            seal.parent.mkdir(parents=True, exist_ok=True)
            seal.write_bytes(b"fixture bundle signature")
        else:
            target.write_bytes(target.read_bytes() + b"\nfixture-adhoc")
    elif target.is_dir():
        if not (target / "Contents/_CodeSignature/CodeResources").is_file():
            sys.exit(72)
        # Model the need to sign nested code before verifying the outer bundle.
        for library in target.rglob("*.dylib"):
            if not library.read_bytes().endswith(b"fixture-adhoc"):
                sys.exit(73)
    elif not target.read_bytes().endswith(b"fixture-adhoc"):
        sys.exit(74)
elif tool == "shasum":
    if "-c" in args:
        if os.environ.get("FAIL_MANIFEST_VERIFY"):
            sys.exit(75)
        manifest = path(args[args.index("-c") + 1])
        for row in manifest.read_text(encoding="utf-8").splitlines():
            wanted, filename = row.split("  ", 1)
            if hashlib.sha256(path(filename).read_bytes()).hexdigest() != wanted:
                sys.exit(76)
    else:
        filename = args[-1]
        if os.environ.get("FAIL_HASH") == filename:
            sys.exit(77)
        print(hashlib.sha256(path(filename).read_bytes()).hexdigest() + "  " + filename)
else:
    sys.exit(78)
'''


@unittest.skipUnless(BASH, "bash is required")
class SignPackage(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="nvmtl signing tests ")
        self.root = Path(self.temp.name)
        self.package = self.root / "package with spaces"
        self.package.mkdir()
        self.bin = self.root / "bin"
        self.bin.mkdir()
        self.log = self.root / "codesign.jsonl"
        helper = self.root / "mock_tools.py"
        helper.write_text(MOCK_TOOLS, encoding="utf-8", newline="\n")
        for tool in ("uname", "codesign", "shasum"):
            wrapper = self.bin / tool
            wrapper.write_text(
                "#!/bin/bash\nexec "
                + shlex.quote(Path(sys.executable).as_posix()) + " "
                + shlex.quote(helper.as_posix()) + " " + tool + ' "$@"\n',
                encoding="utf-8", newline="\n",
            )
            wrapper.chmod(0o755)
        self.plugin = "Library/GPUBundles/NVMTLDriver.bundle"
        self.framebuffer = "Library/Extensions/NVRMFB.kext"
        self.accel15 = "Library/NullMoth/kexts/15/NVAccel.kext"
        self.accel26 = "Library/NullMoth/kexts/26/NVAccel.kext"
        self.translator = "Library/GPUBundles/nvmtl/libnvmtl_translate.dylib"
        self.bundled_translator = self.plugin + "/Contents/MacOS/libnvmtl_translate.dylib"
        for bundle, executable in (
            (self.plugin, "NVMTLDriver"), (self.framebuffer, "NVRMFB"),
            (self.accel15, "NVAccel"), (self.accel26, "NVAccel"),
        ):
            self.put(bundle + "/Contents/Info.plist", b"fixture plist")
            self.put(bundle + "/Contents/MacOS/" + executable, b"fixture binary")
        self.put(self.translator, b"fixture translator")
        self.put(self.bundled_translator, b"fixture translator")
        self.put(self.plugin + "/Contents/Resources/nested/extra.dylib", b"fixture library")
        self.put("Library/Extensions/NVRM.kext/Contents/MacOS/NVRM", b"unchanged RM")
        self.put("Library/Extensions/NVRMAGDC.kext/Contents/MacOS/NVRMAGDC", b"unchanged AGDC")
        self.put("install.sh", b"fixture installer")
        self.put("VERSION", b"fixture package version")
        self.put("payload with spaces.txt", b"payload")
        self.old_manifest = b"previous manifest\n"
        self.put("SHA256SUMS", self.old_manifest)

    def tearDown(self):
        self.temp.cleanup()

    def put(self, relative, content):
        path = self.package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path

    def run_script(self, **faults):
        env = dict(os.environ, **faults)
        env.update(
            SIGN_PACKAGE_TEST_BIN=shell_path(self.bin),
            SIGN_PACKAGE_TEST_ROOT=str(self.package),
            SIGN_PACKAGE_TEST_LOG=str(self.log),
            MSYS2_ARG_CONV_EXCL="*",
        )
        return subprocess.run(
            [BASH, "-c", 'export PATH="$SIGN_PACKAGE_TEST_BIN:/usr/bin:/bin"; exec /bin/bash "$@"',
             "sign-package-test", shell_path(SCRIPT), shell_path(self.package)],
            env=env, capture_output=True, text=True, timeout=45,
        )

    def calls(self):
        return [json.loads(row) for row in self.log.read_text().splitlines()] if self.log.exists() else []

    def assert_manifest_retained(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual((self.package / "SHA256SUMS").read_bytes(), self.old_manifest)
        self.assertFalse(list(self.package.glob(".SHA256SUMS.sign.*")))
        self.assertNotIn("Ready to archive", result.stdout)

    def test_signed_artifacts_and_all_package_files_have_matching_hashes(self):
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        rows = (self.package / "SHA256SUMS").read_text().splitlines()
        expected = {"./" + p.relative_to(self.package).as_posix()
                    for p in self.package.rglob("*") if p.is_file() and p.name != "SHA256SUMS"}
        entries = dict(row.split("  ", 1)[::-1] for row in rows)
        self.assertEqual(set(entries), expected)
        for filename, digest in entries.items():
            self.assertEqual(digest, hashlib.sha256((self.package / filename).read_bytes()).hexdigest())
        self.assertEqual((self.package / "Library/Extensions/NVRM.kext/Contents/MacOS/NVRM").read_bytes(), b"unchanged RM")
        self.assertEqual((self.package / "Library/Extensions/NVRMAGDC.kext/Contents/MacOS/NVRMAGDC").read_bytes(), b"unchanged AGDC")
        self.assertIn(["verify", self.accel15], self.calls())
        self.assertIn(["verify", self.accel26], self.calls())
        self.assertIn("Ready to archive", result.stdout)

    def test_non_macos_refuses_without_signing(self):
        self.assert_manifest_retained(self.run_script(FAKE_SYSTEM="Linux"))
        self.assertEqual(self.calls(), [])

    def test_missing_accelerator_refuses_before_any_signature_changes(self):
        (self.package / self.accel26 / "Contents/MacOS/NVAccel").unlink()
        self.assert_manifest_retained(self.run_script())
        self.assertEqual(self.calls(), [])

    def test_signing_failure_does_not_publish_a_new_manifest(self):
        self.assert_manifest_retained(self.run_script(FAIL_SIGN=self.translator))
        self.assertEqual(self.calls(), [["sign", self.translator]])

    def test_signature_verification_failure_stops_the_package(self):
        self.assert_manifest_retained(self.run_script(FAIL_VERIFY=self.framebuffer))
        self.assertNotIn(["sign", self.accel26], self.calls())

    def test_hash_failure_keeps_the_old_manifest_and_cleans_candidate(self):
        self.assert_manifest_retained(self.run_script(FAIL_HASH="./payload with spaces.txt"))

    def test_candidate_verification_failure_keeps_the_old_manifest(self):
        self.assert_manifest_retained(self.run_script(FAIL_MANIFEST_VERIFY="1"))

    def create_symlink(self, link, target, directory=False):
        try:
            link.symlink_to(Path(target), target_is_directory=directory)
        except OSError as error:
            self.skipTest("symlinks unavailable: " + str(error))

    def test_bundled_translator_symlink_is_preserved(self):
        link = self.package / self.bundled_translator
        link.unlink()
        self.create_symlink(link, "../../../nvmtl/libnvmtl_translate.dylib")
        result = self.run_script()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(link.is_symlink())
        self.assertNotIn(["sign", self.bundled_translator], self.calls())
        self.assertEqual(link.read_bytes(), (self.package / self.translator).read_bytes())

    def test_bundle_directory_link_cannot_sign_outside_the_package(self):
        original = self.package / "Library/GPUBundles"
        external = self.root / "external bundles"
        original.rename(external)
        self.create_symlink(original, external, directory=True)
        self.assert_manifest_retained(self.run_script())
        self.assertEqual(self.calls(), [])
        self.assertEqual((external / "nvmtl/libnvmtl_translate.dylib").read_bytes(), b"fixture translator")


if __name__ == "__main__":
    unittest.main(verbosity=2)
