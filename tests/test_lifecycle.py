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


class HudPreferenceTests(unittest.TestCase):
    def test_clamp_keeps_window_inside_work_area_without_resizing(self):
        adjusted = lifecycle.clamp_window_rect((-15, 891, 387, 973), (0, 0, 1600, 952))
        self.assertEqual(adjusted, (0, 870, 402, 952))
        self.assertEqual(adjusted[2] - adjusted[0], 402)
        self.assertEqual(adjusted[3] - adjusted[1], 82)

    def test_clamp_does_not_move_window_already_inside(self):
        rect = (40, 30, 440, 100)
        self.assertEqual(lifecycle.clamp_window_rect(rect, (0, 0, 1600, 952)), rect)


class HudCliShimTests(unittest.TestCase):
    def test_wrapper_keeps_unicode_paths_in_environment_not_batch_source(self):
        scratch = Path(__file__).resolve().parent.parent / '_scratch/test-runs'
        scratch.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='HUD 中文-', dir=scratch) as temp:
            root = Path(temp)
            with patch.object(lifecycle, 'ROOT', root):
                env = lifecycle.hud_environment()
            wrapper = (root / '.local/hud-bin/codex.cmd').read_text(encoding='ascii')
            self.assertNotIn('中文', wrapper)
            self.assertIn("os.environ['CODEX_MONITOR_ROOT']", wrapper)
            self.assertEqual(env['CODEX_MONITOR_ROOT'], str(root))
            self.assertEqual(env['CODEX_MONITOR_PYTHON'], str(Path(sys.executable).with_name('python.exe')))


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
