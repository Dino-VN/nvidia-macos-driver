#!/usr/bin/env python3
"""Verify that rotation retains production modes, cursor lifecycle and GPU work."""
from pathlib import Path
import re
import subprocess
root=Path(__file__).resolve().parents[2]
base='6d715894d05fca2a90f5886b1ac5f14fdc32a673'
fb='kexts/NVRMFB/fb/nvrm-fb.cpp'
accel='kexts/NVRM/accel/nvrm-accel.cpp'
def baseline(p): return subprocess.check_output(['git','show',base+':'+p],cwd=root,text=True)
def method(text,signature):
    a=text.index(signature);opening=text.index('{',a);end=opening+1;depth=1
    while depth:
        depth+=(text[end]=='{')-(text[end]=='}');end+=1
    return text[a:end]
old,new=baseline(fb),(root/fb).read_text()
checked=0
for found in re.finditer(r'(?m)^.*\bNVRMNVDAFramebuffer::(\w+)\([^;\n]*',old):
    name=found[1];signature='NVRMNVDAFramebuffer::'+name+'('
    before,after=method(old,signature),method(new,signature)
    if name=='start': after=after.replace('    configureRotation();\n','')
    if name in ['getInformationForDisplayMode','validateDetailedTiming']:
        after=after.replace('        rotationModeFlags(info);\n','').replace('    rotationModeFlags(info);\n','')
    if name=='callPlatformFunction':
        after=after.replace('    if (functionName && functionName->isEqualTo(NM_ROTATION_INFO))\n'
            '        return rotationMode((NMRotationMode *)param1);\n'
            '    if (functionName && functionName->isEqualTo(NM_ROTATION_COPY))\n'
            '        return rotationCopy((const NMRotationCopyRequest *)param1);\n','')
        after=after.replace('    if (functionName && functionName->isEqualTo(NM_ROTATION_GPU_FLIP))\n'
            '        return rotationGPUFlip((NMRotationGPUFlip *)param1);\n','')
    if name=='flipToMemory':
        after=after.replace('    // Drain old unrotated asynchronous presents, without putting one back over a\n'
            '    // rotated home image. Standard still uses the original zero-copy flip path.\n'
            '    if (mem && rotationPending() && !fRotationGPUFlipActive) {\n'
            '        if (rcOut) *rcOut = (int)NV_KMS_FLIP_RESULT_IN_PROGRESS;\n'
            '        return false;\n'
            '    }\n','')
    assert before==after,name
    checked+=1
old,new=baseline(accel),(root/accel).read_text()
protected=['NVDisplayPipe::initFramebufferResource(', 'NVDisplayPipe::iopMapSurface(',
    'NVVidMemory::allocPhysical(', 'NVVidMemory::deallocPhysical(', 'NVResource::pageoff(',
    'static bool nvSurfWaitReady(', 'static bool nvAccelIopFlip(IOService *fb,',
    'static void nvAccelIopAsyncRun(', 'static bool nvAccelIopAsyncStart(',
    'static bool nvAccelSurfCopyReady(IOSurface *s,']
for signature in protected:
    def body(text):
        a=text.rindex(signature);return method(text[a:],signature)
    assert body(old)==body(new),signature
for name in ['translator','runtime','kexts/NVRMAGDC','kexts/NVRMFB/fb/nvrm-fb-safety.h']:
    assert not subprocess.check_output(['git','diff',base,'--',name],cwd=root),name
print(f'PASS: {checked} framebuffer methods retain production bodies after opt-in dispatch guards; '
    f'{len(protected)} resource/wait/presentation helpers unchanged; native modes/pitch/apertures/cursor and runtime retained; producer changes are checked separately')
