"""Run the real GUI event handler with widget doubles; never open USB or a window."""
import json
from pathlib import Path
import queue
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'installer'))
import app


class InstallerGui(unittest.TestCase):
    def run_events(self, following, probe=False):
        root, window, ttk, dialogs = Mock(), Mock(), Mock(), Mock()
        ttk.Frame.return_value.winfo_reqheight.return_value = 450
        widgets = types.SimpleNamespace(
            Tk=Mock(return_value=root), Toplevel=Mock(return_value=window),
            StringVar=Mock(), BooleanVar=Mock(), Text=Mock(),
            ttk=ttk, messagebox=dialogs, filedialog=Mock())
        pending = queue.Queue()
        if not probe:
            pending.put({'event': 'reconnect', 'text': 'Unplug and reconnect USB. Keep external power connected.'})

        def mainloop():
            if probe:
                auto_detect = next(c.args[1] for c in root.after.call_args_list if c.args[0] == 300)
                auto_detect()
            else:
                widgets.Toplevel.assert_called_once_with(root)
                window.title.assert_called_once_with('Reconnect USB')
                window.grab_set.assert_called_once()
                window.destroy.assert_not_called()
            for event in following:
                pending.put(event)
            poll = next(c.args[1] for c in root.after.call_args_list if c.args[0] == 100)
            poll()
        root.mainloop.side_effect = mainloop

        with tempfile.TemporaryDirectory(prefix='glaze-gui-test-') as tmp, \
             patch.dict(sys.modules, {'tkinter': widgets}), \
             patch.object(sys, 'argv', ['app.py', '--resources', tmp]), \
             patch.object(app.Path, 'home', return_value=Path(tmp)), \
             patch.dict(app.os.environ, {'LOCALAPPDATA': tmp}), \
             patch.object(app, 'load_catalog', return_value=[]), \
             patch.object(app, 'select', return_value=[]), \
             patch.object(app.queue, 'Queue', return_value=pending), \
             patch.object(app.threading, 'Thread'), \
             patch.object(app.subprocess, 'Popen') as popen:
            self.assertEqual(app.main(), 0)
            popen.assert_not_called()
            logs = list(Path(tmp).rglob('session-*.jsonl'))
            self.assertEqual(len(logs), 1)
            for line in logs[0].read_text().splitlines():
                json.loads(line)
        return window, dialogs

    def test_replug_prompt_dismisses_on_reconnect_and_continues(self):
        window, dialogs = self.run_events([
            {'event': 'reconnected'},
            {'event': 'status', 'text': 'Reading your device…'}])
        window.destroy.assert_called_once()
        dialogs.showerror.assert_not_called()

    def test_timeout_closes_wait_prompt_and_shows_error_with_log_path(self):
        text = 'NAND programming verified; boot verification incomplete. Unplug and reconnect USB once.'
        window, dialogs = self.run_events([
            {'event': 'error', 'text': text}, {'event': 'worker-done', 'code': 1}])
        window.destroy.assert_called_once()
        dialogs.showerror.assert_called_once()
        message = dialogs.showerror.call_args.args[1]
        self.assertIn(text, message)
        self.assertIn('Session log:', message)
        self.assertNotIn('No NAND programming', message)

    def test_background_detection_failure_does_not_open_error_dialog(self):
        _, dialogs = self.run_events([
            {'event': 'error', 'text': 'probe failed'}, {'event': 'worker-done', 'code': 1}], probe=True)
        dialogs.showerror.assert_not_called()


if __name__ == '__main__':
    unittest.main()
