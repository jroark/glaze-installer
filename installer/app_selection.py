"""Offline app selection for a device-specific NAND image; no device access."""
import hashlib
import json
from pathlib import Path, PurePosixPath
import struct

import lz4block

ENTRY = struct.Struct('<48sII')
ROMFS_START, ROMFS_END = 0x40000, 0x500000
# glaze-os's compressed romfs (tools/romfs.py, tools/mkromfs.py --lz4): a ".lz4"
# entry marks it, and every other file is a page container of LZ4 blocks.
PAGE = 4096
LZ4_MARKER, LZ4_MARKER_DATA = '.lz4', b'GZL4 romfs v1\n'


def entries(blob, magic):
    """Every file's contents, by name; a compressed romfs is expanded."""
    files = raw_entries(blob, magic)
    if magic == b'GZRF' and LZ4_MARKER in files:
        if files.pop(LZ4_MARKER) != LZ4_MARKER_DATA:
            raise ValueError('Unsupported compressed ROMFS version')
        files = {name: lz4_expand(data) for name, data in files.items()}
    return files


def compressed(blob):
    """Whether a romfs archive is LZ4-compressed, so a rewrite can keep its format."""
    return LZ4_MARKER in raw_entries(blob, b'GZRF')


def lz4_container(data):
    pages = [data[i:i + PAGE] for i in range(0, len(data), PAGE)]
    head = 12 + 8 * len(pages)
    index, body = bytearray(), bytearray()
    for page in pages:
        page = page.ljust(PAGE, b'\0')
        packed = lz4block.compress(page)
        if len(packed) >= PAGE:
            packed = page                       # stored raw
        index += struct.pack('<II', head + len(body), len(packed))
        body += packed
    return b'GZL4' + struct.pack('<II', len(data), len(pages)) + bytes(index) + bytes(body)


def lz4_expand(blob):
    if len(blob) < 12 or blob[:4] != b'GZL4':
        raise ValueError('Invalid compressed ROMFS file')
    size, count = struct.unpack_from('<II', blob, 4)
    if 12 + 8 * count > len(blob) or size > count * PAGE:
        raise ValueError('Invalid compressed ROMFS file')
    out = bytearray()
    for i in range(count):
        offset, length = struct.unpack_from('<II', blob, 12 + 8 * i)
        if offset + length > len(blob):
            raise ValueError('Invalid compressed ROMFS file')
        chunk = blob[offset:offset + length]
        out += chunk if length == PAGE else lz4block.decompress(chunk, PAGE)
    return bytes(out[:size])


def raw_entries(blob, magic):
    if len(blob) < 8 or blob[:4] != magic:
        raise ValueError('Invalid app archive signature')
    count = struct.unpack_from('<I', blob, 4)[0]
    end = 8 + count * ENTRY.size
    if count > 256 or end > len(blob):
        raise ValueError('Invalid app archive table')
    result = {}
    for i in range(count):
        name, offset, size = ENTRY.unpack_from(blob, 8 + i * ENTRY.size)
        name = name.split(b'\0', 1)[0].decode('utf-8')
        parts = PurePosixPath(name)
        if (not name or '\\' in name or ':' in name or parts.is_absolute() or
                any(p in ('', '.', '..') for p in name.split('/')) or name in result or
                (magic == b'GZRF' and offset % 4096) or
                offset < end or offset + size > len(blob)):
            raise ValueError('Invalid app archive entry: ' + name)
        result[name] = blob[offset:offset + size]
    return result


def archive(files, lz4=False):
    """A romfs archive laid out as glaze-os's mkromfs.py writes it (with --lz4 if lz4)."""
    if lz4:
        files = {name: lz4_container(data) for name, data in files.items()}
        files[LZ4_MARKER] = LZ4_MARKER_DATA
    offset = (8 + len(files) * ENTRY.size + 4095) & ~4095
    table = bytearray(b'GZRF' + struct.pack('<I', len(files)))
    blobs = bytearray()
    for name, data in sorted(files.items()):
        table += ENTRY.pack(name.encode(), offset + len(blobs), len(data))
        blobs += data
        blobs += b'\0' * (-len(blobs) % 4096)
    return table + bytes(offset - len(table)) + blobs


def load_catalog(resources):
    resources = Path(resources)
    path = resources / 'apps.json'
    expected = json.loads((resources / 'manifest.json').read_text())['files'].get('apps.json')
    if hashlib.sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError('App catalog failed verification')
    return json.loads(path.read_text())


def select(catalog, requested=None):
    known = {app['id'] for app in catalog}
    chosen = set(requested if requested is not None else [a['id'] for a in catalog if a['default']])
    if chosen - known:
        raise ValueError('Unknown app selection: ' + ', '.join(sorted(chosen - known)))
    chosen.update(a['id'] for a in catalog if a.get('required'))
    return sorted(chosen)


def customize_logical(logical, catalog, chosen, resources=None):
    image = bytearray(logical)
    if len(image) != 16 * 1024 * 1024:
        raise ValueError('Invalid NAND image size')
    size = struct.unpack_from('<I', image, 4 * 16 + 12)[0] * 512
    if size > ROMFS_END - ROMFS_START:
        raise ValueError('Invalid ROMFS partition size')
    romfs = image[ROMFS_START:ROMFS_START + size]
    files, lz4 = entries(romfs, b'GZRF'), compressed(romfs)
    for app in catalog:
        if app['kind'] == 'builtin':
            name = 'bin/' + app['program']
            if name not in files:
                raise ValueError('Bundled OS does not contain ' + app['name'])
            if app['id'] not in chosen:
                del files[name]
    for app in catalog:
        if app['kind'] == 'firmware':
            for name in app['files']:
                files.pop(name, None)
                if app['id'] in chosen:
                    if resources is None:
                        raise ValueError('Selected firmware payload is unavailable')
                    files[name] = (Path(resources) / name).read_bytes()
    blob = archive(files, lz4)
    if len(blob) > ROMFS_END - ROMFS_START:
        raise ValueError('These options exceed device space. Deselect Windows CE compatibility or another optional app.')
    image[ROMFS_START:ROMFS_END] = b'\xff' * (ROMFS_END - ROMFS_START)
    image[ROMFS_START:ROMFS_START + len(blob)] = blob
    struct.pack_into('<I', image, 4 * 16 + 12, (len(blob) + 511) // 512)
    return bytes(image)


def install_packages(resources, catalog, chosen, userdata):
    resources, userdata = Path(resources), Path(userdata)
    for app in catalog:
        if app['kind'] != 'package' or app['id'] not in chosen:
            continue
        package = resources / 'packages' / (app['program'] + '.gzp')
        files = entries(package.read_bytes(), b'GZPK')
        info = dict(line.split('=', 1) for line in files.get('Info', b'').decode().splitlines() if '=' in line)
        if info.get('id') != app['program'] or info.get('exec', 'app') not in files:
            raise ValueError('Package metadata does not match ' + app['name'])
        bundle = userdata / 'Applications' / (app['program'] + '.app')
        bundle.mkdir(parents=True, exist_ok=False)
        for name, data in files.items():
            if name == 'data' or name.startswith('data/') or any(p.startswith('.pkg-') for p in name.split('/')):
                raise ValueError('Package contains reserved app data')
            target = bundle / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        (bundle / '.install-id').write_text('1')
