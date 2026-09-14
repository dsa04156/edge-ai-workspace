(function(root){
'use strict';
const E=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const reasons={admission_timeout:'gateway 대기 시간 초과',queue_full:'gateway 대기열 가득 참',route_unavailable:'실행 경로 관측 불가',no_ready_target:'준비된 실행체 없음',worker_timeout:'worker 응답 시간 초과',worker_transport_error:'worker 통신 오류',worker_http_error:'worker 오류 응답',worker_response_invalid:'worker 응답 계약 불일치',worker_outcome_unknown:'worker 처리 결과 미확인',demo_stopped_before_dispatch:'부하 제거로 전송 전 취소',node_route_changed:'요청에 지정된 노드 변경',controller_restarted_after_dispatch:'전송 후 재시작 · 결과 미확인',controller_restarted_before_dispatch:'전송 전 재시작 · 요청 중단',request_cancelled:'요청 연결 종료 또는 실행 취소',gateway_exception:'gateway 처리 예외',JSON_object_or_contract_required:'입력 계약 불일치',common_request_or_target_invalid:'공통 입력 또는 실행 후보 불일치',request_id_payload_conflict:'같은 요청 ID의 입력 충돌',request_in_progress:'같은 요청이 이미 처리 중',request_id_pending:'같은 요청이 대기 중',completed:'응답 완료'};
const expanded=new Set();
const states={receiving:'입력 수신',queued:'전송 대기',dispatched:'worker 처리 중',completed:'응답 완료',rejected:'전송 전 거절',cancelled:'취소',unknown:'결과 미확인',interrupted:'중단'};
const ms=v=>Number.isFinite(v)?v.toLocaleString('ko-KR',{maximumFractionDigits:1})+' ms':'미측정';
function view(uid,name,entry={}){
 const value=entry.value,rows=value?.items||[];
 return `<section class="runtime-request-history" aria-label="요청 진단 기록"><div class="runtime-history-heading"><div><h3>요청 진단 기록</h3><p>실패 이유와 요청이 지연된 구간을 확인합니다.</p></div><div class="runtime-history-actions"><button type="button" class="button" data-request-history="failures" data-history-uid="${E(uid)}" data-history-name="${E(name)}" aria-pressed="${entry.mode!=='all'}">실패·미확인</button><button type="button" class="button" data-request-history="all" data-history-uid="${E(uid)}" data-history-name="${E(name)}" aria-pressed="${entry.mode==='all'}">전체 요청</button><button type="button" class="button" data-request-history="refresh" data-history-uid="${E(uid)}" data-history-name="${E(name)}" ${entry.loading?'disabled':''}>${entry.loading?'조회 중…':'새로고침'}</button></div></div>${entry.error?'<p class="runtime-warning" role="alert">요청 기록 조회 실패 · 아래 기록은 마지막 조회 결과입니다. 새로고침으로 다시 확인하세요.</p>':''}${entry.loading?'<p role="status"><span class="runtime-spinner" aria-hidden="true"></span> 요청 원장 조회 중…</p>':''}${!value&&!entry.loading?'<p class="note">실패·미확인 또는 전체 요청을 눌러 저장된 기록을 조회하세요.</p>':''}${value&&!rows.length?`<p class="empty">${entry.mode==='all'?'보관 중인 요청 기록이 없습니다.':'보관 중인 실패·미확인 기록이 없습니다.'} 기록 수집 전의 실패 사유는 복원되지 않습니다.</p>`:''}${rows.length?`<div class="table-wrap"><table class="data-table runtime-request-table"><thead><tr><th>요청 · 시각</th><th>결과 · 사유</th><th>처리 노드</th><th>gateway 대기</th><th>worker 왕복</th><th>worker 추론</th></tr></thead><tbody>${rows.map(r=>`<tr><td><details data-request-detail="${E(uid)}-${E(r.seq)}" ${expanded.has(uid+'-'+r.seq)?'open':''}><summary>${E(r.requestId)}</summary><small>시도 ${E(r.seq)}${r.runId?' · 시험 '+E(r.runId):''}</small><small>진입 노드 ${E(r.admittedNode)} · 실행 revision ${E(r.revision)}</small><small>전체 ${ms(r.totalMilliseconds)} · worker 내부 대기 ${ms(r.workerQueueMilliseconds)}</small></details><small>${E(new Date(r.startedAt*1000).toLocaleString('ko-KR',{hour12:false}))}</small></td><td><strong>${r.replay?'저장된 결과 재조회':E(states[r.state]||r.state)}${r.status?' · HTTP '+E(r.status):''}</strong><span>${E(reasons[r.reason]||r.reason)}</span>${r.upstreamStatus?`<small>worker HTTP ${E(r.upstreamStatus)}</small>`:''}</td><td>${E(r.node||(r.replay?'이번 시도 전송 없음':'미전송'))}</td><td>${ms(r.gatewayQueueMilliseconds)}</td><td>${ms(r.workerRoundTripMilliseconds)}</td><td>${ms(r.inferenceMilliseconds)}</td></tr>`).join('')}</tbody></table></div>`:''}${value?.nextBefore?`<button type="button" class="button" data-request-history="more" data-history-uid="${E(uid)}" data-history-name="${E(name)}" ${entry.loading?'disabled':''}>이전 기록 더 보기</button>`:''}<p class="note">gateway 대기와 worker 왕복은 gateway 실측입니다. 추론·worker 내부 대기는 worker가 보고한 값이며 없으면 미측정입니다. 재조회는 새 추론으로 세지 않습니다.${value?` 최대 ${Math.floor(value.retentionSeconds/86400)}일 · 종료 기록은 실패·미확인 / 나머지 각각 ${E(value.retainedPerOutcomeClass)}건 보관(60초마다 정리). 조회 ${E(new Date(value.observedAt*1000).toLocaleTimeString('ko-KR',{hour12:false}))}`:''}</p></section>`;
}
const entries=new Map();let draw=()=>{};
async function load(uid,name,action){
 let entry=entries.get(uid)||{mode:'failures'};
 if(entry.loading)return;
 const more=action==='more';
 if(!more&&action!=='refresh')entry={mode:action==='all'?'all':'failures'};
 const before=more?entry.value?.nextBefore:null;if(more&&!before)return;
 entry.loading=true;entry.error=null;entries.set(uid,entry);draw();
 try{
  const params=new URLSearchParams({serviceUid:uid,failuresOnly:String(entry.mode!=='all'),limit:'25'});if(before)params.set('before',String(before));
  const r=await root.fetch('/state/runtime-services/'+encodeURIComponent(name)+'/requests?'+params,{cache:'no-store',signal:AbortSignal.timeout(5000)});
  if(!r.ok)throw Error('request_history_unavailable');
  const value=await r.json();if(!Array.isArray(value.items)||value.items.some(x=>x.uid!==uid))throw Error('identity_mismatch');
  if(more)value.items=[...entry.value.items,...value.items];
  entry.value=value;
 }catch(_){entry.error=true;}finally{entry.loading=false;draw();}
}
function setup(callback){draw=callback;root.document.addEventListener('toggle',e=>{const id=e.target.dataset?.requestDetail;if(id&&e.target.isConnected){if(e.target.open)expanded.add(id);else expanded.delete(id);}},true);root.document.addEventListener('click',e=>{const b=e.target.closest('[data-request-history]');if(b&&!b.disabled)load(b.dataset.historyUid,b.dataset.historyName,b.dataset.requestHistory);});}
const api={view,setup,load,render:(uid,name)=>view(uid,name,entries.get(uid))};
if(typeof module!=='undefined'&&module.exports)module.exports=api;root.NexusRequestHistory=api;
})(typeof window!=='undefined'?window:globalThis);
