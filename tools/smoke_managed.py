"""Tiny read-only live acceptance test. Uses model quota; never run as a unit test."""
import json
from pathlib import Path
import time
import urllib.request
import urllib.error
import uuid
import sys

ROOT=Path(__file__).resolve().parent.parent
secret=(ROOT/'.local/token').read_text().strip()
def record_error(kind,value,traceback):
    (ROOT/'.local/managed-smoke-result.json').write_text(json.dumps({'ok':False,'error':str(value)},ensure_ascii=False),encoding='utf-8')
    sys.__excepthook__(kind,value,traceback)
sys.excepthook=record_error

def api(path,payload=None):
    request=urllib.request.Request('http://127.0.0.1:17863'+path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(request,timeout=55) as response:return json.load(response)
    except urllib.error.HTTPError as error:
        value=json.load(error)
        raise RuntimeError(value.get('error','HTTP request failed')) from None

def task(sid):
    return next(item for item in api('/api/state')['managed_tasks'] if item['id']==sid)

def wait_idle(sid):
    deadline=time.monotonic()+180
    while time.monotonic()<deadline:
        item=task(sid)
        if not item['active']:return item
        time.sleep(1)
    raise RuntimeError('Acceptance task did not finish within the observation window')

work=ROOT/'_scratch/managed-smoke';work.mkdir(parents=True,exist_ok=True)
existing=[item for item in api('/api/state')['managed_tasks'] if item['cwd']==str(work)]
if '--continue-existing' in sys.argv and existing:
    sid=existing[0]['id'];current=task(sid)
else:
    started=api('/api/managed/start',{'cwd':str(work),'prompt':'这是监控连通测试。不调用工具，不读写文件。请简短解释光合作用，便于测试中断。',
        'model':'gpt-6-luna','effort':'low','mode':'read-only','request_id':str(uuid.uuid4())})
    sid=started['id'];current=task(sid)
if current['active']:api('/api/managed/interrupt',{'id':sid,'turn_id':current['turn_id']})
stopped=wait_idle(sid)
print(json.dumps({'live_start':True,'stop_state':stopped['status']},ensure_ascii=False),flush=True)
api('/api/managed/send',{'id':sid,'turn_id':stopped['turn_id'],'prompt':'仅回复“监控连接测试成功”。不要调用工具，不读写文件。'})
finished=wait_idle(sid)
print(json.dumps({'live_continue':True,'final_state':finished['status'],'message':finished['message'],'error':finished['error']},ensure_ascii=False),flush=True)
if finished['status']!='completed' or '监控连接测试成功' not in finished['message']:raise RuntimeError('Live continuation was not confirmed')
(ROOT/'.local/managed-smoke-result.json').write_text(json.dumps({'ok':True,'state':finished['status'],'message':finished['message']},ensure_ascii=False),encoding='utf-8')
