import argparse
import hmac
import json
import os
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, parse_qs

from .engine import Engine
from .storage import Store

ROOT = Path(__file__).resolve().parent.parent
LOCAL = ROOT / '.local'


def settings():
    data = json.loads((ROOT / 'settings.example.json').read_text(encoding='utf-8'))
    if (ROOT / 'settings.local.json').exists():
        data.update(json.loads((ROOT / 'settings.local.json').read_text(encoding='utf-8-sig')))
    if data['host'] != '127.0.0.1':
        raise ValueError('监控服务只允许绑定 127.0.0.1')
    return data


def token():
    LOCAL.mkdir(exist_ok=True)
    path = LOCAL / 'token'
    if not path.exists():
        # Exclusive create avoids different tokens during concurrent first starts.
        try:
            with path.open('x', encoding='ascii') as file:
                file.write(secrets.token_urlsafe(32))
        except FileExistsError:
            pass
    value = path.read_text(encoding='ascii').strip()
    if len(value) < 32:
        raise ValueError('本地访问令牌无效')
    return value


def make_handler(engine, access_token):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Request headers and tokens never go into logs.

        def reply(self, code, data, kind='application/json; charset=utf-8'):
            body = json.dumps(data, ensure_ascii=False).encode() if kind.startswith('application/json') else data
            self.send_response(code)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Referrer-Policy', 'no-referrer')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(body)

        def valid_host(self):
            host = f'127.0.0.1:{self.server.server_port}'
            if self.headers.get('Host') != host:
                self.reply(403, {'error': '拒绝非本机来源'})
                return False
            origin = self.headers.get('Origin')
            if origin and origin != f'http://{host}':
                self.reply(403, {'error': '拒绝跨站请求'})
                return False
            return True

        def authorized(self):
            supplied = self.headers.get('Authorization', '')
            if not hmac.compare_digest(supplied, 'Bearer ' + access_token):
                self.reply(401, {'error': '请通过“打开监控”入口进入'})
                return False
            return True

        def do_GET(self):
            if not self.valid_host():
                return
            url = urlsplit(self.path)
            static = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if url.path in static:
                name, content = static[url.path]
                self.reply(200, (ROOT / 'web' / name).read_bytes(), content)
                return
            if not self.authorized():
                return
            if url.path == '/api/state':
                tasks = engine.store.tasks()
                now = time.time()
                for item in tasks:
                    item['quiet'] = item['state'] == 'running' and now - item['updated'] > engine.settings['quiet_warning_seconds']
                    item['suspected_stall'] = item['state'] == 'running' and now-item['updated'] >= engine.settings.get('stalled_notice_seconds',600)
                    # Summaries are enough for the overview; full prompts require an explicit detail request.
                    item.pop('prompt', None)
                    item.pop('last_message', None)
                self.reply(200, {'tasks': tasks, 'notices': engine.notices(), 'service_error': engine.service_error,
                                 'stalled_notice_seconds': engine.settings.get('stalled_notice_seconds',600), 'uptime': now - engine.started,
                                 'process_cpu_seconds': time.process_time(), 'last_hook_at': engine.last_hook_at,
                                 'control_mode': 'checkpoint', 'hard_interrupt_available': False,
                                 'review_enabled': engine.settings['review_enabled'], 'review_queue': engine.review_queue.qsize(),
                                 'review_mode': engine.settings.get('review_mode','economy'), 'review_model': engine.settings['review_model'],
                                 'enabled_roots': engine.settings['enabled_roots']})
            elif url.path == '/api/task':
                sid = parse_qs(url.query).get('id', [''])[0]
                task = engine.store.task(sid)
                if not task:
                    self.reply(404, {'error': '任务不存在'})
                    return
                events = engine.store.events(sid, 80)
                errors = [event for event in events if event['kind']=='PostToolUse' and engine.failed(event['payload'].get('tool_response'))]
                self.reply(200, {'task': task, 'events': events, 'recent_errors': errors[-3:], 'reviews': engine.store.reviews(sid)})
            elif url.path == '/api/gate':
                sid = parse_qs(url.query).get('id', [''])[0]
                self.reply(200, engine.gate(sid))
            else:
                self.reply(404, {'error': '不存在的入口'})

        def do_POST(self):
            if not self.valid_host() or not self.authorized():
                return
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if not 0 < size <= 262144:
                    self.reply(413, {'error': '请求大小不支持'})
                    return
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError('请求必须是对象')
                sid = payload.get('id', '')
                if self.path == '/api/event':
                    self.reply(200, engine.accept(payload))
                elif self.path == '/api/acknowledge':
                    engine.acknowledge(sid)
                    self.reply(200, {'ok': True})
                elif self.path == '/api/pause':
                    self.reply(200, engine.request_pause(sid, '用户手动暂停', payload.get('turn_id')))
                elif self.path == '/api/release':
                    task = engine.store.task(sid)
                    if task and task['state'] == 'waiting_user':
                        raise ValueError('请回到原聊天处理监控确认弹窗')
                    engine.release(sid, payload.get('turn_id'))
                    self.reply(200, {'ok': True})
                elif self.path == '/api/checkpoint-waiting':
                    engine.checkpoint_waiting(sid, payload.get('turn_id'))
                    self.reply(200, {'ok': True})
                elif self.path == '/api/checkpoint-declined':
                    engine.checkpoint_declined(sid, payload.get('turn_id'))
                    self.reply(200, {'ok': True})
                elif self.path == '/api/confirm-continue':
                    engine.release(sid, payload.get('turn_id'))
                    self.reply(200, {'ok': True})
                elif self.path == '/api/review':
                    self.reply(200, engine.request_review(sid, '用户手动复核', manual=True))
                else:
                    self.reply(404, {'error': '不存在的入口'})
            except (ValueError, TypeError, KeyError) as exc:
                self.reply(400, {'error': str(exc)[:240]})
            except Exception:
                self.reply(500, {'error': '服务处理失败，任务控制未确认'})
    return Handler


def serve():
    config = settings()
    secret = token()
    store = Store(LOCAL / 'monitor.sqlite')
    store.prune(config['retention_days'])
    engine = Engine(store, config, LOCAL)
    server = ThreadingHTTPServer((config['host'], config['port']), make_handler(engine, secret))
    server.daemon_threads = True
    engine.start()
    (LOCAL / 'service.json').write_text(json.dumps({'pid': os.getpid(), 'port': config['port'], 'started': time.time()}), encoding='utf-8')
    try:
        server.serve_forever(poll_interval=1)
    finally:
        engine.shutdown.set()
        server.server_close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['serve', 'mcp'])
    args = parser.parse_args()
    if args.mode == 'mcp':
        from .mcp_bridge import run
        run()
    else:
        serve()


if __name__ == '__main__':
    main()
