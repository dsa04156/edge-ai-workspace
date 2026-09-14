(function(root){
'use strict';
const E=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const finite=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0;
const number=v=>finite(v)?v.toLocaleString('ko-KR',{maximumFractionDigits:2}):'미측정';
const pct=v=>finite(v)&&v<=1?(v*100).toFixed(0)+'%':'미측정';
const fresh=(at,now)=>Number.isFinite(at)&&now-at>=0&&now-at<15;
const reasonLabels={node_not_ready:'노드 준비 안 됨',node_pressure_or_unknown:'노드 압력 또는 상태 확인 필요',node_cordoned:'노드 배치 차단',role_not_allowed:'허용하지 않은 노드 역할',untolerated_taint:'배치 제한 조건',selector_or_architecture_mismatch:'실행 조건·아키텍처 불일치',runtime_class_missing:'실행 환경 미등록',resident_on_different_node:'다른 노드에 연결된 실행체',resident_reservation_below_contract:'실행체 예약량 부족',resident_runtime_class_mismatch:'실행 환경 불일치',resident_binding_ambiguous:'실행체 연결 불명확',resident_not_ready:'실행체 준비 안 됨'};
function reason(code){return reasonLabels[code]||(code.startsWith('insufficient:')?'예약 자원 부족 · '+code.slice(13):code);}
function rows(service,options={}){
 const current=options.current!==false&&!service.observation_error&&(service.checkedAt==null||fresh(service.checkedAt,options.now));
 const evaluated=current&&service.managed!==false&&service.phase!=='Suspended';
 const nodes=new Map();
 const put=(node,patch={})=>{if(node)nodes.set(node,{node,...nodes.get(node),...patch});};
 for(const n of options.nodes||[])put(n.hostname);
 for(const r of options.resources||[])put(r.node,{resource:r});
 for(const n of service.contractSummary?.candidateNodes||[])put(n);
 for(const t of service.augmentationStages||[])put(t.node);
 for(const t of [...service.eligibleCandidates||[],...service.excludedCandidates||[],service.active,service.target,...service.retiring||[],service.proposal])if(t)put(t.node);
 return [...nodes.values()].map(row=>{
  const eligible=(service.eligibleCandidates||[]).filter(c=>c.node===row.node);
  const excluded=(service.excludedCandidates||[]).filter(c=>c.node===row.node);
  const qualifications=(service.augmentationStages||[]).filter(c=>c.node===row.node);
  const active=evaluated&&service.serving&&service.active?.node===row.node;
  const preparing=evaluated&&service.target?.node===row.node;
  const retiring=evaluated&&(service.retiring||[]).some(c=>c.node===row.node);
  const recommended=evaluated&&service.proposal?.node===row.node&&options.now<service.proposal.expiresAt;
  let status=!current?'unknown':service.managed===false?'unmanaged':!evaluated?'paused':active?'active':preparing?'preparing':retiring?'retiring':recommended?'recommended':eligible.length?'eligible':excluded.length?'excluded':'unassessed';
  return {...row,eligible,excluded,qualifications,active,preparing,retiring,recommended,status,evaluated,
   label:qualifications.find(x=>x.label)?.label||row.node,
   registered:Boolean((service.contractSummary?.candidateNodes||[]).includes(row.node)||qualifications.length||eligible.length||service.active?.node===row.node||service.target?.node===row.node),
   metrics:options.hardware?.(row.node)||{},resourceCurrent:Boolean(options.resourcesCurrent&&row.resource)};
 }).sort((a,b)=>({active:0,preparing:1,recommended:2,retiring:3,eligible:4}[a.status]??5)-({active:0,preparing:1,recommended:2,retiring:3,eligible:4}[b.status]??5)||Number(b.registered)-Number(a.registered)||a.node.localeCompare(b.node));
}
const statusLabels={unknown:'판단 관측 불가',unmanaged:'공통 제어 미연결',paused:'정지 · 재평가 대기',active:'현재 처리 노드',preparing:'이동 준비 중',retiring:'기존 요청 마무리',recommended:'승인 대기 후보',eligible:'후보 필터 통과',excluded:'후보 제외',unassessed:'서비스 후보 미평가'};
function decision(s,o){
 if(s.managed===false)return {title:'공통 자동 배치 미연결',detail:'이 서비스의 실행 계약과 검증된 후보를 연결해야 자동 판단을 표시할 수 있습니다.',step:-1};
 if(!o.current||s.observation_error)return {title:'최신 판단 확인 불가',detail:'마지막 계약·노드 목록을 표시합니다. 현재 실행 가능 여부를 단정하지 않습니다.',step:-1};
 if(s.phase==='Suspended')return {title:'서비스 정지 · 자동 판단 대기',detail:'서비스 실행 후 지표와 후보 조건을 다시 확인합니다. 이 화면 조회로 서비스나 부하가 시작되지는 않습니다.',step:-1};
 if(s.target)return {title:'이동할 실행체 준비 중',detail:'대상 노드에서 모델 준비가 완료돼야 새 요청 경로를 전환합니다.',step:2};
 if(s.retiring?.length)return {title:'이전 실행체의 요청 마무리 중',detail:'전환 전 요청을 마무리하고 기존 자원 반환을 확인합니다.',step:4};
 if(s.proposal&&o.now<s.proposal.expiresAt)return {title:'추천 후보 승인 대기',detail:'승인 대상으로 제안된 후보입니다. 아직 요청 경로를 전환하지 않았습니다.',step:1};
 if(s.returnState&&fresh(s.returnState.at,o.now)&&['Observing','Waiting'].includes(s.returnState.phase))return {title:'복귀 조건 관찰 중',detail:'하위 후보 처리 여유와 낮은 부하가 일정 시간 유지되는지 확인합니다.',step:0};
 if(s.phase==='Blocked')return {title:'배치 보류',detail:'아래 후보 제외 이유를 확인하세요. 자원 여유가 있어도 서비스 실행 조건을 통과해야 합니다.',step:1};
 const p=s.policyObservation;
 if(p&&fresh(p.at,o.now)&&(p.pressureElapsedSeconds>0||p.latencyElapsedSeconds>0))return {title:'부하·지연 악화 관찰 중',detail:'설정된 지속 시간을 넘는지 확인한 뒤 기존 제어기가 후보를 판단합니다.',step:0};
 return {title:s.serving?'현재 위치에서 처리 유지':'실행 상태 확인 중',detail:'서비스 지표와 등록된 후보 조건을 확인합니다. 후보 표는 자동 선택 명령이 아닙니다.',step:0};
}
function evidence(row){
 if(row.status==='unknown')return '최신 제어기 관측 필요';
 if(row.status==='unmanaged')return '이 서비스의 실행 계약 연결 필요';
 if(row.status==='paused')return row.registered?'등록 후보 · 실행 시 재평가':'서비스 정지 중 · 마지막 평가 근거는 상세에서 확인';
 if(row.status==='active')return '현재 서비스 요청 경로';
 if(row.status==='preparing')return '대상 실행체·모델 Ready 확인 중';
 if(row.status==='retiring')return '진행 중 요청과 자원 반환 확인';
 if(row.status==='recommended')return '제어기가 제안한 후보 · 승인 대기';
 if(row.status==='eligible')return '이 서비스의 후보 필터 통과 · 즉시 이동을 뜻하지 않음';
 return [...new Set(row.excluded.flatMap(c=>c.reasons))].map(reason).slice(0,2).join(' · ')||'노드는 관측됐으나 서비스별 후보 평가 없음';
}
function capacity(row){
 if(!row.resourceCurrent)return '관측 확인 필요';
 if(row.resource.kubernetesReady!==true||row.resource.schedulable!==true)return '현재 배치 제한';
 const a=row.resource.available;
 return `<span>CPU ${finite(a?.cpuCores)?number(a.cpuCores)+' cores':'미측정'}</span><span>메모리 ${finite(a?.memoryBytes)?number(a.memoryBytes/1e9)+' GB':'미측정'}</span>`;
}
function qualifications(row){
 const measured=row.qualifications.filter(q=>finite(q.qualifiedRps)||finite(q.qualifiedP95Milliseconds));
 if(!measured.length)return '<span class="note">성능 값 미연결</span>';
 return measured.map(q=>`<span>${finite(q.qualifiedRps)?number(q.qualifiedRps)+'건/s':'처리율 미측정'} · p95 ${finite(q.qualifiedP95Milliseconds)?number(q.qualifiedP95Milliseconds)+'ms':'미측정'}</span>`).join('');
}
function detail(row,s,o){
 const resources=row.resourceCurrent?row.resource:null;
 const amounts=v=>v?`CPU ${number(v.cpuCores)} cores · 메모리 ${finite(v.memoryBytes)?number(v.memoryBytes/1e9)+' GB':'미측정'}`:'관측 확인 필요';
 const units=resources?.available?.acceleratorUnits;
 return `<aside class="placement-node-detail" aria-label="선택 후보 상세"><h4>${E(row.label)} · 선택 후보 상세</h4><p>${E(row.node)} · ${E(statusLabels[row.status])}</p><dl><div><dt>할당 가능 총량</dt><dd>${amounts(resources?.allocatable)}</dd></div><div><dt>Pod 요청으로 예약됨</dt><dd>${amounts(resources?.requested)}</dd></div><div><dt>예약 차감 잔량</dt><dd>${amounts(resources?.available)}</dd></div><div><dt>가속기 예약 차감 잔량</dt><dd>${units?Object.entries(units).map(([k,v])=>`${E(k)}: ${number(v)}`).join(' · ')||'등록된 가속기 자원 없음':'관측 확인 필요'}</dd></div></dl><p class="note">가속기 자원 단위와 GPU 메모리는 다릅니다. 공유 GPU 슬롯을 물리 GPU 개수나 메모리 여유로 해석하지 않습니다.</p><h4>${row.evaluated?'서비스별 실행 형태와 판단':'마지막 실행 형태와 판단 · 현재 판단 아님'}</h4>${row.eligible.length||row.excluded.length?`<ul>${row.eligible.map(c=>`<li>${E(c.variant)} · ${row.evaluated?'후보 필터 통과':'과거 필터 통과'}</li>`).join('')}${row.excluded.map(c=>`<li>${E(c.variant)} · ${c.reasons.map(x=>E(reason(x))).join(' · ')}</li>`).join('')}</ul>`:'<p>이 노드의 서비스별 평가 정보가 연결되지 않았습니다.</p>'}${row.qualifications.length?`<p>등록 성능: ${row.qualifications.map(q=>E(q.variant)).join(', ')}. 입력 조건·측정 시각은 현재 응답에 연결되지 않아 여기서 최신 재검증 여부를 판단하지 않습니다.</p>`:''}</aside>`;
}
function contract(s){
 const c=s.contractSummary;
 return `<div class="placement-contract"><h3>서비스 실행 설명서 <small>등록된 설정</small></h3><dl><div><dt>모델 · 실행 방식</dt><dd>${E(c?.model||'모델 정보 미연결')}<small>${E(c?.adapter||'실행 방식 상세 미연결')}</small></dd></div><div><dt>실제 입력 종류</dt><dd>${E(({sensor:'센서',image:'영상',text:'텍스트'})[c?.inputType]||c?.inputType||'입력 계약 미연결')}<small>${E(c?.inputSource||'입력 source 미연결')}</small></dd></div><div><dt>서비스 공통 자원 선언</dt><dd>CPU ${E(c?.cpuRequest||'미연결')} · 메모리 ${E(c?.memoryRequest||'미연결')}<small>${E(c?.acceleratorRequest||'가속기 요구량 미연결')}</small></dd></div><div><dt>기본 실행 노드</dt><dd>${E(c?.defaultNode||'기본 노드 정보 미연결')}<small>현재 배치와 다를 수 있습니다.</small></dd></div></dl><p class="note">노드별 이미지·자원 요구량 상세와 실제 입력 / 시험 입력별 유입량 분리는 아직 이 화면에 연결되지 않았습니다.</p></div>`;
}
const filters=new Map();
function render(s,o={}){
 o={...o,current:o.current!==false&&!s.observation_error&&(s.checkedAt==null||fresh(s.checkedAt,o.now))};
 const all=rows(s,o),filter=o.filter||filters.get(s.uid)||'all';
 const shown=all.filter(r=>filter==='all'||filter==='registered'&&r.registered||filter==='excluded'&&r.status==='excluded');
 const d=decision(s,o),eligible=all.filter(r=>['eligible','active','preparing','recommended'].includes(r.status)).length;
 const current=s.managed===false?'제어 미연결':!o.current?'관측 확인 불가':s.active?.node||'배치 없음';
 const selected=all.find(r=>r.node===o.selectedNode);
 return `<section class="panel runtime-placement-overview" aria-label="전체 노드와 서비스 배치 판단"><header class="placement-heading"><div><p class="eyebrow">서비스별 배치 관측</p><h2>전체 노드 · 실행 후보</h2><p>이 서비스가 어디에서 실행 가능한지, 왜 후보가 되거나 제외됐는지 확인합니다.</p></div><span class="badge">읽기 전용 판단 근거</span></header><dl class="placement-summary"><div><dt>선택 서비스</dt><dd>${E(s.displayName||s.name)}</dd></div><div><dt>현재 실행 위치</dt><dd>${E(current)}</dd></div><div><dt>관측·평가에 포함된 노드</dt><dd>${all.length}<small> 노드</small></dd></div><div><dt>현재 필터 통과·사용 노드</dt><dd>${s.managed===false?'미연결':!o.current?'확인 불가':s.phase==='Suspended'?'재평가 대기':eligible}</dd></div></dl><div class="placement-decision"><strong>${E(d.title)}</strong><p>${E(d.detail)}</p><ol aria-label="자동 전환 절차">${['지표 관찰','후보 판단','실행체 준비','새 요청 전환','기존 요청 마무리'].map((label,i)=>`<li ${d.step===i?'aria-current="step"':''}>${label}</li>`).join('')}</ol></div>${contract(s)}<div class="placement-toolbar"><div role="group" aria-label="후보 필터">${[['all','전체 노드'],['registered','등록·연결 후보'],['excluded','현재 제외']].map(([key,label])=>`<button type="button" class="button" data-placement-filter="${key}" data-placement-uid="${E(s.uid)}" aria-pressed="${filter===key}">${label}</button>`).join('')}</div><span>노드 이름을 누르면 자원 예약·실행 형태별 근거를 펼칩니다.</span></div>${!all.length?'<p class="empty">노드 관측을 기다리고 있습니다. 후보를 임의로 만들지 않습니다.</p>':!shown.length?'<p class="empty">이 조건에 해당하는 현재 판단이 없습니다. 정지·관측 불가 상태에서는 제외 여부를 확정하지 않습니다.</p>':`<div class="table-wrap"><table class="data-table placement-candidates"><thead><tr><th>노드 / 실행 환경</th><th>서비스 배치 판단</th><th>등록 처리능력</th><th>예약 차감 자원</th><th>실측 사용률</th><th>판단 근거</th></tr></thead><tbody>${shown.map(r=>`<tr class="placement-row ${r.status}" data-placement-node="${E(r.node)}"><td><button type="button" class="placement-node-name" data-runtime-node="${E(r.node)}" data-runtime-uid="${E(s.uid)}" aria-expanded="${r.node===o.selectedNode}">${E(r.label)}</button>${r.label!==r.node?`<small>${E(r.node)}</small>`:''}<small>${E(r.resource?.architecture||'환경 미연결')} · ${E(r.resource?.accelerator||'가속기 종류 미연결')}</small></td><td><span class="placement-state ${r.status}">${E(statusLabels[r.status])}</span>${r.registered?'<small>서비스 실행 후보에 등록·연결됨</small>':''}</td><td>${qualifications(r)}<small>등록값 · 현재 처리량과 구분</small></td><td>${capacity(r)}</td><td>${r.metrics.current?`<span>CPU ${pct(r.metrics.cpu)} · 메모리 ${pct(r.metrics.memory)}</span><span>GPU ${pct(r.metrics.gpu)} · ${finite(r.metrics.gpuTemperature)?number(r.metrics.gpuTemperature)+'°C':'온도 미측정'}</span>`:'<span>현재 측정 확인 필요</span>'}</td><td>${E(evidence(r))}</td></tr>`).join('')}</tbody></table></div>`}${selected?detail(selected,s,o):''}<footer><p>등록 처리능력은 해당 서비스의 검증 운용점입니다. 노드 전체 순위나 현재 남은 처리능력을 뜻하지 않습니다.</p><p>예약 차감 자원: Kubernetes 할당 가능량 − Pod requests. 실제 사용률·온도: Prometheus. ${o.resourcesCurrent&&o.resourcesReceivedAt?'자원 조회 '+E(new Date(o.resourcesReceivedAt).toLocaleTimeString('ko-KR',{hour12:false})):'자원 예약 관측 확인 필요'}.</p><p>전체 노드의 자동 선택·다중 서비스 예약 조정은 설계 확장 대상입니다. 이 표가 미연결 서비스를 자동 배포하지 않습니다.</p></footer></section>`;
}
function setup(draw){root.document.addEventListener('click',e=>{const b=e.target.closest('[data-placement-filter]');if(b){filters.set(b.dataset.placementUid,b.dataset.placementFilter);draw();}});}
const api={rows,decision,render,setup};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.NexusPlacementOverview=api;
})(typeof window!=='undefined'?window:globalThis);
