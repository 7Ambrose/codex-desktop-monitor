"""Check distribution prerequisites without installing or invoking a model."""
from pathlib import Path
import shutil
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from monitor.reviewer import find_codex

codex = find_codex()
node = shutil.which('node') or str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
version = subprocess.check_output([node, '--version'], text=True).strip()
if int(version.lstrip('v').split('.')[0]) < 22:
    raise SystemExit('Node.js 22+ is required for panel tasks.')
result = subprocess.run([codex, 'login', 'status'], capture_output=True, text=True)
if result.returncode:
    raise SystemExit('Sign in to the official Codex CLI first: codex login')
print('Python, Node.js and Codex login checks passed; no model task was started.')
