"""Resolve the installed CLI on each HUD query; no model task is started."""
import subprocess
import sys
import os
import json
import queue
import threading
import time
from pathlib import Path
from monitor.reviewer import find_codex


def read_allowance(command, input_stream=sys.stdin, output_stream=sys.stdout, timeout=17):
    """Relay only the HUD handshake and read; retry reads, never model operations.

    No cached numbers are returned. The HUD's own outer timeout is 20 seconds.
    """
    requests = []
    for expected in ('initialize', 'initialized', 'account/rateLimits/read'):
        line = input_stream.readline()
        if not line:
            return 1
        request = json.loads(line)
        if request.get('method') != expected:
            raise ValueError('This adapter only supports the HUD account reader')
        requests.append(request)
    process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                               stderr=subprocess.DEVNULL, text=True, encoding='utf-8',
                               creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    received = queue.Queue()
    def consume():
        for line in process.stdout:
            received.put(line)
        received.put(None)
    threading.Thread(target=consume, daemon=True).start()
    started = time.monotonic()
    attempts = 1
    last_error = None
    read = requests[-1]
    try:
        process.stdin.write(''.join(json.dumps(item) + '\n' for item in requests))
        process.stdin.flush()
        while time.monotonic() - started < timeout:
            try:
                line = received.get(timeout=max(.01, timeout - (time.monotonic() - started)))
            except queue.Empty:
                break
            if line is None:
                break
            response = json.loads(line)
            if response.get('id') == read.get('id'):
                if 'error' in response:
                    last_error = line
                    # Auth failures need a user sign-in; repeated reads cannot fix them.
                    message = str(response['error'].get('message', '')).lower()
                    auth_error = any(word in message for word in ('authentication required', 'not logged in', 'unauthorized'))
                    if not auth_error and attempts < 3 and time.monotonic() - started < timeout - 1:
                        attempts += 1
                        time.sleep(.25)
                        process.stdin.write(json.dumps(read) + '\n')
                        process.stdin.flush()
                        continue
                output_stream.write(line); output_stream.flush()
                return 0 if 'error' not in response else 1
            output_stream.write(line); output_stream.flush()
        if last_error:
            output_stream.write(last_error); output_stream.flush()
        return 1
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()
        process.stdin.close(); process.stdout.close()

if __name__ == '__main__':
    if sys.argv[1:] != ['app-server', '--stdio']:
        raise SystemExit('This adapter only supports the HUD account reader')
    shim = Path(__file__).resolve().parent / '.local/hud-bin'
    os.environ['PATH'] = os.pathsep.join(item for item in os.environ.get('PATH', '').split(os.pathsep)
                                       if item and Path(item).resolve() != shim.resolve())
    raise SystemExit(read_allowance([find_codex(), '--disable', 'hooks', '--disable', 'apps', '--disable', 'plugins', *sys.argv[1:]]))
