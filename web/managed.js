'use strict';
let managedRequest=null;
const managedStates={running:'执行中',starting:'正在继续任务',reconnecting:'连接待确认，仍可尝试中断',interrupting:'正在中断，等待确认',needs_approval:'等你确认',completed:'本轮完成',idle:'等待后续要求',interrupted:'已中断',failed:'执行失败',error:'执行失败',disconnected:'连接已断开'};
const followupDrafts=new Map();
let managedRenderKey='';
function renderManaged(data){
  const tasks=data.managed_tasks||[];
  document.getElementById('managed-section').hidden=!tasks.length;
  document.getElementById('managed-submit').disabled=!data.managed_available||document.getElementById('managed-form').dataset.busy==='true';
  const cwd=document.getElementById('managed-cwd');
  if(!cwd.value&&!cwd.matches(':focus')&&data.enabled_roots?.length)cwd.value=data.enabled_roots[0];
  const key=JSON.stringify(tasks.map(task=>[task.id,task.status,task.turn_id,task.active,task.message,task.error,task.pending]));
  const area=document.getElementById('managed-tasks');
  if(key!==managedRenderKey&&!area.contains(document.activeElement)){
    area.replaceChildren(...tasks.map(managedCard));managedRenderKey=key;
  }
}
function managedCard(task){
  const card=element('article','task'+(task.error||task.pending.length?' alert':''));
  const head=element('div','task-top');head.append(element('h3','',task.title),element('span','badge',managedStates[task.status]||task.status));card.append(head,element('p','cwd',task.cwd));
  card.append(element('div','task-output',task.message|| (task.active?'任务已启动，等待输出……':'暂无新输出，可输入后续要求继续。')));
  if(task.error){
    const message=typeof task.error==='string'?task.error:(task.error.message||'任务连接异常');
    card.append(element('p','reason',/Reconnecting|timed out|stream disconnected/i.test(message)?'网络连接暂时中断，CLI 正在尝试重连。你可以等待，或点击“中断任务”。':message));
    if(typeof task.error!=='string'){const details=element('details','');details.append(element('summary','','异常技术详情'),element('pre','task-output',JSON.stringify(task.error,null,2)));card.append(details);}
  }
  const actions=element('div','buttons');
  if(task.active)actions.append(button('中断任务',()=>api('/api/managed/interrupt',{id:task.id,turn_id:task.turn_id})));
  actions.append(button('查看进展与问题',()=>showDetail(task.id)),button('检查结果质量',async()=>{const value=await api('/api/review',{id:task.id});toast(value.queued?'已排队检查，将使用额外模型用量':value.reason);}));
  card.append(actions);
  for(const request of task.pending){
    const box=element('section','approval-box');
    const supported=['item/commandExecution/requestApproval','item/fileChange/requestApproval'].includes(request.method);
    box.append(element('h3','',supported?'这一步需要你确认':'需要处理的请求'),element('pre','',JSON.stringify(request.params,null,2)));
    if(supported){for(const [label,decision] of [['允许这一次','accept'],['拒绝','decline']])box.append(button(label,()=>api('/api/managed/approve',{id:task.id,turn_id:task.turn_id,request_key:request.requestKey,decision})));}
    else box.append(element('p','meta','暂不支持在此回答这类请求。可以中断任务，再补充要求继续。'));
    card.append(box);
  }
  if(!task.active){
    const box=element('div','followup'),input=element('textarea','');input.rows=2;input.maxLength=24000;input.placeholder='补充要求，或直接继续刚才的任务';input.value=followupDrafts.get(task.id)||'';
    input.addEventListener('input',()=>followupDrafts.set(task.id,input.value));
    box.append(input,button('继续任务',async()=>{const prompt=input.value.trim()||'请从中断处继续完成原任务，先核对已完成的操作，避免重复执行。';await api('/api/managed/send',{id:task.id,turn_id:task.turn_id,prompt});followupDrafts.delete(task.id);}));card.append(box);
  }
  return card;
}
document.getElementById('managed-form').addEventListener('submit',async event=>{
  event.preventDefault();const form=event.currentTarget,submit=document.getElementById('managed-submit'),feedback=document.getElementById('managed-feedback');
  if(form.dataset.busy==='true')return;
  const payload={cwd:document.getElementById('managed-cwd').value.trim(),model:document.getElementById('managed-model').value,effort:document.getElementById('managed-effort').value,mode:document.getElementById('managed-mode').value,prompt:document.getElementById('managed-prompt').value.trim()};
  const signature=JSON.stringify(payload);
  if(managedRequest&&managedRequest.signature!==signature){feedback.textContent='上一请求结果尚未确认，请先查看任务列表。刷新页面后可发起新任务。';return;}
  if(!managedRequest)managedRequest={signature,key:crypto.randomUUID()};
  form.dataset.busy='true';submit.disabled=true;feedback.textContent='正在启动，请勿重复点击……';
  try{await api('/api/managed/start',{...payload,request_id:managedRequest.key});managedRequest=null;document.getElementById('managed-prompt').value='';feedback.textContent='任务已启动，可在下方查看进展。';await refresh();}
  catch(error){feedback.textContent=error.message+'；先查看下方是否已有任务，重试相同内容会使用同一请求标识。';}
  finally{form.dataset.busy='false';submit.disabled=false;}
});
