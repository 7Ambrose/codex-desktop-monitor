import json
import queue
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from monitor.engine import Engine, redacted
from monitor.mcp_bridge import Bridge
from monitor.reviewer import validate_result
from monitor.server import make_handler
from monitor.storage import Store


def conclusion(quote='生成报告', pause=True):
    return {'verdict': 'concern' if pause else 'pass', 'summary': '交付文件缺失',
            'requirement_quote': quote, 'evidence': ['预期路径不存在'], 'unverified': [], 'should_pause': pause}


class EngineFixture(unittest.TestCase):
    def setUp(self):
        self.notification_patch = patch('monitor.engine.notify')
        self.notification_patch.start()
        self.addCleanup(self.notification_patch.stop)
        test_root = Path(__file__).resolve().parent.parent / '_scratch' / 'test-runs'
        test_root.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=test_root)
        self.root = Path(self.temp.name)
        self.work = self.root / 'work'
        self.work.mkdir()
        self.local = self.root / 'private'
        self.settings = {'enabled_roots': [str(self.work)], 'excluded_thread_ids': ['excluded'],
                         'review_model': 'test-model', 'review_mode': 'economy',
                         'review_enabled': True, 'review_cooldown_seconds': 60,
                         'review_limit_per_turn': 3, 'repeat_failure_count': 3,
                         'quiet_warning_seconds': 180, 'auto_pause': True}
        self.store = Store(self.local / 'test.sqlite')
        self.engine = Engine(self.store, self.settings, self.local)

    def tearDown(self):
        self.engine.shutdown.set()
        self.store.db.close()
        self.temp.cleanup()

    def event(self, kind='UserPromptSubmit', sid='task1', turn='turn1', **extra):
        event = {'session_id': sid, 'turn_id': turn, 'cwd': str(self.work), 'model': 'test',
                 'hook_event_name': kind, 'prompt': '生成报告'}
        event.update(extra)
        return self.engine.accept(event)


