"""Resolve the installed CLI on each HUD query; no model task is started."""
import subprocess
import sys
import os
from pathlib import Path
from monitor.reviewer import find_codex

if __name__ == '__main__':
    if sys.argv[1:] != ['app-server', '--stdio']:
        raise SystemExit('This adapter only supports the HUD account reader')
    shim = Path(__file__).resolve().parent / '.local/hud-bin'
    os.environ['PATH'] = os.pathsep.join(item for item in os.environ.get('PATH', '').split(os.pathsep)
                                       if item and Path(item).resolve() != shim.resolve())
    raise SystemExit(subprocess.call([find_codex(), '--disable', 'hooks', '--disable', 'apps', '--disable', 'plugins', *sys.argv[1:]]))
