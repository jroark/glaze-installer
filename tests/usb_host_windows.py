"""Compile and execute production USB fixtures on Windows; never opens hardware."""
import os
from pathlib import Path
import subprocess
import shutil
import unittest

ROOT = Path(__file__).resolve().parents[1]
GLAZE = Path(os.environ.get('GLAZE_DIR', ROOT.parent / 'glaze-os'))
CACHE = ROOT / 'out/installer-downloads'
CC = os.environ.get('GLAZE_WIN_CC', str(CACHE / 'toolchain/mingw64/bin/gcc.exe'))


@unittest.skipUnless(os.name == 'nt', 'native Windows fixtures')
class NativeUSB(unittest.TestCase):
    def fixture(self, name, sources):
        folder = ROOT / 'out/native-tests'
        folder.mkdir(parents=True, exist_ok=True)
        binary = folder / (name + '.exe')
        shutil.copy2(CACHE / 'libusb/MinGW64/dll/libusb-1.0.dll', folder)
        flags = ['-std=gnu11', '-O2', '-g', '-Wall', '-Wextra', '-Wno-unused-parameter', '-Wno-unknown-pragmas',
                 '-Wno-pointer-to-int-cast', '-static', '-pthread',
                 '-include', str(ROOT / 'installer/compat.h')]
        for path in (GLAZE / 'lib/include', GLAZE / 'tools/glaze-usb', ROOT / 'installer/compat', CACHE / 'libusb/include',
                     GLAZE.parent / 'be300/src/hw'):
            flags.append('-I' + str(path))
        flags.append('-I' + str(CACHE / 'libusbK-3.1.0.0-src/libusbK-3.1.0.0-src/includes'))
        with (folder / (name + '.log')).open('w', encoding='utf-8') as log:
            build = subprocess.run([CC, *flags, *map(str, sources),
                                    str(CACHE / 'libusb/MinGW64/static/libusb-1.0.dll.a'),
                                    '-lbcrypt', '-o', str(binary)],
                                   stdout=log, stderr=subprocess.STDOUT)
            self.assertEqual(build.returncode, 0, 'See ' + str(log.name))
            result = subprocess.run([str(binary)], stdout=log, stderr=subprocess.STDOUT, timeout=60)
            self.assertEqual(result.returncode, 0, 'See ' + str(log.name))

    def test_wire(self):
        self.fixture('usb-wire', [GLAZE / 'tests/native/usb_wire.c'])

    def test_driver(self):
        self.fixture('usb-driver', [GLAZE / 'tests/native/usb_driver.c', GLAZE.parent / 'be300/src/hw/usbf.c'])

    def test_client_failures(self):
        self.fixture('usb-client', [GLAZE / 'tests/native/usb_client_failures.c', GLAZE / 'tools/glaze-usb/pcconnect.c'])

    def test_capture(self):
        self.fixture('nand-backup', [GLAZE / 'tests/native/nand_backup.c', GLAZE / 'tools/glaze-usb/nand.c'])

    def test_writer(self):
        self.fixture('nand-writer', [GLAZE / 'tests/native/nand_writer.c', GLAZE / 'tools/glaze-usb/nand_write.c'])

    def test_windows_reset(self):
        self.fixture('windows-usb', [ROOT / 'tests/windows_usb.c', ROOT / 'installer/windows_usb.c'])

    def test_pcconnect(self):
        self.fixture('usb-pcconnect', [GLAZE / 'tests/native/usb_pcconnect.c', GLAZE / 'tools/glaze-usb/pcconnect.c'])

    def test_staging(self):
        self.fixture('usb-ce-staging', [GLAZE / 'tests/native/usb_ce_staging.c'])


if __name__ == '__main__':
    unittest.main()
