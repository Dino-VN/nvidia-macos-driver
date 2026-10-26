#!/usr/bin/env python3
"""Protect existing performance, decoder and cursor lifetime code during the rotation replacement."""
import re
import subprocess
from test_support import ROOT, FB, method

base = '6d715894d05fca2a90f5886b1ac5f14fdc32a673'


def historical(revision, path):
    return subprocess.check_output(['git', 'show', revision + ':' + path], cwd=ROOT)


restored = ['plugin/NVMTLEventSync.m', 'plugin/NVMTLObjects.m', 'plugin/nvmtl_vk.c', 'plugin/nvmtl_vk.h']
for path in restored:
    assert (ROOT / path).read_bytes() == historical(base, path), path
for path in subprocess.check_output(['git', 'ls-tree', '-r', '--name-only', 'HEAD', 'plugin', 'translator', 'nvk', 'runtime', 'build'], cwd=ROOT, text=True).splitlines():
    if path in restored or path == 'plugin/NVMTLRotationInline.m':
        continue
    assert (ROOT / path).read_bytes() == historical('HEAD', path), path

accel_path = 'kexts/NVRM/accel/nvrm-accel.cpp'
accel = (ROOT / accel_path).read_text()
marker = '            setProperty("NVAccelNativeRotationProtocol", (unsigned long long)NM_NATIVE_ROTATION_PROTOCOL, 32);\n'
header = '#include "../../NVRMFB/fb/nvrm-rotation.h"\n'
assert accel.count(marker) == 1 and accel.count(header) == 1
assert accel.replace(marker, '').replace(header, '').encode() == historical(base, accel_path)
assert accel.count('static bool nvAccelRestoreParkedForDirty(') == 1
assert not any(word in accel for word in ['nvRotationCopyPresent', 'nvRotationGPUTry', 'NVAccelRotationGPUProtocol'])
assert not (ROOT / 'plugin/NVMTLRotationInline.m').exists()

old = historical(base, 'kexts/NVRMFB/fb/nvrm-fb.cpp').decode()
for name in ['cursorInit', 'cursorFire', 'cursorApply', 'scheduleCall', 'stop',
             'vramGrant', 'vramRelease', 'getApertureRange', 'getVRAMRange',
             'headOff', 'setHeadPower', 'notifyConnectionChanged', 'connectNotifyFire']:
    signature = 'NVRMNVDAFramebuffer::' + name + '('
    assert method(FB, signature) == method(old, signature), name
apply = method(FB, 'bool NVRMNVDAFramebuffer::applyMode(').replace('    publishCursorGeometry(nullptr);\n', '')
assert apply == method(old, 'bool NVRMNVDAFramebuffer::applyMode(')
flip = method(FB, 'bool NVRMNVDAFramebuffer::flipToMemory(')
assert 'notifyConnectionChanged(1);' in flip and 'fConnect.proc(' not in flip
assert not re.search(r'\bthread_call_cancel_wait\s*\(', FB)
assert 'THREAD_CALL_PRIORITY_KERNEL, THREAD_CALL_OPTIONS_ONCE' in FB
assert 'while (OSAddAtomic(0, &fCursorOutstanding)) IOSleep(1);' in FB
print('PASS: full plugin/translator/NVK/decoder/ANGLE/-O2 retention; accelerator differs from pre-rotation fork only by native protocol marker; cursor ONCE/drain, scanout/BAR1/parking/power and deferred family callback preserved')
