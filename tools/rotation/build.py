#!/usr/bin/env python3
"""Build the fork's rotation framebuffer and timed controller. Never installs or signs a kext."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import plistlib
import subprocess
import time

root = Path(__file__).resolve().parents[2]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--ogkm', type=Path, default=Path.home() / 'ogkm615')
parser.add_argument('--output', type=Path, required=True)
parser.add_argument('--package-base', type=Path, help='Read matching release metadata from this existing package')
args = parser.parse_args()
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=False)
ogkm = args.ogkm.resolve()
sdk = Path(subprocess.check_output(['xcrun', '--show-sdk-path'], text=True).strip())
kernel_headers = sdk / 'System/Library/Frameworks/Kernel.framework/Headers'
fb = root / 'kexts/NVRMFB'
includes = [kernel_headers, fb, fb / 'fb']
includes += [ogkm / name for name in [
    'src/nvidia/arch/nvalloc/unix/include', 'src/nvidia/arch/nvalloc/common/inc',
    'src/nvidia/arch/nvalloc/common/inc/gsp', 'src/common/sdk/nvidia/inc',
    'src/common/sdk/nvidia/inc/hw', 'src/common/inc', 'src/common/shared/inc',
    'src/nvidia/inc', 'src/nvidia/inc/os', 'src/nvidia/inc/kernel', 'src/nvidia/kernel/inc',
    'src/nvidia/interface', 'src/common/nvlink/interface', 'src/common/inc/swref',
    'src/common/inc/swref/published', 'src/nvidia/inc/libraries', 'src/nvidia/src/libraries',
    'src/nvidia/generated', 'src/nvidia/src/mm/uvm/interface',
    'src/common/uproc/os/libos-v2.0.0/include', 'src/common/uproc/os/common/include',
    'src/common/inc/displayport', 'src/common/nvlink/inband/interface',
    'src/nvidia-modeset/os-interface/include', 'src/nvidia-modeset/kapi/interface',
    'src/nvidia-modeset/kapi/include', 'src/common/unix/nvidia-push/interface',
    'src/nvidia-modeset/interface', 'src/nvidia-modeset/include',
    'src/common/unix/common/inc', 'src/common/modeset', 'src/common/unix/common/utils/interface']]

bundle = output / 'NVRMFB.kext'
(bundle / 'Contents/MacOS').mkdir(parents=True)
obj = output / 'nvrm-fb.o'
cflags = ['-arch', 'x86_64', '-mmacosx-version-min=15.0', '-fapple-kext', '-mkernel',
          '-nostdinc', '-DKERNEL', '-DKERNEL_PRIVATE', '-DDRIVER_PRIVATE', '-DAPPLE', '-DNeXT',
          '-std=c++17', '-fno-rtti', '-fno-exceptions', '-fno-builtin', '-fno-common',
          '-Wall', '-Wno-unused-parameter', '-Wno-inconsistent-missing-override', '-Wno-unused-function', '-O2']
common = ['-arch', 'x86_64', '-mmacosx-version-min=15.0', '-std=c++17', '-O2', '-Wall', '-Wextra']
commands = {
    'framebuffer-compile': ['xcrun', 'clang++', *cflags, *['-I' + str(p) for p in includes],
                            '-c', str(fb / 'fb/nvrm-fb.cpp'), '-o', str(obj)],
    'framebuffer-link': ['xcrun', 'clang++', '-arch', 'x86_64', '-mmacosx-version-min=15.0',
                         '-fapple-kext', '-nostdlib', '-Xlinker', '-kext', '-lkmodc++', '-lkmod',
                         '-lcc_kext', str(obj), '-o', str(bundle / 'Contents/MacOS/NVRMFB')],
    'protocol-test': ['xcrun', 'clang++', *common, '-Werror', '-fsanitize=address,undefined',
                       str(root / 'tools/rotation/protocol_test.cpp'), '-o', str(output / 'protocol-test')],
    'control': ['xcrun', 'clang++', *common, '-fobjc-arc', str(root / 'tools/rotation/control.mm'),
                 '-framework', 'Foundation', '-framework', 'CoreGraphics', '-framework', 'IOKit',
                 '-o', str(output / 'nv-rotate')],
    'copy-test': ['xcrun', 'clang++', *common, '-Werror', '-fsanitize=address,undefined',
                    str(root / 'tools/rotation/copy_test.cpp'), '-o', str(output / 'copy-test')],
    'cursor-map-test': ['xcrun', 'clang++', *common, '-Werror', '-fsanitize=address,undefined',
                    str(root / 'tools/rotation/cursor_map_test.cpp'), '-o', str(output / 'cursor-map-test')],
    'copy-bench': ['xcrun', 'clang++', *common, '-Werror',
                     str(root / 'tools/rotation/copy_bench.cpp'), '-o', str(output / 'copy-bench')],
    'source-probe-test': ['xcrun', 'clang++', *common, '-Werror', '-Wno-missing-field-initializers', '-fsanitize=address,undefined',
                    str(root / 'tools/rotation/source_probe_test.cpp'), '-o', str(output / 'source-probe-test')],
    'resolution-test': ['xcrun', 'clang++', *common, '-Werror', '-fsanitize=address,undefined',
                    str(root / 'tools/rotation/resolution_test.cpp'), '-o', str(output / 'resolution-test')],
    'physical-plane-test': ['xcrun', 'clang++', *common, '-Werror', '-fsanitize=address,undefined',
                    str(root / 'tools/rotation/physical_plane_test.cpp'), '-o', str(output / 'physical-plane-test')],
}
(output / 'COMMANDS.json').write_text(json.dumps(commands, indent=2) + '\n')
results = {}
for name, cmd in commands.items():
    start = time.monotonic()
    with (output / (name + '.log')).open('w') as log:
        p = subprocess.run(['nice', '-n', '10', *cmd], cwd=root, stdout=log, stderr=subprocess.STDOUT, timeout=120)
    results[name] = {'exit_code': p.returncode, 'seconds': round(time.monotonic() - start, 3)}
    print(name, results[name], flush=True)
    (output / 'BUILD.json').write_text(json.dumps(results, indent=2) + '\n')
    if p.returncode:
        print((output / (name + '.log')).read_text()[-7000:])
        raise SystemExit(p.returncode)

template = fb / 'fb/Info.plist'
if args.package_base:
    template = args.package_base / 'Library/Extensions/NVRMFB.kext/Contents/Info.plist'
info = plistlib.loads(template.read_bytes())
assert info['CFBundleIdentifier'] == 'com.nullmoth.NVRMFB'
assert info['IOKitPersonalities']['NVRMFB']['IOClass'] == 'NVRMNVDAFramebuffer'
info['IOKitPersonalities']['NVRMFB']['NVRMRotationPrototype'] = True
(bundle / 'Contents/Info.plist').write_bytes(plistlib.dumps(info, sort_keys=False))

files = [p for p in (root / 'kexts/NVRMFB').rglob('*') if p.is_file()]
files += [p for p in (root / 'tools/rotation').rglob('*') if p.is_file()]
files += [p for p in (root / 'kexts/NVRM/accel').rglob('*') if p.is_file()]
hashes = {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files
          if '__pycache__' not in p.parts and p.suffix != '.pyc'}
(output / 'SOURCE-HASHES.json').write_text(json.dumps(hashes, indent=2) + '\n')
artifacts = {}
for p in [bundle / 'Contents/MacOS/NVRMFB', output / 'nv-rotate', output / 'protocol-test', output / 'resolution-test', output / 'copy-test', output / 'cursor-map-test', output / 'copy-bench', output / 'source-probe-test', output / 'physical-plane-test']:
    artifacts[p.name] = {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest(),
                         'uuid': subprocess.check_output(['dwarfdump', '--uuid', str(p)], text=True).split()[1]}
(output / 'ARTIFACTS.json').write_text(json.dumps(artifacts, indent=2) + '\n')
print('Built rotation framebuffer; no installation, package staging, signing or display change performed.', flush=True)
