/* Operational overview: existing read APIs, no generated history or control actions. */
(function(root){
'use strict';
const D=root.NexusData,E=D.escape;
const colors=['#1685fb','#0bbf91','#7554fa'];
const aliases={'etri-dev0001-jetorn':'Jetson 01','etri-dev0002-raspi5':'Raspberry Pi 02','etri-dev0003-raspi5':'Raspberry Pi 03','etri-dev0004-tedger':'Tinker Edge R','etri-dev0005-jetagx':'Jetson AGX','etri-ser0001-cg0msb':'서버 01','etri-ser0002-cgnmsb':'서버 02'};
const nodeName=n=>aliases[n]||n||'미확인';
const reasons={execution_lease_expired:'실행 권한 만료 · AI 처리 중단',service_input_stale:'서비스 입력 데이터가 오래됐습니다',model_warming_up:'추론 모델 준비 중',input_stale:'입력 데이터 오래됨',model_not_ready:'모델 준비 미확인',service_performance_unavailable:'유효한 성능 표본 없음',resource_observation_unavailable:'자원 관측 미확인'};
const labels={healthy:'정상',degraded:'점검 필요',stale:'오래됨',fresh:'최신',warming_up:'준비 중',ready:'준비 완료',available:'수신 정상',STANDBY:'처리 중단',ACTIVE:'활성 모드',SHADOW:'보조 모드',BLOCKED:'검토 보류',FAILED:'실패',SUCCEEDED:'완료',warning:'주의'};
const label=v=>labels[v]||v||'미확인';
const time=v=>Number.isFinite(Date.parse(v))?new Date(v).toLocaleString('ko-KR',{timeZone:'Asia/Seoul',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false}):'시각 미확인';
const fresh=(t,now,ttl=60000)=>Number.isFinite(Date.parse(t))&&now-Date.parse(t)>=-5000&&now-Date.parse(t)<=ttl;
const number=v=>typeof v==='number'&&Number.isFinite(v);
const icon=name=>`<img src="/static/nexus/vendor/${name}.svg" alt="" aria-hidden="true">`;
const pill=(text,kind='muted')=>`<span class="ov-pill ${kind}">${E(text)}</span>`;
const link=(text,page)=>`<button class="ov-link" data-live-page="${page}">${E(text)} →</button>`;
const heading=(title,action='')=>`<div class="ov-card-heading"><h2>${title}</h2>${action}</div>`;
let charts=[],frame=null,lastModel=null,metric='cpuRatio';
function model(entries,now=Date.now()){
 const current=k=>D.isCurrent(entries[k],now),items=k=>D.items(entries[k],k);
 const services=items('services'),devices=items('devices'),resources=items('resources');
 const groups=D.groupSources(devices,items('twins')).sources;
 const ops=entries.operations?.data;
 const opsCurrent=current('operations')&&fresh(ops?.generated_at,now);
 const demoCurrent=opsCurrent&&ops?.sources?.demo?.status==='observed';
 const nodeCounts={ready:0,notReady:0,unknown:0};
 resources.forEach(r=>nodeCounts[!current('resources')||typeof r.kubernetesReady!=='boolean'?'unknown':r.kubernetesReady?'ready':'notReady']++);
 const usage=resources.map(r=>({name:r.node,...Object.fromEntries(['cpuRatio','memoryRatio','gpuRatio'].map(k=>[k,current('resources')&&fresh(r.utilization?.observedAt,now)&&number(r.utilization[k])&&r.utilization[k]>=0&&r.utilization[k]<=1?r.utilization[k]*100:null]))}));
 const latency=services.map(s=>{const observed=ops?.services?.find(x=>x.service_id===s.service_id);const q=observed?.quality;return {id:s.service_id,name:s.display_name,value:demoCurrent&&observed?.observation_state==='Observed'&&q?.valid===true&&q.sample_count>0&&fresh(q.observed_at,now)&&number(q.processing_latency_p95_ms)&&q.processing_latency_p95_ms>=0?q.processing_latency_p95_ms:null,samples:q?.sample_count};});
 const execution=s=>current('services')&&s.mode==='live'&&!s.observation_error&&s.execution_ownership&&(!s.execution_ownership.enabled||s.execution_ownership.lease_valid!==false)?s.execution_ownership.effective_mode:current('services')&&s.mode==='live'&&!s.observation_error&&s.execution_ownership?.effective_mode==='STANDBY'?'STANDBY':null;
 const issues=demoCurrent?(ops.issues||[]):[];
 return {services,devices,resources,groups,ops,opsCurrent,demoCurrent,issues,nodeCounts,usage,latency,execution,current,events:[...(ops?.events||[])].sort((a,b)=>(Date.parse(b.timestamp)||0)-(Date.parse(a.timestamp)||0)),errors:['services','resources','devices','operations'].filter(k=>!current(k)),received:Math.max(0,...['services','resources','devices','operations'].map(k=>entries[k]?.receivedAt||0)),refreshing:Object.values(entries).some(e=>e.refreshing)};
}
function kpi(title,value,details,page,symbol,tone){return `<button class="ov-kpi" ${page==='attention'?'data-overview-attention':'data-live-page="'+page+'"'}><span class="ov-kpi-icon ${tone}">${icon(symbol)}</span><span class="ov-kpi-value"><span>${title}</span><strong>${value}</strong></span><span class="ov-kpi-details">${details}</span></button>`;}
const dot=(text,tone='muted')=>`<span class="ov-dot-label ${tone}">${E(text)}</span>`;
const empty=text=>`<div class="ov-empty">${E(text)}</div>`;
function render(entries){
 clear();const m=lastModel=model(entries);const c=m.current;
 const active=m.services.filter(s=>m.execution(s)==='ACTIVE').length;
 const stopped=m.services.filter(s=>m.execution(s)==='STANDBY').length;
 const sourceNames=Object.fromEntries(m.services.map(s=>[s.service_id,s.display_name]));
 const nodeTotal=c('resources')?m.resources.length:'—';
 const dFresh=c('devices')?m.devices.filter(d=>d.overall_status==='available').length:null;
 const table=(heads,rows)=>`<div class="ov-table-wrap"><table class="ov-table"><thead><tr>${heads.map(h=>`<th>${h}</th>`).join('')}</tr></thead><tbody>${rows}</tbody></table></div>`;
 const serviceRows=m.services.map(s=>{const known=c('services')&&s.mode==='live'&&!s.observation_error;const mode=m.execution(s);const q=m.latency.find(x=>x.id===s.service_id);return `<tr><td><button class="ov-service-name" data-live-service="${E(s.service_id)}">${E(s.display_name)}</button><small>${E(s.service_id)}</small></td><td>${pill(mode?label(mode):'현재 미확인',mode==='STANDBY'?'warn':mode==='ACTIVE'?'good':'muted')}<small>${known?E(label(s.model_state)):'관측 확인 필요'}</small></td><td>${E(nodeName(s.node))}<small>${E(s.model_version)}</small></td><td>${q?.value==null?'미측정':E(q.value.toFixed(1))+' ms'}<small>${known?E(label(s.input_state)):'입력 미확인'}</small></td></tr>`;}).join('');
 const issueRows=m.issues.slice(0,4).map(i=>`<tr><td>${pill(label(i.state),'warn')}</td><td><button class="ov-service-name" data-live-service="${E(i.service_id)}">${E(reasons[i.reason]||i.reason)}</button><small>${E(sourceNames[i.service_id]||i.service_id)}</small></td><td><button class="ov-detail" data-live-service="${E(i.service_id)}">상세</button></td></tr>`).join('');
 const eventRows=m.events.slice(0,4).map(e=>`<li><span class="ov-event-marker"></span><div><button data-live-service="${E(e.service_id)}">${E(e.type==='Scheduling Decision'?'배치 검토':e.type)} · ${E(label(e.state))}</button><p title="${E((e.reasons||[]).map(r=>reasons[r]||r).join(' · '))}">${E((e.reasons||[]).map(r=>reasons[r]||r).join(' · ')||e.service_id)}</p></div><time>${E(time(e.timestamp))}</time></li>`).join('');
 const invRows=m.groups.map(g=>`<tr><td><button class="ov-service-name" data-live-source="${E(g.id)}">${E(g.id)}</button><small>${E(nodeName(g.devices[0]?.node_name))}</small></td><td>${c('devices')?g.devices.length:'—'}</td><td>${pill(!c('devices')?'현재 미확인':g.devices.every(d=>d.overall_status==='available')?'수신 정상':'점검 필요',!c('devices')?'muted':g.devices.every(d=>d.overall_status==='available')?'good':'warn')}</td></tr>`).join('');
 const out=`<div class="ov-dashboard"><div class="ov-toolbar"><span>${dot(m.errors.length?'일부 관측 확인 중':'관측 API 응답 확인',m.errors.length?'warn':'good')}<span class="ov-updated">수신 ${m.received?E(time(new Date(m.received).toISOString())):'대기'} · 30초 갱신</span></span><div><button class="ov-link" data-overview-map>전체 장비 지도 →</button><button class="button" data-live-refresh ${m.refreshing?'disabled':''}>${m.refreshing?'갱신 중':'새로고침'}</button></div></div>
 <section class="ov-kpis" aria-label="운영 요약">
 ${kpi('AI 서비스',c('services')?m.services.length:'—',dot((c('services')?active:'—')+' 활성 모드','good')+dot((c('services')?stopped:'—')+' 처리 중단','warn')+dot('Git 등록 기준'),'services','diagram-3','purple')}
 ${kpi('노드',nodeTotal,dot((c('resources')?m.nodeCounts.ready:'—')+' Ready','good')+dot((c('resources')?m.nodeCounts.notReady:'—')+' NotReady','warn')+dot(m.nodeCounts.unknown+' 미확인'),'resources','hdd-network','blue')}
 ${kpi('등록 디바이스',c('devices')?m.devices.length:'—',dot((c('devices')?m.groups.length:'—')+' 물리 source','blue')+dot((dFresh??'—')+' 수신 정상','good')+dot('EdgeX 등록 기준'),'devices','cpu','purple')}
 ${kpi('점검 항목',m.demoCurrent?m.issues.length:'—',dot('서비스 처리·입력','warn')+dot(m.demoCurrent?'현재 관측 근거':'현재 확인 불가')+dot('항목별 상세 확인'),'attention','bell','red')}
 </section>
 <div class="ov-charts">
 <section class="ov-card">${heading('노드 자원 사용률',`<div class="ov-metric-tabs" aria-label="자원 지표">${[['cpuRatio','CPU'],['memoryRatio','메모리'],['gpuRatio','GPU']].map(([k,v])=>`<button data-overview-metric="${k}" aria-pressed="${metric===k}">${v}</button>`).join('')}</div>`)}<div class="ov-chart"><canvas id="ov-resource-chart" role="img" aria-label="노드별 현재 사용률, 상세 수치는 자원 상세에서 확인"></canvas></div><div class="ov-card-foot"><span>현재 실측 · 미관측은 막대 없음</span>${link('자원 상세','resources')}</div></section>
 <section class="ov-card">${heading('노드 준비 상태',link('상세','resources'))}<div class="ov-node-chart"><div class="ov-donut"><canvas id="ov-node-chart" role="img" aria-label="Ready ${m.nodeCounts.ready}, NotReady ${m.nodeCounts.notReady}, 미확인 ${m.nodeCounts.unknown}"></canvas><div><strong>${nodeTotal}</strong><span>전체 노드</span></div></div><dl>${[['Ready',m.nodeCounts.ready,'good'],['NotReady',m.nodeCounts.notReady,'warn'],['미확인',m.nodeCounts.unknown,'muted']].map(([t,n,k])=>`<div><dt>${dot(t,k)}</dt><dd>${n}</dd></div>`).join('')}</dl></div><div class="ov-card-foot">Kubernetes · KubeEdge 기준</div></section>
 <section class="ov-card">${heading('서비스 처리 지연',pill('p95 · ms'))}${m.latency.some(s=>s.value!==null)?'<div class="ov-chart"><canvas id="ov-latency-chart" role="img" aria-label="유효한 서비스별 p95 처리 지연"></canvas></div>':`<div class="ov-no-metric">${icon('activity')}<strong>유효한 성능 표본이 없습니다</strong><span>서비스 처리와 입력 상태를 확인하세요.</span>${link('서비스 확인','services')}</div>`}<div class="ov-card-foot">최근 서비스 측정 window · 미측정 ≠ 0 ms</div></section>
 </div>
 <div class="ov-pair"><section class="ov-card" id="overview-attention" tabindex="-1">${heading(`점검이 필요한 항목 ${pill(m.demoCurrent?String(m.issues.length):'미확인','warn')}`,link('전체 보기','history'))}${!m.demoCurrent?empty('현재 서비스 관측을 확인할 수 없습니다. 새로고침 후 다시 확인하세요.'):issueRows?table(['상태','문제와 영향 서비스','확인'],issueRows):empty('이 응답에서 식별된 서비스 점검 항목이 없습니다.')}<div class="ov-card-foot">현재 서비스 관측 기준 · 과거 알림과 구분</div></section>
 <section class="ov-card">${heading('최근 활동',link('전체 이력','history'))}<ol class="ov-events">${eventRows||'<li>조회된 저장 이력이 없습니다.</li>'}</ol><div class="ov-card-foot">${m.opsCurrent?'저장된 원 시각 · KST':'최근 응답 확인 불가 · 보존된 과거 이력'}</div></section></div>
 <div class="ov-pair"><section class="ov-card">${heading('AI 서비스',link('모든 서비스','services'))}${serviceRows?table(['서비스','실행·모델','배포 노드·버전','p95·입력'],serviceRows):empty(c('services')?'등록된 서비스가 없습니다.':'서비스 목록을 확인하고 있습니다.')}<div class="ov-service-footer"><span>Pod 준비 상태와 AI 처리는 별도입니다.</span>${link('연결과 실행 보기','services')}</div></section>
 <section class="ov-card">${heading('물리 장비 목록',link('모든 디바이스','devices'))}${invRows?table(['물리 source / 연결 노드','등록 Device','수신 상태'],invRows):empty(c('devices')?'물리 source가 지정된 장비가 없습니다.':'장비 목록을 확인하고 있습니다.')}<div class="ov-card-foot">한 물리 source에 여러 EdgeX Device가 연결됩니다.${m.devices.some(d=>!d.physical_device_id)?' source 미지정 '+m.devices.filter(d=>!d.physical_device_id).length+'개':''}</div></section></div>
 </div>`;
 if(root.requestAnimationFrame)frame=root.requestAnimationFrame(()=>mount(m));
 return out;
}
function clear(){if(frame!==null&&root.cancelAnimationFrame)root.cancelAnimationFrame(frame);frame=null;charts.forEach(c=>c.destroy());charts=[];}
function mount(m){
 frame=null;if(!root.Chart||!root.document.getElementById('ov-resource-chart'))return;
 const common={responsive:true,maintainAspectRatio:false,animation:false,plugins:{legend:{display:false}},scales:{x:{grid:{display:false},ticks:{color:'#63758e',font:{size:10},maxRotation:0,minRotation:0}},y:{min:0,max:100,ticks:{stepSize:50,color:'#63758e',callback:v=>v+'%'},grid:{color:'#eaf0f6'},border:{display:false}}}};
 const resource=new root.Chart(root.document.getElementById('ov-resource-chart'),{type:'bar',data:{labels:m.usage.map(r=>nodeName(r.name)),datasets:[{label:{cpuRatio:'CPU',memoryRatio:'메모리',gpuRatio:'GPU'}[metric],data:m.usage.map(r=>r[metric]),backgroundColor:colors[['cpuRatio','memoryRatio','gpuRatio'].indexOf(metric)],borderRadius:3,maxBarThickness:27}]},options:common});charts.push(resource);
 charts.push(new root.Chart(root.document.getElementById('ov-node-chart'),{type:'doughnut',data:{labels:['Ready','NotReady','미확인'],datasets:[{data:[m.nodeCounts.ready,m.nodeCounts.notReady,m.nodeCounts.unknown],backgroundColor:['#0bbf91','#f6ad24','#91a1b7'],borderWidth:0,hoverOffset:3}]},options:{responsive:true,maintainAspectRatio:false,animation:false,cutout:'70%',plugins:{legend:{display:false}}}}));
 const canvas=root.document.getElementById('ov-latency-chart');if(canvas)charts.push(new root.Chart(canvas,{type:'bar',data:{labels:m.latency.map(s=>s.name),datasets:[{label:'p95 (ms)',data:m.latency.map(s=>s.value),backgroundColor:'#a9bfd8',borderRadius:3,maxBarThickness:38}]},options:{...common,scales:{...common.scales,y:{beginAtZero:true,grid:{color:'#eaf0f6'},ticks:{color:'#63758e'}}}}}));
}
if(root.document){
 root.document.addEventListener('click',e=>{const box=root.document.getElementById('overview-search-results');if(box&&(!e.target.closest('.ov-global-search')||e.target.closest('#overview-search-results button')))box.hidden=true;const b=e.target.closest('button');if(!b)return;if(b.hasAttribute('data-overview-attention')){const target=root.document.getElementById('overview-attention');target?.focus();target?.scrollIntoView({block:'center'});}if(b.hasAttribute('data-overview-map')){root.NexusServiceMap.openOverview();root.NexusLive.setServiceView('map');root.location.hash='service-map';}
 if(b.dataset.overviewMetric&&['cpuRatio','memoryRatio','gpuRatio'].includes(b.dataset.overviewMetric)){metric=b.dataset.overviewMetric;root.document.querySelectorAll('[data-overview-metric]').forEach(x=>x.setAttribute('aria-pressed',String(x===b)));const c=charts[0];if(c&&lastModel){c.data.datasets[0].data=lastModel.usage.map(r=>r[metric]);c.data.datasets[0].label={cpuRatio:'CPU',memoryRatio:'메모리',gpuRatio:'GPU'}[metric];c.data.datasets[0].backgroundColor=colors[['cpuRatio','memoryRatio','gpuRatio'].indexOf(metric)];c.update();}}
 if(!e.target.closest('.ov-global-search')){const box=root.document.getElementById('overview-search-results');if(box)box.hidden=true;}
 });
 root.document.addEventListener('input',e=>{if(e.target.id!=='overview-search')return;const box=root.document.getElementById('overview-search-results'),q=e.target.value.trim().toLowerCase(),m=lastModel;box.hidden=!q;if(!q||!m)return;const results=[...m.services.map(s=>({name:s.display_name,id:s.service_id,type:'서비스',attr:'data-live-service'})),...m.groups.map(s=>({name:s.id,id:s.id,type:'물리 장비',attr:'data-live-source'})),...m.resources.map(n=>({name:nodeName(n.node),id:n.node,type:'노드',attr:'data-live-page'}))].filter(x=>(x.name+' '+x.id).toLowerCase().includes(q)).slice(0,8);box.innerHTML=results.map(x=>`<button ${x.attr}="${E(x.attr==='data-live-page'?'resources':x.id)}"><span>${E(x.name)}<small>${E(x.id)}</small></span><small>${x.type}</small></button>`).join('')||'<p>일치하는 서비스·장비·노드가 없습니다.</p>';});
 root.document.addEventListener('keydown',e=>{if(e.key==='Escape'){const box=root.document.getElementById('overview-search-results');if(box)box.hidden=true;}if(e.key==='ArrowDown'&&e.target.id==='overview-search'){const b=root.document.querySelector('#overview-search-results button');if(b){e.preventDefault();b.focus();}}});
}
const api={model,render,clear};root.NexusOverview=api;if(typeof module!=='undefined'&&module.exports)module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
