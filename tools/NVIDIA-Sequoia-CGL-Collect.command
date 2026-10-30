#!/bin/bash
# SPDX-License-Identifier: MIT
# Standalone, read-only CGL evidence collector. No sudo, installation or downloads.
set -u
umask 077
if [ "$#" -gt 1 ] || [ "${1:-}" = --help ]; then
  printf 'Usage: %s [existing output folder; default: Desktop]\n' "$0"
  exit 0
fi
if [ "$EUID" -eq 0 ]; then
  printf 'Run this as the logged-in desktop user, without sudo.\n' >&2
  exit 1
fi
DEST=${1:-"$HOME/Desktop"}
[ -d "$DEST" ] || { printf 'Output folder does not exist: %s\n' "$DEST" >&2; exit 1; }
DEST=$(cd "$DEST" && pwd -P) || exit 1
OUT=$(mktemp -d "$DEST/NVIDIA-CGL-$(date +%Y%m%d-%H%M%S).XXXXXX") || exit 1
export NVK_CGL_COLLECT_OUTPUT="$OUT"
/usr/bin/sw_vers > "$OUT/macos.txt"
/usr/bin/uname -m > "$OUT/architecture.txt"
cat > "$OUT/READ-ME.txt" <<'INFO'
Native Zink / Sequoia CGL evidence

This collection does not install a driver, change preferences, attach to another
process, rotate displays or copy Apple binaries / the dyld shared cache.
With developer tools present, it creates disposable offscreen CGL contexts and
collects symbols, module identities and static CGL/GLD disassembly. Private ABI
evidence is for adapter development; it does not qualify Zink on this OS.
No hardware serial numbers, user files, crash dumps or process memory dumps are
requested. Tool output can contain local paths. Review the archive before sharing.

If STATUS.txt says developer tools are missing, install Apple's Command Line
Tools (xcode-select --install), complete that installation and run this file again.
Sequoia 15.5+ on Intel is the intended target. A Tahoe run is useful as a baseline.
INFO
printf 'Collecting CGL evidence; this can take a few minutes.\n'
if /usr/bin/xcode-select -p > "$OUT/developer-directory.txt" 2>&1 && [ -x /usr/bin/python3 ]; then
  /usr/bin/python3 - <<'PY'
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import subprocess

out = Path(os.environ['NVK_CGL_COLLECT_OUTPUT'])
env = dict(os.environ)
for key in list(env):
    if key.startswith(('DYLD_', 'ZINK_TEST_')) or key in ('VK_DRIVER_FILES', 'VK_ICD_FILENAMES'):
        del env[key]
env['NVKZINK_DISABLE'] = '1'  # Offscreen probe only; no global setting changes.
results = {}

def run(name, argv, timeout=30):
    try:
        process = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                 timeout=timeout, env=env)
        data, code = process.stdout, process.returncode
    except subprocess.TimeoutExpired as error:
        data, code = (error.stdout or b'') + b'\nCollection command timed out.\n', 124
    except OSError as error:
        data, code = (str(error) + '\n').encode(), 127
    (out / name).write_bytes(data)
    results[name] = {'returncode': code}
    return data.decode('utf-8', 'replace')

run('compiler-version.txt', ['/usr/bin/xcrun', 'clang', '--version'])
sdk = run('sdk-path.txt', ['/usr/bin/xcrun', '--show-sdk-path']).strip()
registry, gpu_names = [], set()
for service in ('IOAccelerator', 'NVAccel'):
    try:
        raw = subprocess.check_output(['/usr/sbin/ioreg', '-r', '-c', service, '-d', '1', '-a'],
                                      timeout=20, env=env)
        for node in plistlib.loads(raw):
            keys = ('IORegistryEntryName', 'IOClass', 'CFBundleIdentifier', 'IOGLBundleName',
                    'IOAccelRevision', 'IOAccelIndex', 'MetalPluginName')
            item = {key: node[key] for key in keys if isinstance(node.get(key), (str, int, bool))}
            item['query_class'] = service
            registry.append(item)
            name = node.get('IOGLBundleName', '')
            if isinstance(name, str) and re.fullmatch(r'[A-Za-z0-9_]+', name):
                gpu_names.add(name)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        registry.append({'query_class': service, 'error': str(error)})
(out / 'accelerators.json').write_text(json.dumps(registry, indent=2) + '\n')

