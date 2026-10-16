"""Local task UI adapter over the pinned upstream Supervisor MCP implementation."""
import hashlib
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time
import tomllib

from .engine import redacted, within
from .reviewer import find_codex
from .winjob import attach, close

ROOT=Path(__file__).resolve().parent.parent


class Supervisor:
    def __init__(self, settings, executable=None, app_server_args=None, debug=False):
        env=os.environ.copy()
        args=['--disable','hooks','--disable','memories','--disable','apps','--disable','plugins','-c','service_tier="default"']
        config=Path(env.get('CODEX_HOME') or Path.home()/'.codex')/'config.toml'
        configured=tomllib.loads(config.read_text(encoding='utf-8-sig')).get('mcp_servers',{}) if config.exists() else {}
        for server in configured:
            if all(char.isalnum() or char in '_-' for char in server):args+=['-c',f'mcp_servers.{server}.enabled=false']
        args+=['app-server']
        env.update(CODEX_ALLOWED_ROOTS=os.pathsep.join(settings['enabled_roots']),
                   CODEX_SUPERVISOR_DEBUG='1' if debug else '0',
                   CODEX_BIN=find_codex(settings.get('codex_path','')),CODEX_ALLOW_NETWORK='0',
                   CODEX_SUPERVISOR_MCP_NAME='codex-supervisor',
                   CODEX_APP_SERVER_ARGS=json.dumps(args))
        if executable is not None:env['CODEX_BIN']=executable
        if app_server_args is not None:env['CODEX_APP_SERVER_ARGS']=json.dumps(app_server_args)
        node=shutil.which('node') or str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node.exe')
        with (ROOT/'.local/supervisor.stderr.log').open('a',encoding='utf-8') as diagnostics:
            self.process=subprocess.Popen([node,str(ROOT/'vendor/supervisor/src/index.mjs')],cwd=ROOT,env=env,
                stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=diagnostics,text=True,encoding='utf-8',
                creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        self.job=attach(self.process)
        self.lock=threading.RLock();self.pending={};self.sequence=0
        threading.Thread(target=self._read,daemon=True,name='supervisor-rpc').start()
        self.rpc('initialize',{'protocolVersion':'2025-11-25','capabilities':{},'clientInfo':{'name':'codex-monitor-panel','version':'1.0.0'}})
        self.send({'jsonrpc':'2.0','method':'notifications/initialized'})

    def send(self, value):
        with self.lock:
            self.process.stdin.write(json.dumps(value,ensure_ascii=False)+'\n');self.process.stdin.flush()

    def _read(self):
        try:
            for line in self.process.stdout:
                try:value=json.loads(line)
                except ValueError:continue
                with self.lock: target=self.pending.get(value.get('id'))
                if target:target.put(value)
        finally:
            with self.lock:
                for target in self.pending.values():target.put({'error':{'message':'Supervisor 连接已断开，任务状态需重新核对。'}})

    def rpc(self, method, params, timeout=50):
        with self.lock:
            if self.process.poll() is not None:raise RuntimeError('任务控制后台已断开；不会自动重发任务。')
            self.sequence+=1;ident=self.sequence;target=queue.Queue();self.pending[ident]=target
        try:
            self.send({'jsonrpc':'2.0','id':ident,'method':method,'params':params})
            value=target.get(timeout=timeout)
            if 'error' in value:raise RuntimeError(str(value['error'].get('message','后台请求失败'))[:300])
            return value.get('result',{})
        except queue.Empty:
            raise RuntimeError('请求超时，执行结果暂不确定；请查看任务状态，不要重复发起。') from None
        finally:
            with self.lock:self.pending.pop(ident,None)

    def call(self, name, args):
        for attempt in range(6):
            result=self.rpc('tools/call',{'name':name,'arguments':args})
            value=result.get('structuredContent')
            if value is None:
                value=json.loads(next(item['text'] for item in result.get('content',[]) if item.get('type')=='text'))
            if not result.get('isError'):return value
            error=value.get('error',{});message=str(error.get('message','任务操作失败'))
            # Retry only a failed read that precedes every mutation, never a turn/start.
            if attempt<5 and error.get('method')=='thread/read' and 'session metadata' in message:
                time.sleep(.25);continue
            raise RuntimeError(message[:350])

    def close(self):
        try:
            self.process.stdin.close();self.process.wait(timeout=5)
        except (OSError,subprocess.TimeoutExpired):
            self.process.terminate()
        close(self.job);self.job=None


class Managed:
    def __init__(self, engine, client_factory=Supervisor):
        self.engine=engine;self.settings=engine.settings;self.factory=client_factory
        self.client=None;self.lock=threading.RLock();self.thread_locks={};self.stop=threading.Event()
        self.path=Path(engine.local_dir)/'managed.json'
        saved=json.loads(self.path.read_text(encoding='utf-8')) if self.path.exists() else {}
        self.tasks=saved.get('tasks',{});self.requests=saved.get('requests',{})
        for item in self.tasks.values():
            was_active=item.get('active',False)
            item.update(active=False,pending=[],cursor=0)
            if was_active:
                item['status']='disconnected'
                with engine.store.transaction() as db:db.execute("UPDATE tasks SET state='disconnected' WHERE id=?",(item['id'],))
            if item.get('status')=='completed':item['error']=None
        threading.Thread(target=self._poll,daemon=True,name='managed-progress').start()

    def _save(self):
        temp=self.path.with_suffix('.tmp')
        temp.write_text(json.dumps({'tasks':self.tasks,'requests':self.requests},ensure_ascii=False),encoding='utf-8')
        os.replace(temp,self.path)

    def _client(self):
        with self.lock:
            if self.client is not None and self.client.process.poll() is not None:
                self.client.close();self.client=None
            if self.client is None:self.client=self.factory(self.settings)
            return self.client

    def overview(self):
        with self.lock:
            items=sorted(self.tasks.values(),key=lambda item:(bool(item.get('active')),item.get('updated',0)),reverse=True)[:40]
            return [redacted({key:value for key,value in item.items() if key not in ('events','cursor','pause_interrupt_turn')}) for item in items]

    def _owned(self, sid):
        with self.lock:
            if sid not in self.tasks:raise ValueError('只能控制从本面板启动的任务。')
            return self.tasks[sid]

    def _event(self, task, kind, **extra):
        return self.engine.accept({'session_id':task['id'],'turn_id':task.get('turn_id',''),'cwd':task['cwd'],
               'model':task.get('model',''),'hook_event_name':kind,'managed':True,**extra})

    def start(self, payload):
        prompt=payload.get('prompt','');cwd=payload.get('cwd','');key=payload.get('request_id','')
        if not isinstance(prompt,str) or not prompt.strip() or len(prompt)>24000:raise ValueError('请输入任务，长度不超过 24000 字符。')
        if not isinstance(key,str) or not 16<=len(key)<=128:raise ValueError('启动请求标识无效，请刷新页面。')
        path=Path(cwd).resolve(strict=True)
        if not path.is_dir() or not any(within(path,root) for root in self.settings['enabled_roots']):raise ValueError('请选择监控范围内的工作文件夹。')
        mode=payload.get('mode','workspace-write')
        if mode not in ('read-only','workspace-write'):raise ValueError('任务权限选项无效。')
        effort=payload.get('effort','')
        if effort not in ('','low','medium','high'):raise ValueError('思考强度选项无效。')
        model=payload.get('model','')
        if model not in ('','gpt-6.1-sol','gpt-6-luna','gpt-5.6-sol','gpt-5.6-luna'):raise ValueError('模型选项无效。')
        digest=hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()
        with self.lock:
            old=self.requests.get(key)
            if old:
                if old['hash']!=digest:raise ValueError('请先确认上一次启动结果，再创建新任务。')
                if old.get('id'):return {'id':old['id'],'deduplicated':True}
                raise ValueError('该启动请求正在处理或结果不确定，请勿重复启动。')
            pending=sum(1 for item in self.requests.values() if not item.get('id') and item.get('status')!='failed')
            if sum(bool(t.get('active')) for t in self.tasks.values())+pending>=4:raise ValueError('同时最多执行或等待启动 4 个面板任务；有未确认请求时请先核对状态。')
            self.requests[key]={'hash':digest,'at':time.time()};self._save()
        args={'cwd':str(path),'prompt':prompt,'sandboxMode':mode,'approvalPolicy':'on-request','networkAccess':False}
        if model:args['model']=model
        if effort:args['effort']=effort
        result=self._client().call('codex_start',args)
        sid=result['threadId']
        item={'id':sid,'cwd':str(path),'title':prompt[:64],'model':model,'effort':effort,'mode':mode,
              'turn_id':result['turnId'],'cursor':result.get('eventCursor',0),'active':True,'status':'running',
              'pending':[],'message':'','error':None,'updated':time.time(),'events':[]}
        self._event(item,'UserPromptSubmit',prompt=prompt)
        with self.lock:
            self.tasks[sid]=item;self.requests[key]['id']=sid;self._save()
        return {'id':sid}

    def command(self, sid, action, payload):
        task=self._owned(sid)
        with self.lock:lock=self.thread_locks.setdefault(sid,threading.RLock())
        with lock:
            expected=payload.get('turn_id')
            if expected!=task['turn_id']:raise ValueError('任务轮次已变化，请刷新后操作。')
            if action=='interrupt':
                result=self._client().call('codex_interrupt',{'threadId':sid,'turnId':task['turn_id']})
                with self.lock:task['status']='interrupting';self._save()
                return result
            if action=='send':
                if task.get('active'):raise ValueError('任务仍在运行，请先中断并等待确认。')
                prompt=payload.get('prompt','').strip()
                if not prompt or len(prompt)>24000:raise ValueError('请输入后续要求，长度不超过 24000 字符。')
                if self.engine.gate(sid).get('paused'):self.engine.release(sid,task['turn_id'])
                args={'threadId':sid,'prompt':prompt,'sandboxMode':task['mode'],'approvalPolicy':'on-request','networkAccess':False}
                if task['model']:args['model']=task['model']
                if task['effort']:args['effort']=task['effort']
                with self.lock:task.update(active=True,status='starting',error=None);self._save()
                result=self._client().call('codex_send',args)
                with self.lock:task.update(turn_id=result['turnId'],active=True,status='running',cursor=result.get('eventCursor',0),pending=[],error=None);self._save()
                self._event(task,'UserPromptSubmit',prompt=prompt)
                return {'id':sid,'turn_id':task['turn_id']}
            if action=='approve':
                key=payload.get('request_key');decision=payload.get('decision')
                if decision not in ('accept','decline','cancel'):raise ValueError('审批选项无效。')
                request=next((r for r in task['pending'] if r['requestKey']==key),None)
                if not request or request.get('method') not in ('item/commandExecution/requestApproval','item/fileChange/requestApproval'):
                    raise ValueError('请求已变化或该类型暂不支持审批。')
                return self._client().call('codex_resolve_approval',{'requestKey':key,'decision':decision})
            raise ValueError('不支持的任务操作。')

    def refresh_task(self, sid):
        with self.lock:lock=self.thread_locks.setdefault(sid,threading.RLock())
        with lock:return self._refresh_task(sid)

    def _refresh_task(self, sid):
        task=self._owned(sid)
        result=self._client().call('codex_status',{'threadId':sid,'afterSequence':task.get('cursor',0),'maxEvents':100})
        if result.get('activeTurnId') and result['activeTurnId']!=task['turn_id']:
            with self.lock:task['turn_id']=result['activeTurnId']
        for event in result.get('events',[]):
            params=event.get('params',{});method=event.get('method','');item=params.get('item',{})
            if method in ('item/started','item/completed') and item.get('type') in ('commandExecution','fileChange','mcpToolCall'):
                self._event(task,'PreToolUse' if method=='item/started' else 'PostToolUse',
                            tool_name=item['type'],tool_input=item.get('command',{}),tool_response={'exit_code':item.get('exitCode'), 'isError':item.get('status')=='failed','output':str(item.get('aggregatedOutput',''))[-3000:]})
            elif method=='turn/completed':
                status=params.get('turn',{}).get('status')
                if status=='interrupted':self._event(task,'Interrupt')
                elif status=='failed':
                    self._event(task,'TaskFailed',last_assistant_message=result.get('latestAgentMessage',''))
                else:self._event(task,'Stop',last_assistant_message=result.get('latestAgentMessage',''))
            elif method=='error':
                current=self.engine.store.task(sid)
                if current:self.engine.notice(current,'connection','CLI 报告连接或服务异常，正在等待最终状态；可在面板中断任务。')
        status=result.get('status',{})
        status=status.get('type','') if isinstance(status,dict) else status
        active=bool(result.get('activeTurnId'))
        pending=result.get('pendingRequests',[])
        state='needs_approval' if pending else ('running' if active else 'idle')
        if not active:
            latest=next((e for e in reversed(result.get('events',[])) if e.get('method')=='turn/completed'),None)
            state=(latest or {}).get('params',{}).get('turn',{}).get('status') or ('error' if result.get('latestError') else status or 'idle')
        current_error=None if not active and state=='completed' else redacted(result.get('latestError'))
        with self.lock:
            task.update(active=active,status=state,pending=redacted(pending),message=redacted(result.get('latestAgentMessage',''))[-24000:],
                        error=current_error,cursor=result.get('eventCursor',task['cursor']),
                        events=(task.get('events',[])+[{key:event.get(key) for key in ('method','sequence','receivedAt')} for event in result.get('events',[])])[-25:])
            if result.get('events'):task['updated']=time.time()
            self._save()
        if pending:
            current=self.engine.store.task(sid)
            if current:self.engine.notice(current,'approval','任务正在等待你确认操作，请到面板处理。',pending[0]['requestKey'])
        with self.engine.store.transaction() as db:
            if pending:db.execute("UPDATE tasks SET state='waiting_approval' WHERE id=?",(sid,))
            elif active:db.execute("UPDATE tasks SET state='running' WHERE id=? AND state='waiting_approval'",(sid,))
        if result.get('events'):
            self.engine.last_hook_at=time.time()
            with self.engine.store.transaction() as db:db.execute('UPDATE tasks SET updated=? WHERE id=?',(time.time(),sid))
        return task

    def _poll(self):
        while not self.stop.wait(2):
            with self.lock:ids=[sid for sid,item in self.tasks.items() if item.get('active')]
            for sid in ids:
                try:
                    task=self.refresh_task(sid)
                    if task.get('active') and self.engine.gate(sid).get('paused') and task.get('pause_interrupt_turn')!=task['turn_id']:
                        self.command(sid,'interrupt',{'turn_id':task['turn_id']})
                        with self.lock:task['pause_interrupt_turn']=task['turn_id'];self._save()
                except Exception as exc:
                    with self.lock:
                        self.tasks[sid].update(error=str(exc)[:350],status='reconnecting')
                        self._save()

    def close(self):
        self.stop.set()
        if self.client:self.client.close()
