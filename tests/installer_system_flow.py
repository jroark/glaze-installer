"""System choices fail closed and never replay NAND mutations."""
import contextlib
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'installer'))
from engine import Installer

CATALOG = [{'id': 'builtin:files', 'name': 'Files', 'program': 'files', 'kind': 'builtin', 'required': True}]


class SystemFlow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'glaze.bin').write_bytes(b'standard')
        self.i = Installer(self.root, lambda event: None, '1.2', state_dir=self.root / 'state')
        self.i.manifest = {'build_id': 'release', 'os': {'version': '1.0'}}
        self.i.build = 'release'
        self.i.verify = lambda: None
        self.i.probe = lambda: {'runtime': 'Glaze', 'capabilities': 3}
        self.i.maintenance_session = contextlib.nullcontext
        self.i.maintenance_request = lambda action: {'protocol': 2, 'power_flags': 2}
        self.calls = []
        self.i.ram_boot = lambda mode: self.calls.append(('ram_boot', mode))
        self.i.wait_glaze = lambda **kw: self.calls.append(('wait', kw))
        self.i.run = self.run_command
        self.i.n = SimpleNamespace(native=lambda *a: None, encode=None,
                                   write_new=lambda path, data: path.write_bytes(data))
        self.marker = self.i.state_dir / ('system-' + hashlib.sha256(b'1.2').hexdigest()[:16] + '.json')
        for name, value in [('load_catalog', CATALOG), ('customize_logical', b'logical'),
                            ('prepare_system', (b'target', b'plan', {'write_order': [16]}))]:
            mock = patch('engine.' + name, return_value=value)
            self.addCleanup(mock.stop)
            mock.start()

    def run_command(self, command, *args):
        self.calls.append((command, *args))
        if command == 'backup':
            Path(args[0]).write_bytes(b'two-pass-checked-source')
        if command == 'apply':
            self.assertEqual(json.loads(self.marker.read_text())['phase'], 'programming')

    def test_success_saves_checked_source_and_binds_plan_before_apply(self):
        self.i.configure_system([], self.root / 'backups')
        names = [c[0] for c in self.calls]
        self.assertEqual(names, ['ram_boot', 'backup', 'apply', 'cold-reboot', 'wait'])
        folder = next((self.root / 'backups').iterdir())
        record = json.loads((folder / 'system.json').read_text())
        for name, expected in record['files'].items():
            self.assertEqual(hashlib.sha256((folder / name).read_bytes()).hexdigest(), expected)
        self.assertFalse(self.marker.exists())

    def test_uncertain_apply_is_never_replayed_or_rebooted(self):
        def run(command, *args):
            self.run_command(command, *args)
            if command == 'apply':
                raise RuntimeError('USB reply lost')
        self.i.run = run
        with self.assertRaisesRegex(RuntimeError, 'USB reply lost'):
            self.i.configure_system([], self.root / 'backups')
        with self.assertRaisesRegex(ValueError, 'Do not retry'):
            self.i.configure_system([], self.root / 'backups')
        self.assertEqual([c[0] for c in self.calls].count('apply'), 1)
        self.assertNotIn('cold-reboot', [c[0] for c in self.calls])

    def test_invalid_source_never_programmed(self):
        with patch('engine.prepare_system', side_effect=ValueError('ROMFS differs')):
            with self.assertRaisesRegex(ValueError, 'ROMFS differs'):
                self.i.configure_system([], self.root / 'backups')
        self.assertEqual([c[0] for c in self.calls], ['ram_boot', 'backup'])

    def test_wrong_build_or_no_power_never_ram_boots(self):
        self.i.build = 'different'
        with self.assertRaisesRegex(ValueError, 'matching'):
            self.i.configure_system([], self.root / 'backups')
        self.i.build = 'release'
        self.i.maintenance_request = lambda action: {'protocol': 2, 'power_flags': 0}
        with self.assertRaisesRegex(ValueError, 'external power'):
            self.i.configure_system([], self.root / 'backups')
        self.assertEqual(self.calls, [])

    def test_backup_mismatch_or_publication_failure_never_programs(self):
        for command in ('backup',):
            self.i.run = lambda *a: (_ for _ in ()).throw(RuntimeError('backup mismatch'))
            with self.assertRaisesRegex(RuntimeError, 'backup mismatch'):
                self.i.configure_system([], self.root / 'backups')
        self.i.run = self.run_command
        self.i.n.write_new = lambda *a: (_ for _ in ()).throw(OSError('publication failed'))
        with self.assertRaisesRegex(OSError, 'publication failed'):
            self.i.configure_system([], self.root / 'backups')
        self.assertNotIn('apply', [c[0] for c in self.calls])


if __name__ == '__main__':
    unittest.main()
