#!/usr/bin/env python3
"""Prove that existing plugin behavior survives outside the explicit rotation hooks."""
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parents[2]
base='d12f43607cedf61cc1dfdcb4e1d13fdbd34ad9da'
def before(path):return subprocess.check_output(['git','show',base+':'+path],cwd=root,text=True)
def current(path):return (root/path).read_text()
def without(text,start,end):
 a=text.index(start);b=text.index(end,a);return text[:a]+text[b:]
s=current('plugin/NVMTLEventSync.m')
for addition in ['    NSArray *rotationWork;\n','#import "NVMTLRotationInline.m"\n\n',
 '        if (published && part->rotationWork.count) nvmtl_rotation_part_ready(part);\n',
 '    nvmtl_rotation_prepare(self); // producer thread, outside the class lock and before GPU pending marks\n']:
 assert s.count(addition)==1;s=s.replace(addition,'')
assert s==before('plugin/NVMTLEventSync.m')
s=current('plugin/NVMTLObjects.m').replace('nvmtl_rotation_has_work(self) || (ws && !nvmtl_ws_kernel_waits())','ws && !nvmtl_ws_kernel_waits()')
assert s==before('plugin/NVMTLObjects.m')
s=without(current('plugin/nvmtl_vk.c'),'uint32_t nvmtl_vk_rotation_control(', 'int nvmtl_vk_surface_vram(')
s=without(s,'#include "../tools/rotation/gpu_shader.h"','int nvmtl_vk_cmd_blit_image_2d(')
assert s==before('plugin/nvmtl_vk.c')
for path in subprocess.check_output(['git','ls-tree','-r','--name-only',base,'plugin','translator','nvk'],cwd=root,text=True).splitlines():
 if path in ['plugin/NVMTLEventSync.m','plugin/NVMTLObjects.m','plugin/nvmtl_vk.c','plugin/nvmtl_vk.h']:continue
 assert current(path)==before(path),path
print('PASS: existing plugin, OpenGL/Minecraft, cbuf/shader, MoltenVK and native Vulkan code retained byte-for-byte outside four explicit rotation hooks/helpers')
