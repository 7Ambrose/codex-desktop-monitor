"""Persistent stdio MCP adapter. Normal events require no new Python process."""
import json
import os
import queue
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request

from .server import settings, token


class Bridge:
    def __init__(self, send):
        self.send = send
        self.config = settings()
        self.secret = token()
        self.pending = {}
        self.counter = 0
        self.lock = threading.Lock()
        self.elicitation = False

    def api(self, path, payload=None):
        data = json.dumps(payload, ensure_ascii=False).encode() if payload is not None else None
        req = urllib.request.Request(f"http://127.0.0.1:{self.config['port']}{path}", data=data,
                                     headers={'Authorization': 'Bearer ' + self.secret, 'Content-Type': 'application/json'})
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.load(response)

    def receive(self, message):
        if 'method' not in message and 'id' in message:
            with self.lock:
                target = self.pending.get(str(message['id']))
            if target:
                target.put(message)
            return
        if message.get('method', '').startswith('notifications/'):
            return
        # Never let a model-generated recursive call enter another hook.
        if message.get('method') == 'tools/call':
            threading.Thread(target=self.handle, args=(message,), daemon=True).start()
        else:
            self.handle(message)

    def result(self, ident, value):
        self.send({'jsonrpc': '2.0', 'id': ident, 'result': value})

    def handle(self, message):
        ident, method = message.get('id'), message.get('method')
        params = message.get('params', {})
        if method == 'initialize':
            self.elicitation = 'elicitation' in params.get('capabilities', {})
            self.result(ident, {'protocolVersion': params.get('protocolVersion', '2024-11-05'),
                                'capabilities': {'tools': {}},
                                'serverInfo': {'name': 'codex-desktop-monitor', 'version': '0.1.0'}})
        elif method == 'ping':
            self.result(ident, {})
        elif method == 'tools/list':
            self.result(ident, {'tools': [{'name': 'observe', 'description': '供受信任的生命周期钩子采集事件和检查操作确认状态。不会自行恢复任务。',
                                         'inputSchema': {'type': 'object', 'properties': {'event': {'type': 'object'}}, 'required': ['event']}}]})
        elif method == 'tools/call' and params.get('name') == 'observe':
            try:
                event = params.get('arguments', {}).get('event', {})
                for field in ('tool_input','tool_response'):
                    if field in event:
                        encoded=json.dumps(event[field],ensure_ascii=False)
                        if len(encoded)>12000:
                            original=event[field]
                            event[field]={'_monitor_excerpt':encoded[:12000],'_monitor_truncated':True}
                            if isinstance(original,dict):
                                for key in ('exit_code','isError'):
                                    if key in original:event[field][key]=original[key]
                for field in ('prompt','last_assistant_message'):
                    if isinstance(event.get(field),str):event[field]=event[field][:16000]
                if os.environ.get('CODEX_MONITOR_REVIEWER') == '1':
                    outcome = {}
                else:
                    state = self.api('/api/event', event)
                    outcome = self.checkpoint(event, state)
                self.result(ident, {'content': [{'type': 'text', 'text': json.dumps(outcome, ensure_ascii=False)}], 'structuredContent': outcome})
            except Exception:
                # Hook failures must be visible. Official hooks are fail-open on errors: never claim otherwise.
                outcome = {'systemMessage': '监控连接失败：本次操作没有受到监控检查，无法确认暂停。'}
                self.result(ident, {'content': [{'type': 'text', 'text': json.dumps(outcome, ensure_ascii=False)}], 'structuredContent': outcome})
        else:
            self.send({'jsonrpc': '2.0', 'id': ident, 'error': {'code': -32601, 'message': 'Unsupported monitor method'}})

    def checkpoint(self, event, state):
        kind = event.get('hook_event_name')
        if not state.get('paused'):
            return {}
        reason = state.get('reason') or '监控发现需要你处理的问题。'
        if kind != 'PreToolUse':
            return {'systemMessage': '任务需要处理：' + reason}
        sid, turn = event['session_id'], state.get('turn_id')
        denied = {'hookSpecificOutput': {'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
                                         'permissionDecisionReason': '监控等待用户确认：' + reason},
                  'systemMessage': '后续操作已拦截；已启动的命令不受此操作撤销。'}
        if state.get('checkpoint_declined'):
            return denied
        if not self.elicitation:
            denied['systemMessage'] += ' 当前客户端未提供确认弹窗能力。'
            return denied
        self.api('/api/checkpoint-waiting', {'id': sid, 'turn_id': turn})
        with self.lock:
            self.counter += 1
            request_id = 'monitor-confirm-' + str(self.counter)
            response_queue = queue.Queue(maxsize=1)
            self.pending[request_id] = response_queue
        self.send({'jsonrpc': '2.0', 'id': request_id, 'method': 'elicitation/create',
                   'params': {'message': '任务监控已拦截下一步操作。原因：' + reason + '\n已启动的后台命令可能仍在运行。是否允许继续？',
                              'requestedSchema': {'type': 'object', 'properties': {'allow_continue': {'type': 'boolean', 'title': '允许当前任务继续'}}, 'required': ['allow_continue']}}})
        try:
            # MCP elicitation wait is excluded from hook active-execution timeout.
            response = response_queue.get(timeout=86400)
            answer = response.get('result', {})
            if answer.get('action') == 'accept' and answer.get('content', {}).get('allow_continue') is True:
                self.api('/api/confirm-continue', {'id': sid, 'turn_id': turn})
                return {'systemMessage': '用户已允许任务继续。'}
            self.api('/api/checkpoint-declined', {'id': sid, 'turn_id': turn})
            return denied
        except queue.Empty:
            return denied
        finally:
            with self.lock:
                self.pending.pop(request_id, None)


def run():
    sys.stdin.reconfigure(encoding='utf-8')
    sys.stdout.reconfigure(encoding='utf-8')
    lock = threading.Lock()
    def send(message):
        with lock:
            sys.stdout.write(json.dumps(message, ensure_ascii=False) + '\n')
            sys.stdout.flush()
    bridge = Bridge(send)
    for line in sys.stdin:
        try:
            bridge.receive(json.loads(line))
        except (ValueError, TypeError):
            send({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Invalid JSON'}})
