"""Absolute startup entry; independent of the Windows login working directory."""
import os
from pathlib import Path
import sys
import traceback

root = Path(__file__).resolve().parent
os.chdir(root)
sys.path.insert(0, str(root))
(root / '.local').mkdir(exist_ok=True)
try:
    from monitor.lifecycle import main
    main()
except Exception:
    (root / '.local/lifecycle-crash.txt').write_text(traceback.format_exc(), encoding='utf-8')
    raise
