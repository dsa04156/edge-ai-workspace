(function(root){
'use strict';
const E=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time=value=>value==null?'관측 없음':new Date(value*1000).toLocaleString('ko-KR',{hour12:false});
const reasons={augmentation_approval_required:'실제 부하가 지속되어 증강 승인을 기다립니다',sustained_latency_breach:'지속적인 응답 지연으로 이동',latency_no_qualified_target:'지연 초과 · 검증된 이동 후보 없음',healthy_current_placement:'현재 배치 유지',sustained_pressure:'지속 부하로 처리 용량 확대',sustained_low_load_return:'부하 감소로 선호 위치 복귀',initial_or_unhealthy_or_policy_changed:'최초 배치·상태·정책 재검토',waiting_for_pod_and_application_ready:'새 실행체와 모델 준비 대기',target_ready_route_switched:'준비 완료 후 요청 경로 전환',pressure_no_qualified_capacity:'부하 증가 · 검증된 추가 용량 없음'};
const phases={Serving:'요청 처리 가능',Preparing:'이동 준비',Blocked:'실행 보류',Draining:'남은 요청 처리·반환',Suspended:'중지됨',Recovering:'이전 요청 복구 확인',Reconciling:'상태 확인',Starting:'서비스 시작 중'};
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
const selectedNodes=new Map();
function observationNow(value,monotonic=root.performance.now()/1000){
 const at=value.data?.observed_at;
 return Number.isFinite(at)&&Number.isFinite(value.receivedMonotonic)?at+Math.max(0,monotonic-value.receivedMonotonic):Date.now()/1000;
}
const observationErrors={runtime_snapshot_stale:'제어기 노드 관측이 오래됐습니다',runtime_operator_error:'제어기 관측 처리 오류',runtime_service_observation_stale:'서비스 상태 갱신이 지연됐습니다',runtime_source_unavailable:'제어기 응답을 받지 못했습니다'};
const fresh=(at,now)=>typeof at==='number'&&now-at>=0&&now-at<15;
function serviceMotion(s,now,current){
 const ok=current&&!s.observation_error&&(s.checkedAt==null||fresh(s.checkedAt,now));
 const load=ok&&s.load&&(s.load.at==null||fresh(s.load.at,now))?s.load:null;
 const l=ok&&s.latency&&fresh(s.latency.at,now)?s.latency:null;
 const p=ok&&s.proposal&&now<s.proposal.expiresAt?s.proposal:null;
 const busy=Boolean(ok&&s.serving&&load&&(load.inFlight>0||load.pending>0));
 let title=!ok?'최신 관측 확인 불가':s.target?'모델 준비 중':(s.retiring||[]).length?'이전 요청 마무리 중':p?'추천 도착 · 승인 대기':busy?'AI 추론 실행 중':s.serving?'요청 대기 중':phases[s.phase]||'서비스 준비 확인';
 return {ok,load,l,p,busy,title};
}
function mapNodes(s,m,now){
 const nodes=new Map();
 for(const t of [...(s.augmentationStages||[]),...(m.ok?s.eligibleCandidates||[]:[]),s.active,s.target,...(s.retiring||[]),m.p])if(t?.node)nodes.set(t.node,{...(nodes.get(t.node)||{}),...t});
 return [...nodes.values()].sort((a,b)=>(a.step||99)-(b.step||99)||(a.role==='server')-(b.role==='server')||a.node.localeCompare(b.node)).map(t=>{
  const current=m.ok&&s.active?.node===t.node,preparing=m.ok&&s.target?.node===t.node,retiring=m.ok&&(s.retiring||[]).some(x=>x.node===t.node),recommended=m.p?.node===t.node;
  const source=current?s.active:preparing?s.target:retiring?(s.retiring||[]).find(x=>x.node===t.node):null;
  const health=m.ok&&source?.observation&&fresh(source.observation.at,now)?source.observation.health:null;
  const state=m.ok&&s.phase==='Suspended'?'stopped':!m.ok||(!current&&!preparing&&!retiring&&!recommended&&t.eligible===false)?'unknown':preparing?'preparing':retiring?'retiring':current?(s.serving?'active':'unknown'):recommended?'recommended':'candidate';
  const title={stopped:'서비스 중지 · 모델 해제',unknown:'현재 상태 확인 불가',preparing:'모델 준비 중',retiring:'남은 요청 마무리',active:m.busy?'추론 실행 중':'요청 대기 중',recommended:'증강 추천 · 승인 대기',candidate:'배치 후보 · 모델 미관측'}[state];
  return {...t,state,title,health,flow:state==='active'&&m.busy};
 });
}
let nodeEntry={data:null,error:null,receivedAt:0},nodeFetch=null;
function nodeMetrics(node,now,entry=nodeEntry){
 const snapshot=entry.data?.find(n=>n.hostname===node),at=Date.parse(snapshot?.collected_at)/1000;
 const receivedAge=Number.isFinite(entry.receivedMonotonic)?root.performance.now()/1000-entry.receivedMonotonic:now-entry.receivedAt;
 const current=Boolean(!entry.error&&snapshot&&receivedAge>=0&&receivedAge<60&&Number.isFinite(at)&&now-at>=-5&&now-at<60&&snapshot.raw_metrics?.up===1&&snapshot.node_health!=='unavailable');
 const raw=current?snapshot.raw_metrics:{};
 const finite=v=>typeof v==='number'&&Number.isFinite(v)?v:null;
 const ratio=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0&&v<=1?v:null;
 return {current,at,health:current?snapshot.node_health:null,cpu:ratio(raw.cpu_utilization),memory:ratio(raw.memory_usage_ratio),gpu:ratio(raw.gpu_utilization),gpuMemory:ratio(raw.gpu_memory_usage_ratio),gpuUsed:raw.gpu_memory_used_mib??null,gpuTotal:raw.gpu_memory_total_mib??null,cpuTemperature:finite(raw.cpu_temperature_celsius),gpuTemperature:finite(raw.gpu_temperature_celsius),systemTemperature:finite(raw.system_temperature_celsius)};
}
function nodeMetricsView(node,now,entry=nodeEntry){
 const m=nodeMetrics(node,now,entry),percent=v=>(v*100).toFixed(1)+'%';
 return `<span class="runtime-node-metrics" aria-label="노드 전체 CPU 메모리 GPU 사용률">${[['CPU',m.cpu],['메모리',m.memory],['GPU',m.gpu]].map(([label,v])=>`<span class="runtime-hardware-metric"><span>${label}</span><b>${v==null?(m.current?'미수집':'—'):percent(v)}</b>${v==null?'<i class="missing"></i>':`<i role="meter" aria-label="노드 ${label} 사용률" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${(v*100).toFixed(1)}"><i style="transform:scaleX(${v})"></i></i>`}</span>`).join('')}</span><span class="runtime-node-temperatures" aria-label="노드 온도">${[['CPU 온도',m.cpuTemperature],['GPU 온도',m.gpuTemperature],['시스템 온도',m.systemTemperature]].map(([label,v])=>`<span><span>${label}</span><b>${v==null?(m.current?'미수집':'—'):v.toFixed(1)+' °C'}</b></span>`).join('')}</span><small class="runtime-node-observed">${m.current?`노드 ${E({healthy:'정상',degraded:'주의'}[m.health]||'상태 확인')} · ${E(new Date(m.at*1000).toLocaleTimeString('ko-KR',{hour12:false}))}`:'노드 지표 관측 불가 · 최신 수집 확인 필요'}</small>`;
}
async function refreshNodes(){
 if(nodeFetch)return nodeFetch;
 nodeFetch=(async()=>{try{const r=await root.fetch('/state/nodes',{cache:'no-store',signal:AbortSignal.timeout(4500)});if(!r.ok)throw new Error('node_source_unavailable');const data=await r.json();if(!Array.isArray(data))throw new Error('invalid_nodes');nodeEntry={data,error:null,receivedMonotonic:root.performance.now()/1000};}catch(_){nodeEntry.error='node_source_unavailable';}finally{nodeFetch=null;if(enabled)draw();}})();return nodeFetch;
}
function runtimeMap(s,m,now){
 const nodes=mapNodes(s,m,now),height=Math.max(nodes.length,1)*196-12;
 const chosen=nodes.find(t=>t.node===selectedNodes.get(s.uid));const hardware=chosen?nodeMetrics(chosen.node,now):null;
 const icon='<svg viewBox="0 0 32 32" aria-hidden="true"><rect x="4" y="3" width="24" height="11" rx="2"/><rect x="4" y="18" width="24" height="11" rx="2"/><path d="M8 8h1m4 0h10M8 23h1m4 0h10"/></svg>';
 return `<section class="runtime-map ${s.augmentationStages?.length?'staged':''}" aria-label="AI 서비스 노드 실행 지도"><div class="runtime-map-heading"><h3>${s.augmentationStages?.length?'단계별 증강 경로':'요청 경로와 실행 노드'}</h3><span>노드를 눌러 상세 확인</span></div><div class="runtime-map-canvas"><div class="runtime-map-source"><span class="runtime-source-icon" aria-hidden="true">↗</span><strong>AI 추론 요청</strong><small>${m.ok?`${num(m.load?.pending)}건 대기 · ${num(m.load?.inFlight)}건 처리 중`:'현재 요청 관측 불가'}</small></div><svg class="runtime-map-links" viewBox="0 0 80 ${height}" preserveAspectRatio="none" aria-hidden="true">${nodes.map((t,i)=>`<path class="${t.state} ${t.flow?'flowing':''}" d="M0 ${height/2} C40 ${height/2} 40 ${i*196+92} 80 ${i*196+92}"/>`).join('')}</svg><div class="runtime-map-nodes">${nodes.map(t=>`<div class="runtime-node-card"><button type="button" id="map-${E(s.uid)}-${E(t.node)}" class="runtime-map-node ${t.state}" data-runtime-node="${E(t.node)}" data-runtime-uid="${E(s.uid)}" aria-pressed="${chosen?.node===t.node}"><span class="runtime-node-icon">${icon}</span><span class="runtime-node-copy"><small>${t.step?E(t.step)+'단계 · ':''}${E(t.role==='edge'?'현장 엣지':t.role==='server'?'서버':'실행 노드')}</small><strong>${E(t.label||t.node)}</strong>${t.label?`<small class="runtime-tier-host">${E(t.node)}</small>`:''}<span class="runtime-node-state">${t.state==='preparing'||t.state==='retiring'||t.flow?'<span class="runtime-spinner" aria-hidden="true"></span>':'<span class="runtime-status-dot" aria-hidden="true"></span>'}${E(t.title)}</span><small>${t.health?.modelVramMiB!=null?'모델 '+num(t.health.modelVramMiB)+' MiB':t.state==='recommended'?'클릭 승인 후 모델 준비':t.state==='candidate'?'실행 준비 여부는 별도 확인':'모델 메모리 관측 없음'}</small>${t.step?`<small>검증 ${num(t.qualifiedRps)}건/s · p95 ${num(t.qualifiedP95Milliseconds)}ms</small>`:''}${nodeMetricsView(t.node,now)}</span></button>${t.step?(root.NexusRuntimeDemo?.renderNodeActions(s.uid,t.node,t.label||t.node,m.ok)||''):''}</div>`).join(s.augmentationStages?.length?'<span class="runtime-tier-arrow" aria-hidden="true">→</span>':'')||'<p class="empty">실행 노드 관측 대기</p>'}</div></div><div class="runtime-map-legend"><span><i class="active"></i>현재 요청 경로</span><span><i class="recommended"></i>증강 추천</span><span><i class="preparing"></i>모델 준비</span><span>${s.augmentationStages?.length?'화살표: 증강 순서 · 강조 노드: 현재 요청 경로':'흐르는 선: 실제 처리·대기 요청'} · CPU·메모리·GPU: 노드 전체 실측 · 시스템 온도: ACPI 센서 최댓값</span></div>${chosen?`<div class="runtime-map-detail" role="region" aria-label="선택 노드 상세"><strong>${E(chosen.node)}</strong><span>${E(chosen.variant)} · ${E(chosen.title)}</span><span>동시 처리 한도 ${num(chosen.capacity)}건 · 모델 ${num(chosen.health?.modelVramMiB)} MiB</span><span>노드 GPU 메모리 ${num(hardware.gpuUsed)} / ${num(hardware.gpuTotal)} MiB</span></div>`:''}</section>`;
}
function augmentationView(s,now,current){
 if(!s.aiInference)return '';
 const m=serviceMotion(s,now,current),{ok,load,l,p}=m;
 const ready=Boolean(s.approvalRequired&&s.serving&&p&&!s.target),result=s.lastApproval;
 const ctx=root.NexusRuntimeDemo?.context(s.uid,now);if(ctx){ctx.detailsOpen=expanded.has("run-"+s.uid);ctx.inlineControls=s.approvalRequired;}
 const receipt=result?`<p class="augmentation-receipt" role="status">${E(approvalLabels[result.status]||result.status)}<small>${E(result.sourceNode)} → ${E(result.node)}</small></p>`:'';
 return `<article class="panel augmentation-panel ${s.augmentationStages?.length?'staged':''}" data-augmentation-service="${E(s.uid)}"><header class="augmentation-header"><div><p class="eyebrow">AI 서비스 실행 지도</p><h2>${E(s.name)}</h2></div><div class="runtime-service-state ${ok?'':'unknown'}" role="status">${ok&&(s.target||m.busy||(s.retiring||[]).length)?'<span class="runtime-spinner" aria-hidden="true"></span>':'<span class="runtime-status-dot" aria-hidden="true"></span>'}<strong>${E(m.title)}</strong></div><button class="button runtime-refresh" data-runtime-refresh aria-label="AI 실행 상태 새로고침">↻</button></header>${!ok?`<p class="runtime-warning" role="status">${E(observationErrors[s.observation_error]||'최신 관측 응답을 확인할 수 없습니다')} · 마지막 서비스 관측 ${E(time(s.checkedAt))} · 5초마다 재시도</p>`:''}<div class="augmentation-workspace">${runtimeMap(s,m,now)}<aside class="augmentation-controls" aria-label="부하 시험과 증강 승인"><h3>서비스 실행·중지</h3>${root.NexusRuntimeDemo?.renderActions(s.uid,ok,s.approvalRequired)||(ctx?.loading?'<p class="runtime-loading"><span class="runtime-spinner" aria-hidden="true"></span>시험 설정 조회 중…</p>':`<p>${ctx?.current?'등록된 부하 시험이 없습니다.':'시험 설정 관측을 확인할 수 없습니다.'}</p>`)}${ctx?root.NexusRuntimeDemo.runStatus(ctx,now):''}<div class="augmentation-approval"><div><strong>${p?'증강 추천 도착':s.target?'모델 준비 중':'증강 승인'}</strong><p>${!ok?'최신 관측을 확인한 후 승인할 수 있습니다.':!s.approvalRequired?'승인 기반 증강이 설정되지 않았습니다.':p?`${E(s.augmentationStages?.find(t=>t.variant===p.variant)?.label||p.node)} · ${num(p.qualifiedRps)}건/s · p95 ${num(p.qualifiedP95Milliseconds)}ms`:s.target?'준비 완료 후 신규 요청 경로를 전환합니다.':E(reasons[s.reason]||s.reason||'부하가 지속되면 추천을 표시합니다.')}</p></div><button id="augment-${E(s.uid)}" class="button ${ready?'primary':''}" data-augmentation-approve="${E(s.uid)}" ${!ready||approving.has(s.uid)?'disabled':''} aria-busy="${approving.has(s.uid)}">${approving.has(s.uid)?'<span class="runtime-spinner" aria-hidden="true"></span>승인 접수 중…':ok&&s.target?'<span class="runtime-spinner" aria-hidden="true"></span>모델 준비 중…':'추천 노드 증강 승인'}</button></div>${receipt}${approvalErrors.has(s.uid)?`<p class="runtime-warning" role="alert">${E(approvalErrors.get(s.uid))}</p>`:''}</aside></div><dl class="augmentation-metrics"><div><dt>요청 p95 / 목표</dt><dd>${num(l?.p95Milliseconds)} / ${num(l?.maxP95Milliseconds)} <small>ms</small></dd></div><div><dt>유입 / 완료 처리율</dt><dd>${num(l?.arrivalRps)} / ${num(l?.completedRps)} <small>건/s</small></dd></div><div><dt>대기 / 처리 중</dt><dd>${num(load?.pending)} / ${num(load?.inFlight)} <small>건</small></dd></div><div><dt>검증 수용 요청률</dt><dd>${num(load?.qualifiedRps)} <small>건/s</small></dd></div><div><dt>동시 처리 한도</dt><dd>${num(load?.capacity)} <small>건</small></dd></div><div><dt>실패 / 측정 표본</dt><dd>${num(l?.failures)} / ${num(l?.samples)} <small>건</small></dd></div></dl><footer class="augmentation-footnote"><span>${l?`${num(l.windowSeconds)}초 집계 · ${l.valid?'지연 판단 유효':'표본·오류 확인 필요'}`:'지표 관측 대기'} · ${E(time(s.checkedAt))} · 5초 갱신</span><span>AI 추론만 전환 · 센서 수집 유지 · ${s.augmentationStages?.length?'단계마다 승인 · 저부하 시 단계별 자동 복귀':'저부하 복귀는 기존 정책 적용'}</span></footer></article>`;
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
function renderState(entry,now=observationNow(entry),expanded=new Set()){
 const data=entry.data;
 const current=Boolean(data&&!entry.error&&!data.observation_error&&now-data.observed_at>=0&&now-data.observed_at<15);
 const intro='<div class="section-heading"><div><h2>클러스터 서비스 실행</h2><p class="note">서비스 계약과 전체 노드 조건으로 배치합니다. 새 실행체 준비 → 요청 경로 전환 → 이전 요청 완료 → 자원 반환.</p></div><button class="button" data-runtime-refresh>새로고침</button></div>';
 const notice=entry.error||data?.observation_error||(!current&&data?'관측이 오래되어 현재 상태를 확인할 수 없습니다.':null);
 if(!data)return `<section class="panel runtime-panel">${intro}<p class="runtime-loading" role="status">${!entry.error?'<span class="runtime-spinner" aria-hidden="true"></span>':''}${entry.error?'공통 제어기 관측 불가 · '+E(entry.error):'공통 제어기 조회 중…'}</p></section>`;
 return `${notice?`<p class="runtime-warning" role="status">관측 확인 필요 · ${E(observationErrors[notice]||notice)} · 마지막 수신 ${E(time(data.observed_at))}</p>`:''}${data.services.map(s=>augmentationView(s,now,current)).join('')}<details class="runtime-diagnostics" data-runtime-details="diagnostics" ${expanded.has('diagnostics')?'open':''}><summary>전체 서비스 · 전환 근거 상세</summary><section class="panel runtime-panel">${intro}<p class="note">Kubernetes RuntimeService · 마지막 수신 ${E(time(data.observed_at))} · 5초마다 조회</p>${notice?`<p class="runtime-warning" role="status">관측 확인 필요 · ${E(notice)}</p>`:''}${data.services.length?`<div class="table-wrap"><table class="data-table runtime-table"><thead><tr><th>서비스 / 상태</th><th>요청을 받는 실행체</th><th>이동 준비 / 반환 중</th><th>전환 근거</th></tr></thead><tbody>${data.services.map(s=>{
 const ok=current&&!s.observation_error;
 const release=s.lastRelease,transition=s.lastTransition;
 return `<tr><td><strong>${E(s.name)}</strong><span class="badge ${ok&&s.serving?'ok':''}">${ok?E(phases[s.phase]||s.phase):'현재 관측 확인 불가'}</span><small>${s.active?.memoryOnlyRelease?'모델 메모리 관리':'Pod 생성·축소 관리'}</small>${latencyView(s,now,ok)}${!s.aiInference?(root.NexusRuntimeDemo?.renderActions(s.uid,ok)||''):''}</td><td>${targetView(s.active,now,ok)}</td><td>${s.target?'<small>준비 중</small>'+targetView(s.target,now,ok):''}${s.retiring.map(t=>'<small>반환 중</small>'+targetView(t,now,ok)).join('')}${!s.target&&!s.retiring.length?'<small>진행 중인 전환 없음</small>':''}${release?`<small>마지막 모델 해제: ${E(release.node)} · ${E(release.modelVramMiB)} MiB<br>${E(time(release.at))} · ${release.reservationRetained?'GPU 예약 유지':'예약 유지 확인 안 됨'}</small>`:''}</td><td><span>${E(reasons[s.reason]||s.reason)}</span>${transition?`<small>${E(transition.fromNode||'최초 배치')} → ${E(transition.toNode)}<br>${E(reasons[transition.reason]||transition.reason)}<br>${E(time(transition.at))}</small>`:''}<details data-runtime-details="${E(s.uid)}" ${expanded.has(s.uid)?'open':''}><summary>후보 제외 근거 ${s.excludedCandidates.length}건</summary><ul>${s.excludedCandidates.map(c=>`<li>${E(c.node)} / ${E(c.variant)}<br>${E(c.reasons.join(', '))}</li>`).join('')}</ul></details></td></tr>`;
 }).join('')}</tbody></table></div>`:'<p class="empty">공통 제어기에 등록된 서비스가 없습니다.</p>'}<p class="note">마지막 메모리 해제는 과거 확인 기록입니다. GPU 예약 반환이나 현재 대기 모델 상태를 뜻하지 않습니다. 서비스 등록·정책 변경은 Kubernetes 계약으로 관리합니다.</p></section></details>`;
}
let entry={data:null,error:null},timer=null,clockTimer=null,pending=null,draw=()=>{},enabled=false;
const expanded=new Set();
async function refresh(){
 if(pending)return pending;root.NexusRuntimeDemo?.refresh();refreshNodes();
 pending=(async()=>{const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),4500);try{
  const r=await root.fetch('/state/runtime-services',{method:'GET',cache:'no-store',signal:controller.signal});
  if(!r.ok)throw new Error('HTTP '+r.status);
  const data=await r.json();
  if(data.schema_version!=='edgeai.common-runtime/v1'||!Array.isArray(data.services))throw new Error('응답 계약 확인 필요');
  entry={data,error:null,receivedMonotonic:root.performance.now()/1000};
 }catch(e){entry.error=e.name==='AbortError'?'조회 시간 초과':'공통 제어기 응답 확인 불가';}
 finally{clearTimeout(timeout);pending=null;if(enabled)draw();}})();
 return pending;
}
function tickClock(){if(root.document.hidden)return;const now=observationNow(entry);root.document.querySelectorAll('[data-runtime-elapsed]').forEach(el=>{el.textContent=Math.max(0,Math.floor(now-Number(el.dataset.runtimeElapsed)))+'초';});}
function activate(value){if(value===enabled)return;enabled=value;if(timer)clearInterval(timer);if(clockTimer)clearInterval(clockTimer);timer=null;clockTimer=null;if(value){refresh();clockTimer=setInterval(tickClock,1000);timer=setInterval(()=>{if(!root.document.hidden)refresh();},5000);}}
function setup(callback){draw=callback;root.NexusRuntimeDemo?.setup(callback);root.document.addEventListener('click',e=>{if(e.target.closest('[data-runtime-refresh]'))refresh();const n=e.target.closest('[data-runtime-node]');if(n){selectedNodes.set(n.dataset.runtimeUid,selectedNodes.get(n.dataset.runtimeUid)===n.dataset.runtimeNode?null:n.dataset.runtimeNode);draw();}const b=e.target.closest('[data-augmentation-approve]');if(b&&!b.disabled)approve(b.dataset.augmentationApprove);});root.document.addEventListener('toggle',e=>{const id=e.target.dataset?.runtimeDetails;if(id&&e.target.isConnected){if(e.target.open)expanded.add(id);else expanded.delete(id);}},true);}
const api={observationNow,nodeMetrics,nodeMetricsView,augmentationView,serviceMotion,mapNodes,runtimeMap,renderState,targetView,latencyView,activate,setup,render:()=>renderState(entry,observationNow(entry),expanded)+`<details class="runtime-diagnostics" data-runtime-details="history" ${expanded.has('history')?'open':''}><summary>시험 실행 이력 · 응답 상세</summary>${root.NexusRuntimeDemo?.renderPanel()||''}</details>`};
if(typeof module!=='undefined'&&module.exports)module.exports=api;root.NexusCommonRuntime=api;
})(typeof window!=='undefined'?window:globalThis);
