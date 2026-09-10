(function(root){
'use strict';
const E=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time=value=>value==null?'관측 없음':new Date(value*1000).toLocaleString('ko-KR',{hour12:false});
const reasons={sustained_latency_breach:'지속적인 응답 지연으로 이동',latency_no_qualified_target:'지연 초과 · 검증된 이동 후보 없음',healthy_current_placement:'현재 배치 유지',sustained_pressure:'지속 부하로 처리 용량 확대',sustained_low_load_return:'부하 감소로 선호 위치 복귀',initial_or_unhealthy_or_policy_changed:'최초 배치·상태·정책 재검토',waiting_for_pod_and_application_ready:'새 실행체와 모델 준비 대기',target_ready_route_switched:'준비 완료 후 요청 경로 전환',pressure_no_qualified_capacity:'부하 증가 · 검증된 추가 용량 없음'};
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
function renderState(entry,now=Date.now()/1000,expanded=new Set()){
 const data=entry.data;
 const current=Boolean(data&&!entry.error&&!data.observation_error&&now-data.observed_at>=0&&now-data.observed_at<15);
 const intro='<div class="section-heading"><div><h2>클러스터 서비스 실행</h2><p class="note">서비스 계약과 전체 노드 조건으로 배치합니다. 새 실행체 준비 → 요청 경로 전환 → 이전 요청 완료 → 자원 반환.</p></div><button class="button" data-runtime-refresh>새로고침</button></div>';
 const notice=entry.error||data?.observation_error||(!current&&data?'관측이 오래되어 현재 상태를 확인할 수 없습니다.':null);
 if(!data)return `<section class="panel runtime-panel">${intro}<p role="status">${entry.error?'공통 제어기 관측 불가 · '+E(entry.error):'공통 제어기 조회 중…'}</p></section>`;
 return `<section class="panel runtime-panel">${intro}<p class="note">Kubernetes RuntimeService · 마지막 수신 ${E(time(data.observed_at))} · 5초마다 조회</p>${notice?`<p class="runtime-warning" role="status">관측 확인 필요 · ${E(notice)}</p>`:''}${data.services.length?`<div class="table-wrap"><table class="data-table runtime-table"><thead><tr><th>서비스 / 상태</th><th>요청을 받는 실행체</th><th>이동 준비 / 반환 중</th><th>전환 근거</th></tr></thead><tbody>${data.services.map(s=>{
 const ok=current&&!s.observation_error;
 const release=s.lastRelease,transition=s.lastTransition;
 return `<tr><td><strong>${E(s.name)}</strong><span class="badge ${ok&&s.serving?'ok':''}">${ok?E(phases[s.phase]||s.phase):'현재 관측 확인 불가'}</span><small>${s.active?.memoryOnlyRelease?'모델 메모리 관리':'Pod 생성·축소 관리'}</small>${latencyView(s,now,ok)}</td><td>${targetView(s.active,now,ok)}</td><td>${s.target?'<small>준비 중</small>'+targetView(s.target,now,ok):''}${s.retiring.map(t=>'<small>반환 중</small>'+targetView(t,now,ok)).join('')}${!s.target&&!s.retiring.length?'<small>진행 중인 전환 없음</small>':''}${release?`<small>마지막 모델 해제: ${E(release.node)} · ${E(release.modelVramMiB)} MiB<br>${E(time(release.at))} · ${release.reservationRetained?'GPU 예약 유지':'예약 유지 확인 안 됨'}</small>`:''}</td><td><span>${E(reasons[s.reason]||s.reason)}</span>${transition?`<small>${E(transition.fromNode||'최초 배치')} → ${E(transition.toNode)}<br>${E(reasons[transition.reason]||transition.reason)}<br>${E(time(transition.at))}</small>`:''}<details data-runtime-details="${E(s.uid)}" ${expanded.has(s.uid)?'open':''}><summary>후보 제외 근거 ${s.excludedCandidates.length}건</summary><ul>${s.excludedCandidates.map(c=>`<li>${E(c.node)} / ${E(c.variant)}<br>${E(c.reasons.join(', '))}</li>`).join('')}</ul></details></td></tr>`;
 }).join('')}</tbody></table></div>`:'<p class="empty">공통 제어기에 등록된 서비스가 없습니다.</p>'}<p class="note">마지막 메모리 해제는 과거 확인 기록입니다. GPU 예약 반환이나 현재 대기 모델 상태를 뜻하지 않습니다. 서비스 등록·정책 변경은 Kubernetes 계약으로 관리합니다.</p></section>`;
}
let entry={data:null,error:null},timer=null,pending=null,draw=()=>{},enabled=false;
const expanded=new Set();
async function refresh(){
 if(pending)return pending;
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
function setup(callback){draw=callback;root.document.addEventListener('click',e=>{if(e.target.closest('[data-runtime-refresh]'))refresh();});root.document.addEventListener('toggle',e=>{const id=e.target.dataset?.runtimeDetails;if(id&&e.target.isConnected){if(e.target.open)expanded.add(id);else expanded.delete(id);}},true);}
const api={renderState,targetView,latencyView,activate,setup,render:()=>renderState(entry,Date.now()/1000,expanded)};
if(typeof module!=='undefined'&&module.exports)module.exports=api;root.NexusCommonRuntime=api;
})(typeof window!=='undefined'?window:globalThis);
