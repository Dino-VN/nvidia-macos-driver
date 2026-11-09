#!/usr/bin/env python3
"""Check CGL-only staging on real files; platform signing commands are mocked."""
import errno
import json
import os
from pathlib import Path
import plistlib
import shutil
import sys
import tarfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'build'))
sys.path.insert(0, str(ROOT / 'tools'))
import restage_cgl as pkg
from record_zink_runtime import record
import test_package_zink as fixtures


class CGLRestageTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.PackageZinkTests()
        self.fixture.setUp()
        f = self.fixture
        self.base, self.runtime, self.output = f.base, f.zink, f.out
        self.records = f.root / 'build-records'
        self.dirty = ''
        f.put(self.base / 'VERSION', b'2.8\n')
        for relative in ('Library/Extensions/NVAccel.kext',
                         'Library/NullMoth/kexts/15/NVAccel.kext',
                         'Library/NullMoth/kexts/26/NVAccel.kext'):
            path = self.base / relative / 'Contents/Info.plist'
            data = plistlib.loads(path.read_bytes())
            data['IOKitPersonalities'] = {'NVAccel': {'IOGLBundleName': 'NVKZinkGLDriver'}}
            path.write_bytes(plistlib.dumps(data))
        f.bundle(self.base / 'Optional/NMIntelFB.kext', 'NMIntelFB')
        f.bundle(self.base / 'Optional/NMXAudio.kext', 'NMXAudio')
        f.bundle(self.runtime / 'NVKZinkGLDriver.bundle', 'NVKZinkGLDriver')
        info = self.runtime / 'NVKZinkGLDriver.bundle/Contents/Info.plist'
        data = plistlib.loads(info.read_bytes())
        data.update(NVKZinkExperimentalGLD=True, NVKZinkBuildOS='25G241')
        info.write_bytes(plistlib.dumps(data))
        f.put(self.runtime / 'gld_bundle_probe', b'gld probe')
        f.put(self.runtime / 'nvk_icd.json', json.dumps({
            'ICD': {'library_path': './libnvk_renderer.dylib', 'api_version': '1.4.363'}}).encode())
        record(self.runtime, 'gld')
        shutil.copytree(self.runtime, self.base / pkg.RUNTIME)
        shutil.copytree(self.runtime / 'NVKZinkGLDriver.bundle', self.base / pkg.GLD)
        # The native bundle belongs at GPUBundles, not inside the old runtime.
        shutil.rmtree(self.base / pkg.RUNTIME / 'NVKZinkGLDriver.bundle')
        for name in pkg.BUNDLED_SOURCES:
            f.put(self.base / pkg.RUNTIME / 'zink-source' / Path(name).name, ('old ' + name).encode())
        f.put(self.base / 'Guides/Zink-OpenGL.md', b'old guide')
        f.put(self.base / pkg.BASE_RUNTIME / 'wine/lib/dxvk/d3d11.dll', b'matched d3d11')
        f.put(self.base / pkg.BASE_RUNTIME / 'wine/lib/dxvk/dxgi.dll', b'matched dxgi')
        f.put(self.base / 'Library/GPUBundles/NVIDIAShared.bundle/Contents/Resources/sass/seed', b'signed shader seed')
        f.put(self.base / 'PACKAGE-IDENTITY.json', json.dumps({
            'source_commit': 'b' * 40, 'binary_source_commit': 'c' * 40,
            'package_version': '2.8', 'release_tag': 'v2.8-nvk',
            'runtime_minimum_macos': '15.5', 'native_cgl_macos_majors': ['15', '26'],
            'optional_native_dlss': {'bundled_tools': True, 'default': 'No'},
        }).encode())
        f.put(self.runtime / 'libnvk_cgl.dylib', b'new CGL executable')
        record(self.runtime, 'cgl')
        pkg.integrity.write_manifest(self.base)
        self.refresh_snapshots()

    def tearDown(self):
        self.fixture.tearDown()

    def refresh_snapshots(self):
        self.fixture.original = self.fixture.snapshot(self.base)
        self.fixture.zink_original = self.fixture.snapshot(self.runtime)

    def fake_run(self, *args):
        self.fixture.commands.append(tuple(str(a) for a in args))
        if args[0] == 'git':
            return self.dirty if 'status' in args else 'a' * 40 + '\n'
        if args[0] == 'otool':
            return '0000000000000000 aabbccdd\n' if '-X' in args else (
                'cmd LC_RPATH\n cmdsize 40\n path /temporary/build (offset 12)\n')
        return ''

    def stage(self, version='2.8.1'):
        with patch.object(pkg, 'run', side_effect=self.fake_run):
            return pkg.stage(self.base, self.runtime, self.output, self.records, version)

    def unchanged(self):
        self.fixture.unchanged()
        self.assertFalse(list(self.fixture.root.rglob('.cgl-restage-*')))
        self.assertFalse(list(self.fixture.root.rglob('.cgl-records-*')))

    def edit_record(self, change):
        path = self.runtime / 'ZINK-BUILD.json'
        data = json.loads(path.read_text())
        change(data)
        path.write_text(json.dumps(data))
        self.refresh_snapshots()

    def test_stage_preserves_all_kernels_provider_and_signed_resources(self):
        kernels = pkg.kernel_snapshot(self.base)
        self.stage()
        self.assertEqual(pkg.kernel_snapshot(self.output), kernels)
        for name in ('libnvk_zink.dylib', 'libnvk_renderer.dylib', 'libnvk_zink_vulkan.dylib'):
            self.assertEqual((self.base / pkg.RUNTIME / name).read_bytes(), (self.output / pkg.RUNTIME / name).read_bytes())
        for name in ('d3d11.dll', 'dxgi.dll'):
            path = pkg.BASE_RUNTIME / 'wine/lib/dxvk' / name
            self.assertEqual((self.base / path).read_bytes(), (self.output / path).read_bytes())
        seed = Path('Library/GPUBundles/NVIDIAShared.bundle/Contents/Resources/sass/seed')
        self.assertEqual((self.output / seed).read_bytes(), b'signed shader seed')
        self.assertEqual((self.output / 'VERSION').read_text(), '2.8.1\n')
        identity = json.loads((self.output / 'PACKAGE-IDENTITY.json').read_text())
        self.assertEqual(identity['source_commit'], 'a' * 40)
        self.assertEqual(identity['binary_source_commit'], 'c' * 40)
        self.assertEqual(identity['optional_native_dlss'], {'bundled_tools': True, 'default': 'No'})
        self.assertTrue(identity['optional_intel_panel']['bundled'])
        self.assertTrue(identity['optional_audio']['bundled'])
        self.assertEqual(identity['optional_audio']['default'], 'No')
        self.assertFalse(any(command[0] == '/bin/bash' for command in self.fixture.commands))
        self.assertFalse(any('codesign' == command[0] and '.kext' in ' '.join(command) for command in self.fixture.commands))
        pkg.integrity.verify_manifest(self.output)
        self.unchanged()

    def test_replacement_unlinks_leaf_without_overwriting_other_runtime(self):
        leaf = self.base / pkg.RUNTIME / 'libnvk_cgl.dylib'
        leaf.unlink()
        leaf.symlink_to('libnvk_zink.dylib')
        pkg.integrity.write_manifest(self.base)
        self.refresh_snapshots()
        original = (self.base / pkg.RUNTIME / 'libnvk_zink.dylib').read_bytes()
        self.stage()
        self.assertFalse((self.output / pkg.RUNTIME / 'libnvk_cgl.dylib').is_symlink())
        self.assertEqual((self.output / pkg.RUNTIME / 'libnvk_cgl.dylib').read_bytes(), b'new CGL executable')
        self.assertEqual((self.output / pkg.RUNTIME / 'libnvk_zink.dylib').read_bytes(), original)
        self.unchanged()

    def test_rejects_symlinked_replacement_directory(self):
        source = self.base / pkg.RUNTIME / 'zink-source'
        source.rename(source.with_name('source-redirect'))
        source.symlink_to('source-redirect')
        pkg.integrity.write_manifest(self.base)
        self.refresh_snapshots()
        with self.assertRaisesRegex(ValueError, 'replacement directory'):
            self.stage()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.records.exists())
        self.unchanged()

    def test_refreshes_all_bundled_replacement_source_hashes(self):
        self.stage()
        identity = json.loads((self.output / pkg.RUNTIME / 'ZINK-BUILD.json').read_text())
        for component in ('cgl', 'gld'):
            for source, expected in identity['components'][component]['source_files'].items():
                if source in pkg.BUNDLED_SOURCES:
                    with self.subTest(source=source):
                        path = self.output / pkg.RUNTIME / 'zink-source' / Path(source).name
                        self.assertEqual(pkg.integrity.digest(path), expected)
        self.unchanged()

    def test_rejects_unlisted_reused_file(self):
        self.fixture.put(self.base / pkg.BASE_RUNTIME / 'wine/unlisted.dll', b'unverified runtime')
        self.refresh_snapshots()
        with self.assertRaisesRegex(ValueError, 'incomplete base manifest coverage'):
            self.stage()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.records.exists())
        self.unchanged()

    def test_rejects_omitted_reused_file_checksum(self):
        manifest = self.base / 'SHA256SUMS'
        lines = manifest.read_text().splitlines(keepends=True)
        manifest.write_text(''.join(line for line in lines if not line.endswith('/libnvk_zink.dylib\n')))
        self.refresh_snapshots()
        with self.assertRaisesRegex(ValueError, 'incomplete base manifest coverage'):
            self.stage()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.records.exists())
        self.unchanged()

    def test_rejects_normalized_duplicate_checksum_path(self):
        manifest = self.base / 'SHA256SUMS'
        rows = manifest.read_text()
        manifest.write_text(rows + rows.splitlines(keepends=True)[0].replace('./', '', 1))
        self.refresh_snapshots()
        with self.assertRaisesRegex(ValueError, 'duplicate checksum path'):
            self.stage()
        self.assertFalse(self.output.exists())
        self.unchanged()

    def test_build_records_are_prepared_on_their_destination_filesystem(self):
        self.output = self.fixture.root / 'stage-volume/pkgroot'
        self.records = self.fixture.root / 'records-volume/build-records'
        rename = os.rename

        def local_rename(source, destination, *args, **kwargs):
            if Path(destination) == self.records and not pkg.integrity.inside(Path(source), self.records.parent):
                raise OSError(errno.EXDEV, 'cross-device rename')
            return rename(source, destination, *args, **kwargs)

        with patch.object(pkg.os, 'rename', side_effect=local_rename):
            self.stage()
        self.assertTrue(self.output.is_dir())
        self.assertTrue(self.records.is_dir())
        self.unchanged()

    def test_payload_publication_failure_removes_published_records(self):
        rename = os.rename

        def fail_output(source, destination, *args, **kwargs):
            if Path(destination) == self.output:
                raise OSError('payload publication failed')
            return rename(source, destination, *args, **kwargs)

        with patch.object(pkg.os, 'rename', side_effect=fail_output):
            with self.assertRaisesRegex(OSError, 'payload publication failed'):
                self.stage()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.records.exists())
        self.unchanged()

    def test_rejects_changed_source_identity_without_output(self):
        self.edit_record(lambda data: data['components']['cgl']['source_files'].update({'build/generate_cgl_dispatch.py': '0' * 64}))
        with self.assertRaisesRegex(ValueError, 'component source mismatch'):
            self.stage()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.records.exists())
        self.unchanged()

    def test_rejects_changed_binary_after_recording(self):
        (self.runtime / 'libnvk_cgl.dylib').write_bytes(b'not the recorded build')
        self.refresh_snapshots()
        with self.assertRaisesRegex(ValueError, 'component file mismatch'):
            self.stage()
        self.assertFalse(self.output.exists())
        self.unchanged()

    def test_rejects_mesa_changes_even_with_fresh_hashes(self):
        (self.runtime / 'libnvk_zink.dylib').write_bytes(b'different Mesa')
        self.edit_record(lambda data: data['components']['zink']['files'].update({
            'libnvk_zink.dylib': pkg.integrity.digest(self.runtime / 'libnvk_zink.dylib')}))
        with self.assertRaisesRegex(ValueError, 'reused runtime input'):
            self.stage()
        self.assertFalse(self.output.exists())
        self.unchanged()

    def test_rejects_diagnostic_gld(self):
        path = self.runtime / 'NVKZinkGLDriver.bundle/Contents/Info.plist'
        data = plistlib.loads(path.read_bytes())
        data['NVKZinkDiagnosticOnly'] = True
        path.write_bytes(plistlib.dumps(data))
        record(self.runtime, 'gld')
        self.refresh_snapshots()
        with self.assertRaisesRegex(ValueError, 'diagnostic GLD'):
            self.stage()
        self.assertFalse(self.output.exists())
        self.unchanged()

    def test_rejects_base_that_would_require_changing_accelerator_metadata(self):
        path = self.base / 'Library/NullMoth/kexts/15/NVAccel.kext/Contents/Info.plist'
        data = plistlib.loads(path.read_bytes())
        data['IOKitPersonalities']['NVAccel']['IOGLBundleName'] = 'AppleMetalOpenGLRenderer'
        path.write_bytes(plistlib.dumps(data))
        pkg.integrity.write_manifest(self.base)
        self.refresh_snapshots()
        with self.assertRaisesRegex(ValueError, 'already select'):
            self.stage()
        self.assertFalse(self.output.exists())
        self.unchanged()

    def test_existing_records_are_not_overwritten(self):
        self.records.write_bytes(b'keep this output')
        with self.assertRaisesRegex(ValueError, 'output already exists'):
            self.stage()
        self.assertEqual(self.records.read_bytes(), b'keep this output')
        self.assertFalse(self.output.exists())
        self.unchanged()

    def test_requires_committed_source_and_new_revision(self):
        self.dirty = ' M build/generate_cgl_dispatch.py\n'
        with self.assertRaisesRegex(ValueError, 'commit source'):
            self.stage()
        self.dirty = ''
        with self.assertRaisesRegex(ValueError, 'new package revision'):
            self.stage(version='2.8')
        with self.assertRaisesRegex(ValueError, 'invalid package version'):
            self.stage(version='2.8.1-test')
        self.assertFalse(self.output.exists())
        self.unchanged()

    def test_kernel_invariant_failure_removes_private_staging(self):
        original = pkg.kernel_snapshot(self.base)
        with patch.object(pkg, 'kernel_snapshot', side_effect=[original, {'changed': True}]):
            with self.assertRaisesRegex(ValueError, 'changed a kernel bundle'):
                self.stage()
        self.assertFalse(self.output.exists())
        self.assertFalse(self.records.exists())
        self.unchanged()

    def test_archive_has_only_pkgroot_and_excludes_finder_metadata(self):
        self.fixture.put(self.base / '.DS_Store', b'finder metadata')
        self.refresh_snapshots()
        archive = self.fixture.root / 'nvidia-macos-driver-2.8.1-nvk.tar.gz'
        argv = ['restage_cgl.py', '--base', str(self.base), '--runtime', str(self.runtime),
                '--stage', str(self.output), '--build-records', str(self.records),
                '--version', '2.8.1', '--archive', str(archive)]
        with patch.object(pkg, 'run', side_effect=self.fake_run), patch.object(sys, 'argv', argv):
            pkg.main()
        with tarfile.open(archive, 'r:gz') as tar:
            names = [member.name for member in tar]
        self.assertTrue(all(name == 'pkgroot' or name.startswith('pkgroot/') for name in names))
        self.assertFalse(any(Path(name).name == '.DS_Store' or Path(name).name.startswith('._') for name in names))
        self.unchanged()

    def test_archive_inside_payload_is_refused_before_staging(self):
        archive = self.output / 'nvidia-macos-driver-2.8.1-nvk.tar.gz'
        argv = ['restage_cgl.py', '--base', str(self.base), '--runtime', str(self.runtime),
                '--stage', str(self.output), '--build-records', str(self.records),
                '--version', '2.8.1', '--archive', str(archive)]
        with patch.object(sys, 'argv', argv):
            with self.assertRaisesRegex(ValueError, 'outside the inputs'):
                pkg.main()
        self.assertFalse(self.output.exists())
        self.unchanged()


if __name__ == '__main__':
    unittest.main()
