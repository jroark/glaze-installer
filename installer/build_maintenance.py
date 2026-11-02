"""Build only the device companion against a verified existing bundle's libraries.

GNU mipsel-linux-gnu tools are the default. --zig accepts a portable Zig 0.13
compiler with --linker pointing to ld.lld on Windows; its cache and all outputs
stay under the output directory.
No kernel, signed update, or other device firmware is rebuilt.
"""
import argparse
import os
from pathlib import Path
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_windows import validate_bundle
from package import GLAZE
from app_selection import entries


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--existing-bundle', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--cross', default='mipsel-linux-gnu-')
    parser.add_argument('--zig', type=Path)
    parser.add_argument('--linker', type=Path, help='ELF linker (required with --zig)')
    args = parser.parse_args()
    if args.zig and not args.linker:
        parser.error('--zig requires --linker (ld.lld)')
    resources, _ = validate_bundle(args.existing_bundle)
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(out / 'zig-cache'))
    logical = (resources / 'glaze.bin').read_bytes()
    import struct
    size = struct.unpack_from('<I', logical, 76)[0] * 512
    romfs = entries(logical[0x40000:0x40000+size], b'GZRF')
    for name in ('libc.so.1', 'libgfx.so.1', 'libui.so.1'):
        (out / name).write_bytes(romfs['lib/' + name])
    cc = [str(args.zig.resolve()), 'cc', '-target', 'mipsel-linux-gnu'] if args.zig else [args.cross + 'gcc']
    flags = ['-march=mips2', '-mabi=32', '-G0', '-msoft-float', '-mabicalls', '-fPIC',
             '-std=gnu11', '-ffreestanding', '-fno-builtin', '-nostdlib', '-fno-stack-protector',
             '-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-O2', '-ffunction-sections',
             '-fdata-sections', '-I' + str(GLAZE / 'lib/include'), '-I' + str(GLAZE / 'lib/libc/include')]
    objects = []
    for source in ('lib/crt0_pic.S', 'lib/libc/start.c', 'packages/maintenance/main.c'):
        target = out / (Path(source).stem + '.o')
        subprocess.run([*cc, *flags, '-c', str(GLAZE / source), '-o', str(target)], check=True, env=env)
        objects.append(str(target))
    link_flags = ['--hash-style=sysv', '-z', 'now', '-z', 'relro', '-z', 'max-page-size=4096',
                  '-pie', '-e', '_start', '--export-dynamic', '--gc-sections', '--dynamic-linker', '/lib/ld-glaze.so.1',
                  '-o', str(out / 'maintenance.elf'), *objects, '-L' + str(out), '--as-needed',
                  '-l:libui.so.1', '-l:libgfx.so.1', '-l:libc.so.1']
    command = [str(args.linker.resolve()) if args.linker else args.cross + 'ld', '-m', 'elf32ltsmip',
               '-z', 'separate-code', '-z', 'text', *link_flags]
    subprocess.run(command, check=True, env=env)
    elf = (out / 'maintenance.elf').read_bytes()
    if elf[:6] != b'\x7fELF\x01\x01' or struct.unpack_from('<HH', elf, 16) != (3, 8):
        raise ValueError('Companion is not a little-endian MIPS PIE')
    subprocess.run(([str(args.zig.resolve()), 'objcopy'] if args.zig else [args.cross + 'objcopy']) +
                   ['--strip-all', str(out / 'maintenance.elf'), str(out / 'app')], check=True, env=env)
    # Use the production package writer (four-byte archive alignment).
    subprocess.run([sys.executable, '-B', str(GLAZE / 'tools/mkromfs.py'), '--package', str(out / 'maintenance.gzp'),
                    'Info=' + str(GLAZE / 'packages/maintenance/Info'), 'app=' + str(out / 'app'),
                    'res/icon.gzi=' + str(GLAZE / 'packages/maintenance/icon.gzi')], check=True)
    print('Created', out / 'maintenance.gzp')


if __name__ == '__main__':
    main()
