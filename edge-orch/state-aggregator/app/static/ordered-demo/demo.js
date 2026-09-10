'use strict';
const $ = id => document.getElementById(id);
const names = {'etri-dev0001-jetorn':'Nano','etri-dev0005-jetagx':'AGX Orin','etri-ser0003-cg0ms0':'DGX Spark'};
const statuses = {running:'실행 중',stopping:'중지 요청됨',settling:'복귀·해제 확인 중',passed:'왕복 합격',failed:'확인 실패',stopped:'안전 중지 완료',interrupted:'실행 중단 기록'};
let current = null, connected = false, busy = false;
const num = x => Number.isFinite(x) ? x.toLocaleString('ko-KR', {maximumFractionDigits:1}) : '—';
const text = (id, value) => { $(id).textContent = value; };
function element(tag, value, className) { const e=document.createElement(tag); if(value!==undefined)e.textContent=value; if(className)e.className=className; return e; }
function controls(){
  $('start').disabled = busy || !connected || !current?.can_start;
  $('stop').disabled = busy || !connected || !current?.active;
}
function render(data){
  current=data; const r=data.run, runtime=data.runtime;
  const active=runtime.workers.find(w=>w.node===runtime.target_node);
  text('flow-title',active?.healthy ? `${names[runtime.target_node]||runtime.target_node} · ${runtime.arrival_rps>0 || active.inflight>0 ? '요청 처리 중' : '신규 요청 대기'}` : '현재 처리 가능 여부 확인 중');
  text('run-status',r ? statuses[r.status]||r.status : '시작 대기'); $('run-status').dataset.status=r?.status||'idle';
  $('nodes').replaceChildren(...runtime.execution_order.map(node=>{
    const w=runtime.workers.find(x=>x.node===node), o=w?.observation||{};
    const isActive=node===runtime.target_node && w?.healthy;
    const card=element('article',undefined,`node${isActive?' active':''}`);
    card.append(element('span',w?.role==='edge'?'EDGE · 현장 엣지':'SERVER · 서버','role'),element('h3',names[node]||node));
    let state='관측 미확인';
    if(o.agent_healthy===true && o.runtime_placement_verified===true){
      state=isActive?(runtime.arrival_rps>0 || w.inflight>0 ? '● 신규 요청 처리' : '● 신규 요청 대기'):o.model_loaded===true?'복귀를 위해 모델 유지':o.node_state==='CACHED' && o.model_vram_mib===0?'모델 해제 · 캐시 보관':'모델 준비 상태 확인 중';
    }
    card.append(element('div',state,'state'));
    const dl=element('dl');
    [['이번 실행 성공',`${num((r?.by_node||{})[node]||0)}건`],['모델 메모리',`${num(o.model_vram_mib)} MiB`],['진행 / 대기',`${num(w?.inflight)} / ${num(w?.queued)}`]].forEach(([k,v])=>dl.append(element('dt',k),element('dd',v)));
    card.append(dl); return card;
  }));
  $('visited').replaceChildren(...(r?.visited||[]).map(n=>element('li',names[n]||n)));
  if(!r)$('visited').append(element('li','시작하면 실제 이동을 기록합니다'));
  $('phases').replaceChildren(...data.phases.map((p,i)=>{
    const e=element('div',undefined,`phase${data.active&&r?.phase===i&&r.status==='running'?' current':''}`);
    e.append(element('strong',`${i+1}. ${p.label}`),element('span',`${p.rps} req/s · ${p.seconds}초`)); return e;
  }));
  text('ok',num(r?.ok||0)); text('failed',num(Object.values(r?.errors||{}).reduce((a,b)=>a+b,0)));
  text('pending',num(Math.max(0,(r?.attempted||0)-(r?.completed||0)))); text('rate',`${num(runtime.arrival_rps)} /s`);
  $('progress').value=r?.completed||0; $('progress').max=r?.planned||1622;
  const seconds=Math.floor(r?.elapsed_seconds||0); text('elapsed',`${String(Math.floor(seconds/60)).padStart(2,'0')}:${String(seconds%60).padStart(2,'0')} / 약 07:50`);
  let note = !r ? '시작하면 부하를 단계적으로 조절합니다. 노드 전환은 실행기가 판단합니다.' : `${r.phase_label} · ${num(r.completed)} / ${num(r.planned)}건 완료`;
  if(r?.status==='passed')note='1회 왕복 합격 · 모든 요청 성공 · Nano 복귀 · AGX·Spark 모델 메모리 해제 확인';
  if(r?.status==='stopped')note='신규 부하 중지 · 접수 요청 마무리와 Nano 복귀·모델 해제 확인 완료';
  if(r?.status==='failed')note='이번 실행은 합격 조건을 충족하지 못했습니다. 실패 내역과 실제 이동 기록을 확인하세요.';
  if(r?.status==='interrupted')note='컨트롤러 재시작 또는 종료로 중단된 실행입니다. 미확정 요청을 성공으로 계산하지 않습니다.';
  text('run-note',note);
  if(r?.last_result){text('result-node',names[r.last_result.node]||r.last_result.node);text('result-text',r.last_result.text);text('result-time',`내부 첫 토큰 ${num(r.last_result.ttft_ms)} ms · ${new Date(r.last_result.at*1000).toLocaleTimeString('ko-KR')}`);}
  else {text('result-node','대기');text('result-text','첫 요청의 응답을 기다립니다.');text('result-time','고정 질문 · 최대 8토큰');}
  text('diagnostics',JSON.stringify({run_id:r?.id,status:r?.status,errors:r?.errors,reason:r?.reason,runtime_state:runtime.state,runtime_reason:runtime.reason_code,retained_models:runtime.retained_models,cycles_completed:runtime.cycles_completed,transitions:r?.transitions},null,2));
  controls();
}
async function poll(){
  try{const response=await fetch('/api/demo',{signal:AbortSignal.timeout(5000)});if(!response.ok)throw Error('관측 응답 오류');const data=await response.json();connected=true;document.body.classList.remove('stale');$('error').hidden=true;text('connection',`● 실시간 연결 · ${new Date().toLocaleTimeString('ko-KR')}`);render(data);}
  catch{connected=false;document.body.classList.add('stale');text('connection','연결 끊김 · 마지막 관측');text('error','실시간 상태를 확인할 수 없습니다. 아래 수치는 마지막 관측이며 실행 버튼은 비활성입니다.');$('error').hidden=false;text('flow-title','실시간 처리 위치 미확인');controls();}
  finally{setTimeout(poll,1000);}
}
async function action(kind){
  busy=true;controls();text('action-message',kind==='start'?'실행 요청 중…':'신규 요청 중지 요청 중…');
  try{
    const response=await fetch(`/api/demo/${kind}`,{method:'POST',signal:AbortSignal.timeout(10000)});
    const data=await response.json();
    if(!response.ok){const messages={demo_already_running:'이미 데모가 실행 중입니다.',demo_workers_not_ready_or_busy:'세 장비의 준비와 이전 요청·모델 정리가 완료될 때까지 기다려주세요.'};throw Error(messages[data.detail]||'실행 요청을 완료하지 못했습니다.');}
    render(data);text('action-message',kind==='start'?'실제 왕복 데모를 시작했습니다. 창을 닫아도 실행은 계속됩니다.':'새 부하를 멈췄습니다. 요청 완료와 복귀·모델 해제를 기다립니다.');
  }catch(e){text('action-message',e.name==='TimeoutError'?'응답이 지연됩니다. 실행 상태를 확인한 뒤 다시 시도하세요.':e.message);}
  finally{busy=false;controls();}
}
$('start').addEventListener('click',()=>action('start'));$('stop').addEventListener('click',()=>action('stop'));poll();
