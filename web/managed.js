'use strict';
let managedRequest=null,selectedTaskId=null,managedData=null,managedRenderKey='',composerTask=undefined;
const drafts=new Map(),historyCache=new Map(),historyLoading=new Set();
let newTaskSettings=null;
const managedStates={running:'执行中',starting:'正在继续',reconnecting:'连接待确认',interrupting:'正在中断',needs_approval:'等你确认',completed:'本轮完成',idle:'等待继续',interrupted:'已中断',failed:'执行失败',error:'执行失败',disconnected:'连接已断开'};
try{selectedTaskId=localStorage.getItem('monitor_selected_task')||null;}catch{}
function rememberSelection(){try{if(selectedTaskId)localStorage.setItem('monitor_selected_task',selectedTaskId);else localStorage.removeItem('monitor_selected_task');}catch{}}
function currentManaged(){return managedData?.managed_tasks?.find(task=>task.id===selectedTaskId)||null;}
function chooseManaged(id){
  if(document.getElementById('managed-form').dataset.busy==='true')return;
  const prompt=document.getElementById('managed-prompt');
  drafts.set(selectedTaskId||'_new',prompt.value);
  if(selectedTaskId===null)newTaskSettings={cwd:document.getElementById('managed-cwd').value,model:document.getElementById('managed-model').value,effort:document.getElementById('managed-effort').value,mode:document.getElementById('managed-mode').value};
  selectedTaskId=id;rememberSelection();managedRenderKey='';
  prompt.value=drafts.get(id||'_new')||'';
  document.getElementById('managed-feedback').textContent='沿用 Codex 登录';
  document.getElementById('detail').hidden=true;
  if(managedData)renderManaged(managedData);
}
function renderManaged(data){
  managedData=data;const tasks=data.managed_tasks||[];
  if(selectedTaskId&&!tasks.some(task=>task.id===selectedTaskId)){selectedTaskId=null;rememberSelection();}
  const task=currentManaged(),busy=document.getElementById('managed-form').dataset.busy==='true';
  const nav=document.getElementById('managed-nav');
  nav.replaceChildren(...tasks.map(item=>{
    const button=document.createElement('button');button.type='button';button.className='task-nav'+(selectedTaskId===item.id?' selected':'');
    const dot=element('span','nav-dot'+(item.error||item.pending.length?' problem':item.active?' busy':''));
    const text=element('span','nav-text');text.append(element('strong','',item.title),element('small','',managedStates[item.status]||'等待更新'));button.append(dot,text);
    button.addEventListener('click',()=>chooseManaged(item.id));return button;
  }));
  if(!tasks.length)nav.append(element('p','meta','你的任务会保存在这里'));
  document.getElementById('managed-section').hidden=!task;
  document.getElementById('managed-welcome').hidden=!!task;
  document.getElementById('chat-title').textContent=task?task.title:'新任务';
  document.getElementById('chat-caption').textContent=task?task.cwd:'选择文件夹，然后描述要做的事';
  const submit=document.getElementById('managed-submit');
  submit.disabled=!data.managed_available||busy||!!task?.active;
  submit.textContent=busy?'发送中…':task?'继续 ↑':'发送 ↑';
  const prompt=document.getElementById('managed-prompt');
  prompt.placeholder=task?(task.active?'任务正在执行；需要补充时可先中断。':'补充要求，或直接点“继续”……'):'描述任务，或粘贴报错……';
  const fields=['cwd','model','effort','mode'];
  if(composerTask!==selectedTaskId){
    for(const name of fields){
      const input=document.getElementById('managed-'+name);
      if(task)input.value=task[name]??(name==='mode'?'workspace-write':'');
      else if(newTaskSettings)input.value=newTaskSettings[name];
    }
    composerTask=selectedTaskId;
  }
  for(const name of fields)document.getElementById('managed-'+name).disabled=!!task||busy;
  const cwd=document.getElementById('managed-cwd');
  if(!cwd.value&&!cwd.matches(':focus')&&data.enabled_roots?.length)cwd.value=data.enabled_roots[0];
  const model=document.getElementById('managed-model'),effort=document.getElementById('managed-effort');
  document.getElementById('composer-config-label').textContent=(model.value?model.options[model.selectedIndex]?.text:'Codex 默认模型')+' · '+(effort.value?({low:'低',medium:'中',high:'高'}[effort.value]+'推理'):'Codex 默认推理');
  const key=JSON.stringify(task?[task.id,task.status,task.turn_id,task.active,task.message,task.error,task.pending,historyCache.get(task.id)?.key]:[]);
  if(key!==managedRenderKey){
    const area=document.getElementById('managed-tasks');
    area.replaceChildren(...(task?[managedCard(task)]:[]));managedRenderKey=key;
  }
  if(task)loadManagedHistory(task);
}
async function loadManagedHistory(task){
  const key=task.turn_id+':'+task.status;
  if(historyCache.get(task.id)?.key===key||historyLoading.has(task.id))return;
  historyLoading.add(task.id);
  try{
    const result=await api('/api/task?id='+encodeURIComponent(task.id));
    const messages=[];
    for(const event of result.events||[]){
      if(event.kind==='UserPromptSubmit'&&event.payload.prompt)messages.push({role:'user',text:event.payload.prompt,turn:event.turn_id});
      if(event.kind==='Stop'&&event.payload.last_assistant_message)messages.push({role:'assistant',text:event.payload.last_assistant_message,turn:event.turn_id});
    }
    historyCache.set(task.id,{key,messages:messages.slice(-16)});
    managedRenderKey='';
  }catch{historyCache.set(task.id,{key,messages:[]});}
  finally{historyLoading.delete(task.id);}
  if(managedData&&selectedTaskId===task.id)renderManaged(managedData);
}
function messageBubble(role,text){
  const box=element('section','message '+role);box.append(element('div','message-role',role==='user'?'你':'Codex'),element('div','message-body',text));return box;
}
function managedCard(task){
  const card=element('article','managed-conversation');
  const head=element('div','task-top');head.append(element('h3','','任务进展'),element('span','badge',managedStates[task.status]||'等待更新'));card.append(head);
  const messages=historyCache.get(task.id)?.messages||[];
  if(!messages.length)card.append(messageBubble('user',task.title));
  else for(const message of messages)card.append(messageBubble(message.role,message.text));
  const alreadyShown=messages.some(message=>message.role==='assistant'&&message.text===task.message);
  if(task.message&&!alreadyShown)card.append(messageBubble('assistant',task.message));
  else if(task.active&&!task.message)card.append(element('p','meta','Codex 正在处理…'));
  if(task.error){
    const text=typeof task.error==='string'?task.error:(task.error.message||'连接异常');
    card.append(element('p','reason',/Reconnecting|timed out|stream disconnected/i.test(text)?'连接暂时中断，CLI 正在重连。可以等待，也可以中断任务。':text));
    const details=element('details','');details.append(element('summary','','技术详情'),element('pre','task-output',typeof task.error==='string'?task.error:JSON.stringify(task.error,null,2)));card.append(details);
  }
  for(const request of task.pending){
    const box=element('section','approval-box'),params=request.params||{};
    const supported=['item/commandExecution/requestApproval','item/fileChange/requestApproval'].includes(request.method);
    box.append(element('h3','',supported?'这一步需要你确认':'需要处理的请求'));
    if(params.reason)box.append(element('p','',params.reason));
    const command=params.command;
    box.append(element('pre','',command?(Array.isArray(command)?command.join(' '):String(command)):JSON.stringify(params.changes||params,null,2)));
    if(supported){
      for(const [label,decision] of [['允许这一次','accept'],['拒绝','decline']])box.append(button(label,()=>api('/api/managed/approve',{id:task.id,turn_id:task.turn_id,request_key:request.requestKey,decision})));
    }else box.append(element('p','meta','暂不支持回答这类请求。可以中断，再补充说明继续。'));
    card.append(box);
  }
  const actions=element('div','buttons');
  if(task.active)actions.append(button('中断任务',()=>api('/api/managed/interrupt',{id:task.id,turn_id:task.turn_id}),'stop-button'));
  actions.append(button('进展与问题',()=>showDetail(task.id)),button('检查结果质量',async()=>{const value=await api('/api/review',{id:task.id});toast(value.queued?'已排队检查，将使用额外模型用量':value.reason);}));
  card.append(actions);return card;
}
document.getElementById('new-task').addEventListener('click',()=>chooseManaged(null));
document.getElementById('monitor-toggle').addEventListener('click',event=>{
  const open=document.querySelector('.sidebar').classList.toggle('monitor-open');
  event.currentTarget.setAttribute('aria-expanded',String(open));
});
document.getElementById('managed-form').addEventListener('change',()=>{if(managedData)renderManaged(managedData);});
document.getElementById('managed-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget,feedback=document.getElementById('managed-feedback');
  if(form.dataset.busy==='true')return;
  const task=currentManaged();if(task?.active)return;
  const prompt=document.getElementById('managed-prompt').value.trim();
  if(!task&&!prompt){feedback.textContent='先描述一下你想做什么';document.getElementById('managed-prompt').focus();return;}
  const payload={cwd:document.getElementById('managed-cwd').value.trim(),model:document.getElementById('managed-model').value,effort:document.getElementById('managed-effort').value,mode:document.getElementById('managed-mode').value,prompt};
  const signature=JSON.stringify(payload);
  if(!task&&managedRequest&&managedRequest.signature!==signature){feedback.textContent='上一启动请求结果还没确认，请先查看任务列表。';return;}
  if(!task&&!managedRequest)managedRequest={signature,key:crypto.randomUUID()};
  form.dataset.busy='true';feedback.textContent=task?'正在继续任务…':'正在启动任务…';if(managedData)renderManaged(managedData);
  try{
    let id=task?.id;
    if(task)await api('/api/managed/send',{id,turn_id:task.turn_id,prompt:prompt||'请从中断处继续完成原任务，先核对已完成操作，避免重复执行。'});
    else{id=(await api('/api/managed/start',{...payload,request_id:managedRequest.key})).id;managedRequest=null;newTaskSettings={...payload};drafts.delete('_new');}
    selectedTaskId=id;rememberSelection();drafts.delete(id);document.getElementById('managed-prompt').value='';historyCache.delete(id);managedRenderKey='';
    feedback.textContent='任务已发送';
    await refresh();
  }catch(error){feedback.textContent=error.message;}
  finally{form.dataset.busy='false';if(managedData)renderManaged(managedData);}
});
