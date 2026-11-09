#!/usr/bin/env python3
"""Restage a verified Zink driver with a CGL-only update, preserving kernel bytes."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import tarfile
import tempfile

import stage_package as integrity
from package_layout import organize
from package_zink import BASE_RUNTIME, RUNTIME, archive_identity, copy_bundle, run
from prepare_zink import MESA_COMMIT
from record_zink_runtime import COMPONENTS

ROOT = Path(__file__).resolve().parents[1]
GLD = Path('Library/GPUBundles/NVKZinkGLDriver.bundle')
BUNDLED_SOURCES = sorted({name for component in ('cgl', 'gld')
                          for name in COMPONENTS[component][1]
                          if Path(name).parts[0] in ('zink', 'build')})


def ignored_payload_path(relative):
    """Mirror copy_bundle's Finder metadata and unsealed transient-cache filter."""
    sealed = any(part.endswith(('.bundle', '.framework')) for part in relative.parts)
    return any(part == '.DS_Store' or part.startswith('._') or
               (not sealed and part in ('sass', 'aircache', 'spvcache'))
               for part in relative.parts)


def verify_complete_manifest(root):
    integrity.verify_manifest(root)
    covered = set()
    for row in (root / 'SHA256SUMS').read_text(encoding='utf-8').splitlines():
        if not row or row.startswith('#'):
            continue
        escaped = row.startswith('\\')
        match = re.fullmatch(r'([0-9a-fA-F]{64}) [ *](.+)', row[1:] if escaped else row)
        name = integrity.decode_name(match[2]) if escaped else match[2]
        relative = Path(name)
        integrity.regular(root / relative)
        integrity.require(relative not in covered, 'duplicate checksum path: ' + name)
        covered.add(relative)
    regular = {path.relative_to(root) for path in root.rglob('*')
               if path.is_file() and not path.is_symlink() and path != root / 'SHA256SUMS'}
    covered = {path for path in covered if not ignored_payload_path(path)}
    regular = {path for path in regular if not ignored_payload_path(path)}
    integrity.require(covered == regular, 'incomplete base manifest coverage: ' +
                      ', '.join(str(path) for path in sorted(covered ^ regular)))


def real_directory(root, relative):
    """Replacement parents must not redirect writes into unrelated components."""
    current = root
    for part in relative.parts:
        current /= part
        integrity.require(current.is_dir() and not current.is_symlink(),
                          'replacement directory is missing or symlinked: ' + str(current))


def kernel_snapshot(root):
    """Include optional bundles, OS variants, resources and internal links."""
    result = {}
    for bundle in sorted(root.rglob('*.kext')):
        for path in sorted(bundle.rglob('*')):
            key = path.relative_to(root).as_posix()
            if path.is_symlink():
                result[key] = ('link', os.readlink(path))
            elif path.is_file():
                result[key] = ('file', integrity.digest(path), path.stat().st_mode & 0o777)
    return result


