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


class SimpleHudTests(unittest.TestCase):
    def test_restore_chinese_dark_summary_after_settings_change(self):
        scratch=Path(__file__).resolve().parent.parent/'_scratch/test-runs'
        scratch.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=scratch) as temp:
            state=Path(temp); path=state/'settings.json'
            original={'language':'en','background':'#FFFFFFFF','customLeft':42,
                      'themeStyle':{'surface':'gradient','backgroundImage':'old.png'},
                      'multiTask':{'displayMode':'list'},'fields':{'model':True}}
            path.write_text(json.dumps(original),encoding='utf-8')
            with patch.object(lifecycle,'STATE',state), patch('monitor.server.settings',return_value={'simple_hud_enabled':True}):
                self.assertTrue(lifecycle.ensure_simple_hud())
                actual=json.loads(path.read_text(encoding='utf-8'))
                self.assertEqual(actual['language'],'zh-CN')
                self.assertEqual(actual['background'],'#FF17181C')
                self.assertEqual(actual['themeStyle']['surface'],'solid')
                self.assertEqual(actual['themeStyle']['backgroundImage'],'')
                self.assertEqual(actual['multiTask']['displayMode'],'summary')
                self.assertEqual(actual['customLeft'],42)
                self.assertFalse(lifecycle.ensure_simple_hud())
                actual['language']='en';actual['background']='#FFFFFFFF'
                path.write_text(json.dumps(actual),encoding='utf-8')
                self.assertTrue(lifecycle.ensure_simple_hud())


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
