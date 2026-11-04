"""Exercise the installer transport's diagnostics without opening USB."""
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
GLAZE = Path(os.environ.get('GLAZE_DIR', ROOT.parent / 'glaze-os')).resolve()


class TransportDiagnostics(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc') and shutil.which('pkg-config'), 'requires C compiler and libusb')
    def test_shared_capture_publication_and_failure_handling(self):
        flags = subprocess.run(['pkg-config', '--cflags', 'libusb-1.0'],
                               check=True, capture_output=True, text=True).stdout
        with tempfile.TemporaryDirectory(prefix='glaze-capture-test-') as tmp:
            folder = Path(tmp)
            binary = folder / 'capture-test'
            subprocess.run(['cc', '-std=gnu11', '-O2', '-Wall', '-Wextra', '-Werror',
                            '-include', str(ROOT / 'installer/compat.h'),
                            '-I' + str(GLAZE / 'tools/glaze-usb'), '-I' + str(GLAZE / 'lib/include'),
                            *shlex.split(flags), str(ROOT / 'tests/installer_capture.c'),
                            str(GLAZE / 'tools/glaze-usb/nand.c'), '-o', str(binary)], check=True)
            result = subprocess.run([str(binary), str(folder / 'snapshot.raw')],
                                    check=True, capture_output=True, text=True)
            self.assertIn('snapshot/backup: exact binary data, publication, cleanup, no overwrite, mismatch and read failure PASS', result.stdout)
            self.assertFalse((folder / 'snapshot.raw').exists())
            self.assertFalse((folder / 'snapshot.raw.partial').exists())

    @unittest.skipUnless(shutil.which('cc') and shutil.which('pkg-config'), 'requires C compiler and libusb')
    def test_errors_are_reported_without_packet_contents(self):
        flags = subprocess.run(['pkg-config', '--cflags', '--libs', 'libusb-1.0'],
                               check=True, capture_output=True, text=True).stdout
        with tempfile.TemporaryDirectory(prefix='glaze-transport-test-') as tmp:
            folder = Path(tmp)
            source = folder / 'peer.c'
            source.write_text(r'''
#include "transport.h"
#include <assert.h>
static int result;
void debug_host_close(struct usb_link *l) { (void)l; }
int debug_host_read(struct usb_link *l, void *p, size_t n, unsigned t)
{ (void)l; (void)p; (void)n; (void)t; return result; }
int debug_host_write(struct usb_link *l, const void *p, size_t n, unsigned t)
{ (void)l; (void)p; (void)n; (void)t; return result; }
int main(void) {
    struct usb_link l = {.network = (void *)1};
    char data[] = "PRIVATE NAND AND ENTROPY DATA";
    result = LIBUSB_ERROR_IO;
    assert(usb_read(&l, data, sizeof(data), 1) == result);
    result = LIBUSB_ERROR_PIPE;
    assert(usb_write(&l, data, sizeof(data), 1) == result);
    result = LIBUSB_ERROR_TIMEOUT;
    assert(usb_read(&l, data, sizeof(data), 1) == result);
    result = 0;
    assert(!usb_write(&l, data, sizeof(data), 1));
    return 0;
}
''')
            binary = folder / 'transport-test'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-I' + str(GLAZE / 'tools/glaze-usb'), str(source),
                            str(ROOT / 'installer/usb_transport.c'),
                            *shlex.split(flags), '-o', str(binary)], check=True)
            result = subprocess.run([str(binary)], check=True, capture_output=True, text=True)
            self.assertEqual(result.stdout, '')
            self.assertEqual(result.stderr.splitlines(), [
                'USB bulk IN failed: LIBUSB_ERROR_IO',
                'USB bulk OUT failed: LIBUSB_ERROR_PIPE'])


if __name__ == '__main__':
    unittest.main()
