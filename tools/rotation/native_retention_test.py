#!/usr/bin/env python3
"""Protect existing performance, decoder and cursor lifetime code during the rotation replacement."""
import re
import subprocess
import tempfile
from pathlib import Path
from test_support import ROOT, FB, method

base = '6d715894d05fca2a90f5886b1ac5f14fdc32a673'
native = '6fc2b8101218b872dce8a723d86f865b09947259'
upstream_base = '46779055f68208baa5ddfb9b2e9c77ed028e1d59'
upstream = 'bf23ca740e55d86bac987fb68fb5164ac1237941'
retained = '6ca72cbf96fc19c48ae824f6dcb4c5463e78da80'


def historical(revision, path):
    return subprocess.check_output(['git', 'show', revision + ':' + path], cwd=ROOT)


def with_upstream_changes(path):
    """Compare against the reviewed upstream delta without relaxing fork retention."""
    with tempfile.TemporaryDirectory(prefix='native-rotation-retention-') as tmp:
        files = [Path(tmp) / name for name in ('fork', 'base', 'upstream')]
        for file, revision in zip(files, (native, upstream_base, upstream)):
            file.write_bytes(historical(revision, path))
        return subprocess.check_output(['git', 'merge-file', '-p', *map(str, files)])


changed = ['plugin/NVMTLObjects.m', 'plugin/nvmtl_vk.c', 'plugin/nvmtl_vk.h']
for path in changed:
    assert (ROOT / path).read_bytes() == with_upstream_changes(path), path
for path in subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', retained, 'plugin', 'translator', 'nvk', 'runtime', 'build'], cwd=ROOT, text=True).splitlines():
    # stage_package's new AGDC bundle replacement is covered by the package
    # copy/hash tests; it is the only intended change under these directories.
    if path in changed or path == 'build/stage_package.py':
        continue
    assert (ROOT / path).read_bytes() == historical(retained, path), path
assert (ROOT / 'plugin/NVMTLEventSync.m').read_bytes() == historical(base, 'plugin/NVMTLEventSync.m')

accel_path = 'kexts/NVRM/accel/nvrm-accel.cpp'
accel = (ROOT / accel_path).read_text()
marker = '            setProperty("NVAccelNativeRotationProtocol", (unsigned long long)NM_NATIVE_ROTATION_PROTOCOL, 32);\n'
header = '#include "../../NVRMFB/fb/nvrm-rotation.h"\n'
assert accel.count(marker) == 1 and accel.count(header) == 1
before = historical(retained, accel_path).decode()
assert before.encode() == with_upstream_changes(accel_path)
stable_header = '#include "../nvrm_display_identity.h"\n'
assert accel.count(stable_header) == 1
reviewed = accel.replace(stable_header, '').replace(
    method(accel, 'static bool fbPublished('), method(before, 'static bool fbPublished('))
assert reviewed == before, 'accelerator changes exceed the display-slot callback'
old_accel = historical(native, accel_path).decode()
assert old_accel.replace(marker, '').replace(header, '').encode() == historical(base, accel_path)
assert accel.count('static bool nvAccelRestoreParkedForDirty(') == 1
assert not any(word in accel for word in ['nvRotationCopyPresent', 'nvRotationGPUTry', 'NVAccelRotationGPUProtocol'])
assert not (ROOT / 'plugin/NVMTLRotationInline.m').exists()

old = historical(retained, 'kexts/NVRMFB/fb/nvrm-fb.cpp').decode()
for name in ['cursorInit', 'cursorFire', 'cursorApply', 'scheduleCall', 'stop',
             'vramGrant', 'vramRelease', 'getApertureRange', 'getVRAMRange',
             'headOff', 'setHeadPower', 'notifyConnectionChanged', 'connectNotifyFire']:
    signature = 'NVRMNVDAFramebuffer::' + name + '('
    assert method(FB, signature) == method(old, signature), name
apply = method(FB, 'bool NVRMNVDAFramebuffer::applyMode(')
assert apply == method(old, 'bool NVRMNVDAFramebuffer::applyMode(')
init = method(FB, 'bool NVRMNVDAFramebuffer::kapiInit(')
assert init.replace('    validateInitialDviMode();\n', '') == method(old, 'bool NVRMNVDAFramebuffer::kapiInit(')
for signature in ['bool NVRMNVDAFramebuffer::edidModeFor(', 'unsigned NVRMNVDAFramebuffer::addKmsRefreshModes(']:
    filtered = method(FB, signature)
    check = '        if (fDviModeValidation && !fKms->validateDisplayMode(fDev, fDisplay, &m)) continue;\n'
    assert filtered.count(check) == 1
    assert filtered.replace(check, '') == method(old, signature), signature
flip = method(FB, 'bool NVRMNVDAFramebuffer::flipToMemory(')
assert 'notifyConnectionChanged(1);' in flip and 'fConnect.proc(' not in flip
assert not re.search(r'\bthread_call_cancel_wait\s*\(', FB)
assert 'THREAD_CALL_PRIORITY_KERNEL, THREAD_CALL_OPTIONS_ONCE' in FB
assert 'while (OSAddAtomic(0, &fCursorOutstanding)) IOSleep(1);' in FB
print('PASS: reviewed controller-slot and DVI validation changes only; native rotation rendering, decoder/ANGLE/-O2, translator/NVK/Minecraft, cursor ONCE/drain, scanout/BAR1/parking/power and deferred family callback preserved')
