"""Compile extracted production methods with small host-side OS/GPU doubles."""
from pathlib import Path
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[2]
FB = (ROOT / 'kexts/NVRMFB/fb/nvrm-fb.cpp').read_text()


def method(source, signature):
    start = source.index(signature)
    end = source.index('{', start) + 1
    depth = 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}')
        end += 1
    return source[start:end]


def run(fixture):
    with tempfile.TemporaryDirectory(prefix='nm-native-rotation-') as directory:
        p = Path(directory)
        (p / 'test.cpp').write_text(fixture)
        subprocess.run(['xcrun', 'clang++', '-std=c++17', '-O1', '-g', '-Wall', '-Wextra',
                        '-Werror', '-Wno-unused-parameter', '-Wno-unused-variable', '-Wno-unused-but-set-variable',
                        '-fsanitize=address,undefined', '-fno-sanitize-recover=all', '-I' + str(ROOT / 'kexts/NVRMFB/fb'),
                        '-I' + str(ROOT / 'tools/rotation'), str(p / 'test.cpp'), '-o', str(p / 'test')], check=True)
        subprocess.run([str(p / 'test')], check=True, timeout=30)
