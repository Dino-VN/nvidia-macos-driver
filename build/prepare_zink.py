#!/usr/bin/env python3
"""Apply the Zink overlay to a separate Mesa 17ca6174 source tree."""
from pathlib import Path
import shutil
import subprocess
import sys

def main():
    if len(sys.argv) != 2:
        raise SystemExit('usage: prepare_zink.py MESA_SOURCE')
    source = Path(sys.argv[1]).resolve()
    repo = Path(__file__).resolve().parents[1]
    patch = repo / 'zink/mesa-zink-nvk.patch'
    if not (source / 'src/gallium/drivers/zink/zink_screen.c').is_file():
        raise SystemExit('not a Mesa source directory')
    check = subprocess.run(['git', 'apply', '--check', str(patch)], cwd=source,
                           capture_output=True, text=True)
    if check.returncode == 0:
        subprocess.run(['git', 'apply', str(patch)], cwd=source, check=True)
    else:
        reverse = subprocess.run(['git', 'apply', '--reverse', '--check', str(patch)],
                                 cwd=source, capture_output=True)
        if reverse.returncode != 0:
            raise SystemExit('Zink overlay does not match this Mesa tree:\n' + check.stderr)
    target = source / 'src/gallium/targets/dino-zink'
    target.mkdir(parents=True, exist_ok=True)
    for name in ('dino_zink.c', 'dino_zink.h', 'meson.build'):
        shutil.copy2(repo / 'zink' / name, target / name)
    print(f'Zink overlay ready: {source}')

if __name__ == '__main__':
    main()
