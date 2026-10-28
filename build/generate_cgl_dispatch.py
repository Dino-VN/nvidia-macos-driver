#!/usr/bin/env python3
"""Recover local libGL dispatch slots; emit adapters, never Apple instructions."""
import argparse
import json
from pathlib import Path
import re
import subprocess


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('probe', type=Path)
    ap.add_argument('output', type=Path)
    args = ap.parse_args()
    os_build = subprocess.check_output(['sw_vers', '-buildVersion'], text=True).strip()
    if os_build != '25G241':
        raise SystemExit('Verify CGL/GLI object layouts and swap lifecycle before porting this generator to ' + os_build)
    args.output.mkdir(parents=True, exist_ok=True)
    sdk = subprocess.check_output(['xcrun', '--show-sdk-path'], text=True).strip()
    header = Path(sdk) / 'System/Library/Frameworks/OpenGL.framework/Headers/gl3.h'
    # Some core APIs are declared in ARB sections without OPENGL_DEPRECATED.
    # In particular, leaving map/flush adapters out splits Mesa buffer creation
    # from Apple's mapping implementation and makes Minecraft's upload fail.
    prototypes = re.findall(
        r'GLAPI\s+([^;{}]+?)\s+APIENTRY\s+(gl\w+)\s*\(([^();{}]*?)\)\s*'
        r'(?:OPENGL_DEPRECATED(?:\([^)]*\))?\s*)?;',
        header.read_text())
    if len(prototypes) < 300:
        raise SystemExit('Incomplete SDK GL core prototype inventory')
    required = {'glMapBufferRange', 'glFlushMappedBufferRange', 'glVertexAttribDivisor'}
    if not required.issubset({name for _, name, _ in prototypes}):
        raise SystemExit('SDK buffer mapping or instancing declarations are missing')
    commands = args.output / 'dispatch.lldb'
    commands.write_text('target create ' + str(args.probe.resolve()) + '\n' +
                        ''.join(f'disassemble -n {name}\n' for _, name, _ in prototypes) + 'quit\n')
    result = subprocess.run(['lldb', '--no-lldbinit', '-b', '-s', str(commands)],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (args.output / 'dispatch-local.asm').write_text(result.stdout)
    if result.returncode:
        raise SystemExit(result.stderr)
    blocks = re.split(r'\(lldb\) disassemble -n (gl\w+)\n', result.stdout)
    bodies = dict(zip(blocks[1::2], blocks[2::2]))
    slots = {}
    for _, name, _ in prototypes:
        body = bodies.get(name, '')
        # Public stubs obtain the current CGL object through GS and call exactly
        # one nonzero dispatch offset. The zero offset is its hidden GLI context.
        if '%gs:0xf0' not in body:
            raise SystemExit(f'{name}: unknown current-context convention')
        offsets = set(int(x, 16) for x in re.findall(r'(0x[0-9a-f]+)\(%r(?:ax|bx|cx|dx|si|di|8|9|1[0-5])\)', body))
        offsets.discard(0)
        if len(offsets) != 1:
            raise SystemExit(f'{name}: ambiguous dispatch offsets {offsets}')
        slot = offsets.pop()
        if not 0 < slot < 0x1e80 or slot % 8:
            raise SystemExit(f'{name}: slot outside observed CGL dispatch prefix')
        slots[name] = slot
    # Apple's deletion slot accepts either a shader or a program. Two distinct
    # Mesa adapters at this offset would make the last entry win for both APIs.
    shared = {}
    for name, slot in slots.items():
        shared.setdefault(slot, set()).add(name)
    if any(names != {'glDeleteProgram', 'glDeleteShader'}
           for names in shared.values() if len(names) > 1):
        raise SystemExit('Unknown shared GL dispatch slot; recover its semantics first')
    wrappers = ['/* Generated from public Khronos prototypes and local slot observations. */']
    rows = []
    for ret, name, params in prototypes:
        params = params.strip()
        names = [] if params == 'void' else [re.search(r'(\w+)\s*(?:\[.*\])?$', p.strip()).group(1) for p in params.split(',')]
        with_ctx = 'void *engine' + (', ' + params if params != 'void' else '')
        wrappers += [f'static {ret} dz_{name}({with_ctx}) {{']
        if name == 'glViewport':
            wrappers += ['  if (native_viewport(engine, __builtin_return_address(0), x, y, width, height)) return;']
        wrappers += [f'  {ret} (*dz_apple)({with_ctx}) = original_noncurrent(engine, {slots[name]});',
                     f'  if (dz_apple) {{ {"" if ret == "void" else "return "}dz_apple(engine{", " if names else ""}{", ".join(names)});' +
                     (' return; }' if ret == 'void' else ' }'),
                     '  struct dino_cgl_bridge *dz_bridge = bridge_current(engine);',
                     ('  if (!dz_bridge) return;' if ret == 'void' else '  if (!dz_bridge) return 0;')]
        if name in {'glDeleteProgram', 'glDeleteShader'}:
            wrappers += [
                '  GLboolean (*is_program)(GLuint) = (void *)dino_zink_get_proc_address("glIsProgram");',
                '  void (*delete_object)(GLuint) = (void *)dino_zink_get_proc_address(',
                '     is_program(' + names[0] + ') ? "glDeleteProgram" : "glDeleteShader");',
                '  delete_object(' + names[0] + ');', '}']
        else:
            wrappers += [f'  {ret} (*dz_func)({params}) = (void *)dz_bridge->procs[{len(rows)}];',
                         f'  {"" if ret == "void" else "return "}dz_func({", ".join(names)});', '}']
        rows.append(f'  {{"{name}", {slots[name]}, (void *)dz_{name}, (void *){name}}},')
    wrappers += ['static const struct dispatch_entry entries[] = {', *rows, '};']
    (args.output / 'cgl_dispatch.inc').write_text('\n'.join(wrappers) + '\n')
    (args.output / 'cgl-dispatch-map.json').write_text(json.dumps({
        'macos': subprocess.check_output(['sw_vers'], text=True),
        'source': 'local LLDB static disassembly of libGL public stubs',
        'context_prefix_bytes': 0x1e80, 'slots': slots,
        'limitations': ['Offsets are local OS observations, not a stable Apple ABI.',
                        'No Apple binary or instructions belong in distributable output.']}, indent=2) + '\n')
    print(f'Generated {len(rows)} core GL adapters in {args.output}')


if __name__ == '__main__':
    main()
