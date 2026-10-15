import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from monitor.engine import Engine
from monitor.storage import Store
from monitor.managed import Managed, Supervisor, ROOT


class ManagedTests(unittest.TestCase):
    def setUp(self):
        base=ROOT/'_scratch/test-runs';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.root=Path(self.temp.name)
        self.work=self.root/'work';self.work.mkdir();self.local=self.root/'local';self.local.mkdir()
        self.store=Store(self.local/'test.sqlite')
        self.config={'enabled_roots':[str(self.work)],'excluded_thread_ids':[], 'review_enabled':False,
            'repeat_failure_count':3,'quiet_warning_seconds':180,'review_limit_per_turn':1,'review_cooldown_seconds':600,
            'notify_completed':False,'notify_interrupted':False,'review_model':'gpt-6-luna'}
        self.engine=Engine(self.store,self.config,self.local)
        self.notice=patch('monitor.engine.notify');self.notice.start()
        self.node=str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
        mock=str(ROOT/'vendor/supervisor/test/mock-codex-app-server.mjs')
        self.manager=Managed(self.engine,client_factory=lambda settings:Supervisor(settings,executable=self.node,app_server_args=[mock]))
        self.manager.stop.set()

    def tearDown(self):
        self.manager.close();self.notice.stop();self.store.db.close();self.temp.cleanup()

    def start(self,prompt='approval test',key='request-0000000001'):
        return self.manager.start({'cwd':str(self.work),'prompt':prompt,'request_id':key})['id']

    def test_real_mcp_transport_start_approval_and_finish(self):
        sid=self.start();task=self.manager.refresh_task(sid)
        self.assertEqual(task['status'],'needs_approval')
        self.assertEqual(self.store.task(sid)['state'],'waiting_approval')
        request=task['pending'][0]
        self.manager.command(sid,'approve',{'turn_id':task['turn_id'],'request_key':request['requestKey'],'decision':'accept'})
        time.sleep(.04)
        task=self.manager.refresh_task(sid)
        self.assertFalse(task['active'])
        self.assertIn('Completed:',task['message'])

    def test_interrupt_resume_and_duplicate_start(self):
        sid=self.start();self.assertEqual(sid,self.start())
        task=self.manager.refresh_task(sid);old_turn=task['turn_id']
        self.manager.command(sid,'interrupt',{'turn_id':old_turn})
        task=self.manager.refresh_task(sid)
        self.assertFalse(task['active']);self.assertEqual(task['status'],'interrupted')
        result=self.manager.command(sid,'send',{'turn_id':old_turn,'prompt':'finish test'})
        self.assertNotEqual(result['turn_id'],old_turn)

    def test_rejects_unowned_thread_and_stale_control(self):
        with self.assertRaises(ValueError):self.manager.command('external-thread','interrupt',{'turn_id':'turn'})
        sid=self.start();task=self.manager.refresh_task(sid)
        with self.assertRaises(ValueError):self.manager.command(sid,'interrupt',{'turn_id':'old'})
        with self.assertRaises(ValueError):self.manager.command(sid,'send',{'turn_id':task['turn_id'],'prompt':'duplicate'})

    def test_outside_workspace_is_rejected_before_start(self):
        with self.assertRaises(ValueError):self.manager.start({'cwd':str(self.root),'prompt':'test','request_id':'request-0000000001'})
        self.assertIsNone(self.manager.client)
