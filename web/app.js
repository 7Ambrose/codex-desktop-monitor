'use strict';
const fragment = new URLSearchParams(location.hash.slice(1));
let access = fragment.get('token') || '';
if (!access) {
  try { access = localStorage.getItem('monitor_access') || sessionStorage.getItem('monitor_access') || ''; } catch {}
}
if (access) {
  // Keep authorization across tabs in this browser; localStorage is origin/port scoped.
  try { localStorage.setItem('monitor_access', access); } catch {}
  try { sessionStorage.setItem('monitor_access', access); } catch {}
}
if (fragment.has('token') && access) {
  history.replaceState(null, '', location.pathname);
}
const $ = id => document.getElementById(id);
let previousCpu = null, inflight = false;
const states = {observing:'正在接入',running:'运行中',finished:'本轮已结束',needs_attention:'需要处理',pause_requested:'等待下一步拦截',waiting_user:'等待桌面确认',interrupted:'已中断'};
function element(tag, cls, text) { const el = document.createElement(tag); if (cls) el.className=cls; if (text !== undefined) el.textContent=text; return el; }
function toast(text) { $('toast').textContent=text; $('toast').hidden=false; setTimeout(()=>{$('toast').hidden=true;},5000); }
async function api(path, body) {
  const response = await fetch(path, {method:body?'POST':'GET',headers:{Authorization:'Bearer '+access,...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{})});
  const data = await response.json(); if (!response.ok) throw new Error(data.error || '请求未完成'); return data;
}
function button(label, fn, cls='') { const el=element('button',cls,label); el.addEventListener('click',async()=>{el.disabled=true;try{await fn();await refresh();}catch(e){toast(e.message);}finally{el.disabled=false;}});return el; }
function duration(seconds) { seconds=Math.max(0,Math.floor(seconds));return seconds<60?seconds+' 秒':Math.floor(seconds/60)+' 分 '+seconds%60+' 秒'; }
function parseReview(raw) {try{return raw?JSON.parse(raw):null;}catch{return null;} }
function chatLink(id) {
  if(!/^[0-9a-f]{8}-[0-9a-f-]{27}$/i.test(id)) return element('span','meta','聊天 ID：'+id);
  const link=element('a','link-button','打开原聊天');link.href='codex://threads/'+encodeURIComponent(id);return link;
}
const eventLabels={UserPromptSubmit:'收到需求',PreToolUse:'开始工具操作',PostToolUse:'工具返回结果',Stop:'本轮结束',Interrupt:'已中断',PreCompact:'整理上下文',PostCompact:'上下文整理完成'};
function noticeCard(item) {
  const card=element('article','task'+(['quiet','failures'].includes(item.kind)?' alert':''));
  card.append(element('div','summary',item.message),element('div','meta',new Date(item.at*1000).toLocaleString()));
  const actions=element('div','buttons');actions.append(chatLink(item.task_id));
  if(!item.acknowledged)actions.append(button('知道了',()=>api('/api/acknowledge',{id:item.id})));
  else actions.append(element('span','meta','已读'));
  card.append(actions);return card;
}
function taskCard(task) {
  const concern=!!task.pause_reason, card=element('article','task'+(concern?' alert':''));
  const top=element('div','task-top');top.append(element('h3','',task.title),element('span','badge',states[task.state]||task.state));card.append(top);
  card.append(element('div','cwd',task.cwd));
  card.append(element('div','meta','最近活动：'+duration(Date.now()/1000-task.updated)+'前 · '+(eventLabels[task.last_event]||task.last_event||'等待事件')));
  const review=parseReview(task.review);
  let summary=review?review.summary:'尚未复核。省用量模式下，仅在疑点或你主动请求时调用 GPT。';
  if(task.quiet) summary='一段时间没有新事件，正在观察。可能仍在思考或执行长命令，尚不能判断卡住。';
  card.append(element('div','summary',summary));
  if(concern)card.append(element('div','reason',task.pause_reason));
  card.append(element('div','meta',duration((['running','pause_requested','waiting_user'].includes(task.state)?Date.now()/1000:task.updated)-task.started)+' · '+(task.model||'模型未报告')+' · 本轮复核 '+task.review_count+' 次'));
  const actions=element('div','buttons');
  actions.append(chatLink(task.id));
  actions.append(button('查看依据',()=>showDetail(task.id)));
  actions.append(button('立即复核',async()=>{const result=await api('/api/review',{id:task.id});toast(result.queued?'已排队复核':result.reason);}));
  if(!concern && task.state==='running')actions.append(button('暂停后续操作',()=>api('/api/pause',{id:task.id,turn_id:task.turn_id})));
  if(concern && task.state!=='waiting_user')actions.append(button('允许后续操作',()=>api('/api/release',{id:task.id,turn_id:task.turn_id}),'primary'));
  if(task.state==='waiting_user')actions.append(element('span','meta','请回到原聊天处理确认弹窗'));
  card.append(actions);return card;
}
async function showDetail(id) {
  const data=await api('/api/task?id='+encodeURIComponent(id));
  const box=$('detail-content');box.replaceChildren();
  box.append(element('h3','',data.task.title));
  box.append(element('p','cwd','聊天 ID：'+id));
  box.append(chatLink(id));
  box.append(element('p','summary','最后活动：'+(eventLabels[data.task.last_event]||data.task.last_event)+'。无新事件可能是推理、长命令、等待网络或停滞；本面板不能自动恢复卡住的桌面任务。'));
  if(data.recent_errors?.length){
    box.append(element('h3','','最近错误'));
    for(const error of data.recent_errors){box.append(element('p','meta',new Date(error.at*1000).toLocaleString()+' · '+(error.payload.tool_name||'工具')));box.append(element('pre','',JSON.stringify(error.payload.tool_response,null,2).slice(0,4000)));}
  }
  const review=parseReview(data.task.review);
  if(review){box.append(element('h3','','独立复核'));box.append(element('pre','',JSON.stringify(review,null,2)));}
  box.append(element('h3','','最近进展'));
  for(const event of data.events.slice(-12))box.append(element('p','meta',new Date(event.at*1000).toLocaleTimeString()+' · '+(eventLabels[event.kind]||event.kind)+(event.payload.tool_name?' · '+event.payload.tool_name:'')));
  const raw=element('details','');raw.append(element('summary','','展开原始事件'),element('pre','',JSON.stringify(data.events,null,2)));box.append(raw);
  $('detail').hidden=false;$('detail').scrollIntoView({behavior:'smooth',block:'start'});
}
async function refresh() {
  if(inflight)return;inflight=true;
  try {
    const data=await api('/api/state');
    $('connection').textContent=data.last_hook_at?'已收到任务事件':'服务在线 · 等待任务接入';$('connection').className='live ok';
    $('active').textContent=data.tasks.filter(t=>['running','observing'].includes(t.state)).length;
    $('attention').textContent=data.tasks.filter(t=>t.pause_reason).length+(data.notices||[]).filter(n=>!n.acknowledged&&['quiet','failures'].includes(n.kind)).length;
    const notices=data.notices||[];$('notice-section').hidden=!notices.length;
    $('notices').replaceChildren(...notices.slice(0,8).map(noticeCard));
    if(data.service_error){$('connection').textContent=data.service_error;$('connection').className='live';}
    $('review-state').textContent=data.review_enabled?(data.review_queue?'排队中':({economy:'省用量',balanced:'关键交付复核',comprehensive:'每轮复核'}[data.review_mode]||'按需复核')):'已关闭';
    $('coverage').textContent=data.enabled_roots.length?'监控范围：'+data.enabled_roots.join('、'):'尚未启用工作文件夹';
    const cpu={time:performance.now()/1000,value:data.process_cpu_seconds};
    if(previousCpu){const percent=100*(cpu.value-previousCpu.value)/(cpu.time-previousCpu.time);$('cpu').textContent=Math.max(0,percent).toFixed(1)+'% 单核';}
    previousCpu=cpu;
    $('tasks').replaceChildren(...data.tasks.map(taskCard));$('empty').hidden=data.tasks.length>0;
    $('updated').textContent='更新于 '+new Date().toLocaleTimeString();
  } catch(e){$('connection').textContent='连接未完成';$('connection').className='live';$('empty').querySelector('p').textContent=e.message;}
  finally{inflight=false;}
}
$('close-detail').addEventListener('click',()=>{$('detail').hidden=true;});
refresh();setInterval(()=>{if(!document.hidden)refresh();},5000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
