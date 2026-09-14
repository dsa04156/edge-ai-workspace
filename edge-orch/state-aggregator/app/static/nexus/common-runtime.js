(function(root){
'use strict';
const E=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time=value=>value==null?'관측 없음':new Date(value*1000).toLocaleString('ko-KR',{hour12:false});
const reasons={sustained_idle_return:'무부하 확인 후 이전 단계로 자동 복귀',augmentation_approval_required:'실제 부하가 지속되어 증강 승인을 기다립니다',sustained_latency_breach:'지속적인 응답 지연으로 이동',latency_no_qualified_target:'지연 초과 · 검증된 이동 후보 없음',healthy_current_placement:'현재 배치 유지',sustained_pressure:'지속 부하로 처리 용량 확대',sustained_low_load_return:'부하 감소로 선호 위치 복귀',initial_or_unhealthy_or_policy_changed:'최초 배치·상태·정책 재검토',waiting_for_pod_and_application_ready:'새 실행체와 모델 준비 대기',target_ready_route_switched:'준비 완료 후 요청 경로 전환',pressure_no_qualified_capacity:'부하 증가 · 검증된 추가 용량 없음'};
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
 let title=!ok?'최신 관측 확인 불가':s.target?'실행체 준비 중':(s.retiring||[]).length?'이전 요청 마무리 중':p?'추천 도착 · 승인 대기':busy?(s.aiInference?'AI 추론 실행 중':'서비스 요청 처리 중'):s.serving?'요청 대기 중':phases[s.phase]||'서비스 준비 확인';
 const back=ok&&s.returnState&&fresh(s.returnState.at,now)?s.returnState:null;
 if(back?.phase==='Waiting'&&!busy&&!p&&!s.target)title=back.label+' 자동 복귀 대기';
 if(back?.phase==='Preparing'&&s.target)title=back.label+' 복귀 준비 중';
 return {ok,load,l,p,busy,title};
}
function mapNodes(s,m,now){
 const nodes=new Map();
 for(const t of [...(s.augmentationStages||[]),...(m.ok&&s.aiInference?s.eligibleCandidates||[]:[]),s.active,s.target,...(s.retiring||[]),m.p])if(t?.node)nodes.set(t.node,{...(nodes.get(t.node)||{}),...t});
 return [...nodes.values()].sort((a,b)=>(a.step||99)-(b.step||99)||(a.role==='server')-(b.role==='server')||a.node.localeCompare(b.node)).map(t=>{
  const current=m.ok&&s.active?.node===t.node,preparing=m.ok&&s.target?.node===t.node,retiring=m.ok&&(s.retiring||[]).some(x=>x.node===t.node),recommended=m.p?.node===t.node;
  const source=current?s.active:preparing?s.target:retiring?(s.retiring||[]).find(x=>x.node===t.node):null;
  const health=m.ok&&source?.observation&&fresh(source.observation.at,now)?source.observation.health:null;
  const state=m.ok&&s.phase==='Suspended'?'stopped':!m.ok||(!current&&!preparing&&!retiring&&!recommended&&t.eligible===false)?'unknown':preparing?'preparing':retiring?'retiring':current?(s.serving?'active':'unknown'):recommended?'recommended':'candidate';
  const title={stopped:'서비스 중지 · 모델 해제',unknown:'현재 상태 확인 불가',preparing:'모델 준비 중',retiring:'남은 요청 마무리',active:m.busy?(s.aiInference?'추론 실행 중':'요청 처리 중'):'요청 대기 중',recommended:'증강 추천 · 승인 대기',candidate:'배치 후보 · 모델 미관측'}[state];
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
 return `<section class="runtime-map ${s.augmentationStages?.length?'staged':''}" aria-label="서비스 노드 실행 지도"><div class="runtime-map-heading"><h3>${s.augmentationStages?.length?'단계별 증강 경로':'요청 경로와 실행 노드'}</h3><span>노드를 눌러 상세 확인</span></div><div class="runtime-map-canvas"><div class="runtime-map-source"><span class="runtime-source-icon" aria-hidden="true">↗</span><strong>${s.aiInference?'AI 추론 요청':'HTTP 시험 요청'}</strong><small>${m.ok?`${num(m.load?.pending)}건 대기 · ${num(m.load?.inFlight)}건 처리 중`:'현재 요청 관측 불가'}</small></div><svg class="runtime-map-links" viewBox="0 0 80 ${height}" preserveAspectRatio="none" aria-hidden="true">${nodes.map((t,i)=>`<path class="${t.state} ${t.flow?'flowing':''}" d="M0 ${height/2} C40 ${height/2} 40 ${i*196+92} 80 ${i*196+92}"/>`).join('')}</svg><div class="runtime-map-nodes">${nodes.map(t=>`<div class="runtime-node-card"><button type="button" id="map-${E(s.uid)}-${E(t.node)}" class="runtime-map-node ${t.state}" data-runtime-node="${E(t.node)}" data-runtime-uid="${E(s.uid)}" aria-pressed="${chosen?.node===t.node}"><span class="runtime-node-icon">${icon}</span><span class="runtime-node-copy"><small>${t.step?E(t.step)+'단계 · ':''}${E(t.role==='edge'?'현장 엣지':t.role==='server'?'서버':'실행 노드')}</small><strong>${E(t.label||t.node)}</strong>${t.label?`<small class="runtime-tier-host">${E(t.node)}</small>`:''}<span class="runtime-node-state">${t.state==='preparing'||t.state==='retiring'||t.flow?'<span class="runtime-spinner" aria-hidden="true"></span>':'<span class="runtime-status-dot" aria-hidden="true"></span>'}${E(t.title)}</span><small>${t.health?.modelVramMiB!=null?'모델 '+num(t.health.modelVramMiB)+' MiB':t.state==='recommended'?'클릭 승인 후 모델 준비':t.state==='candidate'?'실행 준비 여부는 별도 확인':'모델 메모리 관측 없음'}</small>${t.step?`<small>검증 ${num(t.qualifiedRps)}건/s · p95 ${num(t.qualifiedP95Milliseconds)}ms</small>`:''}${nodeMetricsView(t.node,now)}</span></button>${t.step?`<details class="runtime-node-test" data-runtime-details="node-test-${E(s.uid)}-${E(t.node)}" ${expanded.has('node-test-'+s.uid+'-'+t.node)?'open':''}><summary>${E(t.label||t.node)} 개별 부하 시험</summary>${root.NexusRuntimeDemo?.renderNodeActions(s.uid,t.node,t.label||t.node,m.ok)||''}</details>`:''}</div>`).join(s.augmentationStages?.length?'<span class="runtime-tier-arrow" aria-hidden="true">→</span>':'')||'<p class="empty">실행 노드 관측 대기</p>'}</div></div><div class="runtime-map-legend"><span><i class="active"></i>현재 요청 경로</span><span><i class="recommended"></i>증강 추천</span><span><i class="preparing"></i>모델 준비</span><span>${s.augmentationStages?.length?'화살표: 증강 순서 · 강조 노드: 현재 요청 경로':'흐르는 선: 실제 처리·대기 요청'} · CPU·메모리·GPU: 노드 전체 실측 · 시스템 온도: ACPI 센서 최댓값</span></div>${chosen?`<div class="runtime-map-detail" role="region" aria-label="선택 노드 상세"><strong>${E(chosen.node)}</strong><span>${E(chosen.variant)} · ${E(chosen.title)}</span><span>동시 처리 한도 ${num(chosen.capacity)}건 · 모델 ${num(chosen.health?.modelVramMiB)} MiB</span><span>노드 GPU 메모리 ${num(hardware.gpuUsed)} / ${num(hardware.gpuTotal)} MiB</span></div>`:''}</section>`;
}
function returnView(s,now,current){
 if(!s.aiInference&&!s.returnState)return '';
 const r=current&&!s.observation_error&&s.returnState&&fresh(s.returnState.at,now)?s.returnState:null;
 const headings={Baseline:'기본 노드 유지',Observing:'자동 복귀 조건 확인 중',Waiting:'자동 복귀 대기',Preparing:'복귀 모델 준비 중',Releasing:'상위 모델 메모리 해제 중',Blocked:'자동 복귀 보류'};
 const remaining=r?.remainingSeconds==null?null:Math.max(0,Math.ceil(r.remainingSeconds-Math.max(0,now-r.at)));
 const detail=!r?'최신 복귀 관측을 확인하고 있습니다.':r.phase==='Baseline'?r.label+'에서 서비스를 유지합니다.':r.phase==='Observing'?`최근 ${num(r.windowSeconds)}초 유입량·대기·지연을 확인합니다. 하위 처리 여유와 저부하 또는 무부하가 ${num(r.dwellSeconds)}초 유지되어야 합니다.`:r.phase==='Waiting'?`${r.label} 복귀 조건 유지 ${num(Math.max(0,r.dwellSeconds-(remaining??r.dwellSeconds)))}/${num(r.dwellSeconds)}초 · ${r.reason==='low_load_dwell'?'저부하·지연 회복 확인':'무부하 확인'}`:r.phase==='Preparing'?`${r.label} 모델 준비가 끝나면 신규 요청 경로를 전환합니다.`:r.phase==='Releasing'?`${r.label}로 경로 전환됨 · 이전 요청 종료와 상위 모델 해제를 확인합니다.`:r.reason==='return_capacity_unverified_or_insufficient'?`${r.label}의 검증 처리량이 부족하거나 가용성을 확인할 수 없어 복귀를 보류합니다.`:`${r.label}의 가용성·검증 성능·반환 상태를 확인해야 합니다.`;
 return `<section class="runtime-run-status runtime-return-status" aria-label="자동 축소와 복귀"><div class="runtime-run-title" role="status"><strong>${E(r?headings[r.phase]:'자동 복귀 관측 확인 불가')}</strong></div><p>${E(detail)}</p>${r?.maxArrivalRps!=null?`<small>유입 ${num(r.arrivalRps)} / 복귀 허용 ${num(r.maxArrivalRps)}건/s</small>`:''}<small>${s.approvalRequired?'증강은 직접 승인':'증강은 자동 처리'} · ${E((s.augmentationStages||[]).slice().reverse().map(t=>t.label).join(' → ')||'선호 위치')} 자동 복귀</small></section>`;
}
function policyView(s,now,current){
 const p=current&&s.policyObservation&&fresh(s.policyObservation.at,now)?s.policyObservation:null;
 if(!p||s.observation_error)return '';
 const left=Math.max(0,Math.ceil(p.cooldownRemainingSeconds-Math.max(0,now-p.at)));
 return `<div class="runtime-policy-evidence"><small>대기 지속 ${num(Math.min(p.pressureElapsedSeconds,p.pressureSeconds))}/${num(p.pressureSeconds)}초${p.maxP95Milliseconds!=null?` · p95 ${num(p.maxP95Milliseconds)}ms 초과 ${num(Math.min(p.latencyElapsedSeconds,p.latencyBreachSeconds))}/${num(p.latencyBreachSeconds)}초`:''}</small><small>복귀 조건 ${num(p.returnSeconds)}초 유지 · 하위 검증 요청률의 ${num(p.returnHeadroomRatio*100)}% 이하</small><small>${left?`전환 후 재판단까지 ${num(left)}초`:`전환 후 대기 ${num(p.cooldownSeconds)}초 · 현재 재판단 가능`}</small></div>`;
}
function augmentationView(s,now,current,includeTest=false){
 if(!s.aiInference&&!includeTest)return '';
 const m=serviceMotion(s,now,current),{ok,load,l,p}=m;
 const ready=Boolean(s.approvalRequired&&s.serving&&p&&!s.target),result=s.lastApproval;
 const ctx=root.NexusRuntimeDemo?.context(s.uid,now);if(ctx){ctx.detailsOpen=expanded.has("run-"+s.uid);ctx.inlineControls=true;}
 const receipt=result?`<p class="augmentation-receipt" role="status">최근 증강 승인 기록 · ${E(approvalLabels[result.status]||result.status)}<small>${E(result.sourceNode)} → ${E(result.node)}</small></p>`:'';
 return `<article class="panel augmentation-panel ${s.augmentationStages?.length?'staged':''}" data-augmentation-service="${E(s.uid)}"><header class="augmentation-header"><div><p class="eyebrow">${s.aiInference?'실제 Llama 추론':'HTTP 시험 서비스 · 합성 응답'} 실행 지도</p><h2>${E(s.name)}</h2></div><div class="runtime-service-state ${ok?'':'unknown'}" role="status">${ok&&(s.target||m.busy||(s.retiring||[]).length)?'<span class="runtime-spinner" aria-hidden="true"></span>':'<span class="runtime-status-dot" aria-hidden="true"></span>'}<strong>${E(m.title)}</strong></div><button class="button runtime-refresh" data-runtime-refresh aria-label="AI 실행 상태 새로고침">↻</button></header>${!ok?`<p class="runtime-warning" role="status">${E(observationErrors[s.observation_error]||'최신 관측 응답을 확인할 수 없습니다')} · 마지막 확인 상태: ${E(phases[s.phase]||s.phase)}${s.active?.node?' / '+E(s.active.node):''} · 마지막 서비스 관측 ${E(time(s.checkedAt))} · 5초마다 재시도</p>`:''}<div class="augmentation-workspace">${runtimeMap(s,m,now)}<aside class="augmentation-controls" aria-label="부하 시험과 증강 승인"><div class="runtime-operation"><h3>서비스 실행·중지</h3>${root.NexusRuntimeDemo?.renderActions(s.uid,ok,true)||(ctx?.loading?'<p class="runtime-loading"><span class="runtime-spinner" aria-hidden="true"></span>시험 설정 조회 중…</p>':`<p>${ctx?.current?'등록된 부하 시험이 없습니다.':'시험 설정 관측을 확인할 수 없습니다.'}</p>`)}</div><div class="runtime-operation">${s.aiInference?'':root.NexusRuntimeDemo?.renderServiceLoadActions(s.uid,ok)||''}${ctx?root.NexusRuntimeDemo.runStatus(ctx,now):''}</div><div class="runtime-operation">${s.approvalRequired?`<div class="augmentation-approval"><div><strong>${p?'증강 추천 도착':s.target?'실행체 준비 중':'증강 승인'}</strong><p>${!ok?'최신 관측을 확인한 후 승인할 수 있습니다.':!s.approvalRequired?'승인 기반 증강이 설정되지 않았습니다.':p?`${E(s.augmentationStages?.find(t=>t.variant===p.variant)?.label||p.node)} · ${num(p.qualifiedRps)}건/s · p95 ${num(p.qualifiedP95Milliseconds)}ms`:s.target?'준비 완료 후 신규 요청 경로를 전환합니다.':E(reasons[s.reason]||s.reason||'부하가 지속되면 추천을 표시합니다.')}</p></div><button id="augment-${E(s.uid)}" class="button ${ready?'primary':''}" data-augmentation-approve="${E(s.uid)}" ${!ready||approving.has(s.uid)?'disabled':''} aria-busy="${approving.has(s.uid)}">${approving.has(s.uid)?'<span class="runtime-spinner" aria-hidden="true"></span>승인 접수 중…':ok&&s.target?'<span class="runtime-spinner" aria-hidden="true"></span>모델 준비 중…':'추천 노드 증강 승인'}</button></div>`:`<div class="augmentation-approval"><strong>시험 서비스 자동 배치</strong><p>등록된 정책에 따라 부하 증가 시 용량을 늘리고, 부하 감소 시 선호 노드로 복귀합니다. 합성 HTTP 응답이며 실제 AI 품질 판별은 아닙니다.</p></div>`}${returnView(s,now,ok)}${receipt}${approvalErrors.has(s.uid)?`<p class="runtime-warning" role="alert">${E(approvalErrors.get(s.uid))}</p>`:''}</div></aside></div><dl class="augmentation-metrics"><div><dt>요청 p95 / 목표</dt><dd>${num(l?.p95Milliseconds)} / ${num(l?.maxP95Milliseconds)} <small>ms</small></dd></div><div><dt>유입 / 완료 처리율</dt><dd>${num(l?.arrivalRps)} / ${num(l?.completedRps)} <small>건/s</small></dd></div><div><dt>대기 / 처리 중</dt><dd>${num(load?.pending)} / ${num(load?.inFlight)} <small>건</small></dd></div><div><dt>검증 수용 요청률</dt><dd>${num(load?.qualifiedRps)} <small>건/s</small></dd></div><div><dt>동시 처리 한도</dt><dd>${num(load?.capacity)} <small>건</small></dd></div><div><dt>실패 / 측정 표본</dt><dd>${num(l?.failures)} / ${num(l?.samples)} <small>건</small></dd></div></dl><footer class="augmentation-footnote"><span>${l?`${num(l.windowSeconds)}초 집계 · ${l.valid?'지연 판단 유효':'표본·오류 확인 필요'}`:'지표 관측 대기'} · ${E(time(s.checkedAt))} · 5초 갱신</span><span>${s.aiInference?'AI 추론만 전환':'선택한 HTTP 시험 서비스 전환'} · 센서 수집 유지 · ${s.augmentationStages?.length?'단계마다 승인 · 저부하 시 단계별 자동 복귀':'저부하 복귀는 기존 정책 적용'}</span></footer></article>`;
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
function renderState(entry,now=observationNow(entry),expanded=new Set(),selectedView=false,detailsOnly=false){
 const data=entry.data;
 const current=Boolean(data&&!entry.error&&!data.observation_error&&now-data.observed_at>=0&&now-data.observed_at<15);
 const intro='<div class="section-heading"><div><h2>클러스터 서비스 실행</h2><p class="note">서비스 계약과 전체 노드 조건으로 배치합니다. 새 실행체 준비 → 요청 경로 전환 → 이전 요청 완료 → 자원 반환.</p></div><button class="button" data-runtime-refresh>새로고침</button></div>';
 const notice=entry.error||data?.observation_error||(!current&&data?'관측이 오래되어 현재 상태를 확인할 수 없습니다.':null);
 if(!data)return `<section class="panel runtime-panel">${intro}<p class="runtime-loading" role="status">${!entry.error?'<span class="runtime-spinner" aria-hidden="true"></span>':''}${entry.error?'공통 제어기 관측 불가 · '+E(entry.error):'공통 제어기 조회 중…'}</p></section>`;
 return `${notice?`<p class="runtime-warning" role="status">관측 확인 필요 · ${E(observationErrors[notice]||notice)} · 마지막 수신 ${E(time(data.observed_at))}</p>`:''}${detailsOnly?'':data.services.map(s=>augmentationView(s,now,current,selectedView)).join('')}<details class="runtime-diagnostics" data-runtime-details="diagnostics" ${expanded.has('diagnostics')?'open':''}><summary>서비스 · 전환 근거 상세</summary><section class="panel runtime-panel">${intro}<p class="note">Kubernetes RuntimeService · 마지막 수신 ${E(time(data.observed_at))} · 5초마다 조회</p>${notice?`<p class="runtime-warning" role="status">관측 확인 필요 · ${E(notice)}</p>`:''}${data.services.length?`<div class="table-wrap"><table class="data-table runtime-table"><thead><tr><th>서비스 / 상태</th><th>요청을 받는 실행체</th><th>이동 준비 / 반환 중</th><th>전환 근거</th></tr></thead><tbody>${data.services.map(s=>{
 const ok=current&&!s.observation_error;
 const release=s.lastRelease,transition=s.lastTransition;
 return `<tr><td><strong>${E(s.name)}</strong><span class="badge ${ok&&s.serving?'ok':''}">${ok?E(phases[s.phase]||s.phase):'현재 관측 확인 불가'}</span><small>${s.active?.memoryOnlyRelease?'모델 메모리 관리':'Pod 생성·축소 관리'}</small>${latencyView(s,now,ok)}${!s.aiInference&&!selectedView?(root.NexusRuntimeDemo?.renderActions(s.uid,ok)||''):''}</td><td>${targetView(s.active,now,ok)}</td><td>${s.target?'<small>준비 중</small>'+targetView(s.target,now,ok):''}${s.retiring.map(t=>'<small>반환 중</small>'+targetView(t,now,ok)).join('')}${!s.target&&!s.retiring.length?'<small>진행 중인 전환 없음</small>':''}${release?`<small>마지막 모델 해제: ${E(release.node)} · ${E(release.modelVramMiB)} MiB<br>${E(time(release.at))} · ${release.reservationRetained?'GPU 예약 유지':'예약 유지 확인 안 됨'}</small>`:''}</td><td><span>${E(reasons[s.reason]||s.reason)}</span>${transition?`<small>${E(transition.fromNode||'최초 배치')} → ${E(transition.toNode)}<br>${E(reasons[transition.reason]||transition.reason)}<br>${E(time(transition.at))}</small>`:''}<details data-runtime-details="${E(s.uid)}" ${expanded.has(s.uid)?'open':''}><summary>후보 제외 근거 ${s.excludedCandidates.length}건</summary><ul>${s.excludedCandidates.map(c=>`<li>${E(c.node)} / ${E(c.variant)}<br>${E(c.reasons.join(', '))}</li>`).join('')}</ul></details></td></tr>`;
 }).join('')}</tbody></table></div>`:'<p class="empty">공통 제어기에 등록된 서비스가 없습니다.</p>'}<p class="note">마지막 메모리 해제는 과거 확인 기록입니다. GPU 예약 반환이나 현재 대기 모델 상태를 뜻하지 않습니다. 서비스 등록·정책 변경은 Kubernetes 계약으로 관리합니다.</p></section></details>`;
}
function selectedService(services,uid){
 return uid?services.find(s=>s.uid===uid)||null:services.find(s=>s.aiInference)||services[0]||null;
}
function legacyServicePicker(value,uid,now){
 const services=value.data?.services||[],current=Boolean(value.data&&!value.error&&!value.data.observation_error&&fresh(value.data.observed_at,now));
 return `<section class="runtime-service-picker" aria-label="운영할 서비스 선택"><div class="runtime-picker-heading"><h2>서비스 선택</h2><span>선택을 바꿔도 실행 중인 서비스와 부하는 유지됩니다.</span></div><div class="runtime-service-list">${services.map(s=>{
  const m=serviceMotion(s,now,current),ctx=root.NexusRuntimeDemo?.context(s.uid,now),busy=ctx?.run&&['Running','Stopping'].includes(ctx.run.phase);
  return `<button type="button" id="runtime-select-${E(s.uid)}" data-runtime-service="${E(s.uid)}" class="runtime-service-choice" aria-pressed="${s.uid===uid}"><span>${s.aiInference?'실제 AI 추론':'HTTP 시험 · 합성 응답'}</span><strong>${E(s.name)}</strong><small>${E(m.title)}${busy?ctx.current?' · 부하 '+(ctx.run.phase==='Stopping'?'제거 중':'실행 중'):' · 부하 상태 확인 필요':''}</small><small>${m.ok?'현재 경로':'마지막 경로'} · ${E(s.active?.node||'실행 노드 없음')}</small></button>`;
 }).join('')}</div></section>`;
}
let selection=null;
function catalogServices(value,catalog=root.NexusLive?.store?.entries?.services){
 const services=[...(value.data?.services||[])];
 for(const s of catalog?.data?.services||[]){
  if(s.category!=='ai_inference'||services.some(r=>r.name===s.service_id))continue;
  services.push({uid:'catalog:'+s.service_id,name:s.service_id,displayName:s.display_name,aiInference:true,managed:false,
   catalog:s,catalogCurrent:Boolean(root.NexusData?.isCurrent(catalog))});
 }
 return services;
}
function catalogStatus(s){
 if(!s.catalogCurrent||s.catalog.observation_error)return '현재 관측 확인 불가';
 const own=s.catalog.execution_ownership;
 if(own?.effective_mode!=='ACTIVE'||own.enabled&&!own.lease_valid)return '추론 대기 · 실행 권한 없음';
 return s.catalog.status==='healthy'?'실행 중':s.catalog.status==='degraded'?'실행 주의':'상태 확인 필요';
}
function policyLabel(s){return s.managed===false?'제어 미연결':s.approvalRequired?'증강 승인 · 자동 복귀':s.placementMode==='preferred'?'선호 배치':'자동 이동 · 복귀';}
function servicePicker(value,uid,now,services=catalogServices(value)){
 const current=Boolean(value.data&&!value.error&&!value.data.observation_error&&fresh(value.data.observed_at,now));
 const rows=items=>`<div class="table-wrap"><table class="data-table runtime-service-catalog"><thead><tr><th>서비스</th><th>현재 상태</th><th>실행 위치</th><th>운영 방식</th><th>시험 부하</th></tr></thead><tbody>${items.map(s=>{
  const m=s.managed===false?{ok:s.catalogCurrent,title:catalogStatus(s)}:serviceMotion(s,now,current),ctx=root.NexusRuntimeDemo?.context(s.uid,now);
  const busy=ctx?.run&&['Running','Stopping'].includes(ctx.run.phase);
  return `<tr class="${s.uid===uid?'selected':''}"><td><button type="button" id="runtime-select-${E(s.uid)}" data-runtime-service="${E(s.uid)}" aria-pressed="${s.uid===uid}">${E(s.displayName||s.name)}</button>${s.displayName?`<small>${E(s.name)}</small>`:''}</td><td><span class="runtime-list-state ${m.ok?'':'unknown'}">${m.ok&&m.busy?'<span class="runtime-spinner" aria-hidden="true"></span>':''}${E(m.title)}</span></td><td>${!m.ok?'<small>마지막 관측</small>':''}${E(s.active?.node||s.catalog?.node||'배치 없음')}</td><td>${E(policyLabel(s))}</td><td>${s.managed===false?'연결 필요':!ctx?.current?'관측 확인 중':busy?ctx.run.phase==='Stopping'?'제거 중':'부하 실행 중':ctx.item?.testConfigured===false?'시험 입력 없음':'부하 없음'}</td></tr>`;
 }).join('')}</tbody></table></div>`;
 const ai=services.filter(s=>s.aiInference),other=services.filter(s=>!s.aiInference);
 return `<section class="runtime-service-picker" aria-label="운영할 서비스 선택"><div class="runtime-picker-heading"><h2>AI 서비스 <small>${ai.length}</small></h2><span>서비스를 선택해 실행 위치와 자동 전환을 확인하세요.</span><button class="button" data-runtime-refresh>새로고침</button></div>${ai.length?rows(ai):'<p class="empty">등록된 AI 서비스가 없습니다.</p>'}${other.length?`<details class="runtime-other-services" data-runtime-details="other-services" ${expanded.has('other-services')||other.some(s=>s.uid===uid)?'open':''}><summary>HTTP 시험·일반 서비스 ${other.length}</summary>${rows(other)}</details>`:''}</section>`;
}
function compactRoute(s,m,now){
 const nodes=mapNodes(s,m,now),chosen=nodes.find(n=>n.node===selectedNodes.get(s.uid));
 return `<section class="runtime-route" aria-label="서비스 실행 경로"><div class="runtime-route-heading"><h3>실행 경로</h3><span>${s.augmentationStages?.length?'부하 증가 → · ← 부하 감소':'등록된 배치 후보'} · 노드 선택 시 상세</span></div><div class="runtime-route-nodes">${nodes.map(t=>{
  const h=nodeMetrics(t.node,now),pct=v=>v==null?(h.current?'미수집':'—'):(v*100).toFixed(0)+'%',temp=v=>v==null?(h.current?'미수집':'—'):v.toFixed(1)+'°C';
  return `<div class="runtime-route-card"><button type="button" class="runtime-route-node ${t.state}" id="map-${E(s.uid)}-${E(t.node)}" data-runtime-node="${E(t.node)}" data-runtime-uid="${E(s.uid)}" aria-pressed="${chosen?.node===t.node}"><strong>${E(t.label||t.node)}</strong>${t.label?`<small>${E(t.node)}</small>`:''}<span class="runtime-node-state">${['preparing','retiring'].includes(t.state)||t.flow?'<span class="runtime-spinner" aria-hidden="true"></span>':''}${E(t.title)}</span><span class="runtime-route-hardware"><span>CPU <b>${pct(h.cpu)}</b></span><span>메모리 <b>${pct(h.memory)}</b></span><span>GPU <b>${pct(h.gpu)}</b></span><span>GPU 온도 <b>${temp(h.gpuTemperature)}</b></span></span></button>${s.aiInference?root.NexusRuntimeDemo?.renderNodeActions(s.uid,t.node,t.label||t.node,m.ok)||'<p class="note">노드 부하 설정 확인 중…</p>':''}</div>`;
 }).join('')||'<p>실행 후보 관측 대기</p>'}</div>${chosen?`<div class="runtime-route-detail"><strong>${E(chosen.label||chosen.node)} · 노드 전체 실측</strong>${nodeMetricsView(chosen.node,now)}</div>`:''}</section>`;
}
function operationsView(s,now,current){
 if(s.managed===false){
  const c=s.catalog,q=c.descriptor?.augmentation_qualification;
  return `<section class="panel runtime-operations"><header><div><h2>${E(s.displayName||s.name)}</h2><p>${E(catalogStatus(s))} · 배치 ${E(c.node||'미관측')}</p></div><span class="badge">공통 제어 미연결</span></header><p>이 서비스는 기존 실행 경로로 배포되어 있습니다. 공통 운영 계약에 실행 이미지·입출력·이동 후보·시험 입력을 연결해야 여기서 제어할 수 있습니다.</p><p class="runtime-warning">${q?.status==='rejected'?'이동 후보 검증 미통과 · '+E(q.reason):'검증된 이동 후보 연결 필요'}${c.execution_ownership?.effective_mode!=='ACTIVE'?' · 현재 추론 실행 권한 비활성':''}</p><div class="runtime-service-buttons"><button class="button" disabled>서비스 실행 · 연결 필요</button><button class="button" disabled>부하 시험 · 연결 필요</button></div><a class="button" href="?service=${encodeURIComponent(c.service_id)}#service-detail">기존 서비스 상세</a></section>`;
 }
 const m=serviceMotion(s,now,current),ctx=root.NexusRuntimeDemo?.context(s.uid,now);
 if(ctx){ctx.detailsOpen=expanded.has('run-'+s.uid);ctx.inlineControls=true;}
 const l=m.ok&&s.requestMetrics&&fresh(s.requestMetrics.at,now)?s.requestMetrics:m.l;
 const metrics=[['유입 / 완료',`${num(l?.arrivalRps)} / ${num(l?.completedRps)}`,'건/s'],['응답 p95',num(l?.p95Milliseconds),'ms'],['대기 / 처리 중',`${num(m.load?.pending)} / ${num(m.load?.inFlight)}`,'건'],['검증 요청률',num(m.load?.qualifiedRps),'건/s'],['동시 처리 한도',num(m.load?.capacity),'건'],['실패 / 표본',`${num(l?.failures)} / ${num(l?.samples)}`,'건']];
 return `<article class="panel runtime-operations" data-augmentation-service="${E(s.uid)}"><header><div><h2>${E(s.name)}</h2><span>${E(policyLabel(s))}</span></div><div class="runtime-service-state ${m.ok?'':'unknown'}" role="status">${m.ok&&(m.busy||s.target||s.retiring?.length)?'<span class="runtime-spinner" aria-hidden="true"></span>':''}<strong>${E(m.title)}</strong></div></header>${!m.ok?`<p class="runtime-warning">${E(observationErrors[s.observation_error]||'최신 관측 확인 불가')} · 마지막 확인 상태: ${E(phases[s.phase]||s.phase)} · 마지막 관측 ${E(time(s.checkedAt))}</p>`:''}<dl class="augmentation-metrics">${metrics.map(([label,value,unit])=>`<div><dt>${label}</dt><dd>${value} <small>${unit}</small></dd></div>`).join('')}</dl>${compactRoute(s,m,now)}<div class="runtime-operations-controls"><div>${root.NexusRuntimeDemo?.renderActions(s.uid,m.ok,true)||'<p>실행 제어 관측 확인 중…</p>'}</div><div>${s.aiInference?'<h3>부하 진행 상태</h3><p class="note">버튼으로 시작한 부하는 서비스 이동 후에도 유지됩니다. 제거는 처음 시작한 노드의 버튼에서 합니다.</p>':root.NexusRuntimeDemo?.renderServiceLoadActions(s.uid,m.ok)||'<p>부하 설정 확인 중…</p>'}${ctx?root.NexusRuntimeDemo.runStatus(ctx,now):''}</div><div class="runtime-policy-status"><h3>${E(policyLabel(s))}</h3><p role="status">${m.ok?E(reasons[s.reason]||s.reason||'운영 조건 확인 중'):'최신 조건 관측 대기'}</p>${s.approvalRequired?`<button id="augment-${E(s.uid)}" class="button primary" data-augmentation-approve="${E(s.uid)}" ${!m.p||!s.serving||s.target||approving.has(s.uid)?'disabled':''}>${approving.has(s.uid)?'승인 접수 중…':'추천 노드 증강 승인'}</button>`:'<small>지속 부하·응답 지연·실행체 장애를 감지하면 검증된 후보로 전환합니다.</small>'}${policyView(s,now,m.ok)}${returnView(s,now,m.ok)}${approvalErrors.has(s.uid)?`<p role="alert">${E(approvalErrors.get(s.uid))}</p>`:''}</div></div><footer>${num(l?.windowSeconds)}초 집계 · ${E(time(s.checkedAt))} · 5초 갱신 · 검증 요청률은 측정된 운용점입니다.</footer></article>`;
}
function renderWorkspace(value,uid,now=observationNow(value)){
 if(!value.data)return renderState(value,now,expanded);
 const services=catalogServices(value),service=selectedService(services,uid);
 const picker=servicePicker(value,service?.uid||uid,now,services);
 if(!service)return picker+`<section class="panel"><h2>${uid?'선택한 서비스를 찾을 수 없습니다':'등록된 서비스가 없습니다'}</h2><p class="note">${uid?'서비스가 삭제되었거나 관측 목록에 없습니다. 운영할 서비스를 직접 선택하세요.':'서비스 등록은 Kubernetes 계약으로 관리합니다.'}</p></section>`;
 const scoped={...value,data:{...value.data,services:[service]}};
 const current=Boolean(!value.error&&!value.data.observation_error&&fresh(value.data.observed_at,now));
 return picker+operationsView(service,now,current)+(service.managed===false?'':(root.NexusRequestHistory?.render(service.uid,service.name)||'')+renderState(scoped,now,expanded,true,true)+`<details class="runtime-diagnostics" data-runtime-details="history" ${expanded.has('history')?'open':''}><summary>${E(service.name)} · 부하 실행 이력과 응답</summary>${root.NexusRuntimeDemo?.renderPanel(service.uid)||''}</details>`);
}
function render(){
 if(selection===null&&root.location)selection=new URLSearchParams(root.location.search||'').get('runtimeService')||null;
 if(!selection&&entry.data?.services?.length)selection=selectedService(entry.data.services,null).uid;
 return renderWorkspace(entry,selection);
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
  if(data.observation_error&&!data.services.length&&entry.data){entry={...entry,error:observationErrors[data.observation_error]||data.observation_error};}
  else entry={data,error:null,receivedMonotonic:root.performance.now()/1000};
 }catch(e){entry.error=e.name==='AbortError'?'조회 시간 초과':'공통 제어기 응답 확인 불가';}
 finally{clearTimeout(timeout);pending=null;if(enabled)draw();}})();
 return pending;
}
function tickClock(){if(root.document.hidden)return;const now=observationNow(entry);root.document.querySelectorAll('[data-runtime-elapsed]').forEach(el=>{el.textContent=Math.max(0,Math.floor(now-Number(el.dataset.runtimeElapsed)))+'초';});}
function activate(value){if(value===enabled)return;enabled=value;if(timer)clearInterval(timer);if(clockTimer)clearInterval(clockTimer);timer=null;clockTimer=null;if(value){refresh();clockTimer=setInterval(tickClock,1000);timer=setInterval(()=>{if(!root.document.hidden)refresh();},5000);}}
function setup(callback){draw=callback;root.NexusRuntimeDemo?.setup(callback);root.NexusRequestHistory?.setup(callback);root.addEventListener?.('popstate',()=>{selection=new URLSearchParams(root.location.search).get('runtimeService');draw();});root.document.addEventListener('click',e=>{const choice=e.target.closest('[data-runtime-service]');if(choice){selection=choice.dataset.runtimeService;const url=new URL(root.location.href);url.searchParams.set('runtimeService',selection);root.history.replaceState(root.history.state,'',url);draw();}if(e.target.closest('[data-runtime-refresh]'))refresh();const n=e.target.closest('[data-runtime-node]');if(n){selectedNodes.set(n.dataset.runtimeUid,selectedNodes.get(n.dataset.runtimeUid)===n.dataset.runtimeNode?null:n.dataset.runtimeNode);draw();}const b=e.target.closest('[data-augmentation-approve]');if(b&&!b.disabled)approve(b.dataset.augmentationApprove);});root.document.addEventListener('toggle',e=>{const id=e.target.dataset?.runtimeDetails;if(id&&e.target.isConnected){if(e.target.open)expanded.add(id);else expanded.delete(id);}},true);}
const api={policyView,catalogServices,catalogStatus,operationsView,compactRoute,returnView,observationNow,nodeMetrics,nodeMetricsView,augmentationView,serviceMotion,mapNodes,runtimeMap,renderState,selectedService,servicePicker,renderWorkspace,targetView,latencyView,activate,setup,render};
if(typeof module!=='undefined'&&module.exports)module.exports=api;root.NexusCommonRuntime=api;
})(typeof window!=='undefined'?window:globalThis);
