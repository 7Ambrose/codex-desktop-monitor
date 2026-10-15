"""Read-only real-runtime compatibility probe; does not create a model turn."""
from pathlib import Path
import json
import sys

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from monitor.server import settings
from monitor.managed import Supervisor
client=Supervisor(settings(),debug=True)
try:
    result=client.call('codex_list_threads',{'limit':1})
    print(json.dumps({'read_only_connection':True,'result_keys':list(result)}))
finally:
    client.close()
