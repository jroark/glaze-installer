"""Build a single offline Windows setup EXE on macOS/Linux with MinGW and NSIS.

No user-installed Python, separate firmware or driver download is required.
Downloads are locked to official upstream URLs and SHA-256 digests.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from package import GLAZE, ROOT, stage_resources, validate_update, builtin_catalog, validate_maintenance


def run(*command):
    subprocess.run(list(map(str, command)), check=True)


def download_dependencies(cache, names=None):
    cache.mkdir(parents=True, exist_ok=True)
    lock = json.loads((ROOT / 'installer/windows-downloads.json').read_text())
    for name, entry in lock.items():
        if names is not None and name not in names:
            continue
        target = cache / name
        if not target.exists():
            partial = cache / (name + '.partial')
            urllib.request.urlretrieve(entry['url'], partial)
            partial.rename(target)
        if hashlib.sha256(target.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError('Dependency checksum mismatch: ' + name)
    return lock


def validate_bundle(bundle):
    resources = Path(bundle).resolve() / 'resources'
    manifest = json.loads((resources / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = (resources / name).resolve()
        if not path.is_relative_to(resources) or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            raise ValueError('Existing bundle failed verification: ' + name)
    metadata = validate_update(resources / 'update.gzu', manifest['build_id'],
                               resources / 'glaze.bin', manifest['os']['version'])
    if metadata != manifest['os']:
        raise ValueError('Existing bundle release metadata differs')
    return resources, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--os-update', type=Path)
    parser.add_argument('--build-id')
    parser.add_argument('--existing-bundle', type=Path, help='Reuse verified firmware and runtime from a matching installer folder')
    parser.add_argument('--maintenance-package', type=Path, help='Rebuilt protocol-2 device companion (.gzp)')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'out/installer-windows')
    args = parser.parse_args()
    cache = ROOT / 'out/installer-downloads'
    existing = validate_bundle(args.existing_bundle) if args.existing_bundle else None
    if existing:
        if args.build_id and args.build_id != existing[1]['build_id']:
            parser.error('--build-id differs from existing bundle')
        args.build_id = existing[1]['build_id']
        validate_maintenance(args.maintenance_package or existing[0] / 'maintenance.gzp')
    elif not args.build_id or not args.os_update:
        parser.error('--build-id and --os-update are required without --existing-bundle')
    download_dependencies(cache, {'libusb-1.0.30.7z', 'libusbK-3.1.0.0-bin.7z', 'libusbK-3.1.0.0-src.7z'} if existing else None)
    out = args.output_dir.resolve()
    if not out.is_relative_to((ROOT / 'out').resolve()):
        parser.error('--output-dir must stay under the checkout out directory')
    native = out / 'native'
    native.mkdir(parents=True, exist_ok=True)
    libusb = cache / 'libusb'
    # Only extract x64 MinGW files: old p7zip cannot decode ARM64 BCJ filters.
    sevenzip = os.environ.get('GLAZE_7ZIP', '7z')
    run(sevenzip, 'x', '-y', '-o' + str(libusb), cache / 'libusb-1.0.30.7z', 'MinGW64/*', 'include/*')
    for name in ('libusbK-3.1.0.0-bin', 'libusbK-3.1.0.0-src'):
        run(sevenzip, 'x', '-y', '-o' + str(cache / name), cache / (name + '.7z'))
    libusbk = cache / 'libusbK-3.1.0.0-bin/libusbK-3.1.0.0-bin'
    libusbk_source = cache / 'libusbK-3.1.0.0-src/libusbK-3.1.0.0-src'
    tcl = cache / 'tcltk'
    if not existing:
        run('msiextract', '-C', tcl, cache / 'tcltk.msi')
    cc = os.environ.get('GLAZE_WIN_CC', 'x86_64-w64-mingw32-gcc')
    windres = os.environ.get('GLAZE_WIN_WINDRES', 'x86_64-w64-mingw32-windres')
    if os.name == 'nt' and Path(cc).is_absolute():
        os.environ['PATH'] = str(Path(cc).parent) + os.pathsep + os.environ.get('PATH', '')
    rc = native / 'installer.rc'
    rc.write_text('1 24 "' + (ROOT / 'installer/windows.manifest').as_posix() + '"\n')
    resource = native / 'manifest.o'
    run(windres, '--preprocessor=' + (Path(cc).name if os.name == 'nt' else cc),
        '--preprocessor-arg=-E', '--preprocessor-arg=-xc', '--preprocessor-arg=-DRC_INVOKED',
        '-i', rc, '-o', resource)
    # installer/compat is this repository's; the rest are glaze-os sources.
    includes = ['tools/glaze-usb', 'lib/include', 'servers/fs', 'third_party/littlefs', 'third_party/dhara']
    flags = ['-std=gnu11', '-O2', '-Wall', '-Wextra', '-Wno-unused-parameter', '-static',
             '-pthread', '-include', str(ROOT / 'installer/compat.h'), '-I' + str(libusb / 'include')]
    flags += ['-I' + str(ROOT / 'installer/compat'), '-I' + str(libusbk_source / 'includes')] + ['-I' + str(GLAZE / name) for name in includes]
    def compile(name, sources, libraries=()):
        run(cc, *flags, *[Path(p) if Path(p).is_absolute() else GLAZE / p for p in sources], resource, *libraries, '-o', native / name)
    usb = 'tools/glaze-usb/'
    compile('glaze-installer-usb.exe', [ROOT / 'installer/helper.c', ROOT / 'installer/windows_usb.c', ROOT / 'installer/usb_transport.c'] + [usb + n + '.c' for n in
            ('client', 'pcconnect', 'nand', 'nand_write')],
            [libusb / 'MinGW64/static/libusb-1.0.dll.a', libusbk / 'bin/lib/amd64/libusbK.lib', '-lbcrypt'])
    compile('nand-inventory.exe', ['host/nand_inventory.c', 'kernel/drivers/nand_boot.c', 'kernel/drivers/nand_ecc.c'])
    fs = ['host/mkfsimg.c', 'servers/fs/ftl.c', 'third_party/littlefs/lfs.c', 'third_party/littlefs/lfs_util.c']
    fs += [str(p.relative_to(GLAZE)) for p in (GLAZE / 'third_party/dhara/dhara').glob('*.c')]
    fs += [str(p.relative_to(GLAZE)) for p in (GLAZE / 'third_party/dhara/ecc').glob('*.c')]
    compile('mkfsimg.exe', fs)
    product = out / 'Glaze Installer'
    if product.exists():
        if not product.resolve().is_relative_to(out.resolve()):
            raise ValueError('Product output escapes build directory')
        shutil.rmtree(product)
    product.mkdir()
    if existing:
        resources = product / 'resources'
        shutil.copytree(existing[0], resources)
        catalog = builtin_catalog((resources / 'glaze.bin').read_bytes())
        builtin_ids = {a['id'] for a in catalog}
        catalog += [a for a in json.loads((resources / 'apps.json').read_text(encoding='utf-8'))
                    if a['id'] not in builtin_ids]
        (resources / 'apps.json').write_text(json.dumps(catalog, indent=2), encoding='utf-8')
        for name in ('glaze-installer-usb.exe', 'nand-inventory.exe', 'mkfsimg.exe'):
            shutil.copy2(native / name, resources / 'bin')
    else:
        resources = stage_resources(product, native, args.build_id, '.exe', args.os_update)
    if args.maintenance_package:
        validate_maintenance(args.maintenance_package)
        shutil.copy2(args.maintenance_package, resources / 'maintenance.gzp')
    shutil.copy2(libusb / 'MinGW64/dll/libusb-1.0.dll', resources / 'bin')
    shutil.copy2(libusbk / 'bin/dll/amd64/libusbK.dll', resources / 'bin')
    (resources / 'drivers').mkdir(exist_ok=True)
    if not existing:
        shutil.copy2(cache / 'zadig-2.9.exe', resources / 'drivers')
        for name in ('libusb-1.0.30.tar.bz2', 'libwdi-v1.5.1.zip'):
            shutil.copy2(cache / name, resources / 'licenses')
    shutil.copy2(cache / 'libusbK-3.1.0.0-src.7z', resources / 'licenses')
    shutil.copytree(libusbk_source / 'license', resources / 'licenses/libusbK', dirs_exist_ok=True)
    shutil.copy2(ROOT / 'installer/windows-downloads.json', resources / 'licenses')
    manifest_path = resources / 'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    for folder in ('bin', 'drivers', 'licenses'):
        for path in (resources / folder).rglob('*'):
            if not path.is_file():
                continue
            manifest['files'][path.relative_to(resources).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest['files']['apps.json'] = hashlib.sha256((resources / 'apps.json').read_bytes()).hexdigest()
    manifest['files']['maintenance.gzp'] = hashlib.sha256((resources / 'maintenance.gzp').read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest, indent=2))
    runtime = product / 'runtime'
    if existing:
        shutil.copytree(args.existing_bundle / 'runtime', runtime)
    else:
        with zipfile.ZipFile(cache / 'python-3.11.9-embed-amd64.zip') as archive:
            archive.extractall(runtime)
        shutil.copytree(tcl / 'DLLs', runtime / 'DLLs')
        shutil.copytree(tcl / 'Lib/tkinter', runtime / 'Lib/tkinter')
        shutil.copytree(tcl / 'tcl', runtime / 'tcl')
    (runtime / 'python311._pth').write_text('python311.zip\n.\nDLLs\nLib\n../app\n')
    app = product / 'app'
    app.mkdir()
    for name in ('app.py', 'engine.py', 'app_selection.py', 'system_image.py'):
        shutil.copy2(ROOT / 'installer' / name, app)
    run(cc, '-O2', '-static', '-municode', '-mwindows', ROOT / 'installer/windows-launcher.c', resource,
        '-o', product / 'Glaze Installer.exe')
    shutil.copy2(ROOT / 'installer/START-HERE.txt', product)
    output = out / 'Glaze-Installer-windows-x64.exe'
    run(os.environ.get('GLAZE_MAKENSIS', 'makensis'), '-DPRODUCT_DIR=' + str(product), '-DOUTPUT_FILE=' + str(output), ROOT / 'installer/windows.nsi')
    (out / 'SHA256SUMS').write_text(hashlib.sha256(output.read_bytes()).hexdigest() + '  ' + output.name + '\n')
    print('Created', output)


if __name__ == '__main__':
    main()
