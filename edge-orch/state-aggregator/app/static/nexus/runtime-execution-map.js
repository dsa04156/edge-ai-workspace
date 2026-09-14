(function(root){
'use strict';
const E=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const N=v=>typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('ko-KR',{maximumFractionDigits:1}):'—';
const fresh=(at,now)=>Number.isFinite(at)&&now-at>=0&&now-at<15;
const reasons={sustained_pressure:'대기 요청과 처리 용량 부족 지속',sustained_latency_breach:'응답 지연 기준 초과 지속',initial_or_unhealthy_or_policy_changed:'최초 배치 · 실행 상태 또는 정책 재검토',sustained_idle_return:'무부하 확인 · 이전 단계 복귀',sustained_low_load_return:'부하 감소 확인 · 이전 단계 복귀',latency_no_qualified_target:'지연 기준을 만족하는 후보 없음',pressure_no_qualified_capacity:'추가 처리 용량을 제공하는 후보 없음'};
const bases={stage_order:'등록된 단계 순서',preferred_role_then_capacity:'선호 역할 → 작은 처리 용량 → 노드 이름',qualified_latency:'검증 p95가 짧은 순 → 노드 이름',smallest_sufficient_capacity:'현재보다 큰 검증 용량 중 작은 순 → 노드 이름'};
function view(s,m,now){
 const stopped=s.phase==='Suspended',d=m.ok&&!stopped?s.placementDecision:null;
 const linked=Boolean(d&&s.target?.name===d.selectedRevision&&d.status==='Preparing');
 const evaluated=Boolean(d?.status==='Evaluated'&&fresh(d.at,now));
 const applied=Boolean(d?.status==='Applied'&&s.active?.name===d.selectedRevision&&now-d.appliedAt>=0&&now-d.appliedAt<60);
 const ranking=d&&(linked||evaluated||applied)?d:null;
 const p=m.ok&&fresh(s.policyObservation?.at,now)?s.policyObservation:null;
 const detecting=Boolean(p&&(p.pressureElapsedSeconds>0||p.latencyElapsedSeconds>0));
 let step=0,title=m.title;
 if(!m.ok||stopped)step=-1;
 else if(s.target){step=3;title=s.returnState?.phase==='Preparing'?'복귀 노드 준비 중':'선택 노드 준비 중';}
 else if(s.retiring?.length){step=5;title=s.serving?'새 노드에서 처리 · 이전 요청 마무리':'요청 마무리 · 서비스 중지 중';}
 else if(m.p){step=2;title='후보 선정 완료 · 승인 대기';}
 else if(evaluated){step=2;title=d.candidates.length?'후보 평가 완료 · 실행 조건 확인':'이동 보류 · 조건을 만족하는 후보 없음';}
 else if(detecting){step=1;title='문제 조건 감지 · 지속 시간 확인';}
 else if(applied){step=4;title='요청 경로 전환 완료';}
 const hint=!m.ok?'최신 관측을 받을 때 실행 경로를 다시 표시합니다.':stopped?'서비스를 실행하면 실제 요청을 받는 노드가 표시됩니다.':detecting?`용량 부족 ${N(p.pressureElapsedSeconds)} / ${N(p.pressureSeconds)}초 · 지연 초과 ${N(p.latencyElapsedSeconds)} / ${N(p.latencyBreachSeconds)}초${p.cooldownRemainingSeconds>0?' · 재이동 대기 '+N(p.cooldownRemainingSeconds)+'초':''}`:ranking?reasons[ranking.reason]||ranking.reason:s.returnState?.phase==='Waiting'?'부하 감소 조건 유지 시간을 확인한 뒤 복귀 후보를 평가합니다.':'문제가 지속되면 제어기가 실행 조건을 확인하고 이동 후보를 평가합니다.';
 return {step,title,hint,ranking,decision:d,detecting};
}
function render(s,m,now,o={}){
 const v=view(s,m,now),nodes=new Map((o.nodes||[]).map(n=>[n.node,n]));
 for(const n of [...(s.contractSummary?.candidateNodes||[]),...(v.ranking?.candidates||[]).map(c=>c.node)])if(!nodes.has(n))nodes.set(n,{node:n,state:m.ok?'candidate':'unknown',title:'실행 조건 확인 필요'});
 const names=n=>nodes.get(n)?.label||n||'최초 배치';
 const d=v.ranking,selected=d?.selectedRevision?d.candidates[0]:null;
 const source=s.active?.node,target=s.target?.node||m.p?.node;
 const steps=['실행 관측','문제·복귀 확인','후보 평가','실행체 준비','요청 경로 전환','이전 요청 마무리'];
 const cards=[...nodes.values()].map(t=>{
  const ranks=d?.candidates.filter(c=>c.node===t.node)||[],h=o.hardware?.(t.node)||{};
  const active=m.ok&&s.serving&&source===t.node,preparing=m.ok&&s.target?.node===t.node;
  const pct=x=>x==null?(h.current?'미수집':'—'):N(x*100)+'%';
  return `<div class="execution-node ${E(t.state)} ${active?'routing':''}" data-execution-node="${E(t.node)}"><div class="execution-node-connection ${active?'current':''} ${active&&m.busy?'flowing':''}"><span>${active?'현재 요청 경로':preparing?'선택된 이동 경로':ranks.length?(d.status==='Applied'?'전환 당시 후보':'평가된 이동 후보'):'등록된 노드'}</span></div><button type="button" class="execution-node-select" id="map-${E(s.uid)}-${E(t.node)}" data-runtime-node="${E(t.node)}" data-runtime-uid="${E(s.uid)}" aria-pressed="${o.selectedNode===t.node}"><span class="execution-node-heading"><strong>${E(t.label||t.node)}</strong>${preparing?'<span class="runtime-spinner" aria-hidden="true"></span>':active?'<span class="badge ok">실행 위치</span>':''}</span>${t.label?`<small>${E(t.node)}</small>`:''}<span class="execution-node-service ${active?'occupied':''}">${active?`${m.busy?'● 처리 중':'● 요청 대기'} · ${E(s.name)}`:preparing?`${E(s.name)} · 준비 중`:E(t.title||'실행 관측 없음')}</span>${ranks.map(r=>`<span class="execution-rank"><b>${d.status==='Applied'?'전환 당시 ':''}${E(r.rank)}위</b> ${E(r.variant)}${selected?.node===r.node&&selected?.variant===r.variant?' · 선택':''}<small>검증 ${N(r.qualifiedRps)}건/s · p95 ${N(r.qualifiedP95Milliseconds)}ms · 동시 ${N(r.capacity)}건</small></span>`).join('')}<span class="runtime-route-hardware"><span>CPU <b>${pct(h.cpu)}</b></span><span>메모리 <b>${pct(h.memory)}</b></span><span>GPU <b>${pct(h.gpu)}</b></span><span>GPU 온도 <b>${h.gpuTemperature==null?(h.current?'미수집':'—'):N(h.gpuTemperature)+'°C'}</b></span></span></button>${s.aiInference?root.NexusRuntimeDemo?.renderNodeActions(s.uid,t.node,t.label||t.node,m.ok)||'<p class="note">노드 부하 설정 확인 중…</p>':''}</div>`;
 });
 const list=[...nodes.values()],rows=[];
 for(let i=0;i<cards.length;i+=3){const group=list.slice(i,i+3);rows.push(`<div class="execution-map-row"><svg class="execution-branches" viewBox="0 0 1000 64" preserveAspectRatio="none" aria-hidden="true">${group.map((n,j)=>{const x=(j+.5)*1000/group.length,active=m.ok&&s.serving&&source===n.node,preparing=m.ok&&s.target?.node===n.node;return `<path class="${active?'current':preparing?'preparing':'available'} ${active&&m.busy?'flowing':''}" d="M500 0 V16 Q500 28 ${x} 28 V64"/>`;}).join('')}</svg><div class="execution-node-grid" style="--map-columns:${group.length}">${cards.slice(i,i+3).join('')}</div></div>`);}
 return `<section class="execution-map" aria-label="서비스 실행과 오프로딩 맵"><header class="execution-map-heading"><div><h3>서비스 실행 맵</h3><p role="status">${E(v.title)}</p></div><span class="badge">${!m.ok?'관측 확인 필요':s.phase==='Suspended'?'중지됨':s.approvalRequired?'승인 후 이동':s.placementMode==='preferred'?'선호 배치':'자동 이동·복귀'}</span></header><ol class="execution-steps" aria-label="실제 전환 진행 단계">${steps.map((x,i)=>`<li ${v.step===i?'aria-current="step"':''}><span>${i+1}</span>${x}</li>`).join('')}</ol><p class="execution-trigger ${v.detecting?'attention':''}">${E(v.hint)}</p><div class="execution-gateway"><span class="execution-service-token">${E(s.name)}</span><span>${m.ok&&s.serving?`요청 입구 → ${E(names(source))} · 대기 ${N(m.load?.pending)}건 / 처리 ${N(m.load?.inFlight)}건`:m.ok?'활성 요청 경로 없음':'마지막 위치 '+E(names(source))+' · 현재 경로 미확인'}</span></div>${m.ok&&target?`<div class="execution-handoff"><strong>${E(names(source))}</strong><span class="execution-transfer" aria-hidden="true">→</span><strong>${E(names(target))}</strong><span>${s.target?'선택 노드 준비 중 · 준비 완료 후 신규 요청 전환':'승인 대기 · 현재 요청 경로 유지'}</span></div>`:''}<div class="execution-topology">${rows.join('')||'<p class="empty">등록된 실행 노드 관측 대기</p>'}</div>${d?`<div class="execution-ranking-basis"><strong>${d.status==='Applied'?'전환 당시 후보 순위':'제어기 후보 평가'} · ${d.candidates.length}개 실행 후보</strong><span>${E(bases[d.basis]||d.basis)}${d.staged?' · 현재 정책의 다음/이전 단계로 제한':''}</span><small>${E(new Date(d.at*1000).toLocaleTimeString('ko-KR',{hour12:false}))} 결정 당시의 검증 값입니다. 다른 노드는 아래에서 제외·등록 조건을 확인할 수 있습니다.</small></div>`:`<p class="note execution-ranking-empty">${!m.ok?'최신 후보 순위 확인 불가':s.phase==='Suspended'?'실행 전 · 후보 평가 대기':'새 이동 판단 전 · 후보 순위 대기'} · 조건을 통과한 후보만 실제 선택 순서로 표시합니다.</p>`}${o.selectedNode&&nodes.has(o.selectedNode)?`<div class="runtime-route-detail"><strong>${E(names(o.selectedNode))} · 노드 전체 실측</strong>${o.hardwareDetail?.(o.selectedNode)||''}</div>`:''}${m.ok&&s.lastTransition?`<p class="execution-last-transition">마지막 경로 전환 · ${E(names(s.lastTransition.fromNode))} → ${E(names(s.lastTransition.toNode))} · ${E(new Date(s.lastTransition.at*1000).toLocaleString('ko-KR',{hour12:false}))}${v.decision?.status==='Interrupted'?' · 이후 이동 준비 중단':''}</p>`:''}</section>`;
}
const api={view,render};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.NexusExecutionMap=api;
})(typeof window!=='undefined'?window:globalThis);