probe = r'''
#include <OpenGL/OpenGL.h>
#include <OpenGL/gl3.h>
#include <mach-o/dyld.h>
#include <mach-o/loader.h>
#include <dlfcn.h>
#include <stdio.h>
#include <string.h>
static void profile(CGLPixelFormatAttribute version, const char *name) {
 CGLPixelFormatAttribute attrs[]={kCGLPFAOpenGLProfile,version,0};
 CGLPixelFormatObj format=NULL;CGLContextObj context=NULL;GLint count=0;
 CGLError error=CGLChoosePixelFormat(attrs,&format,&count);
 if(!error && format)error=CGLCreateContext(format,NULL,&context);
 if(format)CGLDestroyPixelFormat(format);
 printf("PROFILE %s: create=%d\n",name,error);
 if(error || !context)return;
 error=CGLSetCurrentContext(context);printf("make-current=%d\n",error);
 if(!error){
  printf("vendor=%s\nrenderer=%s\nversion=%s\n",glGetString(GL_VENDOR),glGetString(GL_RENDERER),glGetString(GL_VERSION));
  GLint renderer=0,interval=0;
  CGLGetParameter(context,kCGLCPCurrentRendererID,&renderer);CGLGetParameter(context,kCGLCPSwapInterval,&interval);
  printf("renderer-id=0x%x swap-interval=%d\n",renderer,interval);
 }
 CGLSetCurrentContext(NULL);CGLDestroyContext(context);
}
int main(void) {
 setvbuf(stdout,NULL,_IOLBF,0);
 profile((CGLPixelFormatAttribute)kCGLOGLPVersion_GL4_Core,"core 4.1");
 profile((CGLPixelFormatAttribute)kCGLOGLPVersion_GL3_Core,"core 3.2");
 profile((CGLPixelFormatAttribute)kCGLOGLPVersion_Legacy,"legacy");
 for(uint32_t i=0;i<_dyld_image_count();++i){
  const char *name=_dyld_get_image_name(i);
  if(!name || (!strstr(name,"OpenGL") && !strstr(name,"GLEngine") && !strstr(name,"GLDriver")))continue;
  printf("IMAGE %s",name);
  const struct mach_header *header=_dyld_get_image_header(i);
  if(header->magic==MH_MAGIC_64){
   const unsigned char *cursor=(const unsigned char *)header+sizeof(struct mach_header_64);
   const unsigned char *end=cursor+((const struct mach_header_64 *)header)->sizeofcmds;
   for(uint32_t c=0;c<header->ncmds && cursor+sizeof(struct load_command)<=end;++c){
    const struct load_command *command=(const void *)cursor;
    if(command->cmdsize<sizeof(*command) || command->cmdsize>(size_t)(end-cursor))break;
    if(command->cmd==LC_UUID && command->cmdsize>=sizeof(struct uuid_command)){
     const struct uuid_command *uuid=(const void *)cursor;printf(" UUID=");
     for(unsigned b=0;b<16;++b)printf("%02x",uuid->uuid[b]);
    }
    cursor+=command->cmdsize;
   }
  }
  putchar('\n');
 }
 return 0;
}
'''
(out / 'cgl-evidence-probe.c').write_text(probe)
executable = out / 'cgl-evidence-probe'
run('probe-build.txt', ['/usr/bin/xcrun', 'clang', '-arch', 'x86_64',
    '-mmacosx-version-min=15.5', '-std=c11', '-Wall', '-Wextra', '-Werror',
    '-Wno-deprecated-declarations', str(out / 'cgl-evidence-probe.c'),
    '-framework', 'OpenGL', '-o', str(executable)], 60)
if executable.is_file() and os.uname().machine == 'x86_64':
    run('cgl-runtime.txt', [str(executable)], 45)

targets = {
    'OpenGL': '/System/Library/Frameworks/OpenGL.framework/Versions/A/OpenGL',
    'libGL': '/System/Library/Frameworks/OpenGL.framework/Versions/A/Libraries/libGL.dylib',
    'GLEngine': '/System/Library/Frameworks/OpenGL.framework/Versions/A/Resources/GLEngine.bundle/GLEngine',
}
gpu_names.add('AppleMetalOpenGLRenderer')
for name in sorted(gpu_names):
    targets[name] = '/System/Library/Extensions/' + name + '.bundle/Contents/MacOS/' + name
identities = {}
for name, path in targets.items():
    item = {'path': path, 'exists_on_disk': Path(path).is_file()}
    if Path(path).is_file():
        item['sha256'] = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        run(name + '-exports.txt', ['/usr/bin/xcrun', 'nm', '-gU', path])
        run(name + '-dependencies.txt', ['/usr/bin/xcrun', 'otool', '-L', path])
        run(name + '-load-commands.txt', ['/usr/bin/xcrun', 'otool', '-l', path])
    else:
        item['note'] = 'May be present only in the dyld shared cache; use LLDB evidence and runtime module UUIDs.'
    identities[name] = item
