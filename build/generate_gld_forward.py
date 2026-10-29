#!/usr/bin/env python3
"""Generate ABI-neutral tail-call forwarding stubs from local GLD exports.

Only symbol names are used; no Apple binary bytes or disassembly are copied.
"""
from pathlib import Path
import re
import subprocess
import sys

if len(sys.argv) != 2:
    raise SystemExit('usage: generate_gld_forward.py NEW_BUILD_DIRECTORY')
if subprocess.check_output(['sw_vers', '-buildVersion'], text=True).strip() != '25G241':
    raise SystemExit('GLD proxy ABI has only been verified on 25G241')
out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
apple = '/System/Library/Extensions/AppleMetalOpenGLRenderer.bundle/Contents/MacOS/AppleMetalOpenGLRenderer'
exports = subprocess.check_output(['nm', '-gU', apple], text=True)
names = sorted(set(re.findall(r'\b_(gld[A-Z]\w*)$', exports, re.M)))
overrides = {'gldGetVersion', 'gldCreateContext', 'gldDestroyContext'}
if not overrides.issubset(names): raise SystemExit('Required lifecycle exports are missing')
header = ['static const char *const gld_names[] = {']
header += ['   "' + name + '",' for name in names]
header += ['};', f'void *gld_targets[{len(names)}];']
header += [f'#define GLD_INDEX_{name} {i}' for i, name in enumerate(names)]
(out / 'gld_forward.inc').write_text('\n'.join(header) + '\n')
asm = ['.text', '.private_extern _gld_targets']
for i, name in enumerate(names):
    if name in overrides: continue
    asm += [f'.globl _{name}', f'_{name}:', f'  jmpq *_gld_targets+{i*8}(%rip)']
(out / 'gld_forward.S').write_text('\n'.join(asm) + '\n')
print(f'Generated {len(names)} GLD exports, including {len(overrides)} lifecycle overrides')
