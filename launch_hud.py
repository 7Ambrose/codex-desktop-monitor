"""Desktop shortcut entry: open the small HUD without opening the dashboard."""
import os
from pathlib import Path
import subprocess
import sys
import traceback

ROOT = Path(__file__).resolve().parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))

if __name__ == '__main__':
    try:
        from monitor.lifecycle import start_monitors
        # Task Scheduler owns the lifecycle watcher independently of Codex.
        subprocess.run(['schtasks.exe', '/Run', '/TN', 'CodexMonitorLifecycle'],
                       creationflags=subprocess.CREATE_NO_WINDOW,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
        start_monitors()
    except Exception:
        (ROOT / '.local').mkdir(exist_ok=True)
        (ROOT / '.local/hud-launch-error.txt').write_text(traceback.format_exc(), encoding='utf-8')