def validate_inputs(base, runtime):
    integrity.validate_links(base)
    verify_complete_manifest(base)
    for relative in (RUNTIME, RUNTIME / 'zink-source', GLD / 'Contents/MacOS'):
        real_directory(base, relative)
    real_directory(runtime, Path('NVKZinkGLDriver.bundle/Contents/MacOS'))
    integrity.regular(base / 'PACKAGE-IDENTITY.json')
    integrity.regular(base / RUNTIME / 'ZINK-BUILD.json')
    previous = json.loads((base / 'PACKAGE-IDENTITY.json').read_text())
    for name in ('install.sh', 'uninstall.sh', 'nullmoth-runtime-check.sh', 'nullmoth-runtime-check', 'VERSION'):
        integrity.regular(base / name)
    integrity.require(previous.get('package_version') == (base / 'VERSION').read_text().strip(),
                      'base package version identity differs')
    for name in ('NVRM', 'NVRMFB', 'NVRMAGDC', 'NVAccel'):
        integrity.bundle(base / 'Library/Extensions' / (name + '.kext'), name)
    for name in ('NVMTLDriver', 'NVIDIAShared'):
        integrity.bundle(base / 'Library/GPUBundles' / (name + '.bundle'), name)
    identity = json.loads((runtime / 'ZINK-BUILD.json').read_text())
    integrity.validate_links(runtime)
    integrity.bundle(runtime / 'NVKZinkGLDriver.bundle', 'NVKZinkGLDriver')
    for component in ('zink', 'cgl', 'gld'):
        item = identity.get('components', {}).get(component, {})
        files, sources = COMPONENTS[component]
        for name in files:
            integrity.regular(runtime / name)
            integrity.require(item.get('files', {}).get(name) == integrity.digest(runtime / name),
                              'component file mismatch: ' + name)
        for name in sources:
            integrity.require(item.get('source_files', {}).get(name) == integrity.digest(ROOT / name),
                              'component source mismatch: ' + name)
    mesa = identity['components']['zink'].get('mesa_source', {})
    integrity.require(mesa.get('commit') == MESA_COMMIT and
                      mesa.get('overlay_sha256') == integrity.digest(ROOT / 'zink/mesa-zink-nvk.patch'),
                      'unverified Mesa source identity')
    # This mode cannot update Mesa, its API metadata, or the private NVK pair.
    for name in (*COMPONENTS['zink'][0], 'libnvk_renderer.dylib',
                 'libnvk_zink_vulkan.dylib', 'NATIVE-BUILD.json', 'nvk_icd.json'):
        integrity.regular(base / RUNTIME / name)
        integrity.regular(runtime / name)
        integrity.require(integrity.digest(base / RUNTIME / name) == integrity.digest(runtime / name),
                          'CGL-only update changed a reused runtime input: ' + name)
    native = json.loads((runtime / 'NATIVE-BUILD.json').read_text())
    integrity.require(native.get('renderer_original_sha256') == integrity.digest(base / BASE_RUNTIME / 'libvulkan_nouveau.dylib'),
                      'private renderer does not match the driver')
    integrity.require(native.get('frontend_source_sha256') == integrity.digest(ROOT / 'nvk/native-macos/bridge.mm'),
                      'private frontend source mismatch')
    for name in ('plugin/nvmtl_fd_token.h', 'plugin/nvmtl_rebind_import.h'):
        integrity.require(native.get('frontend_headers', {}).get(name) == integrity.digest(ROOT / name),
                          'private frontend header mismatch: ' + name)
    for name in ('libnvk_renderer.dylib', 'libnvk_zink_vulkan.dylib'):
        integrity.require(native.get('files', {}).get(name) == integrity.digest(runtime / name),
                          'private runtime hash mismatch: ' + name)
    for relative in ('Library/Extensions/NVAccel.kext',
                     'Library/NullMoth/kexts/15/NVAccel.kext',
                     'Library/NullMoth/kexts/26/NVAccel.kext'):
        integrity.bundle(base / relative, 'NVAccel')
        info = plistlib.loads((base / relative / 'Contents/Info.plist').read_bytes())
        integrity.require(info.get('IOKitPersonalities', {}).get('NVAccel', {}).get('IOGLBundleName') == 'NVKZinkGLDriver',
                          'base must already select the native Zink GLD: ' + relative)
    info = plistlib.loads((runtime / 'NVKZinkGLDriver.bundle/Contents/Info.plist').read_bytes())
    integrity.require(info.get('NVKZinkExperimentalGLD') and not info.get('NVKZinkDiagnosticOnly'),
                      'diagnostic GLD cannot be packaged')
    integrity.require(info.get('NVKZinkBuildOS') == (runtime / 'cgl-os-build.txt').read_text().strip(),
                      'GLD and CGL build provenance differ')
    run('codesign', '--verify', '--strict', runtime / 'libnvk_cgl.dylib')
    run('codesign', '--verify', '--strict', runtime / 'NVKZinkGLDriver.bundle')
    return previous, identity


def relocate(binary, rpath, bundle=None):
    run('lipo', binary, '-verify_arch', 'x86_64')
    before = run('otool', '-X', '-s', '__TEXT', '__text', binary)
    integrity.require(bool(before.strip()), 'missing machine-code section: ' + str(binary))
    commands = run('otool', '-l', binary)
    paths = re.findall(r'cmd LC_RPATH\n.*?path (.+?) \(offset', commands, re.S)
    for path in paths:
        run('install_name_tool', '-delete_rpath', path, binary)
    run('install_name_tool', '-add_rpath', rpath, binary)
    run('codesign', '--force', '--sign', '-', '--timestamp=none', bundle or binary)
    run('codesign', '--verify', '--strict', bundle or binary)
    integrity.require(before == run('otool', '-X', '-s', '__TEXT', '__text', binary),
                      'machine code changed during relocation: ' + str(binary))


