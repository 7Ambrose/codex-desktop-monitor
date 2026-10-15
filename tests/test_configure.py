import json
import os
import tempfile
import tomllib
import unittest
from pathlib import Path
from unittest.mock import patch

import configure


class ConfigureTests(unittest.TestCase):
    def setUp(self):
        parent=Path(__file__).resolve().parent.parent/'_scratch/test-runs'
        parent.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=parent)
        self.root=Path(self.temp.name)
        self.home=self.root/'codex-home';self.home.mkdir()
        (self.root/'settings.example.json').write_text('{"enabled_roots":[]}',encoding='utf-8')
        self.patch_root=patch.object(configure,'ROOT',self.root)
        self.patch_env=patch.dict(os.environ,{'CODEX_HOME':str(self.home)})
        self.patch_root.start();self.patch_env.start()

    def tearDown(self):
        self.patch_root.stop();self.patch_env.stop();self.temp.cleanup()

    def test_install_and_uninstall_preserve_other_configuration(self):
        original='model = "gpt-5.6-sol"\n[features]\nhooks = true\n'
        (self.home/'config.toml').write_text(original,encoding='utf-8')
        other={'type':'command','command':'echo existing'}
        (self.home/'hooks.json').write_text(json.dumps({'hooks':{'PreToolUse':[{'matcher':'Bash','hooks':[other]}]}}),encoding='utf-8')
        configure.install()
        data=tomllib.loads((self.home/'config.toml').read_text(encoding='utf-8'))
        self.assertEqual(data['model'],'gpt-5.6-sol')
        self.assertIn(configure.SERVER,data['mcp_servers'])
        configure.uninstall()
        data=tomllib.loads((self.home/'config.toml').read_text(encoding='utf-8'))
        self.assertEqual(data['model'],'gpt-5.6-sol')
        hooks=json.loads((self.home/'hooks.json').read_text(encoding='utf-8'))
        self.assertEqual(hooks['hooks']['PreToolUse'][0]['hooks'],[other])

    def test_mixed_group_does_not_drop_other_handlers(self):
        groups=[{'matcher':'Bash','hooks':[{'type':'command','command':'existing'},{'type':'mcp_tool','server':configure.SERVER,'tool':'observe'}]}]
        self.assertEqual(configure.without_monitor(groups),[{'matcher':'Bash','hooks':[{'type':'command','command':'existing'}]}])

    def test_invalid_existing_toml_is_not_overwritten(self):
        path=self.home/'config.toml'
        path.write_text('invalid = [',encoding='utf-8')
        with self.assertRaises(tomllib.TOMLDecodeError):configure.install()
        self.assertEqual(path.read_text(encoding='utf-8'),'invalid = [')
