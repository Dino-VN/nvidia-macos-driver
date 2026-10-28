#!/usr/bin/env python3
"""Run the native GLD installer against a private filesystem with mocked kernel tools."""
import hashlib
from pathlib import Path
import plistlib
import struct
import unittest

from primary_install_fixture import Install


class NativeGLDInstall(Install):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # Runtime qualification is mocked, as in the shared installer fixture.
        cls.guard.write_text(cls.guard.read_text().replace(
            '*.dylib)', '*.dylib|*/Contents/MacOS/DinoZinkGLDriver)'))

    def setUp(self):
        super().setUp()
        self.env['FAKE_OS_VERSION'] = '26.7.1'
        for relative in ('Library/Extensions/NVAccel.kext',
                         'Library/NullMoth/kexts/26/NVAccel.kext'):
            info = self.payload / relative / 'Contents/Info.plist'
            data = plistlib.loads(info.read_bytes()) if info.exists() else {}
            data['IOKitPersonalities'] = {'NVAccel': {'IOGLBundleName': 'DinoZinkGLDriver'}}
            info.write_bytes(plistlib.dumps(data))
        self.gld_info = self.payload / 'Library/GPUBundles/DinoZinkGLDriver.bundle/Contents/Info.plist'
        self.gld_info.parent.mkdir(parents=True)
        self.gld_info.write_bytes(plistlib.dumps({'DinoVerifiedOSBuild': '25G241'}))
        binary = self.gld_info.parent / 'MacOS/DinoZinkGLDriver'
        binary.parent.mkdir()
        load = struct.pack('<6I', 0x32, 24, 1, 0x000f0500, 0x000f0500, 0)
        self.new_gld = struct.pack('<8I', 0xfeedfacf, 0x01000007, 3, 8, 1, len(load), 0, 0) + load
        binary.write_bytes(self.new_gld)
        probe = self.payload / 'Library/GPUBundles/nvmtl/gld_bundle_probe'
        probe.write_text('#!/bin/bash\n[ "$1" = DinoZinkGLDriver ] || exit 2\n'
                         '[ "${FAKE_GLD_LOOKUP_FAIL:-0}" != 1 ]\n')
        probe.chmod(0o755)
        old = self.root / 'Library/GPUBundles/DinoZinkGLDriver.bundle/Contents/MacOS/DinoZinkGLDriver'
        old.parent.mkdir(parents=True)
        old.write_bytes(b'old-native-gld')
        self.old[old] = old.read_bytes()
        for rel in ('Library/Extensions/NVAccel.kext/Contents/Info.plist',
                    'Library/NullMoth/kexts/26/NVAccel.kext/Contents/Info.plist'):
            info = self.root / rel
            info.parent.mkdir(parents=True, exist_ok=True)
            info.write_bytes(plistlib.dumps({'IOKitPersonalities': {
                'NVAccel': {'IOGLBundleName': 'AppleMetalOpenGLRenderer'}}}))
            self.old[info] = info.read_bytes()
        self.refresh_manifest()

    def refresh_manifest(self):
        rows = [hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + str(p.relative_to(self.payload))
                for p in self.payload.rglob('*') if p.is_file() and p.name != 'SHA256SUMS']
        (self.payload / 'SHA256SUMS').write_text('\n'.join(rows) + '\n')

    def test_complete_native_install_and_boot_fallback(self):
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_creates(2)
        binary = self.root / 'Library/GPUBundles/DinoZinkGLDriver.bundle/Contents/MacOS/DinoZinkGLDriver'
        self.assertEqual(binary.read_bytes(), self.new_gld)
        self.assertEqual(binary.stat().st_mode & 0o022, 0)
        for relative in ('Library/Extensions/NVAccel.kext', 'Library/NullMoth/kexts/26/NVAccel.kext'):
            data = plistlib.loads((self.root / relative / 'Contents/Info.plist').read_bytes())
            self.assertEqual(data['IOKitPersonalities']['NVAccel']['IOGLBundleName'], 'DinoZinkGLDriver')
        data = plistlib.loads((self.root / 'Library/NullMoth/kexts/15/NVAccel.kext/Contents/Info.plist').read_bytes())
        self.assertNotEqual(data.get('IOKitPersonalities', {}).get('NVAccel', {}).get('IOGLBundleName'), 'DinoZinkGLDriver')
        self.assertIn('DinoZinkGLDriver.bundle', (self.root / 'Library/NullMoth/lastgood.sh').read_text())

    def test_lookup_failure_restores_plugin_runtime_personalities_and_collection(self):
        result = self.run_install(FAKE_GLD_LOOKUP_FAIL='1')
        self.assert_restored(result)
        self.assertIn('does not trust the installed OpenGL bundle', result.stdout + result.stderr)
        self.assert_creates(1)

    def test_late_collection_failure_restores_native_installation(self):
        result = self.run_install(FAKE_LIVE_FAIL='1')
        self.assert_restored(result)
        self.assert_creates(2)

    def test_first_native_install_failure_removes_new_plugin(self):
        import shutil
        plugin = self.root / 'Library/GPUBundles/DinoZinkGLDriver.bundle'
        self.old = {p: data for p, data in self.old.items() if not p.is_relative_to(plugin)}
        shutil.rmtree(plugin)
        self.assert_restored(self.run_install(FAKE_GLD_LOOKUP_FAIL='1'))
        self.assertFalse(plugin.exists())

    def test_other_build_is_rejected_before_live_replacement(self):
        self.gld_info.write_bytes(plistlib.dumps({'DinoVerifiedOSBuild': '25H999'}))
        self.refresh_manifest()
        result = self.run_install()
        self.assert_restored(result)
        self.assertIn('requires macOS build 25H999', result.stdout + result.stderr)
        self.assertFalse((self.root / 'creates').exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