class EngineTests(EngineFixture):
    def test_economy_does_not_review_every_chat_reply(self):
        self.event()
        self.event('Stop', last_assistant_message='4')
        self.assertEqual(self.engine.review_queue.qsize(), 0)

    def test_daily_limit_counts_attempts(self):
        self.event()
        self.settings['review_daily_limit']=1
        with self.store.transaction() as db:
            db.execute("INSERT INTO decisions(task_id,turn_id,at,action,reason) VALUES(?,?,?,?,?)", ('another','other',time.time(),'review_started','test'))
        result=self.engine.request_review('task1','test',manual=True)
        self.assertFalse(result['queued'])
        self.assertEqual(self.engine.review_queue.qsize(),0)

    def test_ignored_paths_and_threads(self):
        self.assertTrue(self.event(sid='excluded')['ignored'])
        self.assertTrue(self.event(cwd=str(self.root / 'outside'))['ignored'])
        self.assertEqual(self.store.tasks(), [])

    def test_pause_is_scoped_and_not_claimed_as_interrupted(self):
        self.event()
        self.event(sid='task2')
        self.engine.request_pause('task1', '异常', 'turn1')
        self.assertTrue(self.engine.gate('task1')['paused'])
        self.assertFalse(self.engine.gate('task2')['paused'])
        self.assertEqual(self.store.task('task1')['pause_confirmed'], 0)
        self.engine.checkpoint_waiting('task1', 'turn1')
        self.assertEqual(self.store.task('task1')['state'], 'waiting_user')
        self.assertEqual(self.store.task('task1')['pause_confirmed'], 0)

    def test_declined_checkpoint_can_be_released_explicitly(self):
        self.event()
        self.engine.request_pause('task1','异常','turn1')
        self.engine.checkpoint_waiting('task1','turn1')
        self.engine.checkpoint_declined('task1','turn1')
        self.assertTrue(self.engine.gate('task1')['checkpoint_declined'])
        self.engine.release('task1','turn1')
        self.assertFalse(self.engine.gate('task1')['paused'])

    def test_stale_review_cannot_pause_new_turn(self):
        self.event()
        snapshot = self.engine.snapshot('task1')
        self.event(turn='turn2', prompt='改为只做说明')
        self.assertFalse(self.engine.apply_review(snapshot, conclusion(), {}))
        self.assertFalse(self.engine.gate('task1')['paused'])
        self.assertEqual(self.store.reviews('task1')[0]['stale'], 1)

    def test_tool_activity_invalidates_pending_review(self):
        self.event()
        snapshot = self.engine.snapshot('task1')
        self.event('PostToolUse', tool_response={'exit_code': 0})
        self.assertFalse(self.engine.apply_review(snapshot, conclusion(), {}))

    def test_stale_stop_does_not_finish_current_turn(self):
        self.event()
        self.event(turn='turn2')
        result = self.event('Stop', turn='turn1')
        self.assertTrue(result['stale'])
        self.assertEqual(self.store.task('task1')['turn_id'], 'turn2')
        self.assertEqual(self.store.task('task1')['state'], 'running')

    def test_unsupported_quote_cannot_pause(self):
        self.event()
        snapshot = self.engine.snapshot('task1')
        self.engine.apply_review(snapshot, conclusion('用户从未要求'), {})
        self.assertFalse(self.engine.gate('task1')['paused'])

    def test_actual_interrupt_confirmation(self):
        self.event()
        self.engine.request_pause('task1', '异常', 'turn1')
        self.event('Interrupt')
        self.assertEqual(self.store.task('task1')['state'], 'interrupted')
        self.assertEqual(self.store.task('task1')['pause_confirmed'], 1)

    def test_finished_task_flagged_without_false_pause(self):
        self.event()
        self.event('Stop', last_assistant_message='已完成')
        snapshot = self.engine.snapshot('task1')
        self.engine.apply_review(snapshot, conclusion(), {})
        self.assertEqual(self.store.task('task1')['state'], 'needs_attention')
        self.assertEqual(self.store.task('task1')['pause_confirmed'], 0)

    def test_pending_pause_not_bypassed_by_new_prompt(self):
        self.event()
        self.engine.request_pause('task1', '异常', 'turn1')
        self.event(turn='turn2')
        self.assertTrue(self.engine.gate('task1')['paused'])
        with self.assertRaises(ValueError):
            self.engine.release('task1', 'turn1')
        self.engine.release('task1', 'turn2')
        self.assertFalse(self.engine.gate('task1')['paused'])

    def test_repeated_explicit_failures_queue_once(self):
        self.event()
        for _ in range(4):
            self.event('PostToolUse', tool_name='Bash', tool_input={'command':'bad'}, tool_response={'exit_code':1,'output':'failed'})
        self.assertEqual(self.engine.review_queue.qsize(), 1)
        self.assertFalse(self.engine.gate('task1')['paused'])

    def test_changed_strategy_not_treated_as_identical(self):
        self.event()
        for index in range(4):
            self.event('PostToolUse', tool_name='Bash', tool_input={'command':str(index)}, tool_response={'exit_code':1})
        self.assertEqual(self.engine.review_queue.qsize(), 0)

    def test_artifacts_are_bounded_and_sensitive_paths_excluded(self):
        output = self.work / 'report.txt'
        output.write_text('可检查的产物', encoding='utf-8')
        secret = self.work / 'secret.txt'
        secret.write_text('private', encoding='utf-8')
        self.event(prompt=f'生成报告 {output} {secret}')
        checks = self.engine.snapshot('task1')['artifact_checks']
        self.assertEqual(len(checks), 1)
        self.assertEqual(checks[0]['excerpt'], '可检查的产物')

    def test_redacts_known_secrets(self):
        result = redacted({'api_key':'sk-'+ 'a'*30, 'nested':'Bearer '+'a'*30})
        self.assertNotIn('a'*30, json.dumps(result))

    def test_invalid_review_schema_rejected(self):
        bad=conclusion();bad['evidence']=[]
        with self.assertRaises(ValueError):
            validate_result(bad)


