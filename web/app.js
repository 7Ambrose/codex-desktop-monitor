'use strict';
const fragment = new URLSearchParams(location.hash.slice(1));
if (fragment.has('token')) {
  sessionStorage.setItem('monitor_access', fragment.get('token'));
  history.replaceState(null, '', location.pathname);
}
const access = sessionStorage.getItem('monitor_access') || '';
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
function taskCard(task) {
  const concern=!!task.pause_reason, card=element('article','task'+(concern?' alert':''));
  const top=element('div','task-top');top.append(element('h3','',task.title),element('span','badge',states[task.state]||task.state));card.append(top);
  card.append(element('div','cwd',task.cwd));
  const review=parseReview(task.review);
  let summary=review?review.summary:'尚未复核。省用量模式下，仅在疑点或你主动请求时调用 GPT。';
  if(task.quiet) summary='一段时间没有新事件，正在观察。可能仍在思考或执行长命令，尚不能判断卡住。';
  card.append(element('div','summary',summary));
  if(concern)card.append(element('div','reason',task.pause_reason));
  card.append(element('div','meta',duration((['running','pause_requested','waiting_user'].includes(task.state)?Date.now()/1000:task.updated)-task.started)+' · '+(task.model||'模型未报告')+' · 本轮复核 '+task.review_count+' 次'));
  const actions=element('div','buttons');
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
  const review=parseReview(data.task.review);
  if(review){box.append(element('h3','','独立复核'));box.append(element('pre','',JSON.stringify(review,null,2)));}
  box.append(element('h3','','近期事件（本机记录）'));
  box.append(element('pre','',JSON.stringify(data.events,null,2)));
  $('detail').hidden=false;$('detail').scrollIntoView({behavior:'smooth',block:'start'});
}
async function refresh() {
  if(inflight)return;inflight=true;
  try {
    const data=await api('/api/state');
    $('connection').textContent=data.last_hook_at?'已收到任务事件':'服务在线 · 等待任务接入';$('connection').className='live ok';
    $('active').textContent=data.tasks.filter(t=>['running','observing'].includes(t.state)).length;
    $('attention').textContent=data.tasks.filter(t=>t.pause_reason).length;
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
