"""Read official account activity through app-server. No model turn is created."""
import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parent.parent
sys.path.insert(0,str(ROOT))
from monitor.reviewer import find_codex


def main():
    flags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0
    process=subprocess.Popen([find_codex(),'--disable','hooks','app-server','--stdio'],stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',creationflags=flags)
    received=queue.Queue()
    def read():
        for line in process.stdout:
            try:received.put(json.loads(line))
            except ValueError:pass
    threading.Thread(target=read,daemon=True).start()
    def send(value):
        process.stdin.write(json.dumps(value)+'\n');process.stdin.flush()
    def response(ident):
        import time
        end=time.monotonic()+40
        while time.monotonic()<end:
            data=received.get(timeout=max(.1,end-time.monotonic()))
            if data.get('id')==ident and 'method' not in data:
                if 'error' in data:raise RuntimeError(str(data['error'].get('message','Account usage unavailable'))[:250])
                return data.get('result',{})
        raise RuntimeError('Account activity request timed out')
    try:
        send({'id':1,'method':'initialize','params':{'clientInfo':{'name':'codex_monitor_usage_reader','version':'0.1.0'}}})
        response(1);send({'method':'initialized','params':{}})
        send({'id':2,'method':'account/usage/read'})
        data=response(2)
        buckets=data.get('dailyUsageBuckets')
        if buckets is not None:data['dailyUsageBuckets']=sorted(buckets,key=lambda item:item.get('startDate',''))[-14:]
        print(json.dumps(data,ensure_ascii=False))
    finally:
        process.stdin.close()
        try:process.wait(timeout=3)
        except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=3)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        print('Account activity unavailable: '+str(exc)[:250],file=sys.stderr)
        sys.exit(1)
