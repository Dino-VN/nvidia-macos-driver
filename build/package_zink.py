#!/usr/bin/env python3
"""Build one complete local driver archive with Zink and native CGL adapters."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import tarfile
import tempfile

import stage_package as base_tools

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = Path('Library/GPUBundles/nvmtl')
ZINK_FILES = ('libdino_zink.dylib', 'libdino_cgl.dylib', 'dino_zink.h', 'dino_cgl.h',
              'zink_probe', 'cgl_renderer_probe', 'cgl_zink_probe', 'cgl_zink_window_probe', 'cgl-os-build.txt')


def run(*args):
    return subprocess.check_output([str(a) for a in args], text=True, stderr=subprocess.STDOUT)


def copy_bundle(source, dest):
    base_tools.validate_links(source.resolve())
    if dest.exists():
        shutil.rmtree(dest)
    # Installed bundles can carry macOS rootless flags. Copy bytes and normal
    # modes; those installation flags do not belong on a user-owned archive.
    for directory, dirs, files in os.walk(source):
        dirs[:] = [n for n in dirs if n not in ('sass', 'aircache', 'spvcache')]
        target = dest / Path(directory).relative_to(source)
        target.mkdir(parents=True, exist_ok=True)
        for name in files:
            if name == '.DS_Store': continue
            src = Path(directory) / name
            dst = target / name
            if src.is_symlink(): dst.symlink_to(os.readlink(src))
            else: copy_file(src, dst)


def copy_file(source, destination):
    if destination.exists() or destination.is_symlink(): destination.unlink()
    shutil.copyfile(source, destination)
    destination.chmod(source.stat().st_mode & 0o777)


def stage(base, zink, output, components=None, native_gld=False):
    base = base.resolve(strict=True)
    zink = zink.resolve(strict=True)
    output = output.absolute()
    if output.exists() or output.is_symlink() or base_tools.inside(output.resolve(), base):
        raise ValueError('Output must be new and outside the base package')
    base_tools.verify_manifest(base)
    base_tools.validate_links(base)
    for name in ('install.sh', 'uninstall.sh', 'nullmoth-runtime-check.sh', 'nullmoth-runtime-check', 'VERSION'):
        base_tools.regular(base / name)
    for name in ('NVRM', 'NVRMFB', 'NVRMAGDC', 'NVAccel'):
        base_tools.bundle(base / 'Library/Extensions' / (name + '.kext'), name)
    for major in ('15', '26'):
        base_tools.bundle(base / 'Library/NullMoth/kexts' / major / 'NVAccel.kext', 'NVAccel')
    for name in ('NVMTLDriver', 'NVIDIAShared'):
        base_tools.bundle(base / 'Library/GPUBundles' / (name + '.bundle'), name)
    for name in ('libvulkan_nouveau.dylib', 'libvulkan.1.4.362.dylib', 'nvk_icd.json'):
        base_tools.regular(base / RUNTIME / name)
    for name in ZINK_FILES:
        base_tools.regular(zink / name)
    if native_gld:
        base_tools.bundle(zink / 'DinoZinkGLDriver.bundle', 'DinoZinkGLDriver')
        info = plistlib.loads((zink / 'DinoZinkGLDriver.bundle/Contents/Info.plist').read_bytes())
        build = (zink / 'cgl-os-build.txt').read_text().strip()
        if info.get('DinoDiagnosticOnly') or not info.get('DinoExperimentalGLD'):
            raise ValueError('A diagnostic GLD cannot be used for native installation')
        if info.get('DinoVerifiedOSBuild') != build or build != '25G241':
            raise ValueError('GLD and CGL verified OS builds differ')
        base_tools.regular(zink / 'gld_bundle_probe')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.zink-package-', dir=output.parent) as temp:
        payload = Path(temp) / 'pkgroot'
        shutil.copytree(base, payload, symlinks=True)
        replacements = {}
        if components:
            components = components.resolve(strict=True)
            for name in ('libvulkan_nouveau.dylib', 'libvulkan.1.4.362.dylib'):
                if base_tools.digest(components / 'GPUBundles/nvmtl' / name) != base_tools.digest(base / RUNTIME / name):
                    raise ValueError('Component runtime differs from the verified base: ' + name)
            for name in ('NVRM', 'NVRMFB', 'NVAccel', 'NVRMAGDC'):
                source = components / 'Extensions' / (name + '.kext')
                base_tools.bundle(source, name)
                run('lipo', source / 'Contents/MacOS' / name, '-verify_arch', 'x86_64')
                relative = Path('Library/Extensions') / source.name
                copy_bundle(source, payload / relative)
                replacements[str(relative)] = base_tools.digest(source / 'Contents/MacOS' / name)
            copy_bundle(components / 'Extensions/NVAccel.kext', payload / 'Library/NullMoth/kexts/26/NVAccel.kext')
            source = components / 'GPUBundles/NVMTLDriver.bundle'
            copy_bundle(source, payload / 'Library/GPUBundles/NVMTLDriver.bundle')
            replacements['NVMTLDriver'] = base_tools.digest(source / 'Contents/MacOS/NVMTLDriver')
            for name in ('libnvmtl_translate.dylib', 'air-opt'):
                copy_file(components / 'GPUBundles/nvmtl' / name, payload / RUNTIME / name)
            version = plistlib.loads((components / 'Extensions/NVRMFB.kext/Contents/Info.plist').read_bytes())['CFBundleVersion']
            if not re.fullmatch(r'[0-9]+(?:\.[0-9]+)+', version):
                raise ValueError('Invalid component version')
            (payload / 'VERSION').write_text(version + '\n')
            run('codesign', '--force', '--sign', '-', payload / 'Library/GPUBundles/NVMTLDriver.bundle')
        # Verify the firmware version from the actual NVRM image, not stale text
        # in release manifests. Every referenced mandatory firmware must exist.
        nvrm_strings = run('strings', payload / 'Library/Extensions/NVRM.kext/Contents/MacOS/NVRM')
        firmware_paths = set(re.findall(r'/Library/NullMoth/nvfw/(nvidia/[^\s]+/(?:gsp|ucodes)_[^\s]+\.bin)', nvrm_strings))
        firmware_paths = {p for p in firmware_paths if '/gsp_log_' not in p}
        if not firmware_paths:
            raise ValueError('Cannot establish NVRM firmware requirements')
        for path in firmware_paths:
            base_tools.regular(payload / 'Users/Shared/nvfw' / path)
        runtime = payload / RUNTIME
        for name in ZINK_FILES:
            shutil.copy2(zink / name, runtime / name)
        if native_gld:
            bundle = payload / 'Library/GPUBundles/DinoZinkGLDriver.bundle'
            copy_bundle(zink / bundle.name, bundle)
            binary = bundle / 'Contents/MacOS/DinoZinkGLDriver'
            run('lipo', binary, '-verify_arch', 'x86_64')
            commands = run('otool', '-l', binary)
            for path in re.findall(r'cmd LC_RPATH\n.*?path (.+?) \(offset', commands, re.S):
                run('install_name_tool', '-delete_rpath', path, binary)
            run('install_name_tool', '-add_rpath', '@loader_path/../../../nvmtl', binary)
            run('codesign', '--force', '--sign', '-', bundle)
            shutil.copy2(zink / 'gld_bundle_probe', runtime / 'gld_bundle_probe')
            for relative in ('Library/Extensions/NVAccel.kext', 'Library/NullMoth/kexts/26/NVAccel.kext'):
                plist = payload / relative / 'Contents/Info.plist'
                data = plistlib.loads(plist.read_bytes())
                data.setdefault('IOKitPersonalities', {}).setdefault('NVAccel', {})['IOGLBundleName'] = 'DinoZinkGLDriver'
                plist.write_bytes(plistlib.dumps(data))
        # The copied ICD must refer to this archive's NVK when testing before
        # installation, and to its neighbour after installation.
        icd = json.loads((runtime / 'nvk_icd.json').read_text())
        icd['ICD']['library_path'] = './libvulkan_nouveau.dylib'
        (runtime / 'nvk_icd.json').write_text(json.dumps(icd, indent=2) + '\n')
        for name in ('libdino_zink.dylib', 'libdino_cgl.dylib'):
            binary = runtime / name
            run('lipo', binary, '-verify_arch', 'x86_64')
            # Keep dlopen resolution within the packaged runtime. A successful
            # probe must not accidentally load the installed Vulkan loader.
            commands = run('otool', '-l', binary)
            paths = re.findall(r'cmd LC_RPATH\n.*?path (.+?) \(offset', commands, re.S)
            for path in paths:
                run('install_name_tool', '-delete_rpath', path, binary)
            run('install_name_tool', '-add_rpath', '@loader_path', binary)
            run('codesign', '--force', '--sign', '-', binary)
        shutil.copy2(ROOT / 'docs/ZINK-OPENGL.md', runtime / 'ZINK-OPENGL.md')
        source_dir = runtime / 'zink-source'
        source_dir.mkdir()
        for name in ('dino_zink.c', 'dino_zink.h', 'dino_cgl.c', 'dino_cgl.h', 'dino_cgl_gld.h',
                     'gld_bridge.c', 'meson.build', 'mesa-zink-nvk.patch'):
            shutil.copy2(ROOT / 'zink' / name, source_dir / name)
        for name in ('build_zink.sh', 'prepare_zink.py', 'build_cgl_zink.sh', 'generate_cgl_dispatch.py',
                     'build_gld_bridge.sh', 'generate_gld_forward.py'):
            shutil.copy2(ROOT / 'build' / name, source_dir / name)
        for name in ('Install.command', 'Uninstall.command', 'Verify.command'):
            shutil.copy2(ROOT / 'package' / name, payload / name)
            (payload / name).chmod(0o755)
        # Use this checkout's installer fixes, preserving its private payload,
        # preflight, backup, rollback and OS accelerator-selection behavior.
        for name in ('install.sh', 'uninstall.sh'):
            shutil.copy2(ROOT / 'package' / name, payload / name)
            (payload / name).chmod(0o755)
        licenses = payload / 'licenses'
        licenses.mkdir(exist_ok=True)
        for source, name in ((ROOT / 'LICENSE', 'NullMoth-LICENSE-PolyForm-Noncommercial-1.0.0.txt'),
                             (ROOT / 'NOTICE', 'NOTICE'), (ROOT / 'translator/LICENSE', 'translator-LICENSE'),
                             (ROOT / 'translator/COPYING', 'translator-COPYING')):
            shutil.copy2(source, licenses / name)
        for source in (ROOT / 'licenses').iterdir():
            if source.is_file(): shutil.copy2(source, licenses / source.name)
        (licenses / 'Dino-Zink-MIT.txt').write_text(
            'Copyright (c) 2026 Dino Zink contributors\n\n' +
            'Permission is hereby granted, free of charge, to any person obtaining a copy of this software '
            'and associated documentation files (the "Software"), to deal in the Software without restriction, '
            'including without limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, '
            'and/or sell copies of the Software, and to permit persons to whom the Software is furnished to do so, '
            'subject to the following conditions:\n\n'
            'The above copyright notice and this permission notice shall be included in all copies or substantial '
            'portions of the Software.\n\nTHE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS '
            'OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR '
            'PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY '
            'CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, '
            'OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.\n')
        identity = {'base': str(base), 'base_manifest_sha256': base_tools.digest(base / 'SHA256SUMS'),
                    'source_commit': run('git', '-C', ROOT, 'rev-parse', 'HEAD').strip(),
                    'component_replacements': replacements, 'firmware': sorted(firmware_paths),
                    'zink_sha256': base_tools.digest(runtime / 'libdino_zink.dylib'),
                    'cgl_sha256': base_tools.digest(runtime / 'libdino_cgl.dylib'),
                    'gld_sha256': (base_tools.digest(payload / 'Library/GPUBundles/DinoZinkGLDriver.bundle/Contents/MacOS/DinoZinkGLDriver')
                                   if native_gld else None),
                    'zink_source_sha256': {p.name: base_tools.digest(p) for p in sorted(source_dir.iterdir()) if p.is_file()},
                    'native_cgl': ('automatic GLD proxy; loader/rendering tested with process-local lookup substitution; installation/reboot untested'
                                   if native_gld else 'explicit application attachment; GLD bundle is not included'),
                    'native_cgl_os_build': (runtime / 'cgl-os-build.txt').read_text().strip()}
        (payload / 'PACKAGE-IDENTITY.json').write_text(json.dumps(identity, indent=2) + '\n')
        shutil.copy2(ROOT / 'docs/COMBINED-INSTALL.md', payload / 'READ-ME.md')
        for major in ('15', '26'):
            plist = plistlib.loads((payload / 'Library/NullMoth/kexts' / major / 'NVAccel.kext/Contents/Info.plist').read_bytes())
            if plist.get('IOKitPersonalities', {}).get('NVAccel', {}).get('IOGLBundleName') == 'DinoZinkGLDriver' and not (native_gld and major == '26'):
                raise ValueError('The incomplete diagnostic GLD must not be activated')
            base_tools.write_manifest(payload / 'Library/NullMoth/kexts' / major)
        names = sorted(p.relative_to(payload).as_posix() for p in payload.rglob('*') if p.is_file() or p.is_symlink())
        (payload / 'MANIFEST.txt').write_text('\n'.join(n for n in names if n != 'SHA256SUMS') + '\n')
        base_tools.validate_links(payload)
        base_tools.write_manifest(payload)
        run('/bin/bash', payload / 'nullmoth-runtime-check.sh', payload, run('sw_vers', '-productVersion').strip())
        os.rename(payload, output)
    return output


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--base', required=True, type=Path)
    ap.add_argument('--zink', required=True, type=Path)
    ap.add_argument('--components', type=Path, help='Explicit matching Library directory containing current driver bundles')
    ap.add_argument('--stage', required=True, type=Path)
    ap.add_argument('--archive', required=True, type=Path)
    ap.add_argument('--native-gld', action='store_true', help='Include and select the verified experimental macOS 25G241 GLD proxy')
    args = ap.parse_args()
    if args.archive.exists(): raise SystemExit('Archive already exists')
    payload = stage(args.base, args.zink, args.stage, args.components, args.native_gld)
    args.archive.parent.mkdir(parents=True, exist_ok=True)
    temporary = args.archive.with_name('.' + args.archive.name + '.tmp')
    try:
        with tarfile.open(temporary, 'w:gz', compresslevel=6) as archive:
            archive.add(payload, arcname='nvidia-zink-installer')
        os.rename(temporary, args.archive)
    finally:
        temporary.unlink(missing_ok=True)
    checksum = base_tools.digest(args.archive)
    args.archive.with_name(args.archive.name + '.sha256').write_text(checksum + '  ' + args.archive.name + '\n')
    print(args.archive)
    print(checksum)


if __name__ == '__main__':
    main()
