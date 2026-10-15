"""Download pinned official HUD release, retaining partial data and verifying SHA256."""
import hashlib
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
EXPECTED = '5d0138ad6dd7d478f3c5788ba6c0dd5a7a08bdb1275e195cd537d5320ab17368'
NAME = 'CodexMonitorHUD-windows-x64.zip'


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if urllib.parse.urlsplit(newurl).hostname != urllib.parse.urlsplit(req.full_url).hostname:
            redirected.remove_header('Authorization')
        return redirected


def main():
    env = os.environ.copy()
    env.update(GIT_TERMINAL_PROMPT='0', GCM_INTERACTIVE='never')
    result = subprocess.run(['git', 'credential', 'fill'],
        input='protocol=https\nhost=github.com\n\n', text=True, capture_output=True, env=env)
    credentials = dict(line.split('=', 1) for line in result.stdout.splitlines() if '=' in line)
    headers = {'User-Agent': 'codex-monitor-setup', 'Accept': 'application/vnd.github+json'}
    if credentials.get('password'):
        headers['Authorization'] = 'Bearer ' + credentials['password']
    opener = urllib.request.build_opener(Redirect())
    release_url = 'https://api.github.com/repos/LH-03/codex-monitor-hud/releases/tags/v3.3.0'
    with opener.open(urllib.request.Request(release_url, headers=headers), timeout=20) as response:
        release = json.load(response)
    asset = next(a for a in release['assets'] if a['name'] == NAME)
    stage = ROOT / '_scratch' / 'hud-release'
    stage.mkdir(parents=True, exist_ok=True)
    target = stage / NAME
    if target.exists() and target.stat().st_size == asset['size']:
        verify(target)
        return
    parts = stage / 'parts'
    parts.mkdir(exist_ok=True)
    chunk = (asset['size'] + 7) // 8
    def fetch(index):
        start, end = index * chunk, min(asset['size'], (index + 1) * chunk) - 1
        path = parts / str(index)
        if not path.exists() and target.exists() and target.stat().st_size > start:
            with target.open('rb') as source:
                source.seek(start)
                path.write_bytes(source.read(end - start + 1))
        done = path.stat().st_size if path.exists() else 0
        if done == end - start + 1:
            return True
        part_headers = dict(headers, Accept='application/octet-stream', Range=f'bytes={start+done}-{end}')
        request = urllib.request.Request(asset['url'] + f'?download=1&part={index}&t={time.time_ns()}', headers=part_headers)
        try:
            with urllib.request.build_opener(Redirect()).open(request, timeout=15) as response:
                expected_range = f'bytes {start+done}-{end}/{asset["size"]}'
                if response.status != 206 or response.headers.get('Content-Range') != expected_range:
                    raise RuntimeError('Server did not honor the requested byte range')
                deadline = time.monotonic() + 45
                with path.open('ab') as output:
                    remaining = end - start + 1 - done
                    while remaining and time.monotonic() < deadline:
                        block = response.read(min(65536, remaining))
                        if not block:
                            break
                        output.write(block)
                        remaining -= len(block)
            return path.stat().st_size == end - start + 1
        except (OSError, TimeoutError):
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        complete = all(list(pool.map(fetch, range(8))))
    downloaded = sum(path.stat().st_size for path in parts.iterdir() if path.is_file())
    print(json.dumps({'downloaded': downloaded, 'expected': asset['size']}))
    if not complete:
        raise RuntimeError('Download incomplete; run again to resume')
    with target.open('wb') as output:
        for index in range(8):
            output.write((parts / str(index)).read_bytes())
    verify(target)


def verify(path):
    if hashlib.sha256(path.read_bytes()).hexdigest() != EXPECTED:
        raise RuntimeError('SHA256 mismatch; do not install')
    print('Verified official HUD v3.3.0 SHA256')


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc) if isinstance(exc, RuntimeError) else type(exc).__name__, file=sys.stderr)
        sys.exit(1)
