"""System customization against production physical packing and RS encoding."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
GLAZE = Path(os.environ.get('GLAZE_DIR', ROOT.parent / 'glaze-os'))
sys.path.insert(0, str(ROOT / 'installer'))
from app_selection import archive, entries
from system_image import prepare_system, BLOCK, FS_FIRST, FS_END
spec = importlib.util.spec_from_file_location('physical', GLAZE / 'tools/physical_nand.py')
n = importlib.util.module_from_spec(spec)
spec.loader.exec_module(n)

CATALOG = [{'id': 'builtin:' + x, 'name': x, 'program': x, 'kind': 'builtin', 'default': True,
            'required': x in ('files', 'settings')} for x in ('files', 'settings', 'calculator')]
CATALOG += [{'id': 'firmware:wl54cf', 'name': 'WL54-CF', 'program': 'wl54cf', 'kind': 'firmware',
             'default': False, 'files': ['firmware/cf8385_helper.bin', 'firmware/cf8385.bin']}]


class SystemImage(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        (cls.root / 'firmware').mkdir()
        for name in CATALOG[-1]['files']:
            (cls.root / name).write_bytes(b'firmware fixture ' + name.encode() + bytes(70000))
        logical = bytearray(b'\xff' * (16*1024*1024))
        for i, (start, count) in enumerate([(0,32), (32,1), (160,1), (10240,22528), (512,8)]):
            struct.pack_into('<II', logical, i*16+8, start, count)
        record = struct.pack('<III', 0x80f00000, 4, 0xffffffff) + bytes(4) + struct.pack('<IIII',0,0x80f00000,0,0xffffffff)
        spl = b'B000FF\n' + struct.pack('<II',0x80f00000,len(record)) + record
        logical[0x4000:0x4000+len(spl)] = spl
        files = {'bin/' + x: x.encode() for x in ('files', 'settings', 'calculator', 'springboard', 'fs')}
        files['lib/libc.so.1'] = b'library fixture'
        blob = archive(files)
        logical[0x40000:0x40000+len(blob)] = blob
        struct.pack_into('<I', logical, 76, len(blob)//512)
        cls.logical = bytes(logical)
        factory = b'\xff' * n.RAW_SIZE
        inv = {'version': 1, 'source_sha256': n.sha(factory), 'quarantined': [20,321,1005]}
        fs = bytearray(b'\x59' * (n.FS_BLOCKS * n.DATA_BLOCK))
        fs[n.DATA_BLOCK:2*n.DATA_BLOCK] = b'\xff' * n.DATA_BLOCK
        cls.source, _ = n.build(cls.logical, factory, inv, fs)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def prepare(self, source=None, requested=None, logical=None):
        return prepare_system(source if source is not None else self.source, logical or self.logical, CATALOG,
                              requested if requested is not None else ['firmware:wl54cf'], self.root, n.encode)

    def check_boot(self, raw):
        path = self.root / 'check.raw'
        path.write_bytes(raw)
        n.native(['--check-boot', path])

    def test_install_firmware_remove_app_preserve_filesystem_and_quarantine(self):
        target, plan, review = self.prepare()
        self.check_boot(self.source)
        self.check_boot(target)
        self.assertEqual(target[FS_FIRST*BLOCK:FS_END*BLOCK], self.source[FS_FIRST*BLOCK:FS_END*BLOCK])
        for b in (20,321,1005):
            self.assertEqual(target[b*BLOCK:(b+1)*BLOCK], self.source[b*BLOCK:(b+1)*BLOCK])
        self.assertEqual(plan[8:40], hashlib.sha256(self.source).digest())
        self.assertEqual(plan[40:72], hashlib.sha256(target).digest())
        self.assertNotEqual(target, self.source)
        self.assertTrue(set(review['write_order']) <= {0, *range(16,320),1004})

    def test_reinstall_builtin_and_remove_firmware_without_factory_record(self):
        target, _, _ = self.prepare()
        restored, _, review = self.prepare(target, ['builtin:calculator'])
        self.check_boot(restored)
        # Repacking restores the original standard ROMFS and preserves all FS bytes.
        again, _, unchanged = self.prepare(restored, ['builtin:calculator'])
        self.assertEqual(again, restored)
        self.assertEqual(unchanged['write_order'], [])
        self.assertTrue(review['write_order'])

    def test_reject_damaged_ecc_or_boot_mapping(self):
        for offset in (512, 520, 16*BLOCK+512):
            bad = bytearray(self.source)
            bad[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises(ValueError):
                self.prepare(bytes(bad))

    def test_reject_wrong_kernel_and_unknown_romfs_changes(self):
        for offset in (0x14000, 0x40000 + 4096):
            different = bytearray(self.logical)
            different[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaisesRegex(ValueError, 'differs'):
                self.prepare(logical=bytes(different))

    def test_reject_ambiguous_mapping(self):
        raw = bytearray(self.source)
        raw[1006*BLOCK:1007*BLOCK] = self.source[17*BLOCK:18*BLOCK]
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            self.prepare(bytes(raw))

    def test_preserves_reserved_boot_replacement(self):
        # ROMFS block 20 lives at physical 1004, outside the FS. It must be
        # updated in place; no guessed remapping or file-system writes.
        target, _, review = self.prepare()
        self.assertIn(1004, review['write_order'])
        self.assertEqual(target[1004*BLOCK+512:1004*BLOCK+520], self.source[1004*BLOCK+512:1004*BLOCK+520])


if __name__ == '__main__':
    unittest.main()
