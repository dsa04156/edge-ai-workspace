(function(root){
'use strict';
const E=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time=value=>value==null?'관측 없음':new Date(value*1000).toLocaleString('ko-KR',{hour12:false});
const reasons={augmentation_approval_required:'실제 부하가 지속되어 증강 승인을 기다립니다',sustained_latency_breach:'지속적인 응답 지연으로 이동',latency_no_qualified_target:'지연 초과 · 검증된 이동 후보 없음',healthy_current_placement:'현재 배치 유지',sustained_pressure:'지속 부하로 처리 용량 확대',sustained_low_load_return:'부하 감소로 선호 위치 복귀',initial_or_unhealthy_or_policy_changed:'최초 배치·상태·정책 재검토',waiting_for_pod_and_application_ready:'새 실행체와 모델 준비 대기',target_ready_route_switched:'준비 완료 후 요청 경로 전환',pressure_no_qualified_capacity:'부하 증가 · 검증된 추가 용량 없음'};
const phases={Serving:'요청 처리 가능',Preparing:'이동 준비',Blocked:'실행 보류',Draining:'남은 요청 처리·반환',Suspended:'중지됨',Recovering:'이전 요청 복구 확인',Reconciling:'상태 확인'};
function targetView(target,now,current){
 if(!target)return '<span class="note">없음</span>';
 const o=target.observation,h=current&&o&&now-o.at>=0&&now-o.at<15?o.health:null;
 return `<strong>${E(target.node)}</strong><small>${E(target.role==='edge'?'엣지':target.role==='server'?'서버':target.role)} · ${E(target.variant)}</small><small>${h?`${E(h.nodeState|| (h.ready?'준비됨':'준비 대기'))} · 처리 중 ${E(h.inFlight)}건`:'실행체 관측 확인 불가'}</small>${target.memoryOnlyRelease?`<small>모델 메모리 ${h?.modelVramMiB!=null?E(h.modelVramMiB.toFixed(1))+' MiB':'—'} · GPU 예약 유지</small>`:''}`;
}
function latencyView(s,now,current){
 const l=s.latency;if(!l)return '';
 if(!current||now-l.at<0||now-l.at>=15)return '<small>지연 관측 확인 불가</small>';
 if(!l.valid)return `<small>지연 판단 대기 · 성공 표본 ${E(l.successfulSamples)}개 · 실패 ${E(l.failures)}개</small>`;
 return `<small>요청 p95 ${E(l.p95Milliseconds.toFixed(1))} ms / 기준 ${E(l.maxP95Milliseconds)} ms<br>대기·응답 포함 · ${E(l.windowSeconds)}초 창 · ${E(l.successfulSamples)}개 표본</small>`;
}
const num=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('ko-KR',{maximumFractionDigits:2}):'—';
const approvalLabels={Approved:'승인 접수 · 실행 조건 재확인',Preparing:'모델 준비 중 · 기존 서비스 처리 유지',Applied:'증강 적용 · 신규 요청 경로 전환 완료',Failed:'증강 실패 · 실행 근거 확인 필요',Expired:'추천 조건 변경 · 승인 만료',Interrupted:'제어기 재시작 · 다시 추천 필요'};
function augmentationView(s,now,current){
 if(!s.aiInference)return '';
 const ok=current&&!s.observation_error,load=ok?s.load:null,l=ok?s.latency:null;
 const p=ok?s.proposal:null,ready=Boolean(s.approvalRequired&&s.serving&&p&&now<p.expiresAt&&!s.target);
 const result=s.lastApproval;
 return `<article class="panel augmentation-panel" data-augmentation-service="${E(s.uid)}"><div class="section-heading"><div><p class="eyebrow">AI 추론 · 지표 기반 증강</p><h2>${E(s.name)}</h2></div><span class="badge">${!ok?'관측 확인 불가':s.target?'모델 준비 중':p?'승인 대기':s.serving?'처리 중':'준비 확인 필요'}</span></div><p class="note">센서 수집은 유지하고 AI 추론 요청만 전환합니다. 부하 시험은 실제 등록 입력을 사용합니다.</p><dl class="augmentation-metrics"><div><dt>요청 p95 / 목표</dt><dd>${num(l?.p95Milliseconds)} / ${num(l?.maxP95Milliseconds)} <small>ms</small></dd></div><div><dt>유입 / 완료 처리율</dt><dd>${num(l?.arrivalRps)} / ${num(l?.completedRps)} <small>건/s</small></dd></div><div><dt>대기 / 처리 중</dt><dd>${num(load?.pending)} / ${num(load?.inFlight)} <small>건</small></dd></div><div><dt>검증된 수용 요청률</dt><dd>${num(load?.qualifiedRps)} <small>건/s</small></dd></div><div><dt>동시 처리 한도</dt><dd>${num(load?.capacity)} <small>건</small></dd></div><div><dt>실패 / 측정 표본</dt><dd>${num(l?.failures)} / ${num(l?.samples)} <small>건</small></dd></div></dl><p class="note">${l?`${num(l.windowSeconds)}초 집계 · ${l.valid?'지연 판단 유효':'지연 판단 대기 (표본·오류 확인)'}`:'아직 유효한 지표를 받지 못했습니다.'} · ${E(time(s.checkedAt))}. 노드 CPU·GPU 사용률은 아래 노드 관측에서 별도로 확인합니다.</p><div class="augmentation-route"><div><small>현재 추론 위치</small><strong>${E(ok?s.active?.node:'확인 불가')}</strong>${ok&&s.active?.observation?.health?.modelVramMiB!=null?`<small>모델 메모리 ${num(s.active.observation.health.modelVramMiB)} MiB</small>`:''}</div><span aria-hidden="true">→</span><div><small>${s.target?'준비 중인 노드':'증강 추천 노드'}</small><strong>${E(ok?(s.target?.node||p?.node||'추천 조건 대기'):'확인 불가')}</strong>${p?`<small>${E(p.reason==='sustained_latency_breach'?'지속적인 응답 지연으로 추천':p.reason==='sustained_pressure'?'지속 부하로 추가 처리 용량 추천':p.reason)} · 검증 처리율 ${num(p.qualifiedRps)}건/s · 기준 p95 ${num(p.qualifiedP95Milliseconds)}ms</small>`:''}</div></div>${root.NexusRuntimeDemo?.renderActions(s.uid,ok,s.approvalRequired)||''}<div class="augmentation-approval"><button id="augment-${E(s.uid)}" class="button primary" data-augmentation-approve="${E(s.uid)}" ${!ready||approving.has(s.uid)?'disabled':''}>${approving.has(s.uid)?'승인 접수 중…':'추천 노드 증강 승인'}</button><p>${!s.approvalRequired?'승인 기반 증강이 설정되지 않았습니다.':p?'클릭하면 최신 부하·노드 자격을 다시 확인하고 모델을 준비합니다.':E(reasons[s.reason]||s.reason||'부하가 지속되면 추천 노드가 표시됩니다.')}</p></div>${result?`<p class="augmentation-receipt" role="status">마지막 승인: ${E(approvalLabels[result.status]||result.status)} · ${E(result.sourceNode)} → ${E(result.node)}</p>`:''}${approvalErrors.has(s.uid)?`<p class="runtime-warning" role="alert">${E(approvalErrors.get(s.uid))}</p>`:''}<small class="note">부하 기반 증강은 승인 후 실행 · 저부하 복귀·남은 요청 마무리는 기존 정책 적용 · 모델 메모리 해제와 GPU 예약 반환은 별개입니다.</small></article>`;
}
const approving=new Set(),approvalErrors=new Map();
async function approve(uid){
 const s=entry.data?.services?.find(x=>x.uid===uid),p=s?.proposal;
 if(!p||approving.has(uid))return;
 approving.add(uid);approvalErrors.delete(uid);draw();
 try{
  const response=await root.fetch('/api/runtime-demos/'+encodeURIComponent(s.name)+'/augmentation/approve',{method:'POST',headers:{'Content-Type':'application/json','X-Runtime-Demo':'1'},body:JSON.stringify({serviceUid:uid,recommendationId:p.id}),signal:AbortSignal.timeout(15000)});
  const result=await response.json();
  if(!response.ok)throw new Error(response.status===409?'추천 조건이 변경됐습니다. 최신 추천을 확인한 후 다시 승인하세요.':'승인 요청 실패: '+String(result.detail||response.status));
  s.lastApproval=result;s.proposal=null;
 }catch(e){approvalErrors.set(uid,e.name==='TimeoutError'?'접수 결과 확인 중입니다. 마지막 승인 기록을 확인하세요.':e.message||'승인 결과 확인 필요');}
 finally{approving.delete(uid);await refresh();draw();}
}
function renderState(entry,now=Date.now()/1000,expanded=new Set()){
 const data=entry.data;
 const current=Boolean(data&&!entry.error&&!data.observation_error&&now-data.observed_at>=0&&now-data.observed_at<15);
 const intro='<div class="section-heading"><div><h2>클러스터 서비스 실행</h2><p class="note">서비스 계약과 전체 노드 조건으로 배치합니다. 새 실행체 준비 → 요청 경로 전환 → 이전 요청 완료 → 자원 반환.</p></div><button class="button" data-runtime-refresh>새로고침</button></div>';
 const notice=entry.error||data?.observation_error||(!current&&data?'관측이 오래되어 현재 상태를 확인할 수 없습니다.':null);
 if(!data)return `<section class="panel runtime-panel">${intro}<p role="status">${entry.error?'공통 제어기 관측 불가 · '+E(entry.error):'공통 제어기 조회 중…'}</p></section>`;
 return `${data.services.map(s=>augmentationView(s,now,current)).join('')}<section class="panel runtime-panel">${intro}<p class="note">Kubernetes RuntimeService · 마지막 수신 ${E(time(data.observed_at))} · 5초마다 조회</p>${notice?`<p class="runtime-warning" role="status">관측 확인 필요 · ${E(notice)}</p>`:''}${data.services.length?`<div class="table-wrap"><table class="data-table runtime-table"><thead><tr><th>서비스 / 상태</th><th>요청을 받는 실행체</th><th>이동 준비 / 반환 중</th><th>전환 근거</th></tr></thead><tbody>${data.services.map(s=>{
 const ok=current&&!s.observation_error;
 const release=s.lastRelease,transition=s.lastTransition;
 return `<tr><td><strong>${E(s.name)}</strong><span class="badge ${ok&&s.serving?'ok':''}">${ok?E(phases[s.phase]||s.phase):'현재 관측 확인 불가'}</span><small>${s.active?.memoryOnlyRelease?'모델 메모리 관리':'Pod 생성·축소 관리'}</small>${latencyView(s,now,ok)}${!s.aiInference?(root.NexusRuntimeDemo?.renderActions(s.uid,ok)||''):''}</td><td>${targetView(s.active,now,ok)}</td><td>${s.target?'<small>준비 중</small>'+targetView(s.target,now,ok):''}${s.retiring.map(t=>'<small>반환 중</small>'+targetView(t,now,ok)).join('')}${!s.target&&!s.retiring.length?'<small>진행 중인 전환 없음</small>':''}${release?`<small>마지막 모델 해제: ${E(release.node)} · ${E(release.modelVramMiB)} MiB<br>${E(time(release.at))} · ${release.reservationRetained?'GPU 예약 유지':'예약 유지 확인 안 됨'}</small>`:''}</td><td><span>${E(reasons[s.reason]||s.reason)}</span>${transition?`<small>${E(transition.fromNode||'최초 배치')} → ${E(transition.toNode)}<br>${E(reasons[transition.reason]||transition.reason)}<br>${E(time(transition.at))}</small>`:''}<details data-runtime-details="${E(s.uid)}" ${expanded.has(s.uid)?'open':''}><summary>후보 제외 근거 ${s.excludedCandidates.length}건</summary><ul>${s.excludedCandidates.map(c=>`<li>${E(c.node)} / ${E(c.variant)}<br>${E(c.reasons.join(', '))}</li>`).join('')}</ul></details></td></tr>`;
 }).join('')}</tbody></table></div>`:'<p class="empty">공통 제어기에 등록된 서비스가 없습니다.</p>'}<p class="note">마지막 메모리 해제는 과거 확인 기록입니다. GPU 예약 반환이나 현재 대기 모델 상태를 뜻하지 않습니다. 서비스 등록·정책 변경은 Kubernetes 계약으로 관리합니다.</p></section>`;
}
let entry={data:null,error:null},timer=null,pending=null,draw=()=>{},enabled=false;
const expanded=new Set();
async function refresh(){
 if(pending)return pending;root.NexusRuntimeDemo?.refresh();
 pending=(async()=>{const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),4500);try{
  const r=await root.fetch('/state/runtime-services',{method:'GET',cache:'no-store',signal:controller.signal});
  if(!r.ok)throw new Error('HTTP '+r.status);
  const data=await r.json();
  if(data.schema_version!=='edgeai.common-runtime/v1'||!Array.isArray(data.services))throw new Error('응답 계약 확인 필요');
  entry={data,error:null};
 }catch(e){entry.error=e.name==='AbortError'?'조회 시간 초과':'공통 제어기 응답 확인 불가';}
 finally{clearTimeout(timeout);pending=null;if(enabled)draw();}})();
 return pending;
}
function activate(value){if(value===enabled)return;enabled=value;if(timer)clearInterval(timer);timer=null;if(value){refresh();timer=setInterval(()=>{if(!root.document.hidden)refresh();},5000);}}
function setup(callback){draw=callback;root.NexusRuntimeDemo?.setup(callback);root.document.addEventListener('click',e=>{if(e.target.closest('[data-runtime-refresh]'))refresh();const b=e.target.closest('[data-augmentation-approve]');if(b&&!b.disabled)approve(b.dataset.augmentationApprove);});root.document.addEventListener('toggle',e=>{const id=e.target.dataset?.runtimeDetails;if(id&&e.target.isConnected){if(e.target.open)expanded.add(id);else expanded.delete(id);}},true);}
const api={augmentationView,renderState,targetView,latencyView,activate,setup,render:()=>renderState(entry,Date.now()/1000,expanded)+(root.NexusRuntimeDemo?.renderPanel()||'')};
if(typeof module!=='undefined'&&module.exports)module.exports=api;root.NexusCommonRuntime=api;
})(typeof window!=='undefined'?window:globalThis);
