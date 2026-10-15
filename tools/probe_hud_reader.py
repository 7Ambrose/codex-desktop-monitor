"""Exercise the exact HUD account protocol without starting any model task."""
import json
from pathlib import Path
import subprocess
import sys
import time
import queue
import threading

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from monitor.lifecycle import hud_environment

env = hud_environment()
messages = [
    {'id': 1, 'method': 'initialize', 'params': {'clientInfo': {'name': 'codex-monitor-hud', 'version': '3.3.0'}, 'capabilities': {'optOutNotificationMethods': ['account/updated', 'account/rateLimits/updated']}}},
    {'method': 'initialized', 'params': {}},
    {'id': 2, 'method': 'account/rateLimits/read', 'params': {}}
]
started = time.monotonic()
process = subprocess.Popen(['cmd.exe', '/d', '/c', str(ROOT / '.local/hud-bin/codex.cmd'), 'app-server', '--stdio'],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding='utf-8', env=env,
    creationflags=subprocess.CREATE_NO_WINDOW)
try:
    received = queue.Queue()
    def read():
        for line in process.stdout:
            received.put(line)
        received.put(None)
    threading.Thread(target=read, daemon=True).start()
    process.stdin.write('\n'.join(json.dumps(message) for message in messages) + '\n'); process.stdin.flush()
    lines = []
    while time.monotonic() - started < 22:
        line = received.get(timeout=max(.1, 22 - (time.monotonic() - started)))
        if line is None:
            break
        lines.append(line)
        try:
            if json.loads(line).get('id') == 2:
                break
        except ValueError:
            pass
    out, err = ''.join(lines), ''
    found = False
    for line in out.splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if value.get('id') == 2:
            found = True
            result = value.get('result', {}).get('rateLimits', {})
            print(json.dumps({'elapsed_seconds': round(time.monotonic()-started, 2), 'error': value.get('error'),
                              'windows': {key: result.get(key) for key in ('primary', 'secondary')}}))
    if not found:
        print(json.dumps({'response_received': False, 'exit_code': process.returncode, 'diagnostic': err[-500:]}))
finally:
    process.stdin.close()
    try:
        process.wait(timeout=3)
    except subprocess.TimeoutExpired:
        pass
    if process.poll() is None:
        process.kill(); process.wait()