def stage(base, runtime, output, records, version):
    integrity.require(bool(re.fullmatch(r'[0-9]+(?:\.[0-9]+){1,3}', version)), 'invalid package version')
    base, runtime = Path(base).resolve(strict=True), Path(runtime).resolve(strict=True)
    output, records = Path(output).absolute(), Path(records).absolute()
    for destination in (output, records):
        integrity.require(not destination.exists() and not destination.is_symlink(), 'output already exists')
        integrity.require(not integrity.inside(destination.resolve(), base) and
                          not integrity.inside(destination.resolve(), runtime), 'output overlaps an input')
    integrity.require(not integrity.inside(records.resolve(), output.resolve()) and
                      not integrity.inside(output.resolve(), records.resolve()), 'output and build records overlap')
    previous, identity = validate_inputs(base, runtime)
    integrity.require(version != previous.get('package_version'), 'use a new package revision')
    commit = run('git', '-C', ROOT, 'rev-parse', 'HEAD').strip()
    dirty = run('git', '-C', ROOT, 'status', '--porcelain', '--untracked-files=no').strip()
    integrity.require(not dirty, 'commit source changes before release staging')
    original_kernels = kernel_snapshot(base)
    output.parent.mkdir(parents=True, exist_ok=True)
    records.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.cgl-restage-', dir=output.parent) as temporary, \
            tempfile.TemporaryDirectory(prefix='.cgl-records-', dir=records.parent) as record_temporary:
        payload = Path(temporary) / 'pkgroot'
        copy_bundle(base, payload)
        for name in COMPONENTS['cgl'][0]:
            integrity.replace_file(runtime / name, payload / RUNTIME / name)
        copy_bundle(runtime / 'NVKZinkGLDriver.bundle', payload / GLD)
        integrity.replace_file(runtime / 'gld_bundle_probe', payload / RUNTIME / 'gld_bundle_probe')
        relocate(payload / RUNTIME / 'libnvk_cgl.dylib', '@loader_path')
        relocate(payload / GLD / 'Contents/MacOS/NVKZinkGLDriver',
                 '@loader_path/../../../nvmtl/zink', payload / GLD)
        for component in ('cgl', 'gld'):
            item = identity['components'][component]
            item['build_input_files'] = dict(item['files'])
            item['files'] = {name: integrity.digest(payload / ('Library/GPUBundles' if '/' in name else RUNTIME) / name)
                             for name in COMPONENTS[component][0]}
        identity.setdefault('packaging', {}).update(
            source_commit=commit, cgl_producer_commit=commit, gld_producer_commit=commit,
            base_manifest_sha256=integrity.digest(base / 'SHA256SUMS'),
            kernel_bundles_reused_unchanged=True,
            load_paths='runtime local; machine-code sections unchanged after RPATH normalization')
        (payload / RUNTIME / 'ZINK-BUILD.json').write_text(json.dumps(identity, indent=2) + '\n')
        for name in BUNDLED_SOURCES:
            integrity.replace_file(ROOT / name, payload / RUNTIME / 'zink-source' / Path(name).name)
        integrity.replace_file(ROOT / 'docs/ZINK-OPENGL.md', payload / RUNTIME / 'ZINK-OPENGL.md')
        (payload / 'VERSION').write_text(version + '\n')
        detail = dict(previous)
        detail.update(source_commit=commit, source_dirty=False, package_version=version,
                      release_tag='v' + version + '-nvk', native_cgl_source_commit=commit,
                      reused_release=previous.get('release_tag'),
                      base_manifest_sha256=integrity.digest(base / 'SHA256SUMS'),
                      component_builds=identity, kernel_bundles_reused_unchanged=True)
        organized = Path(record_temporary) / 'build-records'
        organize(payload, organized, detail)
        compact_path = payload / 'PACKAGE-IDENTITY.json'
        compact = json.loads(compact_path.read_text())
        for key in ('optional_native_dlss',):
            if key in previous:
                compact[key] = previous[key]
        compact['zink_source_commit'] = previous.get('zink_source_commit', previous.get('source_commit'))
        compact['native_cgl_source_commit'] = commit
        compact['components_sha256'].update({
            str(RUNTIME / 'libnvk_cgl.dylib'): integrity.digest(payload / RUNTIME / 'libnvk_cgl.dylib'),
            str(GLD / 'Contents/MacOS/NVKZinkGLDriver'): integrity.digest(payload / GLD / 'Contents/MacOS/NVKZinkGLDriver')})
        compact_path.write_text(json.dumps(compact, indent=2) + '\n')
        integrity.require(kernel_snapshot(payload) == original_kernels, 'CGL update changed a kernel bundle')
        integrity.validate_links(payload)
        integrity.write_manifest(payload)
        integrity.verify_manifest(payload)
        os.rename(organized, records)
        try:
            os.rename(payload, output)
        except OSError:
            shutil.rmtree(records)
            raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--stage', type=Path, required=True)
    parser.add_argument('--build-records', type=Path, required=True)
    parser.add_argument('--version', required=True)
    parser.add_argument('--archive', type=Path, required=True)
    args = parser.parse_args()
    integrity.require(not args.archive.exists() and not args.archive.is_symlink(), 'archive already exists')
    integrity.require(args.archive.name == f'nvidia-macos-driver-{args.version}-nvk.tar.gz', 'unexpected driver archive name')
    for directory in (args.base, args.runtime, args.stage):
        integrity.require(not integrity.inside(args.archive.absolute().resolve(), directory.absolute().resolve()),
                          'archive must be outside the inputs and pkgroot')
    payload = stage(args.base, args.runtime, args.stage, args.build_records, args.version)
    args.archive.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix='.cgl-archive-', dir=args.archive.parent, delete=False) as temporary:
        temporary_path = Path(temporary.name)
    try:
        with tarfile.open(temporary_path, 'w:gz', compresslevel=6) as archive:
            archive.add(payload, arcname='pkgroot', filter=archive_identity)
        temporary_path.chmod(0o644)
        # Atomic creation, not replacement if another process used this name.
        os.link(temporary_path, args.archive)
    finally:
        temporary_path.unlink(missing_ok=True)
    print(args.archive)
    print(integrity.digest(args.archive))


if __name__ == '__main__':
    main()
