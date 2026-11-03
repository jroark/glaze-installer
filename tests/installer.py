"""Wizard orchestration tests: never open USB or program hardware."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'installer'))
from engine import Installer, digest


class InstallerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.events = []
        self.engine = Installer(self.root, self.events.append, state_dir=self.root / 'state')

    def record(self):
        names = ['original-ce.raw', 'candidate.raw', 'inventory.json', 'placement.json', 'install.bin', 'review.json']
        for name in names:
            (self.root / name).write_bytes(b'{}')
        record = {'version': 1, 'device': '1.2', 'files': {n: digest(self.root / n) for n in names}}
        path = self.root / 'installation.json'
        path.write_text(json.dumps(record))
        return path

    def test_device_status_uses_only_installer_capability(self):
        with patch.object(self.engine, 'run') as run:
            self.engine.device_status(1)
            run.assert_not_called()
            self.engine.install_ui = True
            self.engine.device_status(1)
            run.assert_called_once_with('status', 1, 0, 0)

    def test_staging_space_failure_explains_ce_app_removal(self):
        from unittest.mock import Mock
        process = Mock()
        process.stdout = iter(['No CE staging volume has enough additional free space; existing files were preserved\n'])
        process.wait.return_value = 1
        with patch('engine.subprocess.Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, 'In Windows CE, delete built-in apps'):
                self.engine.run('boot', 'artifacts')
        process.stdout = iter(['Waiting for CE PC Connect (up to 60 seconds)...\n'])
        with patch('engine.subprocess.Popen', return_value=process):
            with self.assertRaisesRegex(RuntimeError, '^boot failed'):
                self.engine.run('boot', 'artifacts')

    def test_automatic_install_keeps_chosen_backup(self):
        calls = []
        def prepare(destination, apps, verify_wince):
            folder = Path(destination) / 'saved'
            folder.mkdir()
            record = folder / 'installation.json'
            record.write_text('{}')
            (folder / 'original-ce.raw').write_bytes(b'CE')
            calls.append(('prepare', verify_wince))
            return record
        with patch.object(self.engine, 'verify'), patch.object(self.engine, 'probe', return_value={'runtime': 'CE'}), \
             patch.object(self.engine, 'prepare', side_effect=prepare), \
             patch.object(self.engine, 'apply', side_effect=lambda r: calls.append(('apply', r))):
            self.engine.install_device(self.root / 'backups', [], save_backup=True, verify_wince=False)
        self.assertEqual(calls[0], ('prepare', False))
        self.assertEqual(calls[1][0], 'apply')
        self.assertTrue((self.root / 'backups/saved/original-ce.raw').exists())
        self.assertTrue(any(e['event'] == 'backup-saved' for e in self.events))

    def test_skip_backup_removes_source_after_success_or_failure(self):
        for fails in (False, True):
            paths = []
            def prepare(destination, apps, verify_wince):
                self.assertFalse(verify_wince)
                folder = Path(destination) / 'transient'
                folder.mkdir()
                source = folder / 'original-ce.raw'
                source.write_bytes(b'CE')
                record = folder / 'installation.json'
                record.write_text('{}')
                paths.append(source)
                return record
            def apply(record):
                self.assertTrue(paths[-1].exists())
                if fails:
                    raise RuntimeError('simulated failure')
            with patch.object(self.engine, 'verify'), patch.object(self.engine, 'probe', return_value={'runtime': 'CE'}), \
                 patch.object(self.engine, 'prepare', side_effect=prepare), patch.object(self.engine, 'apply', side_effect=apply):
                if fails:
                    with self.assertRaisesRegex(RuntimeError, 'simulated failure'):
                        self.engine.install_device(self.root / 'unused', [], save_backup=False, verify_wince=False)
                else:
                    self.engine.install_device(self.root / 'unused', [], save_backup=False, verify_wince=False)
            self.assertFalse(paths[-1].exists())
            self.assertFalse((self.root / 'unused').exists())
        self.assertFalse(any(e['event'] == 'backup-saved' for e in self.events))

    def test_skip_wince_check_omits_ce_execution_probe(self):
        from app_selection import archive, entries
        (self.root / 'ram').mkdir()
        (self.root / 'ram/romfs.img').write_bytes(archive({}))
        self.engine.verify_wince = False
        def check_marker(*args):
            if args[0] == 'boot':
                files = entries((Path(args[1]) / 'romfs.img').read_bytes(), b'GZRF')
                self.assertEqual(files['installer/session'], b'GZINST1\n')
        with patch.object(self.engine, 'run', side_effect=check_marker) as run, patch.object(self.engine, 'wait_glaze'):
            self.engine.ram_boot('ro')
        self.assertNotIn('installer/session', entries((self.root / 'ram/romfs.img').read_bytes(), b'GZRF'))
        self.assertEqual(run.call_args.args[0], 'boot')
        self.assertEqual(run.call_args.args[-1], '--skip-ce-test')

    def test_reconnect_refreshes_stale_usb_configuration(self):
        clock = [0]
        calls = []
        def run(command):
            calls.append(command)
            if command == 'reset-link':
                return []
            if 'reset-link' not in calls:
                raise RuntimeError('USB: LIBUSB_ERROR_OTHER')
            return [{'event': 'device', 'runtime': 'Glaze'}, {'event': 'capabilities', 'value': 4096}]
        with patch('engine.time.monotonic', side_effect=lambda: clock[0]), \
             patch('engine.time.sleep', side_effect=lambda n: clock.__setitem__(0, clock[0] + n)), \
             patch.object(self.engine, 'run', side_effect=run):
            self.engine.wait_glaze(4096)
        self.assertEqual(calls, ['probe', 'probe', 'probe', 'reset-link', 'probe'])

    def test_reconnect_retries_reset_when_usb_was_powered_down(self):
        clock, resets = [0], [0]
        def run(command):
            if command == 'reset-link':
                resets[0] += 1
                if resets[0] == 1:
                    raise RuntimeError('USB not ready')
                return []
            if resets[0] < 2:
                raise RuntimeError('USB: LIBUSB_ERROR_OTHER')
            return [{'event': 'device', 'runtime': 'Glaze'}, {'event': 'capabilities', 'value': 4096}]
        with patch('engine.time.monotonic', side_effect=lambda: clock[0]), \
             patch('engine.time.sleep', side_effect=lambda n: clock.__setitem__(0, clock[0] + n)), \
             patch.object(self.engine, 'run', side_effect=run):
            self.engine.wait_glaze(4096)
        self.assertEqual(resets[0], 2)
        self.assertEqual(clock[0], 9)

    def test_reconnect_stops_at_deadline_with_actionable_error(self):
        clock = [0]
        with patch('engine.time.monotonic', side_effect=lambda: clock[0]), \
             patch('engine.time.sleep', side_effect=lambda n: clock.__setitem__(0, clock[0] + n)), \
             patch.object(self.engine, 'run', side_effect=RuntimeError('unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'Unplug and reconnect USB once'):
                self.engine.wait_glaze(4096)
        self.assertEqual(clock[0], 90)

    def test_connected_kernel_with_missing_capabilities_is_not_reset(self):
        with patch('engine.time.sleep'), patch.object(self.engine, 'run', return_value=[
                {'event': 'device', 'runtime': 'Glaze'}, {'event': 'capabilities', 'value': 0}]) as run:
            with self.assertRaisesRegex(RuntimeError, 'lacks required USB capabilities'):
                self.engine.wait_glaze(4096)
        self.assertEqual(run.call_args_list[0].args, ('probe',))
        self.assertEqual(run.call_count, 1)

    def test_nand_boot_waits_for_repair_session_to_exit(self):
        def response(caps):
            return [{'event': 'device', 'runtime': 'Glaze'}, {'event': 'capabilities', 'value': caps}]
        with patch('engine.time.sleep'), patch.object(self.engine, 'run', side_effect=[response(32768|16384|3), response(3)]) as run:
            self.engine.wait_glaze(programmed=True, nand_boot=True)
        self.assertEqual(run.call_count, 2)
        self.assertTrue(any(e['event'] == 'reconnected' for e in self.events))

    def test_tampered_saved_backup_never_boots_or_writes(self):
        record = self.record()
        (self.root / 'original-ce.raw').write_bytes(b'changed')
        with patch.object(self.engine, 'verify'), patch.object(self.engine, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'differs'):
                self.engine.apply(record)
            run.assert_not_called()

    def test_incomplete_record_never_boots(self):
        record = self.record()
        data = json.loads(record.read_text())
        del data['files']['original-ce.raw']
        record.write_text(json.dumps(data))
        with patch.object(self.engine, 'verify'), patch.object(self.engine, 'run') as run:
            with self.assertRaisesRegex(ValueError, 'incomplete'):
                self.engine.apply(record)
            run.assert_not_called()

    def test_install_order_and_port_binding(self):
        record = self.record()
        self.engine.manifest = {'build_id': 'test'}
        self.engine.build = 'test'
        calls = []
        with patch.object(self.engine, 'verify'), patch.object(self.engine, 'probe'), \
             patch.object(self.engine, 'ram_boot', side_effect=lambda m: calls.append(m)), \
             patch.object(self.engine, 'run', side_effect=lambda *a: calls.append(a[0])), \
             patch.object(self.engine, 'wait_glaze'):
            self.engine.apply(record)
        self.assertEqual(calls, ['repair', 'apply', 'cold-reboot'])
        self.assertEqual(self.engine.device, '1.2')
        self.assertEqual(self.events[-1]['event'], 'success')

    def test_write_failure_never_reboots_or_claims_success(self):
        record = self.record()
        with patch.object(self.engine, 'verify'), patch.object(self.engine, 'probe'), \
             patch.object(self.engine, 'ram_boot'), \
             patch.object(self.engine, 'run', side_effect=RuntimeError('write failed')) as run:
            with self.assertRaisesRegex(RuntimeError, 'write failed'):
                self.engine.apply(record)
        self.assertEqual(run.call_count, 1)
        self.assertFalse(any(e['event'] in ('verified', 'success') for e in self.events))

    def test_verified_programming_distinguished_from_boot_failure(self):
        record = self.record()
        self.engine.manifest = {'build_id': 'test'}
        with patch.object(self.engine, 'verify'), patch.object(self.engine, 'probe'), \
             patch.object(self.engine, 'ram_boot'), patch.object(self.engine, 'run'), \
             patch.object(self.engine, 'wait_glaze', side_effect=RuntimeError('timeout')):
            with self.assertRaisesRegex(RuntimeError, 'programming verified; boot verification incomplete'):
                self.engine.apply(record)
        self.assertTrue(any(e['event'] == 'verified' for e in self.events))
        self.assertFalse(any(e['event'] == 'success' for e in self.events))

    def test_prepare_refuses_existing_glaze(self):
        with patch.object(self.engine, 'verify'), patch.object(self.engine, 'probe', return_value={'runtime': 'Glaze'}), \
             patch.object(self.engine, 'ram_boot') as boot:
            with self.assertRaisesRegex(ValueError, 'stock Windows CE'):
                self.engine.prepare(self.root)
            boot.assert_not_called()

    def test_payload_integrity_before_loading_code(self):
        (self.root / 'glaze.bin').write_bytes(b'changed')
        (self.root / 'manifest.json').write_text(json.dumps({'files': {'glaze.bin': hashlib.sha256(b'original').hexdigest()}}))
        with self.assertRaisesRegex(ValueError, 'failed verification'):
            self.engine.verify()

    def test_boot_identity_must_match(self):
        record = self.record()
        self.engine.manifest = {'build_id': 'expected'}
        self.engine.build = 'old'
        with patch.object(self.engine, 'verify'), patch.object(self.engine, 'probe'), \
             patch.object(self.engine, 'ram_boot'), patch.object(self.engine, 'run'), patch.object(self.engine, 'wait_glaze'):
            with self.assertRaisesRegex(RuntimeError, 'Expected build expected, detected old'):
                self.engine.apply(record)

    def test_optional_status_failure_does_not_abort(self):
        self.engine.install_ui = True
        with patch.object(self.engine, 'run', side_effect=RuntimeError('USB disconnected')):
            self.engine.device_status(2)
        self.assertIn('Optional device status', self.events[-1]['text'])

    def test_reconnect_rejects_wrong_build(self):
        self.engine.manifest = {'build_id': 'expected'}
        self.engine.build = 'another'
        with patch('engine.time.sleep'), patch.object(self.engine, 'run', return_value=[
                {'event': 'device', 'runtime': 'Glaze'}, {'event': 'capabilities', 'value': 4096}]):
            with self.assertRaisesRegex(RuntimeError, 'Expected build expected'):
                self.engine.wait_glaze(4096)
        self.assertFalse(any(e['event'] == 'reconnected' for e in self.events))

    def test_final_boot_timeout_does_not_instruct_reinstallation(self):
        clock = [0]
        with patch('engine.time.monotonic', side_effect=lambda: clock[0]), \
             patch('engine.time.sleep', side_effect=lambda n: clock.__setitem__(0, clock[0]+n)), \
             patch.object(self.engine, 'run', side_effect=RuntimeError('unavailable')):
            with self.assertRaisesRegex(RuntimeError, 'Use Check status.*do not reinstall'):
                self.engine.wait_glaze(programmed=True)

    def test_programming_phase_blocks_second_apply(self):
        record = self.record()
        self.engine.device = '1.2'
        self.engine.save_pending(record, 'programming')
        with patch.object(self.engine, 'verify'), patch.object(self.engine, 'probe') as probe, \
             patch.object(self.engine, 'run') as run:
            with self.assertRaisesRegex(RuntimeError, 'Automatic programming retry is disabled'):
                self.engine.apply(record)
        probe.assert_not_called()
        run.assert_not_called()

    def test_matching_repair_session_avoids_second_ram_boot(self):
        record = self.record()
        self.engine.manifest = {'build_id': 'test'}
        self.engine.build = 'test'
        device = {'runtime': 'Glaze', 'capabilities': 4096 | 16384 | 32768}
        with patch.object(self.engine, 'verify'), patch.object(self.engine, 'probe', return_value=device), \
             patch.object(self.engine, 'ram_boot') as boot, patch.object(self.engine, 'run'), \
             patch.object(self.engine, 'wait_glaze'):
            self.engine.apply(record)
        boot.assert_not_called()
        self.assertFalse(self.engine.pending_path().exists())

    def test_handoff_failure_preserves_prepared_record(self):
        record = self.record()
        with patch.object(self.engine, 'verify'), patch.object(self.engine, 'probe', return_value={'runtime': 'CE'}), \
             patch.object(self.engine, 'ram_boot', side_effect=RuntimeError('handoff failed')):
            with self.assertRaisesRegex(RuntimeError, 'handoff failed'):
                self.engine.apply(record)
        self.assertEqual(self.engine.pending()['phase'], 'prepared')
        self.assertEqual(self.engine.pending()['record_sha256'], digest(record))

    def test_unknown_pending_phase_is_rejected(self):
        record = self.record()
        self.engine.save_pending(record, 'prepared')
        path = self.engine.pending_path()
        data = json.loads(path.read_text())
        data['phase'] = 'unknown'
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'Invalid pending'):
            self.engine.pending()

    def test_tampered_pending_record_is_not_resumed(self):
        record = self.record()
        self.engine.device = '1.2'
        self.engine.save_pending(record, 'prepared')
        record.write_text('{}')
        with patch.object(self.engine, 'verify'), \
             patch.object(self.engine, 'probe', return_value={'runtime': 'Glaze'}), \
             patch.object(self.engine, 'apply') as apply:
            with self.assertRaisesRegex(ValueError, 'pending installation record differs'):
                self.engine.install_device(self.root)
        apply.assert_not_called()

    def test_stalled_probe_is_killed_at_reconnect_deadline(self):
        import time
        script = self.root / 'blocked.py'
        script.write_text('import time\ntime.sleep(10)\n')
        self.engine.helper = Path(sys.executable)
        self.engine.device = str(script)
        self.engine.command_deadline = time.monotonic() + 0.2
        start = time.monotonic()
        with self.assertRaises(RuntimeError):
            self.engine.run('probe')
        self.assertLess(time.monotonic() - start, 3)

    def test_complete_pending_preparation_resumes_install_flow(self):
        record = self.record()
        saved = json.loads(record.read_text())
        saved.update(payload={'build_id': 'test'}, apps=[], verify_wince=True)
        record.write_text(json.dumps(saved))
        self.engine.device = '1.2'
        self.engine.manifest = {'build_id': 'test'}
        self.engine.build = 'test'
        self.engine.save_pending(record, 'prepared')
        device = {'runtime': 'Glaze', 'capabilities': 4096 | 16384 | 32768}
        with patch.object(self.engine, 'verify'), patch.object(self.engine, 'probe', return_value=device), \
             patch('engine.load_catalog', return_value=[]), \
             patch.object(self.engine, 'prepare') as prepare, patch.object(self.engine, 'apply') as apply:
            self.engine.install_device(self.root, [])
        prepare.assert_not_called()
        apply.assert_called_once_with(record.resolve())

    @unittest.skipUnless(sys.platform == 'win32', 'Windows helper ownership')
    def test_second_windows_helper_stops_before_device_access(self):
        import ctypes
        import subprocess
        helper = Path(__file__).resolve().parents[1] / 'out/installer/resources/bin/glaze-installer-usb.exe'
        if not helper.exists():
            self.skipTest('requires staged Windows helper')
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        kernel.CreateMutexW.restype = ctypes.c_void_p
        kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.CreateMutexW(None, True, 'Local\\GlazeInstallerUSB07CF2002')
        self.assertTrue(handle)
        try:
            result = subprocess.run([str(helper), 'auto', 'probe'], capture_output=True,
                                    text=True, encoding='utf-8', timeout=5,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('"stage":"busy"', result.stdout)
            self.assertNotIn('"event":"device"', result.stdout)
        finally:
            kernel.ReleaseMutex(handle)
            kernel.CloseHandle(handle)


class OfflinePipelineTest(unittest.TestCase):
    @unittest.skipUnless((Path(__file__).resolve().parents[1] / 'out/installer/resources/manifest.json').exists(),
                         'requires staged installer resources')
    def test_prepare_and_fresh_restore_with_production_encoder(self):
        import importlib.util
        import shutil
        root = Path(__file__).resolve().parents[1]
        # glaze-os's physical NAND fixture (GLAZE_DIR, default ../glaze-os).
        glaze = Path(__import__('os').environ.get('GLAZE_DIR', root.parent / 'glaze-os')).resolve()
        spec = importlib.util.spec_from_file_location('physical_fixture', glaze / 'tests/physical_nand.py')
        fixture = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(fixture)
        fixture.PhysicalNand.setUpClass()
        self.addCleanup(fixture.PhysicalNand.tearDownClass)
        factory = fixture.PhysicalNand.backup
        events, calls = [], []
        with tempfile.TemporaryDirectory() as tmp:
            engine = Installer(root / 'out/installer/resources', events.append, '1.2', state_dir=Path(tmp) / 'state')
            def run(*args):
                calls.append(args[0])
                if args[0] == 'probe':
                    return [{'event': 'device', 'runtime': 'CE', 'location': '1.2'}]
                if args[0] == 'backup':
                    Path(args[1]).write_bytes(factory)
                return []
            with patch.object(engine, 'run', side_effect=run), patch.object(engine, 'ram_boot'):
                engine.prepare(tmp, ['builtin:files', 'builtin:settings', 'package:sketch'])
            record = Path(next(e['record'] for e in events if e['event'] == 'prepared'))
            folder = record.parent
            self.assertEqual(json.loads(record.read_text())['apps'], ['builtin:files', 'builtin:settings', 'package:sketch'])
            # Retry after a failed handoff can reuse this installer's RO RAM
            # session instead of requiring another CE boot or touching NAND.
            resumed = Installer(root / 'out/installer/resources', events.append, '1.2', state_dir=Path(tmp) / 'state')
            resumed.install_ui = True
            resumed.build = json.loads((root / 'out/installer/resources/manifest.json').read_text())['build_id']
            def resumed_run(*args):
                if args[0] == 'probe':
                    return [{'event': 'device', 'runtime': 'Glaze', 'location': '1.2'},
                            {'event': 'capabilities', 'value': 4096 | 8}]
                return run(*args)
            with patch.object(resumed, 'run', side_effect=resumed_run), patch.object(resumed, 'ram_boot') as boot:
                resumed.prepare(tmp, [])
                boot.assert_not_called()
            older = Installer(root / 'out/installer/resources', events.append, '1.2', state_dir=Path(tmp) / 'state')
            older.build = 'previous-ram-build'
            def older_run(*args):
                if args[0] == 'probe':
                    return [{'event': 'device', 'runtime': 'Glaze', 'location': '1.2'},
                            {'event': 'capabilities', 'value': 4096 | 8}]
                return run(*args)
            with patch.object(older, 'run', side_effect=older_run), patch.object(older, 'ram_boot') as boot:
                older.prepare(tmp, [])
                boot.assert_called_once_with('ro')
            self.assertEqual((folder / 'original-ce.raw').read_bytes(), factory)
            single_pass = Installer(root / 'out/installer/resources', events.append, '1.2', state_dir=Path(tmp) / 'state')
            fast_calls = []
            def fast_run(*args):
                fast_calls.append(args[0])
                if args[0] == 'snapshot':
                    Path(args[1]).write_bytes(factory)
                    return []
                return run(*args)
            with patch.object(single_pass, 'run', side_effect=fast_run), patch.object(single_pass, 'ram_boot'):
                fast_record = single_pass.prepare(tmp, [], verify_wince=False)
            self.assertIn('snapshot', fast_calls)
            self.assertNotIn('backup', fast_calls)
            self.assertFalse(json.loads(fast_record.read_text())['verify_wince'])
            candidate = (folder / 'candidate.raw').read_bytes()
            self.assertEqual(len(candidate), 17301504)
            fresh = bytearray(candidate)
            fresh[400 * 32 * 528] ^= 1  # live filesystem changed since installation
            calls.clear()
            def restore_run(*args):
                calls.append(args[0])
                if args[0] == 'probe':
                    return [{'event': 'device', 'runtime': 'CE', 'location': '1.2'}]
                if args[0] == 'backup':
                    Path(args[1]).write_bytes(fresh)
                if args[0] == 'apply':
                    plan = Path(args[3]).read_bytes()
                    self.assertEqual(plan[8:40], hashlib.sha256(fresh).digest())
                    self.assertEqual(plan[40:72], hashlib.sha256(factory).digest())
                return []
            with patch.object(engine, 'run', side_effect=restore_run), patch.object(engine, 'ram_boot'), \
                 patch('engine.time.sleep'):
                engine.apply(record, restore=True)
            self.assertEqual(calls, ['probe', 'backup', 'apply', 'cold-reboot', 'probe'])
            self.assertEqual(events[-1]['event'], 'success')


if __name__ == '__main__':
    unittest.main()
