#!/usr/bin/env python3
"""Read Apple GLD binaries and registry; never modify or copy the binaries."""
import hashlib
import json
from pathlib import Path
import plistlib
import subprocess
import sys

TARGET = Path('/System/Library/Extensions/AMDRadeonX6000GLDriver.bundle/Contents/MacOS/AMDRadeonX6000GLDriver')
FUNCTIONS = ('gldGetVersion', 'gldInitializeLibrary', 'gldCreateDevice',
             'gldChoosePixelFormat', 'gldDestroyPixelFormat', 'gldGetDeviceString',
             'gldPopulateContextDispatch', 'gldUpdateDispatch',
             'gldPresentFramebufferData', 'gldFlushQueue', 'gldFinishQueue',
             'gldCreateContext', 'gldDestroyContext', 'gldAttachDrawable',
             'gldDestroyDevice')

def run(*args):
    return subprocess.check_output(args, text=True)

def main():
    if len(sys.argv) not in (2, 3):
        raise SystemExit('usage: collect_gld_evidence.py NEW_OUTPUT_DIRECTORY [APPLE_GLD_BINARY]')
    target = Path(sys.argv[2]).resolve() if len(sys.argv) == 3 else TARGET
    out = Path(sys.argv[1]).resolve()
    if out.exists():
        raise SystemExit('choose a new evidence directory')
    if not target.is_file():
        raise SystemExit(f'Apple GLD binary missing: {target}')
    objdump = run('xcrun', '--find', 'llvm-objdump').strip()
    symbols = run('nm', '-an', str(target))
    addresses, names = set(), {}
    for line in symbols.splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        try:
            address = int(parts[0], 16)
        except ValueError:
            continue
        addresses.add(address)
        names[parts[-1]] = address
    addresses = sorted(addresses)
    data = {'binary_path': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
            'macos': run('sw_vers'), 'functions': {},
            'limitations': ['Static disassembly is not runtime call evidence.',
                            'Function end is bounded by the next symbol; aliases or stripped symbols can affect coverage.',
                            'Registry presence does not establish which properties GLEngine requires.']}
    registry = plistlib.loads(subprocess.check_output(['ioreg', '-r', '-c', 'IOAccelerator', '-d', '1', '-a']))
    keys = ('IORegistryEntryName', 'IOClass', 'CFBundleIdentifier', 'IOGLBundleName',
            'IOAccelRevision', 'IOAccelIndex', 'IOAccelTypes', 'MetalPluginName',
            'MetalPluginClassName', 'IOPCIPrimaryMatch', 'AccelCaps')
    data['accelerators'] = [{k: n[k] for k in keys if k in n} for n in registry]
    out.mkdir(parents=True)
    for command, file in ((('otool', '-L'), 'dependencies.txt'),
                           (('nm', '-u'), 'imports.txt'), (('nm', '-gU'), 'exports.txt')):
        (out / file).write_text(run(*command, str(target)))
    for name in FUNCTIONS:
        start = names.get('_' + name)
        if start is None:
            data['functions'][name] = {'available': False}
            continue
        stop = next((a for a in addresses if a > start), start + 256)
        text = run(objdump, '--disassemble', f'--start-address={start}', f'--stop-address={stop}', str(target))
        (out / (name + '.asm')).write_text(text)
        data['functions'][name] = {'address': hex(start), 'stop': hex(stop), 'file': name + '.asm'}
    (out / 'manifest.json').write_text(json.dumps(data, indent=2) + '\n')
    print(out)

if __name__ == '__main__':
    main()
