/* Physical node → container virtual device. Existing GET observations only. */
(function(root){
'use strict';
const D=root.NexusData, V=root.VirtualDeviceView, E=D.escape;
const fresh=(stamp,now)=>V.ageFresh(stamp,now,90);
const workloadKey=p=>p.namespace+'/'+p.service;
const runtimeKey=row=>{const r=row.definition.spec.runtimeRef;return r.namespace+'/'+r.workloadRef?.name;};
const states={ready:'모델 준비됨',processing:'요청 처리 중',not_ready:'모델 준비 안 됨',terminating:'종료 중',unknown:'확인 불가',no_instance:'실행체 없음',observed:'실행체 관측'};
const pill=(text,tone='')=>`<span class="dm-status ${tone}">${E(text)}</span>`;
const count=v=>v==null?'—':v;
const num=(v,d=1)=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(d):'—';
// Preserve independent scroll regions when the surrounding dashboard refreshes.
const scrollPositions=new Map();
function rememberScroll(){if(!root.document)return;root.document.querySelectorAll('[data-dm-scroll]').forEach(el=>scrollPositions.set(el.dataset.dmScroll,{top:el.scrollTop,left:el.scrollLeft}));}
function restoreScroll(){if(!root.document)return;root.document.querySelectorAll('[data-dm-scroll]').forEach(el=>{const p=scrollPositions.get(el.dataset.dmScroll);if(p){el.scrollTop=p.top;el.scrollLeft=p.left;}});}
function resetScroll(){scrollPositions.clear();}
const serviceStates={running:'실행 중',starting:'시작 중',stopping:'중지 중',stopped:'중지',blocked:'실행 대기 · 확인 필요',unknown:'현재 확인 불가'};
function serviceView(entry,now){
 const data=entry?.data;
 const elapsed=entry?.receivedMonotonic!=null&&root.performance?Math.max(0,(root.performance.now()-entry.receivedMonotonic)/1000):Math.max(0,(now-(entry?.receivedAt||0))/1000);
 const current=Boolean(data&&!entry.lastFetchFailed&&!entry.error&&!data.observation_error&&elapsed<15);
 const rows=(data?.devices||[]).map(d=>{
  const age=data.observed_at-d.checked_at+elapsed;
  const valid=current&&!d.observation_error&&d.checked_at!=null&&age>=0&&age<15;
  return valid?{...d,locations:d.locations.map(l=>{const age=data.observed_at-l.observed_at+elapsed;return l.observed_at!=null&&age>=0&&age<15?l:{...l,ready:null,in_flight:null,observed_at:null};})}:{...d,state:'unknown',serving:null,locations:[]};
 });
 // A cached running flag cannot outlive the active model-health observation.
 for(const d of rows)if(d.serving&&!d.locations.some(l=>l.role==='active'&&l.ready===true)){d.state='unknown';d.serving=null;}
 return {rows,current,total:current?data.total:null,running:current&&rows.every(d=>d.serving!=null)?rows.filter(d=>d.serving).length:null};
}
function serviceCard(d,selected){
 const locations=d.locations.map(l=>(l.role==='preparing'?'준비 위치':l.role==='retiring'?'정리 중 위치':l.ready===true?'실행 위치':'관측 위치')+' · '+l.node);
 const related=selected?.startsWith('node:')&&d.locations.some(l=>l.node===selected.slice(5));
 return `<button class="dm-container ${related?'related':''}" data-dm-select="${E(d.id)}" aria-pressed="${selected===d.id}"><span class="dm-identity"><strong>${E(d.service_name)}</strong><small>${E(({ai:'AI 서비스',service:'서비스',test:'시험 서비스'})[d.service_kind])}${d.contract?.model?' · '+E(d.contract.model):''}</small></span><span class="dm-row-state">${pill(serviceStates[d.state]||'현재 확인 불가',d.serving?'ok':'')}</span><span class="dm-location">${locations.length?locations.map(l=>`<small>${E(l)}</small>`).join(''):'<small>'+ (d.state==='stopped'?'현재 실행 위치 없음':'실행 위치 미확인')+'</small>'}${!locations.length&&d.contract?.defaultNode?`<small>설정 위치 · ${E(d.contract.defaultNode)}</small>`:''}</span></button>`;
}
function model(entries,now=Date.now()){
 const good=k=>D.isCurrent(entries[k],now);
 const raw=entries.virtual?.data;
 const serviceDevices=serviceView(entries.serviceVirtual,now);
 // A failed row or node reader must not invalidate independently observed siblings.
 const virtual=V.displayState(raw,Boolean(entries.virtual?.lastFetchFailed),now);
 const profiles=entries.profiles?.data?.service_resource_profiles||[];
 const profileCurrent=good('profiles')&&fresh(entries.profiles?.data?.generated_at,now);
 const resources=D.items(entries.resources,'resources'),metrics=D.items(entries.nodes,'nodes');
 const nodes=new Map();
 const ensure=name=>{if(!name||name==='unknown')return null;if(!nodes.has(name))nodes.set(name,{name,resource:null,metric:null,kube:null,registered:[],workloads:[],sensors:[]});return nodes.get(name);};
 for(const r of resources)ensure(r.node).resource=r;
 for(const n of metrics)ensure(n.hostname).metric=n;
 for(const n of raw?.nodes||[])ensure(n.name).kube=n;
 const loose=[];
 for(const row of virtual.resources){
   const placed=new Map();
   for(const pod of row.instances||[]){if(!pod.node)continue;if(!placed.has(pod.node))placed.set(pod.node,[]);placed.get(pod.node).push(pod);}
   for(const [name,pods] of placed){const node=ensure(name);if(node)node.registered.push({row,pods,planned:false});}
   if(!placed.size){
     const planned=(row.plannedNodeSelector||row.definition.spec.nodeSelector)?.['kubernetes.io/hostname'];
     // A selector is a plan, never evidence of an actual node or running instance.
     if(planned&&nodes.has(planned))nodes.get(planned).registered.push({row,pods:[],planned:true});
     else loose.push(row);
   }
 }
 for(const row of serviceDevices.rows)for(const location of row.locations){const node=nodes.get(location.node);if(node){node.serviceDevices=node.serviceDevices||[];node.serviceDevices.push(row);}}
 const registeredKeys=new Set(virtual.resources.map(runtimeKey));
 for(const p of profiles){if(registeredKeys.has(workloadKey(p)))continue;for(const name of p.nodes||[]){const node=ensure(name);if(node)node.workloads.push(p);}}
 // Each EdgeX Device is an independent sensor row, even when hardware IDs are shared or absent.
 const sensors=D.items(entries.devices,'devices');
 for(const sensor of sensors){if(nodes.has(sensor.node_name))nodes.get(sensor.node_name).sensors.push(sensor);}
 const virtualFresh=Boolean(raw&&!entries.virtual?.lastFetchFailed&&V.ageFresh(raw.observedAt,now,raw.maxAgeSeconds));
 return {nodes:[...nodes.values()].sort((a,b)=>Number(b.registered.length>0)-Number(a.registered.length>0)||Number(b.sensors.length>0)-Number(a.sensors.length>0)||a.name.localeCompare(b.name)),virtual,loose,sensors,serviceDevices,
   profiles,profileStamp:entries.profiles?.data?.generated_at,now,valid:{resources:good('resources'),metrics:good('nodes'),devices:good('devices'),profiles:profileCurrent,virtual:virtualFresh,kube:virtualFresh&&!raw?.nodeError},
   totals:{nodes:good('resources')?resources.length:virtualFresh&&!raw.nodeError?raw.summary.physicalNodes:null,definitions:raw?virtual.resources.length:null,instances:virtual.summary.observedInstances,sensors:good('devices')?sensors.length:null}};
}
function nodeStatus(n,m){
 if(n.kube&&m.valid.kube)return pill(n.kube.ready===true?'노드 준비됨':n.kube.ready===false?'노드 준비 안 됨':'노드 확인 불가',n.kube.ready===true?'ok':'');
 if(n.resource&&m.valid.resources)return pill(({healthy:'노드 정상',degraded:'노드 주의',unavailable:'노드 사용 불가',unhealthy:'노드 장애'})[n.resource.health]||'노드 확인 불가',n.resource.health==='healthy'?'ok':'');
 return pill('노드 확인 불가');
}
function nodeUsage(n,m){
 const u=n.resource?.utilization;
 const metric=n.metric,down=m.valid.metrics&&fresh(metric?.collected_at,m.now)&&(metric?.node_health==='unavailable'||metric?.raw_metrics?.up===0);
 const ok=m.valid.resources&&fresh(u?.observedAt,m.now)&&!down;
 return `<div class="dm-usage"><span>CPU <b>${ok?num(typeof u?.cpuRatio==='number'?u.cpuRatio*100:null,0):'—'}%</b></span><span>메모리 <b>${ok?num(typeof u?.memoryRatio==='number'?u.memoryRatio*100:null,0):'—'}%</b></span></div>`;
}
function registeredCard(row,selected){
 const id='vd:'+row.id,pods=row.instances||[],actual=[...new Set(pods.map(p=>p.node).filter(Boolean))];
 const planned=(row.plannedNodeSelector||row.definition.spec.nodeSelector)?.['kubernetes.io/hostname'];
 const related=selected?.startsWith('node:')&&(actual.length?actual.includes(selected.slice(5)):planned===selected.slice(5));
 return `<button class="dm-container ${actual.length?'':'planned'} ${related?'related':''}" data-dm-select="${E(id)}" aria-pressed="${selected===id}"><span class="dm-identity"><strong>${E(row.definition.spec.displayName||row.id)}</strong><code>${E(row.id)}</code></span><span class="dm-row-state">${pill(states[row.executionState]||row.executionState,['ready','processing'].includes(row.executionState)?'ok':'')}${actual.length?pill('실행체(Pod) '+pods.length+'개'):''}</span><span class="dm-location"><small>${E(actual.length?'실행 위치 · '+actual.join(', '):planned?'설정 위치 · '+planned:'실행 위치 미확인')}</small>${!actual.length?'<small>현재 실행 위치는 확인되지 않았습니다</small>':''}</span></button>`;
}
function workloadCard(p,m,selected){
 const valid=m.valid.profiles&&fresh(p.generated_at||m.profileStamp,m.now);
 const id='workload:'+workloadKey(p),related=selected?.startsWith('node:')&&p.nodes.includes(selected.slice(5));
 return `<button class="dm-container workload ${related?'related':''}" data-dm-select="${E(id)}" aria-pressed="${selected===id}"><span class="dm-identity"><strong>${E(p.service)}</strong><small>${E(p.namespace)}</small></span><span class="dm-row-state">${pill(valid?'실행체(Pod) '+count(p.pod_count)+'개':'배치 확인 불가')}${valid&&p.container_count!=null?pill(p.container_count+' 컨테이너'):''}<small>${valid?'실행체 준비 '+count(p.ready_pod_count)+' / '+count(p.pod_count)+' · 워크로드 전체':'현재 준비 상태 확인 불가'}</small></span><span class="dm-location"><small>${valid?'실행 위치':'마지막 관측 위치'} · ${E(p.nodes.join(', ')||'미확인')}</small></span></button>`;
}
function sensor(d,current){
 const status=current?({available:'사용 가능',unavailable:'사용 불가',degraded:'확인 필요'})[d.overall_status]||'확인 불가':'현재 확인 불가';
 const freshness=current?({fresh:'최신 수신',stale:'수신 지연',no_events:'수신 이력 없음'})[d.telemetry_freshness]||'수신 상태 확인 불가':'수신 상태 확인 불가';
 return `<button class="dm-sensor" data-live-device="${E(d.name)}"><span class="dm-identity"><strong>${E(d.name)}</strong><small>센서 디바이스 · ${E(d.physical_device_id||'연결 장비 미지정')}</small></span><span class="dm-row-state">${pill(status,current&&d.overall_status==='available'?'ok':'')}<small>${E(freshness)}</small></span><span class="dm-location"><small>수집 노드 · ${E(d.node_name||'미확인')}</small></span></button>`;
}
function nodeCard(n,m,selected){
 const type=n.resource?.nodeType,kind=({cloud_server:'서버',edge_ai_server:'엣지 AI 서버',edge_ai_device:'엣지 AI 노드',edge_light_device:'경량 엣지 노드',edge_device:'엣지 노드'})[type]||'노드';
 const related=(n.serviceDevices||[]).some(d=>d.id===selected)||n.registered.some(x=>'vd:'+x.row.id===selected)||n.workloads.some(p=>'workload:'+workloadKey(p)===selected);
 return `<button class="dm-node ${related?'related':''}" data-dm-node="${E(n.name)}" aria-pressed="${selected==='node:'+n.name}"><span class="dm-identity"><strong class="dm-node-name">${E(n.name)}</strong><small>${E(kind)}</small></span><span class="dm-row-state">${nodeStatus(n,m)}</span>${nodeUsage(n,m)}</button>`;
}
function detail(m,selected,opened){
 if(!selected||selected.startsWith('node:'))return '';
 const row=m.virtual.resources.find(r=>'vd:'+r.id===selected),p=m.profiles.find(p=>'workload:'+workloadKey(p)===selected);
 const service=m.serviceDevices.rows.find(d=>d.id===selected);
 let body,title;
 if(service){title=service.service_name;body=`<p class="note">서비스 1개를 가상 디바이스 1개로 표시합니다. 실행 위치는 제어기의 서비스 관측이며 Pod 개수가 아닙니다.</p><dl><dt>서비스 UID</dt><dd>${E(service.service_uid)}</dd><dt>상태</dt><dd>${E(serviceStates[service.state])}</dd><dt>모델</dt><dd>${E(service.contract?.model)}</dd><dt>모델 버전</dt><dd>${E(service.contract?.modelVersion)}</dd><dt>입력</dt><dd>${E(service.contract?.inputType)} · ${E(service.contract?.inputSource)}</dd><dt>자원 요청</dt><dd>CPU ${E(service.contract?.cpuRequest)} · 메모리 ${E(service.contract?.memoryRequest)} · 가속기 ${E(service.contract?.acceleratorRequest)}</dd><dt>설정 위치</dt><dd>${E(service.contract?.defaultNode||'미지정')}</dd><dt>등록 후보 노드</dt><dd>${(service.contract?.candidateNodes||[]).map(E).join(', ')||'미연결'}</dd><dt>실행 관측</dt><dd>${service.locations.map(l=>E(l.role+' · '+l.node+' · '+l.revision)).join('<br>')||'현재 실행 위치 없음 또는 확인 불가'}</dd></dl><a class="button" href="?runtimeService=${E(encodeURIComponent(service.service_uid))}#runtime-services">서비스 실행·중지 화면 열기 ↗</a>${root.NexusServiceSettings?.render(service)||''}`;}
 else
 if(row){title=row.definition.spec.displayName||row.id;body=`<p class="note">등록 정의와 컨테이너 실행체를 구분합니다. 연결 설정은 실제 요청 성공과 별개입니다.</p>${V.detail(row)}<button class="button" data-workspace="virtual">기존 가상 디바이스 운영 도구 ↗</button>`;}
 else if(p){title=p.service;body=`<p class="note">${m.valid.profiles?'실행 중인 Pod 기준 관측':'현재 확인 불가 · 마지막 응답'}. 이 워크로드에는 별도 가상 디바이스 정의가 연결되어 있지 않습니다.</p><dl><dt>Namespace / 워크로드</dt><dd>${E(workloadKey(p))}</dd><dt>관측 노드</dt><dd>${E(p.nodes.join(', '))}</dd><dt>실행체 준비 / 전체</dt><dd>${m.valid.profiles?count(p.ready_pod_count)+' / '+count(p.pod_count):'확인 불가'}</dd><dt>관측 시각</dt><dd>${E(p.generated_at)}</dd><dt>컨테이너</dt><dd>${(p.containers||[]).map(c=>`<div>${E(c.container)} · ${E(c.pod)} · ${E(c.node)}</div>`).join('')||'세부 관측 없음'}</dd></dl>`;}
 else {title='선택한 항목 확인 불가';body='<p>선택한 정의 또는 실행체가 최신 목록에 없습니다. 다른 항목으로 자동 변경하지 않습니다.</p>';}
 let index=0;body=body.replace(/<details>/g,()=>{const key='detail:'+selected+':'+index++;return `<details data-dm-disclosure="${E(key)}" ${opened.has(key)?'open':''}>`;});
 return `<section class="dm-detail panel"><div class="section-heading"><h2 id="dm-detail-title" tabindex="-1">${E(title)}</h2><button class="button" data-dm-close>상세 닫기</button></div>${body}</section>`;
}
function render(entries,{query='',selected=null,opened=new Set()}={},now=Date.now()){
 if(entries.managed&&root.NexusManagedDevices)return root.NexusManagedDevices.render(entries,{query,selected,opened},now);
 const m=model(entries,now),q=query.trim().toLocaleLowerCase();
 const matches=value=>JSON.stringify(value).toLocaleLowerCase().includes(q);
 const serviceRows=m.serviceDevices.rows.filter(d=>matches(d));
 const rows=m.virtual.resources.filter(row=>matches([row.id,row.definition.spec,row.instances]));
 const registeredKeys=new Set(m.virtual.resources.map(runtimeKey));
 for(const d of m.serviceDevices.rows)for(const l of d.locations)if(!l.resident&&d.namespace)registeredKeys.add(d.namespace+'/'+l.revision);
 const allWorkloads=m.profiles.filter(p=>!registeredKeys.has(workloadKey(p)));
 const workloads=allWorkloads.filter(matches);
 const nodes=m.nodes.filter(n=>matches([n.name,n.resource?.nodeType,n.registered.map(x=>x.row),n.workloads,n.sensors,n.serviceDevices]));
 const sensors=m.sensors.filter(s=>matches(s));
 const physicalTotal=m.totals.nodes==null||m.totals.sensors==null?null:m.totals.nodes+m.totals.sensors;
 const virtualTotal=m.valid.virtual&&m.serviceDevices.total!=null?m.totals.definitions+m.serviceDevices.total:null;
 const prototypeRunning=m.virtual.resources.some(r=>r.executionState==='unknown')?null:m.virtual.resources.filter(r=>['ready','processing'].includes(r.executionState)).length;
 const running=m.valid.virtual&&prototypeRunning!=null&&m.serviceDevices.running!=null?prototypeRunning+m.serviceDevices.running:null;
 const total=physicalTotal==null||virtualTotal==null?null:physicalTotal+virtualTotal;
 const totalLabel=n=>n==null?'전체 수 확인 불가':'총 '+n+'개';
 const listCount=(shown,total)=>totalLabel(total)+(q?' · 검색 결과 '+shown+'개':'');
 const summary=[['컴퓨팅 노드',m.totals.nodes],['센서 디바이스',m.totals.sensors],['가상 디바이스',virtualTotal],['실행 중 가상 디바이스',running]];
 const issues=Object.entries({resources:'노드 자원',profiles:'컨테이너 배치',virtual:'가상 디바이스',devices:'센서 디바이스'}).filter(([k])=>!m.valid[k]||entries[k]?.error).map(([,label])=>label);
 if(!m.serviceDevices.current)issues.push('서비스 실행');
 return `<div class="dm-map"><div class="dm-total" role="status"><strong>전체 디바이스 ${totalLabel(total)}</strong><span>물리 ${count(physicalTotal)}개 + 가상 ${count(virtualTotal)}개 · 실행체(Pod)는 별도 집계</span></div><div class="dm-summary">${summary.map(([label,value])=>`<div><span>${label}</span><strong>${count(value)}</strong></div>`).join('')}</div>${issues.length?`<p class="dm-notice" role="status">${E(issues.join(' · '))} 관측 확인 필요. 이전 정보의 현재 상태는 확인 불가로 표시합니다.</p>`:''}
 <section class="dm-section dm-physical-section" aria-labelledby="dm-physical-title"><div class="dm-section-heading"><div><span class="dm-section-number">01 / PHYSICAL</span><h2 id="dm-physical-title">물리 디바이스 <span class="dm-count">${listCount(nodes.length+sensors.length,physicalTotal)}</span></h2></div><p>엣지·워커·서버와 개별 센서</p></div><div id="dm-physical-scroll" class="dm-scroll" data-dm-scroll="physical" role="region" aria-label="물리 디바이스 목록" tabindex="0"><div class="dm-list-head" aria-hidden="true"><span>디바이스 / 종류</span><span>상태</span><span>자원 · 수집 노드</span></div><div class="dm-grid dm-physical-grid">${nodes.map(n=>nodeCard(n,m,selected)).join('')}${sensors.map(s=>sensor(s,m.valid.devices)).join('')}</div>${!nodes.length&&!sensors.length?'<p class="empty">표시할 물리 디바이스가 없습니다. 검색과 관측 상태를 확인하세요.</p>':''}</div></section>
 <section class="dm-section dm-virtual-section" aria-labelledby="dm-virtual-title"><div class="dm-section-heading"><div><span class="dm-section-number">02 / VIRTUAL</span><h2 id="dm-virtual-title">가상 디바이스 <span class="dm-count">${listCount(rows.length+serviceRows.length,virtualTotal)}</span></h2></div><p>등록된 기능 실행 단위 · Pod 수와 별도 집계</p></div>${root.NexusServiceDefinition?.launcher()||''}${selected?.startsWith('node:')?`<div class="dm-selection"><span><b>${E(selected.slice(5))}</b>의 실행·설정 관계를 강조합니다. 전체 목록은 유지됩니다.</span><button class="button" data-dm-clear>선택 해제</button></div>`:''}${selected?.startsWith('workload:')?'':detail(m,selected,opened)}<div id="dm-virtual-scroll" class="dm-scroll" data-dm-scroll="virtual" role="region" aria-label="가상 디바이스 목록" tabindex="0"><div class="dm-list-head" aria-hidden="true"><span>이름 / 식별자</span><span>실행 상태</span><span>실행 · 설정 위치</span></div><div class="dm-grid dm-virtual-grid">${serviceRows.map(row=>serviceCard(row,selected)).join('')}${rows.map(row=>registeredCard(row,selected)).join('')}</div>${!rows.length&&!serviceRows.length?`<p class="empty">${q?'검색과 일치하는 가상 디바이스가 없습니다.':m.valid.virtual?'등록된 가상 디바이스가 없습니다.':'가상 디바이스 정의를 확인하고 있습니다.'}</p>`:''}
 </div></section>
 <details class="dm-workloads-section" data-dm-disclosure="workloads" ${opened.has('workloads')||selected?.startsWith('workload:')?'open':''}><summary>기타 워크로드 <span class="dm-count">${listCount(workloads.length,m.valid.profiles&&m.valid.virtual&&m.serviceDevices.current?allWorkloads.length:null)}</span></summary><p class="dm-footnote">${m.valid.virtual&&m.serviceDevices.current?'개별 가상 디바이스로 집계하지 않는 시스템·애플리케이션 컨테이너입니다. 서비스 제어기가 관리하는 실행 배치는 제외하며, 상주 모델 서버 같은 공용 기반 컨테이너는 남을 수 있습니다.':'가상 디바이스 등록 정보를 확인할 수 없어 아래 항목의 등록 여부는 확인 불가입니다.'}</p>${selected?.startsWith('workload:')?detail(m,selected,opened):''}<div id="dm-workload-scroll" class="dm-scroll" data-dm-scroll="workloads" role="region" aria-label="기타 워크로드 목록" tabindex="0"><div class="dm-list-head" aria-hidden="true"><span>워크로드 / Namespace</span><span>실행 상태</span><span>실행 위치</span></div><div class="dm-grid dm-workload-grid">${workloads.map(p=>workloadCard(p,m,selected)).join('')}</div>${!workloads.length?'<p class="dm-empty">표시할 기타 워크로드가 없습니다. 검색과 관측 상태를 확인하세요.</p>':''}</div></details>
 <details class="dm-glossary" data-dm-disclosure="terms" ${opened.has('terms')?'open':''}><summary>이 페이지의 용어 안내</summary><dl><dt>물리 디바이스</dt><dd>실제 하드웨어입니다. 엣지·워커·서버는 컴퓨팅 노드, 센서·PLC·카메라 등은 연결 장비입니다. 센서 목록은 EdgeX에 등록한 디바이스별로 한 행씩 표시하며, 같은 장비에 연결되어 있어도 합치지 않습니다.</dd><dt>가상 디바이스</dt><dd>컨테이너 기반의 기능 실행 단위로 등록한 대상입니다. 실행이 멈춰도 등록 정의는 남습니다.</dd><dt>실행체(Pod)</dt><dd>실제로 배치된 Kubernetes 실행 단위입니다. 하나의 Pod에 여러 컨테이너가 포함될 수 있습니다.</dd><dt>기타 워크로드</dt><dd>개별 가상 디바이스로 집계하지 않는 시스템·애플리케이션 컨테이너입니다. 공용 기반 컨테이너가 서비스 실행을 지원할 수 있지만, Pod가 존재한다는 이유만으로 별도 가상 디바이스가 되지는 않습니다.</dd><dt>실행 위치 / 설정 위치</dt><dd>실행 위치는 실제 Pod가 관측된 노드입니다. 설정 위치는 등록 조건에 지정한 노드이며, 그곳에서 실행 중이라는 뜻은 아닙니다.</dd><dt>EdgeX 등록 항목 / 관측 트윈</dt><dd>EdgeX 등록 항목은 장비의 기능별 등록 정보입니다. 관측 트윈은 이 등록 정보와 최신 측정값을 합친 조회용 표현입니다.</dd></dl></details><p class="dm-footnote">노드 준비, 실행체 준비, 모델 준비, 요청 처리 상태는 각각 따로 확인합니다.</p></div>`;
}
function workloads(entries,{query='',selected=null,opened=new Set()}={},now=Date.now()){
 const m=model(entries,now),q=query.trim().toLocaleLowerCase();
 const registeredKeys=new Set(m.virtual.resources.map(runtimeKey));
 for(const d of m.serviceDevices.rows)for(const l of d.locations)if(!l.resident&&d.namespace)registeredKeys.add(d.namespace+'/'+l.revision);
 const allWorkloads=m.profiles.filter(p=>!registeredKeys.has(workloadKey(p)));
 const workloads=allWorkloads.filter(p=>JSON.stringify(p).toLocaleLowerCase().includes(q));
 const listCount=(shown,total)=>(total==null?'전체 수 확인 불가':'총 '+total+'개')+(q?' · 검색 결과 '+shown+'개':'');
 return `<details class="dm-workloads-section" data-dm-disclosure="workloads" ${opened.has('workloads')||selected?.startsWith('workload:')?'open':''}><summary>기타 워크로드 <span class="dm-count">${listCount(workloads.length,m.valid.profiles&&m.valid.virtual&&m.serviceDevices.current?allWorkloads.length:null)}</span></summary><p class="dm-footnote">${m.valid.virtual&&m.serviceDevices.current?'개별 가상 디바이스로 집계하지 않는 시스템·애플리케이션 컨테이너입니다. 서비스 제어기가 관리하는 실행 배치는 제외하며, 상주 모델 서버 같은 공용 기반 컨테이너는 남을 수 있습니다.':'가상 디바이스 등록 정보를 확인할 수 없어 아래 항목의 등록 여부는 확인 불가입니다.'}</p>${selected?.startsWith('workload:')?detail(m,selected,opened):''}<div id="dm-workload-scroll" class="dm-scroll" data-dm-scroll="workloads" role="region" aria-label="기타 워크로드 목록" tabindex="0"><div class="dm-list-head" aria-hidden="true"><span>워크로드 / Namespace</span><span>실행 상태</span><span>실행 위치</span></div><div class="dm-grid dm-workload-grid">${workloads.map(p=>workloadCard(p,m,selected)).join('')}</div>${!workloads.length?'<p class="dm-empty">표시할 기타 워크로드가 없습니다. 검색과 관측 상태를 확인하세요.</p>':''}</div></details>`;
}
const api={model,render,workloads,serviceView,rememberScroll,restoreScroll,resetScroll};if(typeof module!=='undefined')module.exports=api;root.NexusDeviceMap=api;
})(typeof window!=='undefined'?window:globalThis);