class HttpTests(EngineFixture):
    def setUp(self):
        super().setUp()
        self.secret='x'*40
        self.http=ThreadingHTTPServer(('127.0.0.1',0), make_handler(self.engine,self.secret))
        self.thread=threading.Thread(target=self.http.serve_forever,daemon=True)
        self.thread.start()
        self.base=f'http://127.0.0.1:{self.http.server_port}'

    def tearDown(self):
        self.http.shutdown();self.http.server_close();self.thread.join()
        super().tearDown()

    def request(self,path,body=None,headers=None):
        req=urllib.request.Request(self.base+path,data=json.dumps(body).encode() if body is not None else None,
                                   headers=headers or {'Authorization':'Bearer '+self.secret})
        with urllib.request.urlopen(req) as response:
            return json.load(response)

    def test_api_requires_token_and_rejects_foreign_origin(self):
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/state',headers={'Authorization':'bad'})
        self.assertEqual(error.exception.code,401)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/pause', {'id':'task1'},headers={'Authorization':'Bearer '+self.secret,'Origin':'https://evil.example'})
        self.assertEqual(error.exception.code,403)

    def test_end_to_end_event_and_pause(self):
        self.request('/api/event', {'session_id':'task1','turn_id':'turn1','cwd':str(self.work),'hook_event_name':'UserPromptSubmit','prompt':'生成报告'})
        self.request('/api/pause', {'id':'task1','turn_id':'turn1'})
        result=self.request('/api/state')
        self.assertFalse(result['hard_interrupt_available'])
        self.assertEqual(result['tasks'][0]['state'],'pause_requested')
        self.assertNotIn('prompt',result['tasks'][0])

    def test_pending_elicitation_cannot_be_bypassed_by_panel(self):
        self.event();self.engine.request_pause('task1','异常','turn1');self.engine.checkpoint_waiting('task1','turn1')
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/release',{'id':'task1','turn_id':'turn1'})
        self.assertEqual(error.exception.code,400)


class BridgeTests(unittest.TestCase):
    def bridge(self, supports=True, answer=True):
        sent=[]
        with patch('monitor.mcp_bridge.settings',return_value={'port':17863}),patch('monitor.mcp_bridge.token',return_value='x'*40):
            bridge=Bridge(lambda value:send(value))
        def send(value):
            sent.append(value)
            if value.get('method')=='elicitation/create':
                bridge.receive({'id':value['id'],'result':{'action':'accept','content':{'allow_continue':answer}}})
        bridge.elicitation=supports
        bridge.api=lambda path,payload=None: sent.append({'api':path}) or {}
        return bridge,sent

    def test_acceptance_releases_only_after_human_reply(self):
        bridge,sent=self.bridge()
        outcome=bridge.checkpoint({'hook_event_name':'PreToolUse','session_id':'task1'}, {'paused':True,'reason':'异常','turn_id':'turn1'})
        self.assertIn('用户已允许',outcome['systemMessage'])
        self.assertTrue(any(v.get('api')=='/api/confirm-continue' for v in sent))

    def test_declining_does_not_release(self):
        bridge,sent=self.bridge(answer=False)
        outcome=bridge.checkpoint({'hook_event_name':'PreToolUse','session_id':'task1'}, {'paused':True,'reason':'异常','turn_id':'turn1'})
        self.assertEqual(outcome['hookSpecificOutput']['permissionDecision'],'deny')
        self.assertFalse(any(v.get('api')=='/api/confirm-continue' for v in sent))

    def test_no_elicitation_support_blocks_tool_but_never_claims_task_stopped(self):
        bridge,sent=self.bridge(supports=False)
        outcome=bridge.checkpoint({'hook_event_name':'PreToolUse','session_id':'task1'}, {'paused':True,'reason':'异常','turn_id':'turn1'})
        self.assertEqual(outcome['hookSpecificOutput']['permissionDecision'],'deny')
        self.assertFalse(any(v.get('method')=='elicitation/create' for v in sent))


if __name__=='__main__':
    unittest.main()
