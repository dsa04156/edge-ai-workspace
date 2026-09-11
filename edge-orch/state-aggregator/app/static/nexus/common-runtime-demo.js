(function(root){
'use strict';
const E=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={Running:'시험 중',Stopping:'남은 요청 마무리',Stopped:'부하 제거 완료',Completed:'검증 통과',Incomplete:'검증 미완료',Interrupted:'중단 · 결과 확인 필요'};
function newId(crypto=root.crypto){if(crypto.randomUUID)return crypto.randomUUID();const b=crypto.getRandomValues(new Uint8Array(16));b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;return [...b].map(x=>x.toString(16).padStart(2,'0')).join('');}
const active=r=>['Running','Stopping'].includes(r.phase);
function actions(data,uid,current,pending,manual=false){
 const item=data?.items?.find(x=>x.uid===uid);if(!item)return '';
 if(manual&&item.serviceControl)return serviceActions(data,uid,current,pending);
 const run=data.runs.find(r=>r.uid===uid&&active(r)),request=pendingActions.get(uid);
 const disabled=!current||!item.available||Boolean(run)||pending;
 const spinning=Boolean(current&&(request||run));
 const label=mode=>!current&&run?.mode===mode?'상태 확인 중':request?.mode===mode&&!request.stop?'시작 요청 중…':run?.mode===mode?(run.phase==='Stopping'?'요청 마무리 중…':'실행 중…'):mode==='single'?'시험 요청 1건':manual?'AI 추론 부하 주기':'왕복 시험';
 const button=(mode,id)=>`<button id="${id}-${E(uid)}" class="button ${mode==='load'?'primary':''}" data-demo-start="${E(uid)}" data-demo-mode="${mode}" ${disabled?'disabled':''} aria-busy="${Boolean(spinning&&(request?.mode===mode||run?.mode===mode))}">${spinning&&(request?.mode===mode||run?.mode===mode)?'<span class="runtime-spinner" aria-hidden="true"></span>':''}${label(mode)}</button>`;
 return `<div class="runtime-demo-actions"><small>${E(item.label)}</small><div class="runtime-action-buttons ${manual?'with-stop':''}">${button('single','demo-single')}${button(manual?'load':'round-trip','demo-round')}${manual?`<button class="button runtime-stop" id="demo-stop-control-${E(uid)}" ${run?`data-demo-stop="${E(run.id)}" data-demo-uid="${E(run.uid)}" data-demo-name="${E(run.name)}"`:''} ${!current||!run||run.phase==='Stopping'||request?'disabled':''} aria-busy="${Boolean(request?.stop||run?.phase==='Stopping')}">${request?.stop?'제거 접수 중…':run?.phase==='Stopping'?'부하 제거 중…':'■ 부하 제거'}</button>`:''}</div><small>최대 ${E(item.maxRequests)}건 · 동시 ${E(item.concurrency)}건${item.retryAfterSeconds?' · 재시험까지 '+E(item.retryAfterSeconds)+'초':''}</small></div>`;
}
const controlLabels={Running:'서비스 실행 중',Starting:'서비스 시작 중 · 모델 준비',Stopping:'서비스 중지 중 · 요청 마무리·모델 해제',Stopped:'서비스 중지됨'};
function serviceActions(value,uid,current,pending=false){
 const item=value?.items?.find(x=>x.uid===uid),state=item?.serviceControl;if(!state)return '';
 const request=controlPending.get(uid),run=value.runs.find(r=>r.uid===uid&&active(r));
 const stopping=state.phase==='Stopping',starting=state.phase==='Starting';
 return `<section class="runtime-service-controls" aria-label="서비스 실행 제어"><div class="runtime-control-status" role="status">${current&&(request||starting||stopping)?'<span class="runtime-spinner" aria-hidden="true"></span>':''}<strong>${!current?'서비스 상태 확인 불가':request?(request==='start'?'서비스 시작 접수 중…':'서비스 중지 접수 중…'):E(controlLabels[state.phase])}</strong></div><div class="runtime-service-buttons"><button id="service-start-${E(uid)}" class="button primary" data-service-action="start" data-service-uid="${E(uid)}" ${!current||!state.canStart||request?'disabled':''} aria-busy="${Boolean(request==='start'||current&&starting)}">${request==='start'||current&&starting?'시작 중…':'서비스 실행'}</button><button id="service-stop-${E(uid)}" class="button runtime-service-stop" data-service-action="stop" data-service-uid="${E(uid)}" ${!current||!state.canStop||request?'disabled':''} aria-busy="${Boolean(request==='stop'||current&&stopping)}">${request==='stop'||current&&stopping?'중지 중…':'서비스 중지'}</button></div><p>실행: 모델 준비 후 요청 대기<br>중지: 모든 시험 부하 제거 → 진행 요청 마무리 → 모델 해제</p>${controlErrors.has(uid)?`<p class="runtime-warning" role="alert">${E(controlErrors.get(uid))}</p>`:''}<button id="demo-single-${E(uid)}" class="button runtime-single" data-demo-start="${E(uid)}" data-demo-mode="single" ${!current||!item.available||pending||request?'disabled':''}>${pendingActions.get(uid)?.mode==='single'?'요청 접수 중…':'시험 요청 1건'}</button>${run&&!run.targetNode?`<button class="button runtime-stop" data-demo-stop="${E(run.id)}" data-demo-uid="${E(uid)}" data-demo-name="${E(item.name)}" ${run.phase==='Stopping'?'disabled':''}>${run.phase==='Stopping'?'기존 부하 제거 중…':'기존 시험 부하 제거'}</button>`:''}</section>`;
}
function nodeActions(value,uid,node,label,current,pending=false){
 const item=value?.items?.find(x=>x.uid===uid),target=item?.nodes?.find(x=>x.node===node);
 const rows=(value?.runs||[]).filter(r=>r.uid===uid&&r.targetNode===node).sort((a,b)=>b.createdAt-a.createdAt);
 const run=rows.find(active),last=run||rows[0],request=pendingActions.get(uid),ownRequest=request?.targetNode===node;
 const busy=Boolean(current&&(run||ownRequest)),stopping=Boolean(run?.phase==='Stopping'||ownRequest&&request?.stop);
 const note=!current?'부하 상태 확인 불가':stopping?'새 요청 중단 · 진행 요청 마무리 중':run?'부하 제거 전까지 이 노드에서 계속 실행':ownRequest?'부하 시작 접수 중…':last?.reason==='node_route_changed'?'실행 노드 이동 · 이 노드 부하 종료':last?.phase==='Stopped'?'이 노드 부하 제거 완료':last?.phase==='Completed'?'이 노드 부하 완료':target?.retryAfterSeconds?'재시험까지 '+target.retryAfterSeconds+'초':target?.currentRoute?'부하 대기 · 서비스 실행 유지':'서비스가 이 노드에서 실행되면 사용';
 return `<section class="runtime-node-controls" aria-label="${E(label)} 부하 제어"><div class="runtime-node-load-buttons"><button id="node-load-${E(uid)}-${E(node)}" class="button primary" data-demo-start="${E(uid)}" data-demo-mode="node-load" data-demo-target-node="${E(node)}" ${!current||!target?.available||pending||controlPending.has(uid)?'disabled':''} aria-busy="${Boolean(busy&&!stopping)}">${busy&&!stopping?'<span class="runtime-spinner" aria-hidden="true"></span>':''}${busy&&!stopping?E(label)+' 부하 중…':E(label)+'에 부하 주기'}</button><button id="node-unload-${E(uid)}-${E(node)}" class="button runtime-node-stop" ${run?`data-demo-stop="${E(run.id)}" data-demo-uid="${E(uid)}" data-demo-name="${E(run.name)}" data-demo-target-node="${E(node)}"`:''} ${!run||stopping||request?.stop?'disabled':''} aria-busy="${Boolean(current&&stopping)}">${stopping?E(label)+' 제거 중…':E(label)+' 부하 제거'}</button></div><p role="status">${E(note)}</p><small>제거할 때까지 유지 · 동시 ${E(item?.concurrency)}건</small>${last?`<small>전송 ${E(last.sent)} · 성공 ${E(last.succeeded)} · 취소 ${E(last.cancelled||0)} · 실패 ${E(last.failed)}${last.unknown?' · 미확인 '+E(last.unknown):''}</small>`:''}${busy?'<div class="runtime-indeterminate" role="progressbar" aria-label="노드 부하 처리 중"><span></span></div>':''}</section>`;
}
const stageLabels={baseline:'기준 부하 측정 · 엣지 복귀 확인',pressure:'집중 부하 실행 중',recovery:'저부하 측정 · 복귀 확인',single:'추론 요청 처리 중'};
function serverNow(){return Number.isFinite(data?.observedAt)&&Number.isFinite(receivedMonotonic)?data.observedAt+Math.max(0,root.performance.now()/1000-receivedMonotonic):Date.now()/1000;}
function context(uid,now=serverNow()){
 const current=Boolean(data&&!error&&!data.observation_error&&now-data.observedAt>=0&&now-data.observedAt<15);
 const rows=(data?.runs||[]).filter(r=>r.uid===uid).sort((a,b)=>b.createdAt-a.createdAt);
 return {current,loading:!data&&!error,sourceError:error,run:rows.find(active)||rows[0],item:data?.items.find(x=>x.uid===uid),sending:pendingActions.get(uid),intent:intents.get(uid),error:actionError?.uid===uid?actionError.message:null};
}
function runStatus(ctx,now=serverNow()){
 const {run:r,current,sending:request,intent,error}=ctx;
 const busy=Boolean(current&&r&&active(r));
 let title=request?(request.stop?'부하 제거 요청 중…':'시작 요청 접수 중…'):intent?'접수 결과 확인 필요':!current?'실행 상태 확인 불가':!r?'부하 시험 대기':r.phase==='Stopping'?'진행 중 요청 마무리 중':active(r)?stageLabels[r.stage]||'시험 실행 중':['load','node-load'].includes(r.mode)&&r.phase==='Completed'?'부하 시험 완료':r.phase==='Completed'?'추론 요청 완료':labels[r.phase]||r.phase;
 const elapsed=r?Math.max(0,Math.floor(((active(r)?now:r.finishedAt)||now)-r.createdAt)):0;
 return `<section class="runtime-run-status" aria-label="부하 시험 진행 상태"><div class="runtime-run-title" role="status">${(request||busy)?'<span class="runtime-spinner" aria-hidden="true"></span>':'<span class="runtime-status-dot" aria-hidden="true"></span>'}<strong>${r?.targetLabel?E(r.targetLabel)+' · ':''}${E(title)}</strong>${r?`<small ${busy?`data-runtime-elapsed="${E(r.createdAt)}"`:''}>${current||!active(r)?E(elapsed)+'초':'시간 확인 불가'}</small>`:''}</div>${r?`<p class="runtime-run-counts">전송 <b>${E(r.sent)}</b> · 성공 <b>${E(r.succeeded)}</b> · 실패 <b>${E(r.failed)}</b> · 취소 <b>${E(r.cancelled||0)}</b> · 미확인 <b>${E(r.unknown)}</b></p>`:'<p>부하를 시작하면 실행 단계와 결과가 여기에 표시됩니다.</p>'}${busy&&r.mode==='load'?`<ol class="runtime-run-stages" aria-label="부하 시험 단계">${['baseline','pressure','recovery'].map((stage,i)=>`<li ${r.stage===stage?'aria-current="step"':''}>${i+1}. ${['기준 부하','집중 부하','저부하'][i]}</li>`).join('')}</ol>`:''}${request||busy?'<div class="runtime-indeterminate" role="progressbar" aria-label="요청 처리 중 · 완료율 미산정"><span></span></div>':''}${busy&&!ctx.inlineControls?`<button class="button runtime-stop" id="demo-stop-${E(r.id)}" data-demo-stop="${E(r.id)}" data-demo-uid="${E(r.uid)}" data-demo-name="${E(r.name)}" ${r.phase==='Stopping'||request?'disabled':''}>${r.phase==='Stopping'?'중단 접수됨 · 요청 마무리 중':'새 시험 요청 중단'}</button>`:''}${busy&&ctx.inlineControls?'<p>부하 제거: 새 요청을 멈추고 진행 중 요청을 마무리합니다.</p>':''}${intent&&!request?`<button class="button" id="demo-retry-${E(intent.uid)}" data-demo-retry="${E(intent.uid)}">같은 실행 ID로 확인·재접수</button>`:''}${!current?'<p class="runtime-warning">마지막 수신 기록입니다. 연결이 복구되면 현재 상태를 다시 확인합니다.</p>':''}${error?`<p class="runtime-warning" role="alert">${E(error)}</p>`:''}${r&&!busy&&r.lastResult?`<details data-runtime-details="run-${E(r.uid)}" ${ctx.detailsOpen?'open':''}><summary>최근 실행 결과 보기</summary><pre>${E(r.lastResult)}</pre></details>`:''}</section>`;
}
function panel(data,error,intents=[],now=Date.now()/1000){
 if(!data?.enabled&&!error&&!intents.length)return '';
 const current=Boolean(data&&!error&&!data.observation_error&&now-data.observedAt>=0&&now-data.observedAt<15);
 const rows=data?.runs||[];
 return `<section class="panel runtime-demo-panel"><h2>데모 실행·결과</h2><p class="note">계약에 등록된 입력으로 요청합니다. 왕복 시험은 제한된 부하 뒤 요청 간격을 늘려 전환·복귀를 확인합니다. 노드별 부하는 부하 제거 또는 실행 노드 변경까지 유지됩니다. 기존 전체 경로 시험은 시간·요청 수 상한을 적용합니다. 추천 노드로 증강하려면 별도 승인 버튼을 클릭하세요. 부하 시험 완료와 증강 적용은 별도로 표시합니다.</p>${!current?'<p class="runtime-warning" role="status">시험 원장 관측을 확인할 수 없습니다. 아래 결과는 마지막 수신 기록입니다.</p>':''}${intents.map(i=>`<div class="runtime-demo-intent" role="status"><strong>${E(i.name)} · 접수 결과 확인 필요</strong><p>응답을 받지 못해 실행 여부가 불명확합니다. 같은 실행 ID로 확인합니다.</p><button class="button" id="demo-retry-${E(i.uid)}" data-demo-retry="${E(i.uid)}">같은 실행 ID로 확인·재접수</button></div>`).join('')}${rows.length?rows.slice(0,8).map(r=>`<article class="runtime-demo-result"><div class="section-heading"><div><h3>${E(r.name)} · ${r.mode==='single'?'단일 요청':['load','node-load'].includes(r.mode)?(r.targetLabel||'AI')+' 부하 시험':'왕복 시험'}</h3><small>${E(new Date(r.createdAt*1000).toLocaleString('ko-KR',{hour12:false}))} · ${E(r.label)}</small></div><span class="badge">${active(r)&&!current?'현재 진행 상태 확인 불가':E(['load','node-load'].includes(r.mode)&&r.phase==='Completed'?'부하 시험 완료':labels[r.phase]||r.phase)}</span></div>${r.mode==='load'&&active(r)?`<p role="status">${E({baseline:'기준 부하 측정 · 엣지 복귀 확인 중',pressure:'집중 부하 · 추천 노드가 표시되면 승인할 수 있습니다',recovery:'저부하 측정 · 복귀 조건 확인 중'}[r.stage]||'시험 준비 중')}</p>`:''}<p>요청 ${E(r.sent)}건 · 성공 ${E(r.succeeded)}건 · 실패 ${E(r.failed)}건 · 취소 ${E(r.cancelled||0)}건 · 미확인 ${E(r.unknown)}건</p><p class="runtime-demo-route">${(r.routeHistory||[]).map(t=>E(t.node)+' ('+E(t.role)+')').join(' → ')||'실행 위치 관측 대기'}</p>${r.mode==='round-trip'?`<p>역할 복귀 ${r.returned?'확인':'미확인'} · 반환 중 ${E(r.retiring)}개</p>`:''}${active(r)?`<button class="button" id="demo-stop-history-${E(r.id)}" data-demo-stop="${E(r.id)}" data-demo-uid="${E(r.uid)}" data-demo-name="${E(r.name)}" ${r.phase==='Stopping'?'disabled':''}>${r.phase==='Stopping'?'진행 중 요청 마무리 중':'새 시험 요청 중단'}</button>`:''}${r.lastResult?`<pre aria-label="마지막 서비스 응답">${E(r.lastResult)}</pre>`:''}<small>실행 ID ${E(r.id)}${r.reason?' · '+E(r.reason):''}</small></article>`).join(''):'<p class="empty">실행한 데모가 없습니다. 서비스 행에서 시험을 시작하세요.</p>'}</section>`;
}
let receivedMonotonic=null,data=null,error=null,actionError=null,fetching=null,draw=()=>{};
const intents=new Map(),sending=new Set(),pendingActions=new Map(),controlPending=new Map(),controlErrors=new Map();
function persist(){try{root.localStorage.setItem('nexus-runtime-demo-intents-v1',JSON.stringify([...intents.values()]));}catch(_){}}
async function refresh(){if(fetching)return fetching;fetching=(async()=>{const c=new AbortController(),timer=setTimeout(()=>c.abort(),4500);try{
 const r=await root.fetch('/state/runtime-demos',{cache:'no-store',signal:c.signal});if(!r.ok)throw new Error('HTTP '+r.status);
 const value=await r.json();if(!Array.isArray(value.items)||!Array.isArray(value.runs))throw new Error('invalid_response');
 data=value;receivedMonotonic=root.performance.now()/1000;error=value.observation_error||null;
 for(const [uid,i] of intents)if(value.runs.some(r=>r.uid===uid&&r.id===i.id))intents.delete(uid);
 persist();
 }catch(_){error='demo_source_unavailable';}finally{clearTimeout(timer);fetching=null;draw();}})();return fetching;}
async function submit(i,stop=false){if(sending.has(i.uid))return;sending.add(i.uid);pendingActions.set(i.uid,{...i,stop});actionError=null;draw();const c=new AbortController(),timer=setTimeout(()=>c.abort(),5000);try{
 const url='/api/runtime-demos/'+encodeURIComponent(i.name)+'/runs/'+encodeURIComponent(i.id)+(stop?'/stop':'');
 const r=await root.fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Runtime-Demo':'1'},body:JSON.stringify(stop?{serviceUid:i.uid}:{serviceUid:i.uid,mode:i.mode,...(i.targetNode?{targetNode:i.targetNode}:{})}),signal:c.signal});
 const result=await r.json();
 if(!r.ok){if(r.status<500&&!stop){intents.delete(i.uid);persist();}actionError={uid:i.uid,message:String(result.detail||'demo_request_failed')};return;}
 if(!stop){intents.delete(i.uid);persist();}
 if(data){data.runs=[result,...data.runs.filter(x=>!(x.uid===result.uid&&x.id===result.id))];}
 error=null;
 }catch(_){actionError={uid:i.uid,message:stop?'중단 접수 결과 확인 필요':'시작 접수 결과 확인 필요'};}
 finally{clearTimeout(timer);sending.delete(i.uid);pendingActions.delete(i.uid);draw();refresh();}}
async function serviceControl(uid,action){
 const item=data?.items.find(x=>x.uid===uid);if(!item||controlPending.has(uid))return;
 controlPending.set(uid,action);controlErrors.delete(uid);draw();
 try{
  const r=await root.fetch('/api/runtime-demos/'+encodeURIComponent(item.name)+'/service',{method:'POST',headers:{'Content-Type':'application/json','X-Runtime-Demo':'1'},body:JSON.stringify({serviceUid:uid,action}),signal:AbortSignal.timeout(10000)});
  const receipt=await r.json();if(!r.ok)throw new Error(String(receipt.detail||'서비스 제어 접수 실패'));
  item.serviceControl=receipt;item.available=false;
 }catch(e){controlErrors.set(uid,e.name==='TimeoutError'?'접수 결과 확인 필요 · 상태 갱신 후 다시 확인하세요.':e.message||'서비스 제어 접수 결과 확인 필요');}
 finally{controlPending.delete(uid);draw();refresh();}
}
function setup(callback){draw=callback;try{for(const i of JSON.parse(root.localStorage.getItem('nexus-runtime-demo-intents-v1')||'[]').slice(0,20))if(i&&typeof i.uid==='string'&&typeof i.id==='string'&&typeof i.name==='string'&&['single','round-trip','load','node-load'].includes(i.mode))intents.set(i.uid,i);}catch(_){}
 root.document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b||b.disabled)return;
 if(b.dataset.demoStart){const item=data?.items.find(x=>x.uid===b.dataset.demoStart);if(!item)return;const i={uid:item.uid,name:item.name,id:newId(),mode:b.dataset.demoMode,...(b.dataset.demoTargetNode?{targetNode:b.dataset.demoTargetNode}:{})};intents.set(i.uid,i);persist();submit(i);}
 if(b.dataset.demoRetry){const i=intents.get(b.dataset.demoRetry);if(i)submit(i);}
 if(b.dataset.demoStop)submit({id:b.dataset.demoStop,uid:b.dataset.demoUid,name:b.dataset.demoName,targetNode:b.dataset.demoTargetNode},true);
 if(b.dataset.serviceAction)serviceControl(b.dataset.serviceUid,b.dataset.serviceAction);
 });}
const api={actions,serviceActions,nodeActions,panel,
 renderNodeActions:(uid,node,label,current)=>nodeActions(data,uid,node,label,current&&context(uid).current,intents.has(uid)||sending.has(uid)),newId,setup,refresh,context,runStatus,renderActions:(uid,current,manual=false)=>actions(data,uid,current&&context(uid).current,intents.has(uid)||sending.has(uid),manual),renderPanel:()=>panel(data,error,[...intents.values()],serverNow())+(actionError?`<p class="runtime-warning" role="alert">시험 접수: ${E(actionError.message)}</p>`:'')};
if(typeof module!=='undefined'&&module.exports)module.exports=api;root.NexusRuntimeDemo=api;
})(typeof window!=='undefined'?window:globalThis);
