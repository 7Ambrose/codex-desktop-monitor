import unittest
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
from monitor import lifecycle
from monitor.lifecycle import is_desktop


class DesktopIdentityTests(unittest.TestCase):
    def test_packaged_desktop(self):
        self.assertTrue(is_desktop(r'C:\Program Files\WindowsApps\OpenAI.Codex_26.1_x64__id\app\ChatGPT.exe'))

    def test_other_chatgpt_is_not_desktop(self):
        self.assertFalse(is_desktop(r'C:\Program Files\WindowsApps\OpenAI.ChatGPT_26.1\ChatGPT.exe'))

    def test_cli_and_app_server_are_not_desktop(self):
        self.assertFalse(is_desktop(r'C:\Users\name\AppData\Local\OpenAI\Codex\bin\version\codex.exe'))


@unittest.skipUnless(os.name == 'nt', 'Windows process identity guard')
class StopGuardTests(unittest.TestCase):
    def check_stop(self, wrong_start):
        scratch = Path(__file__).resolve().parent.parent / '_scratch/test-runs'
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temp:
            root = Path(temp); (root / '.local').mkdir(); state = root / 'hud'; state.mkdir()
            started = time.time()
            child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'], creationflags=subprocess.CREATE_NO_WINDOW)
            try:
                (root / '.local/service.json').write_text(json.dumps({'pid': child.pid, 'started': started + (100 if wrong_start else 0)}))
                with patch.object(lifecycle, 'ROOT', root), patch.object(lifecycle, 'STATE', state):
                    lifecycle.stop_monitors()
                if wrong_start:
                    self.assertIsNone(child.poll(), 'A reused PID or wrong process must not be killed')
                else:
                    self.assertEqual(child.wait(timeout=3), 0)
                self.assertTrue((state / 'exit.signal').exists())
            finally:
                if child.poll() is None:
                    child.terminate(); child.wait(timeout=3)

    def test_only_verified_service_is_stopped(self):
        self.check_stop(False)

    def test_mismatched_start_time_is_preserved(self):
        self.check_stop(True)