(out / 'apple-module-identities.json').write_text(json.dumps(identities, indent=2) + '\n')

symbols = ['CGLCreateContext', 'CGLDestroyContext', 'CGLSetCurrentContext', 'CGLFlushDrawable',
           'CGLSetParameter', 'CGLGetParameter', 'CGLTexImageIOSurface2D', 'CGLUpdateContext',
           'gliCreateContext', 'gliDestroyContext', 'gliInitDispatchTable', 'gliSetCurrentContext',
           'gliMakeCurrentContext', 'gldCreateContext', 'gldDestroyContext', 'gldGetVersion',
           'gldPopulateContextDispatch', 'gldUpdateDispatch', 'gldAttachDrawable', 'gldFlushQueue']
prototypes = {}
for header in ('gl.h', 'gl3.h', 'glext.h'):
    path = Path(sdk) / 'System/Library/Frameworks/OpenGL.framework/Headers' / header
    if path.is_file():
        for name in re.findall(r'\b(gl[A-Z]\w*)\s*\(', path.read_text(errors='replace')):
            prototypes[name] = True
symbols += sorted(prototypes)
(out / 'requested-symbols.json').write_text(json.dumps(symbols, indent=2) + '\n')
if executable.is_file():
    program = ('import lldb\n'
               'target=lldb.debugger.CreateTarget(' + repr(str(executable)) + ')\n'
               'for path in ' + repr(list(targets.values())) + ':\n'
               ' module=target.AddModule(path,None,None)\n'
               ' print("MODULE",path,"resolved="+str(module.IsValid()))\n'
               'for command in ["image list -o -f", "image lookup -r -n ^gli"]+' +
               repr(['disassemble -n ' + n for n in symbols]) + ':\n'
               ' result=lldb.SBCommandReturnObject()\n'
               ' lldb.debugger.GetCommandInterpreter().HandleCommand(command,result)\n'
               ' print("(lldb) "+command)\n'
               ' print(result.GetOutput() or result.GetError())\n')
    commands = out / 'collect-static.lldb'
    commands.write_text('script exec(' + repr(program) + ')\nquit\n')
    asm = run('cgl-static-disassembly.txt', ['/usr/bin/xcrun', 'lldb', '--no-lldbinit',
              '--batch', '--source', str(commands)], 120)
    blocks = re.split(r'\(lldb\) disassemble -n (\w+)\n', asm)
    bodies = dict(zip(blocks[1::2], blocks[2::2]))
    slots = {}
    for name in prototypes:
        body = bodies.get(name, '')
        if '%gs:0xf0' in body:
            offsets = sorted(set(re.findall(r'0x[0-9a-f]+(?=\(%r(?:ax|bx|cx|dx|si|di|8|9|1[0-5])\))', body)))
            slots[name] = offsets
    (out / 'observed-dispatch-offsets.json').write_text(json.dumps({
        'source': 'Static observations from the collecting OS; no Tahoe offsets assumed',
        'slots': slots, 'requested_public_symbols': len(prototypes),
        'limitation': 'Candidate offsets require review; not an adapter or ABI validation.'}, indent=2) + '\n')
    results['dispatch_evidence'] = {'symbols_observed': len(slots)}
(out / 'collection-results.json').write_text(json.dumps(results, indent=2) + '\n')
(out / 'STATUS.txt').write_text('Collection completed. Review collection-results.json for skipped or failed steps.\n'
    'This is evidence collection only; Sequoia native Zink support is not installed or qualified.\n')
print('Collected evidence:', out)
PY
  RESULT=$?
  if [ "$RESULT" -ne 0 ]; then
    printf 'Collection returned %s; partial evidence is retained.\n' "$RESULT" >> "$OUT/STATUS.txt"
  fi
else
  printf 'Developer tools missing. Install Command Line Tools, then rerun for CGL evidence.\n' > "$OUT/STATUS.txt"
fi
(
  cd "$OUT" || exit 1
  /usr/bin/find . -type f ! -name SHA256SUMS ! -name '.DS_Store' ! -name '._*' \
    -exec /usr/bin/shasum -a 256 '{}' \; > SHA256SUMS
) || exit 1
ARCHIVE="$OUT.tar.gz"
COPYFILE_DISABLE=1 /usr/bin/tar --exclude='.DS_Store' --exclude='._*' -czf "$ARCHIVE" \
  -C "$(dirname "$OUT")" "$(basename "$OUT")" || exit 1
printf '\nFinished. Send this archive:\n%s\n' "$ARCHIVE"
printf 'The evidence folder is retained next to it.\n'
