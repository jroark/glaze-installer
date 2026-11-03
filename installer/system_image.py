"""Change a matching installed ROMFS, retaining every other NAND byte.

Only the existing, unambiguous tagged boot mapping is used. This cannot
upgrade an OS, remap a bad block, format a volume, or restore Windows CE.
"""
import hashlib
import struct
import zlib
from pathlib import Path
from app_selection import entries, customize_logical, select, ROMFS_START, ROMFS_END

PAGE, BLOCK, RAW_SIZE = 528, 32 * 528, 32768 * 528
FS_FIRST, FS_END = 320, 1004


def sha(data):
    return hashlib.sha256(data).digest()


def prepare_system(source, standard, catalog, requested, resources, encode):
    """Return a source-bound target, native transaction, and review.

    The caller must capture twice in a read-only repair RAM session and run
    the native boot checker on both images before invoking the writer.
    """
    if len(source) != RAW_SIZE or len(standard) != 16 * 1024 * 1024:
        raise ValueError('Invalid installed NAND geometry')
    manifest = source[PAGE:PAGE + 512]
    if (manifest[:8] != b'GZNAND1\0' or
            struct.unpack_from('<4I', manifest, 8) != (1, FS_FIRST, FS_END-FS_FIRST, FS_END) or
            struct.unpack_from('<I', manifest, 508)[0] != zlib.crc32(manifest[:508])):
        raise ValueError('Installed NAND lacks a valid physical manifest')
    mask = manifest[28:156]
    bad = {b for b in range(1024) if mask[b//8] >> (b % 8) & 1}
    if 0 in bad or len(bad) != struct.unpack_from('<I', manifest, 24)[0]:
        raise ValueError('Invalid installed quarantine policy')
    mapping = {}
    for physical in range(1024):
        if physical in bad or FS_FIRST <= physical < FS_END:
            continue
        at = physical * BLOCK
        tag = source[at + 512:at + 520]
        logical = struct.unpack_from('<I', tag, 4)[0]
        if tag[:4] != b'\xaa\x55\x0f\xff' or logical >= FS_FIRST:
            continue
        if logical in mapping or any(source[at+p*PAGE+512:at+p*PAGE+520] != tag for p in range(32)):
            raise ValueError('Ambiguous or damaged installed boot mapping')
        mapping[logical] = physical
    if set(mapping) != set(range(FS_FIRST)) or mapping[0] != 0:
        raise ValueError('Incomplete installed boot mapping')
    pages = [source[mapping[b]*BLOCK+p*PAGE:mapping[b]*BLOCK+(p+1)*PAGE]
             for b in range(FS_FIRST) for p in range(32)]
    if encode([p[:520] for p in pages]) != b''.join(pages):
        raise ValueError('Installed boot content has damaged ECC; use recovery before changing apps')
    logical = b''.join(p[:512] for p in pages)
    header = bytearray(logical[:512])
    if struct.unpack_from('<I', header, 60)[0] != (FS_END-FS_FIRST)*32:
        raise ValueError('Unexpected installed file system geometry')
    # Physical packing adjusts the file-system size; customization adjusts ROMFS.
    for offset in (60, 76):
        header[offset:offset+4] = standard[offset:offset+4]
    if header != standard[:512] or logical[1024:ROMFS_START] != standard[1024:ROMFS_START]:
        raise ValueError('Installed boot/kernel differs from the bundled OS; use a matching installer')
    size = struct.unpack_from('<I', logical, 76)[0] * 512
    standard_size = struct.unpack_from('<I', standard, 76)[0] * 512
    if not 0 < size <= ROMFS_END-ROMFS_START:
        raise ValueError('Invalid installed ROMFS size')
    current = entries(logical[ROMFS_START:ROMFS_START+size], b'GZRF')
    original = entries(standard[ROMFS_START:ROMFS_START+standard_size], b'GZRF')
    managed = {}
    for app in catalog:
        if app['kind'] == 'builtin':
            name = 'bin/' + app['program']
            managed[name] = original[name]
            if app.get('required') and name not in current:
                raise ValueError('Installed OS is missing a required app: ' + app['name'])
        elif app['kind'] == 'firmware':
            present = [name in current for name in app['files']]
            if any(present) and not all(present):
                raise ValueError('Installed hardware firmware is incomplete')
            for name in app['files']:
                managed[name] = (Path(resources) / name).read_bytes()
    if ({k:v for k,v in current.items() if k not in managed} !=
            {k:v for k,v in original.items() if k not in managed} or
            any(value != managed[name] for name, value in current.items() if name in managed)):
        raise ValueError('Installed ROMFS differs from the bundled OS; use a matching installer')
    chosen = select(catalog, requested)
    customized = customize_logical(standard, catalog, chosen, resources)
    updated = bytearray(logical)
    updated[76:80] = customized[76:80]
    updated[ROMFS_START:ROMFS_END] = customized[ROMFS_START:ROMFS_END]
    encoded = encode([updated[i*512:(i+1)*512] + pages[i][512:520] for i in range(len(pages))])
    if len(encoded) != FS_FIRST * BLOCK:
        raise ValueError('Incomplete encoded system image')
    target = bytearray(source)
    for b, physical in mapping.items():
        if updated[b*16384:(b+1)*16384] != logical[b*16384:(b+1)*16384]:
            if b != 0 and not ROMFS_START//16384 <= b < ROMFS_END//16384:
                raise ValueError('System choices unexpectedly change boot code')
            target[physical*BLOCK:(physical+1)*BLOCK] = encoded[b*BLOCK:(b+1)*BLOCK]
    target = bytes(target)
    changed = [b for b in reversed(range(1024)) if source[b*BLOCK:(b+1)*BLOCK] != target[b*BLOCK:(b+1)*BLOCK]]
    if any(b in bad or FS_FIRST <= b < FS_END for b in changed):
        raise ValueError('System choices would change a protected block')
    plan = b'GZNDTX1\0' + sha(source) + sha(target) + mask
    plan += struct.pack('<I', zlib.crc32(plan))
    review = {'version': 1, 'operation': 'built-in apps and hardware; file system retained',
              'source_sha256': sha(source).hex(), 'target_sha256': sha(target).hex(),
              'apps': chosen, 'write_order': changed, 'preserve_blocks': sorted(bad),
              'filesystem_sha256': sha(source[FS_FIRST*BLOCK:FS_END*BLOCK]).hex()}
    return target, plan, review
