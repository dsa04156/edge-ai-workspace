(function(root){
'use strict';
const E=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const labels={Running:'시험 중',Stopping:'남은 요청 마무리',Stopped:'부하 제거 완료',Completed:'검증 통과',Incomplete:'검증 미완료',Interrupted:'중단 · 결과 확인 필요'};
function newId(crypto=root.crypto){if(crypto.randomUUID)return crypto.randomUUID();const b=crypto.getRandomValues(new Uint8Array(16));b[6]=(b[6]&15)|64;b[8]=(b[8]&63)|128;return [...b].map(x=>x.toString(16).padStart(2,'0')).join('');}
const active=r=>['Running','Stopping'].includes(r.phase);
function actions(data,uid,current,pending,manual=false){
 const item=data?.items?.find(x=>x.uid===uid);if(!item)return '';
 const run=data.runs.find(r=>r.uid===uid&&active(r)),request=pendingActions.get(uid);
 const disabled=!current||!item.available||Boolean(run)||pending;
 const spinning=Boolean(current&&(request||run));
 const label=mode=>!current&&run?.mode===mode?'상태 확인 중':request?.mode===mode&&!request.stop?'시작 요청 중…':run?.mode===mode?(run.phase==='Stopping'?'요청 마무리 중…':'실행 중…'):mode==='single'?'시험 요청 1건':manual?'AI 추론 부하 주기':'왕복 시험';
 const button=(mode,id)=>`<button id="${id}-${E(uid)}" class="button ${mode==='load'?'primary':''}" data-demo-start="${E(uid)}" data-demo-mode="${mode}" ${disabled?'disabled':''} aria-busy="${Boolean(spinning&&(request?.mode===mode||run?.mode===mode))}">${spinning&&(request?.mode===mode||run?.mode===mode)?'<span class="runtime-spinner" aria-hidden="true"></span>':''}${label(mode)}</button>`;
 return `<div class="runtime-demo-actions"><small>${E(item.label)}</small><div class="runtime-action-buttons ${manual?'with-stop':''}">${button('single','demo-single')}${button(manual?'load':'round-trip','demo-round')}${manual?`<button class="button runtime-stop" id="demo-stop-control-${E(uid)}" ${run?`data-demo-stop="${E(run.id)}" data-demo-uid="${E(run.uid)}" data-demo-name="${E(run.name)}"`:''} ${!current||!run||run.phase==='Stopping'||request?'disabled':''} aria-busy="${Boolean(request?.stop||run?.phase==='Stopping')}">${request?.stop?'제거 접수 중…':run?.phase==='Stopping'?'부하 제거 중…':'■ 부하 제거'}</button>`:''}</div><small>최대 ${E(item.maxRequests)}건 · 동시 ${E(item.concurrency)}건${item.retryAfterSeconds?' · 재시험까지 '+E(item.retryAfterSeconds)+'초':''}</small></div>`;
}
const stageLabels={baseline:'기준 부하 측정 · 엣지 복귀 확인',pressure:'집중 부하 실행 중',recovery:'저부하 측정 · 복귀 확인',single:'추론 요청 처리 중'};
function context(uid,now=Date.now()/1000){
 const current=Boolean(data&&!error&&!data.observation_error&&now-data.observedAt>=0&&now-data.observedAt<15);
 const rows=(data?.runs||[]).filter(r=>r.uid===uid).sort((a,b)=>b.createdAt-a.createdAt);
 return {current,loading:!data&&!error,sourceError:error,run:rows.find(active)||rows[0],item:data?.items.find(x=>x.uid===uid),sending:pendingActions.get(uid),intent:intents.get(uid),error:actionError?.uid===uid?actionError.message:null};
}
function runStatus(ctx,now=Date.now()/1000){
 const {run:r,current,sending:request,intent,error}=ctx;
 const busy=Boolean(current&&r&&active(r));
 let title=request?(request.stop?'부하 제거 요청 중…':'시작 요청 접수 중…'):intent?'접수 결과 확인 필요':!current?'실행 상태 확인 불가':!r?'부하 시험 대기':r.phase==='Stopping'?'진행 중 요청 마무리 중':active(r)?stageLabels[r.stage]||'시험 실행 중':r.mode==='load'&&r.phase==='Completed'?'부하 시험 완료':r.phase==='Completed'?'추론 요청 완료':labels[r.phase]||r.phase;
 const elapsed=r?Math.max(0,Math.floor(((active(r)?now:r.finishedAt)||now)-r.createdAt)):0;
 return `<section class="runtime-run-status" aria-label="부하 시험 진행 상태"><div class="runtime-run-title" role="status">${(request||busy)?'<span class="runtime-spinner" aria-hidden="true"></span>':'<span class="runtime-status-dot" aria-hidden="true"></span>'}<strong>${E(title)}</strong>${r?`<small ${busy?`data-runtime-elapsed="${E(r.createdAt)}"`:''}>${current||!active(r)?E(elapsed)+'초':'시간 확인 불가'}</small>`:''}</div>${r?`<p class="runtime-run-counts">전송 <b>${E(r.sent)}</b> · 성공 <b>${E(r.succeeded)}</b> · 실패 <b>${E(r.failed)}</b> · 미확인 <b>${E(r.unknown)}</b></p>`:'<p>부하를 시작하면 실행 단계와 결과가 여기에 표시됩니다.</p>'}${busy&&r.mode==='load'?`<ol class="runtime-run-stages" aria-label="부하 시험 단계">${['baseline','pressure','recovery'].map((stage,i)=>`<li ${r.stage===stage?'aria-current="step"':''}>${i+1}. ${['기준 부하','집중 부하','저부하'][i]}</li>`).join('')}</ol>`:''}${request||busy?'<div class="runtime-indeterminate" role="progressbar" aria-label="요청 처리 중 · 완료율 미산정"><span></span></div>':''}${busy&&!ctx.inlineControls?`<button class="button runtime-stop" id="demo-stop-${E(r.id)}" data-demo-stop="${E(r.id)}" data-demo-uid="${E(r.uid)}" data-demo-name="${E(r.name)}" ${r.phase==='Stopping'||request?'disabled':''}>${r.phase==='Stopping'?'중단 접수됨 · 요청 마무리 중':'새 시험 요청 중단'}</button>`:''}${busy&&ctx.inlineControls?'<p>부하 제거: 새 요청을 멈추고 진행 중 요청을 마무리합니다.</p>':''}${intent&&!request?`<button class="button" id="demo-retry-${E(intent.uid)}" data-demo-retry="${E(intent.uid)}">같은 실행 ID로 확인·재접수</button>`:''}${!current?'<p class="runtime-warning">마지막 수신 기록입니다. 연결이 복구되면 현재 상태를 다시 확인합니다.</p>':''}${error?`<p class="runtime-warning" role="alert">${E(error)}</p>`:''}${r&&!busy&&r.lastResult?`<details data-runtime-details="run-${E(r.uid)}" ${ctx.detailsOpen?'open':''}><summary>최근 실행 결과 보기</summary><pre>${E(r.lastResult)}</pre></details>`:''}</section>`;
}
function panel(data,error,intents=[],now=Date.now()/1000){
 if(!data?.enabled&&!error&&!intents.length)return '';
 const current=Boolean(data&&!error&&!data.observation_error&&now-data.observedAt>=0&&now-data.observedAt<15);
 const rows=data?.runs||[];
 return `<section class="panel runtime-demo-panel"><h2>데모 실행·결과</h2><p class="note">계약에 등록된 입력으로 요청합니다. 왕복 시험은 제한된 부하 뒤 요청 간격을 늘려 전환·복귀를 확인합니다. AI 부하 시험은 기준 부하 → 집중 부하 → 저부하 순서입니다. 추천 노드로 증강하려면 별도 승인 버튼을 클릭하세요. 부하 시험 완료와 증강 적용은 별도로 표시합니다.</p>${!current?'<p class="runtime-warning" role="status">시험 원장 관측을 확인할 수 없습니다. 아래 결과는 마지막 수신 기록입니다.</p>':''}${intents.map(i=>`<div class="runtime-demo-intent" role="status"><strong>${E(i.name)} · 접수 결과 확인 필요</strong><p>응답을 받지 못해 실행 여부가 불명확합니다. 같은 실행 ID로 확인합니다.</p><button class="button" id="demo-retry-${E(i.uid)}" data-demo-retry="${E(i.uid)}">같은 실행 ID로 확인·재접수</button></div>`).join('')}${rows.length?rows.slice(0,8).map(r=>`<article class="runtime-demo-result"><div class="section-heading"><div><h3>${E(r.name)} · ${r.mode==='single'?'단일 요청':r.mode==='load'?'AI 부하 시험':'왕복 시험'}</h3><small>${E(new Date(r.createdAt*1000).toLocaleString('ko-KR',{hour12:false}))} · ${E(r.label)}</small></div><span class="badge">${active(r)&&!current?'현재 진행 상태 확인 불가':E(r.mode==='load'&&r.phase==='Completed'?'부하 시험 완료':labels[r.phase]||r.phase)}</span></div>${r.mode==='load'&&active(r)?`<p role="status">${E({baseline:'기준 부하 측정 · 엣지 복귀 확인 중',pressure:'집중 부하 · 추천 노드가 표시되면 승인할 수 있습니다',recovery:'저부하 측정 · 복귀 조건 확인 중'}[r.stage]||'시험 준비 중')}</p>`:''}<p>요청 ${E(r.sent)}건 · 성공 ${E(r.succeeded)}건 · 실패 ${E(r.failed)}건 · 미확인 ${E(r.unknown)}건</p><p class="runtime-demo-route">${(r.routeHistory||[]).map(t=>E(t.node)+' ('+E(t.role)+')').join(' → ')||'실행 위치 관측 대기'}</p>${r.mode==='round-trip'?`<p>역할 복귀 ${r.returned?'확인':'미확인'} · 반환 중 ${E(r.retiring)}개</p>`:''}${active(r)?`<button class="button" id="demo-stop-history-${E(r.id)}" data-demo-stop="${E(r.id)}" data-demo-uid="${E(r.uid)}" data-demo-name="${E(r.name)}" ${r.phase==='Stopping'?'disabled':''}>${r.phase==='Stopping'?'진행 중 요청 마무리 중':'새 시험 요청 중단'}</button>`:''}${r.lastResult?`<pre aria-label="마지막 서비스 응답">${E(r.lastResult)}</pre>`:''}<small>실행 ID ${E(r.id)}${r.reason?' · '+E(r.reason):''}</small></article>`).join(''):'<p class="empty">실행한 데모가 없습니다. 서비스 행에서 시험을 시작하세요.</p>'}</section>`;
}
let data=null,error=null,actionError=null,fetching=null,draw=()=>{};
const intents=new Map(),sending=new Set(),pendingActions=new Map();
function persist(){try{root.localStorage.setItem('nexus-runtime-demo-intents-v1',JSON.stringify([...intents.values()]));}catch(_){}}
async function refresh(){if(fetching)return fetching;fetching=(async()=>{const c=new AbortController(),timer=setTimeout(()=>c.abort(),4500);try{
 const r=await root.fetch('/state/runtime-demos',{cache:'no-store',signal:c.signal});if(!r.ok)throw new Error('HTTP '+r.status);
 const value=await r.json();if(!Array.isArray(value.items)||!Array.isArray(value.runs))throw new Error('invalid_response');
 data=value;error=value.observation_error||null;
 for(const [uid,i] of intents)if(value.runs.some(r=>r.uid===uid&&r.id===i.id))intents.delete(uid);
 persist();
 }catch(_){error='demo_source_unavailable';}finally{clearTimeout(timer);fetching=null;draw();}})();return fetching;}
async function submit(i,stop=false){if(sending.has(i.uid))return;sending.add(i.uid);pendingActions.set(i.uid,{...i,stop});actionError=null;draw();const c=new AbortController(),timer=setTimeout(()=>c.abort(),5000);try{
 const url='/api/runtime-demos/'+encodeURIComponent(i.name)+'/runs/'+encodeURIComponent(i.id)+(stop?'/stop':'');
 const r=await root.fetch(url,{method:'POST',headers:{'Content-Type':'application/json','X-Runtime-Demo':'1'},body:JSON.stringify(stop?{serviceUid:i.uid}:{serviceUid:i.uid,mode:i.mode}),signal:c.signal});
 const result=await r.json();
 if(!r.ok){if(r.status<500&&!stop){intents.delete(i.uid);persist();}actionError={uid:i.uid,message:String(result.detail||'demo_request_failed')};return;}
 if(!stop){intents.delete(i.uid);persist();}
 if(data){data.runs=[result,...data.runs.filter(x=>!(x.uid===result.uid&&x.id===result.id))];}
 error=null;
 }catch(_){actionError={uid:i.uid,message:stop?'중단 접수 결과 확인 필요':'시작 접수 결과 확인 필요'};}
 finally{clearTimeout(timer);sending.delete(i.uid);pendingActions.delete(i.uid);draw();refresh();}}
function setup(callback){draw=callback;try{for(const i of JSON.parse(root.localStorage.getItem('nexus-runtime-demo-intents-v1')||'[]').slice(0,20))if(i&&typeof i.uid==='string'&&typeof i.id==='string'&&typeof i.name==='string'&&['single','round-trip','load'].includes(i.mode))intents.set(i.uid,i);}catch(_){}
 root.document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b||b.disabled)return;
 if(b.dataset.demoStart){const item=data?.items.find(x=>x.uid===b.dataset.demoStart);if(!item)return;const i={uid:item.uid,name:item.name,id:newId(),mode:b.dataset.demoMode};intents.set(i.uid,i);persist();submit(i);}
 if(b.dataset.demoRetry){const i=intents.get(b.dataset.demoRetry);if(i)submit(i);}
 if(b.dataset.demoStop)submit({id:b.dataset.demoStop,uid:b.dataset.demoUid,name:b.dataset.demoName},true);
 });}
const api={actions,panel,newId,setup,refresh,context,runStatus,renderActions:(uid,current,manual=false)=>actions(data,uid,current&&!error&&Date.now()/1000-(data?.observedAt||0)<15,intents.has(uid)||sending.has(uid),manual),renderPanel:()=>panel(data,error,[...intents.values()])+(actionError?`<p class="runtime-warning" role="alert">시험 접수: ${E(actionError.message)}</p>`:'')};
if(typeof module!=='undefined'&&module.exports)module.exports=api;root.NexusRuntimeDemo=api;
})(typeof window!=='undefined'?window:globalThis);
