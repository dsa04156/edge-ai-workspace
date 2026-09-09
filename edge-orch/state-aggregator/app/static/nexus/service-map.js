/* Read-only placement map. Running Pod snapshots are not execution ownership or migration events. */
(function(root){
'use strict';
const paths={profiles:'/state/service-resource-profiles',services:'/state/services',resources:'/api/resources',devices:'/state/devices',demo:'/state/service-demo'};
const E=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const key=p=>p.namespace+'/'+p.service;
const recent=(time,now=Date.now())=>Number.isFinite(Date.parse(time))&&now-Date.parse(time)>=-5000&&now-Date.parse(time)<90000;
const fresh=(entry,now=Date.now())=>Boolean(entry?.data&&!entry.error&&now-entry.receivedAt<90000);
const num=(v,d=1)=>typeof v==='number'&&Number.isFinite(v)?v.toFixed(d):'—';
const clock=t=>t?new Date(t).toLocaleTimeString('ko-KR',{hour12:false}):'—';
const names={healthy:'정상',degraded:'주의',unhealthy:'장애',unknown:'확인 불가',fresh:'최신',stale:'오래됨',ready:'준비됨',warming_up:'준비 중',STANDBY:'대기',SHADOW:'검증 대기',ACTIVE:'실행 권한 활성'};
const label=v=>names[v]||v||'확인 불가';
function validate(k,d){
 const rows=k==='profiles'?d?.service_resource_profiles:k==='services'?d?.services:k==='demo'?null:d;
 if(k==='demo'){if(!d||typeof d!=='object'||!d.inference_routing)throw Error('서비스 실행 응답 형식 확인 필요');}
 else if(!Array.isArray(rows)||rows.some(x=>!x||typeof x!=='object'||(k==='profiles'?(typeof x.namespace!=='string'||typeof x.service!=='string'||!Array.isArray(x.nodes)):typeof x[k==='services'?'service_id':k==='resources'?'node':'name']!=='string')))throw Error('배치 관측 응답 형식 확인 필요');
 return d;
}
function associations(services,devices){
 const out=new Map();
 const add=(id,s,role,title)=>{const a=out.get(id);if(a){if(!a.services.some(x=>x.service_id===s.service_id))a.services.push(s);if(a.services.length>1)a.title=(role==='remote'?'공유 서버 추론':'공유 실행체')+' · 서비스 '+a.services.length+'개';}else out.set(id,{service:s,services:[s],role,title});};
 for(const s of services){
  const w=s.descriptor?.workload;if(w)add(w.namespace+'/'+w.name,s,'service',s.display_name);
  const r=s.descriptor?.runtime_offloading?.target_workload;if(r)add(r.namespace+'/'+r.name,s,'remote','서버 추론 · '+s.display_name);
 }
 // Device Service names come from EdgeX; namespace is the approved edge collection boundary.
 for(const d of devices)if(d.device_service_name){const id='edgex-edge/'+d.device_service_name;if(!out.has(id))out.set(id,{role:'source',title:d.device_service_name,sources:[]});const a=out.get(id);if(a.role==='source'&&d.physical_device_id&&!a.sources.includes(d.physical_device_id))a.sources.push(d.physical_device_id);}
 return out;
}
function serviceDevices(service,devices){
 const names=new Set(service.input_devices||service.design_contract?.inputs?.map(x=>x.device_name)||[]);
 return devices.filter(d=>names.has(d.name)||(!names.size&&service.device_service&&d.device_service_name===service.device_service&&(!service.physical_source||d.physical_device_id===service.physical_source)));
}
function serviceKeys(service,devices){
 if(!service)return new Set();
 const keys=new Set(),w=service.descriptor?.workload,r=service.descriptor?.runtime_offloading?.target_workload;
 if(w?.namespace&&w?.name)keys.add(w.namespace+'/'+w.name);
 if(r?.namespace&&r?.name)keys.add(r.namespace+'/'+r.name);
 for(const d of serviceDevices(service,devices))if(d.device_service_name)keys.add('edgex-edge/'+d.device_service_name);
 return keys;
}
function scopedProfiles(service,devices,profiles){const keys=serviceKeys(service,devices);return profiles.filter(p=>keys.has(key(p)));}
function placements(profiles){return new Map(profiles.map(p=>[key(p),[...new Set(p.nodes)].sort()]));}
function changes(before,after){
 if(!before)return [];
 const out=[];
 for(const [id,nodes] of after){const prev=before.get(id);if(!prev)out.push({id,text:'Running 목록에 나타남',to:nodes});else if(JSON.stringify(prev)!==JSON.stringify(nodes))out.push({id,text:'배치 관측 변경',from:prev,to:nodes});}
 for(const [id,nodes] of before)if(!after.has(id))out.push({id,text:'Running 목록에서 사라짐',from:nodes,to:[]});
 return out;
}
function execution(s,valid){
 if(!valid||s?.mode!=='live'||s?.observation_error)return {text:'처리 상태 확인 불가',tone:'unknown'};
 const o=s.execution_ownership;
 if(o?.enabled&&o.lease_valid===false)return {text:'대기 · 실행 권한 없음',tone:'warn'};
 if(o?.effective_mode&&o.effective_mode!=='ACTIVE')return {text:label(o.effective_mode),tone:'warn'};
 return {text:'서비스 '+label(s.status),tone:s.status==='healthy'?'ok':'warn'};
}
function routeState(d,valid,now=Date.now()){
 const r=d?.inference_routing;
 if(!valid||!r||!recent(r.observed_at,now)||d.mode!=='live'||d.observation_error)return {mode:'UNKNOWN',text:'추론 경로 확인 불가',canFlow:false};
 const owner=d.execution_ownership;
 const canFlow=['LOCAL','REMOTE','LOCAL_FALLBACK'].includes(r.inference_mode)&&d.input_state==='fresh'&&d.model_state==='ready'&&(!owner?.enabled||(owner.lease_valid===true&&owner.effective_mode==='ACTIVE'));
 return {mode:r.inference_mode||'UNKNOWN',text:r.inference_mode==='REMOTE'?'서버 추론 경로':r.inference_mode==='LOCAL_FALLBACK'?'로컬 복귀 경로':r.inference_mode==='LOCAL'?'로컬 추론 경로':'추론 경로 확인 불가',canFlow};
}
function advance(before,after,now=Date.now()){
 // Only a newer, fresh saved result is evidence for a finite pulse, never a looping traffic rate.
 if(!before||!after||!recent(after.latest?.observed_at,now))return false;
 const route=routeState(after,true,now),mode=String(after.latest.execution_mode||'').toUpperCase();
 const samePath=route.mode==='REMOTE'?mode==='REMOTE':mode==='LOCAL'||mode==='LOCAL_FALLBACK';
 return Date.parse(after.latest.observed_at)>Date.parse(before.latest?.observed_at)&&route.canFlow&&samePath;
}
const entries=Object.fromEntries(Object.keys(paths).map(k=>[k,{data:null,error:null,receivedAt:0}]));
let serviceSelection=null,viewMode='graph',graphZoom=1,graphScroll={left:0,top:0};
let pending=null,selected=null,contextService=null,scope='linked',showEmpty=false,example=false,step=0,playing=false,lastExampleTick=0;
const disclosures=new Set();let watchedService=null,highlightResults=true;const observationLog=[];let observationPrevious=new Map();const graphFlashes=new Map();
let previous=null,events=[],pulseUntil=0,changedUntil=new Map(),lastCycle=0,installed=false;
const scenarios=[
 {title:'현장에서 처리',note:'예시 엣지 A가 수집·전처리·추론·저장을 수행합니다.',mode:'LOCAL',node:'예시 엣지 A'},
 {title:'서버 자원으로 추론',note:'수집과 저장은 유지하고 추론 요청·결과만 서버를 오갑니다.',mode:'REMOTE',node:'예시 엣지 A'},
 {title:'서버 장애 · 로컬 복귀',note:'서버 호출 실패 후 현장 추론 경로로 복귀하는 예시입니다.',mode:'LOCAL_FALLBACK',node:'예시 엣지 A'},
 {title:'실행 위치 전환',note:'새 위치의 준비와 실행 권한 전환이 확인된 상황을 가정합니다.',mode:'LOCAL',node:'예시 엣지 B'}
];
function sample(){
 const x=scenarios[step],now=new Date().toISOString();
 const svc={service_id:'example-anomaly',display_name:'예시 이상감지 서비스',mode:'live',status:'healthy',input_state:'fresh',model_state:'ready',model_version:'example-model',physical_source:'예시 센서',input_devices:['example-input'],execution_ownership:{enabled:true,lease_valid:true,effective_mode:'ACTIVE'},descriptor:{workload:{namespace:'example',name:'edge-analysis'},runtime_offloading:{target_workload:{namespace:'example',name:'server-inference'}},augmentation_qualification:{status:'example'}}};
 const profiles=[{namespace:'example',service:'edge-analysis',nodes:[x.node],pods_by_node:{[x.node]:1},pod_count:1,ready_pod_count:1,current_usage:{}},{namespace:'example',service:'server-inference',nodes:['예시 서버'],pods_by_node:{'예시 서버':1},pod_count:1,ready_pod_count:step===2?0:1,current_usage:{}}];
 const resources=['예시 엣지 A','예시 엣지 B','예시 서버'].map(node=>({node,nodeType:node==='예시 서버'?'cloud_server':'edge_device',health:'healthy',utilization:{}}));
 const demo={mode:'live',input_state:'fresh',model_state:'ready',execution_ownership:svc.execution_ownership,inference_routing:{inference_mode:x.mode,observed_at:now,source_node:x.node,remote_node:'예시 서버'},latest:{observed_at:now,source_node:x.node,remote_node:'예시 서버',execution_mode:x.mode==='REMOTE'?'remote':'local',model_version:'example-model'},performance:{metrics_valid:false}};
 return {profiles,services:[svc],resources,devices:[{name:'example-input',physical_device_id:'예시 센서',node_name:x.node,device_service_name:'example-collector'}],demo,valid:{profiles:true,services:true,resources:true,devices:true,demo:true}};
}
function data(){if(example)return sample();return {profiles:entries.profiles.data?.service_resource_profiles||[],services:entries.services.data?.services||[],resources:entries.resources.data||[],devices:entries.devices.data||[],demo:entries.demo.data,valid:Object.fromEntries(Object.entries(entries).map(([k,e])=>[k,fresh(e)&&(!['profiles','services'].includes(k)||recent(e.data?.generated_at))]))};}
async function refresh(){
 if(pending||example)return pending;
 pending=Promise.all(Object.entries(paths).map(async([k,url])=>{const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),12000),entry=entries[k];try{
  const res=await root.fetch(url,{method:'GET',cache:'no-store',headers:{Accept:'application/json'},signal:abort.signal});if(!res.ok)throw Error('HTTP '+res.status);
  const d=validate(k,await res.json()),now=Date.now();
  if(k==='profiles'){
   // Generated timestamps must progress. API receipt alone must not fabricate a placement event.
   if(recent(d.generated_at,now)&&(!entry.data||Date.parse(d.generated_at)>Date.parse(entry.data.generated_at))){
    const next=placements(d.service_resource_profiles);
    if(fresh(entry,now))for(const event of changes(previous,next)){events.unshift({...event,time:now});changedUntil.set(event.id,now+4000);}
    previous=next;events=events.slice(0,24);
   }
  }
  if(k==='demo'&&fresh(entry,now)&&advance(entry.data,d,now))pulseUntil=now+2400;
  entry.data=d;entry.error=null;entry.receivedAt=now;
 }catch(error){entry.error=error.name==='AbortError'?'요청 시간 초과':error.message;}finally{clearTimeout(timer);}})).finally(()=>{pending=null;lastCycle=Date.now();observeRuntime();paint();});
 paint();return pending;
}
const nodeTitle=n=>({'etri-dev0001-jetorn':'Jetson 01','etri-dev0002-raspi5':'Raspberry Pi 02','etri-dev0003-raspi5':'Raspberry Pi 03','etri-dev0004-tedger':'Tinker Edge R','etri-dev0005-jetagx':'Jetson AGX','etri-ser0001-cg0msb':'서버 01','etri-ser0002-cgnmsb':'서버 02'}[n]||n);
const cardTitle=(p,a)=>a?.role==='source'?(a.sources.includes('arduino-001')?'Arduino 센서 수집':a.sources.includes('sensehat-001')?'Sense HAT 센서 수집':a.title):a?.role==='remote'&&a.services.length===1?'서버 추론':a?.title||p.service;
function pill(text,tone=''){return `<span class="sm-pill ${tone}">${E(text)}</span>`;}
function usage(r,valid){const u=r?.utilization||{},ok=valid&&recent(u.observedAt);return `<div class="sm-util"><span>CPU <b>${ok?num(typeof u.cpuRatio==='number'?u.cpuRatio*100:null,0):'—'}%</b></span><span>메모리 <b>${ok?num(typeof u.memoryRatio==='number'?u.memoryRatio*100:null,0):'—'}%</b></span></div>`;}
function card(p,node,a,d){
 const isSelected=selected===key(p),valid=d.valid.profiles&&recent(p.generated_at||entries.profiles.data?.generated_at)||example;
 const ready=valid&&p.ready_pod_count===p.pod_count&&p.pod_count>0;
 const podText=!valid?'Pod 관측 확인 불가':ready?'Pod 준비됨':p.nodes.length===1?`Pod 준비 ${p.ready_pod_count}/${p.pod_count}`:`전체 Pod 준비 ${p.ready_pod_count}/${p.pod_count}`;
 const appState=a?.role==='service'?(a.services.length>1?{text:'서비스별 상태 확인',tone:'unknown'}:execution(a.service,d.valid.services)):null;
 const selectedLink=associations(d.services,d.devices).get(selected);
 const related=selected&&a?.services?.some(s=>selectedLink?.services?.some(x=>x.service_id===s.service_id));
 return `<button class="sm-card ${isSelected?'selected':''} ${related?'related':''} ${a?.role||'workload'} ${!example&&changedUntil.get(key(p))>Date.now()?'changed':''}" data-sm-select="${E(key(p))}" data-sm-node="${E(node)}" aria-pressed="${isSelected}"><span class="sm-card-top"><span>${E(a?.role==='service'?'AI 서비스':a?.role==='remote'?'증강 실행체':a?.role==='source'?'센서 수집':'워크로드')}</span><span>${E(p.pods_by_node?.[node]??'—')} Pod</span></span><strong>${E(cardTitle(p,a))}</strong><span class="sm-card-status">${pill(podText,valid?(ready?'ok':'warn'):'unknown')}${appState?pill(appState.text,appState.tone):''}</span></button>`;
}
function sourceGroups(devices){
 const groups=new Map();for(const d of devices){if(!d.physical_device_id)continue;let g=groups.get(d.physical_device_id);if(!g){g={id:d.physical_device_id,nodes:[],devices:[]};groups.set(g.id,g);}if(d.node_name&&!g.nodes.includes(d.node_name))g.nodes.push(d.node_name);g.devices.push(d);}return [...groups.values()];
}
function sourcePanel(g,d){const services=d.services.filter(s=>serviceDevices(s,g.devices).length);return `<div class="sm-equipment-source"><small>물리 입력 장비</small><strong>${E(g.id)}</strong><span>${d.valid.devices?'EdgeX 등록 기능 '+g.devices.length+'개':'등록 관측 확인 불가'}</span>${services.map(s=>`<button class="text-button" data-sm-service="${E(s.service_id)}">${E(s.display_name)} 보기 ↗</button>`).join('')||`<span>${d.valid.services?'연결된 등록 서비스 없음':'서비스 연결 확인 불가'}</span>`}</div>`;}
function nodePanel(r,ps,links,d){const overview=!example&&serviceSelection==='*';const sources=overview?sourceGroups(d.devices).filter(g=>g.nodes.length===1&&g.nodes[0]===r.node):[];const services=overview?d.services.filter(s=>d.profiles.some(p=>p.nodes.includes(r.node)&&serviceKeys(s,d.devices).has(key(p)))):[];return `<article class="sm-node"><header><div><span class="sm-node-icon" aria-hidden="true">${r.nodeType==='cloud_server'?'▤':'▣'}</span><div><h3>${E(nodeTitle(r.node))}</h3><small class="sm-node-id">${E(r.node)}</small></div></div>${pill(d.valid.resources?label(r.health):'관측 확인 불가',d.valid.resources&&r.health==='healthy'?'ok':'unknown')}</header>${usage(r,d.valid.resources)}${sources.length?`<div class="sm-node-sources">${sources.map(g=>sourcePanel(g,d)).join('')}</div>`:''}<div class="sm-node-apps">${ps.map(p=>card(p,r.node,links.get(key(p)),d)).join('')||'<p class="sm-vacant">이 필터의 Running 워크로드 없음</p>'}</div>${services.length?`<div class="sm-node-services">${services.map(s=>`<button class="text-button" data-sm-service="${E(s.service_id)}">${E(s.display_name)} 보기 ↗</button>`).join('')}</div>`:''}</article>`;}
function flow(s,d){
 const isDemo=example||s.service_id==='sensor-anomaly-demo';
 const ds=isDemo?d.demo:null,rs=routeState(ds,d.valid.demo);
 const local=s.descriptor?.workload,remote=s.descriptor?.runtime_offloading?.target_workload;
 const lp=d.profiles.find(p=>key(p)===local?.namespace+'/'+local?.name),rp=d.profiles.find(p=>key(p)===remote?.namespace+'/'+remote?.name);
 const localNode=lp?.nodes.map(nodeTitle).join(', ')||'실행 위치 미관측',remoteNode=rp?.nodes.map(nodeTitle).join(', ')||'서버 위치 미관측';
 const remoteActive=rs.mode==='REMOTE'&&rs.canFlow;
 const pulse=(example||(pulseUntil>Date.now()))&&rs.canFlow;
 const q=s.descriptor?.augmentation_qualification?.status;
 return `<section class="sm-flow ${pulse?'pulse':''} ${remoteActive?'remote-active':''}"><div class="sm-section-title"><div><span class="eyebrow">선택한 서비스</span><h3 id="sm-detail-heading" tabindex="-1">${E(s.display_name)}</h3></div>${pill(rs.text,rs.mode==='UNKNOWN'?'unknown':'')}</div><div class="sm-flow-grid"><div class="sm-flow-box source"><small>입력 장비</small><strong>${E(s.physical_source||'물리 source 미지정')}</strong><span>${d.valid.services?'입력 '+E(label(s.input_state)):'입력 확인 불가'}</span></div><div class="sm-hop ${pulse?'observed-pulse':''}" aria-hidden="true">→</div><div class="sm-flow-box edge"><small>전처리 · 결과 저장 / ${rs.mode==='REMOTE'?'원격 요청':'로컬 추론'}</small><strong>${E(localNode)}</strong><span>${E(execution(s,d.valid.services).text)}</span></div>${remote?`<div class="sm-exchange ${remoteActive?'active':''}"><span>추론 요청 ↓</span><i class="sm-packet outbound" aria-hidden="true"></i><i class="sm-packet inbound" aria-hidden="true"></i><span>↑ 결과 반환</span></div><div class="sm-flow-box remote"><small>서버 추론</small><strong>${E(remoteNode)}</strong><span>${remoteActive?'원격 경로 활성':rs.mode==='LOCAL_FALLBACK'?'로컬 복귀 관측':q==='rejected'?'성능 자격 미통과':'증강 후보 · 사용 여부 별도 확인'}</span></div>`:''}</div><p class="sm-caption">${example?'설명용 예시 · 실제 장비 변경 없음':rs.canFlow?'최신 처리 결과가 들어오면 경로를 짧게 강조합니다.':'현재 처리 흐름 미확인 · 연결 구조를 표시합니다.'}</p></section>`;
}
// Graph edges are contracts until fresh routing identifies both endpoints.
function graphRoute(s,d,from,to){
 const ds=s.service_id==='sensor-anomaly-demo'||s.service_id==='example-anomaly'&&example?d.demo:null;
 const rs=routeState(ds,d.valid.demo),r=ds?.inference_routing;
 const owner=s.execution_ownership;const ownerValid=!owner?.enabled||(owner.lease_valid===true&&owner.effective_mode==='ACTIVE');
 const valid=d.valid.services&&d.valid.profiles&&s.mode==='live'&&!s.observation_error&&ownerValid&&rs.canFlow;
 const active=Boolean(valid&&rs.mode==='REMOTE'&&r.source_node===from&&r.remote_node===to);
 const fallback=Boolean(valid&&rs.mode==='LOCAL_FALLBACK'&&r.source_node===from);
 return {active,fallback,text:active?'원격 추론 관측':fallback?'로컬 복귀 · 서버 경로 비활성':'설정된 서버 경로 · 사용 미확인'};
}
function graphModel(d,services,visible,profiles,allSources=false){
 const nodes=visible.map(r=>({id:'node:'+r.node,title:nodeTitle(r.node),kind:r.nodeType==='cloud_server'?'server':'edge',resource:r,profiles:profiles.filter(p=>p.nodes.includes(r.node))}));
 const sourceData=allSources?d.devices:d.devices.filter(x=>services.some(s=>serviceDevices(s,[x]).length));
 const groups=sourceGroups(sourceData),edges=[];
 for(const g of groups){nodes.push({id:'source:'+g.id,title:g.id,kind:'source',group:g});if(g.nodes.length===1&&nodes.some(n=>n.id==='node:'+g.nodes[0]))edges.push({from:'source:'+g.id,to:'node:'+g.nodes[0],kind:'input',text:'등록 수집 연결',active:false});}
 const find=w=>profiles.find(p=>key(p)===w?.namespace+'/'+w?.name)?.nodes||[];
 for(const s of services){const local=find(s.descriptor?.workload),remote=find(s.descriptor?.runtime_offloading?.target_workload);
  for(const from of local)for(const to of remote){if(from===to)continue;const state=graphRoute(s,d,from,to);edges.push({from:'node:'+from,to:'node:'+to,kind:'request',service:s,...state});edges.push({from:'node:'+to,to:'node:'+from,kind:'response',service:s,...state});}
 }
 return {nodes,edges};
}
function runtimeObservation(s,d,now=Date.now()){
 const valid=Boolean(d.valid.services&&s.mode==='live'&&!s.observation_error);
 const ds=s.service_id==='sensor-anomaly-demo'||example&&s.service_id==='example-anomaly'?d.demo:null;
 const r=routeState(ds,d.valid.demo,now),owner=s.execution_ownership;
 const ownerValid=!owner?.enabled||(owner.lease_valid===true&&owner.effective_mode==='ACTIVE');
 const w=s.descriptor?.workload,p=d.profiles.find(x=>key(x)===w?.namespace+'/'+w?.name);
 const profileValid=Boolean(d.valid.profiles&&p&&(!p.generated_at||recent(p.generated_at,now)));
 const latest=ds?.latest,resultAt=latest?.observed_at||s.latest_observed_at;
 const path=ds?.inference_routing,executionMode=String(latest?.execution_mode||'').toUpperCase();
 const routeMatches=r.mode==='REMOTE'?executionMode==='REMOTE'&&latest?.remote_node===path?.remote_node:['LOCAL','LOCAL_FALLBACK'].includes(executionMode);
 const modelMatches=!s.model_version||latest?.model_version===s.model_version;
 const endpoints=Boolean(path?.source_node&&latest?.source_node===path.source_node&&p?.nodes.includes(path.source_node));
 const target=s.descriptor?.runtime_offloading?.target_workload,targetProfile=d.profiles.find(x=>key(x)===target?.namespace+'/'+target?.name);
 const remoteMatches=r.mode!=='REMOTE'||Boolean(path?.remote_node&&targetProfile?.nodes.includes(path.remote_node));
 const confirmed=Boolean(valid&&profileValid&&ownerValid&&r.canFlow&&recent(resultAt,now)&&routeMatches&&modelMatches&&endpoints&&remoteMatches);
 let text='처리 관측 확인 불가',reason='현재 서비스 실행 관측을 확인할 수 없습니다.',tone='unknown';
 if(valid){if(!ownerValid){text='대기 · 실행 권한 없음';reason='실행 권한이 만료됐거나 활성 소유자가 아닙니다.';tone='warn';}
 else if(s.input_state!=='fresh'){text='입력 대기';reason='서비스 입력이 최신 상태가 아닙니다.';tone='warn';}
 else if(s.model_state!=='ready'){text='모델 준비 중';reason='추론 모델 준비가 확인되지 않았습니다.';tone='warn';}
 else if(confirmed){text='최근 처리 확인';reason=r.mode==='REMOTE'?'서버에서 처리한 최신 저장 결과를 확인했습니다.':'현장에서 처리한 최신 저장 결과를 확인했습니다.';tone='ok';}
 else {text='새 처리 결과 미확인';reason='준비 상태와 실제 처리 결과를 구분해 관측합니다.';}}
 const perf=confirmed&&d.valid.demo&&ds?.performance?.metrics_valid?ds.performance:null;
 return {id:s.service_id,name:s.display_name,valid,observationValid:Boolean(valid&&d.valid.demo&&profileValid),atTime:now,confirmed,text,reason,tone,resultAt,mode:r.canFlow&&ownerValid?r.mode:'UNKNOWN',source:path?.source_node,remote:path?.remote_node,running:profileValid?p.pod_count:null,ready:profileValid?p.ready_pod_count:null,latency:perf?.processing_latency_p95_ms,rate:perf?.throughput_per_second};
}
function runtimeChanges(before,after){
 if(!before?.valid||!after.valid||!before.observationValid||!after.observationValid||after.atTime-before.atTime>=90000)return [];
 const changes=[];if(after.confirmed&&Date.parse(after.resultAt)>Date.parse(before.resultAt))changes.push({kind:'result',text:'새 처리 결과 관측',at:after.resultAt});
 if(before.text!==after.text)changes.push({kind:'state',text:before.text+' → '+after.text});
 if(before.mode!==after.mode&&after.mode!=='UNKNOWN')changes.push({kind:'route',text:'추론 경로 관측: '+after.mode});
 return changes;
}
function observeRuntime(){
 if(example)return;const d=data(),next=new Map();
 for(const s of d.services){const o=runtimeObservation(s,d);next.set(s.service_id,o);for(const change of runtimeChanges(observationPrevious.get(s.service_id),o)){observationLog.unshift({...change,id:s.service_id,name:s.display_name,time:Date.now()});if(change.kind==='result')graphFlashes.set(s.service_id,{until:Date.now()+2200,at:o.resultAt});}}
 observationPrevious=next;observationLog.splice(18);
}
function runtimePanel(d,services){
 const picked=services.find(s=>s.service_id===watchedService)||services[0];if(!picked)return '';
 const current=runtimeObservation(picked,d),logs=example?[]:observationLog.filter(e=>e.id===picked.service_id);
 return `<section class="sm-live-panel" aria-label="현재 실행 관측"><header><div><h2>현재 실행 관측</h2><p>${example?'설명용 예시 데이터':'15초 간격 관측 · 새 결과가 확인될 때만 경로 강조'}</p></div><button class="button" id="sm-highlight" data-sm-action="highlight" aria-pressed="${highlightResults}">결과 강조 ${highlightResults?'켜짐':'꺼짐'}</button></header><div class="sm-live-services">${services.map(s=>{const o=runtimeObservation(s,d);return `<button data-sm-watch="${E(s.service_id)}" aria-pressed="${picked.service_id===s.service_id}"><strong>${E(s.display_name)}</strong>${pill(o.text,o.tone)}<span>실행체 ${o.running??'—'} · 준비 ${o.ready??'—'}</span></button>`;}).join('')}</div><div class="sm-live-current"><p role="status"><strong>${E(current.text)}</strong> ${E(current.reason)}</p><dl><div><dt>마지막 저장 결과</dt><dd>${current.resultAt?E(new Date(current.resultAt).toLocaleString('ko-KR')):'관측 없음'}</dd></div><div><dt>유효한 추론 경로</dt><dd>${E(current.mode==='REMOTE'?'서버 추론':current.mode==='LOCAL_FALLBACK'?'로컬 복귀':current.mode==='LOCAL'?'로컬 추론':'처리 경로 미확인')}</dd></div><div><dt>지연 p95 / 처리량</dt><dd>${num(current.latency)} ms / ${num(current.rate)} 건/s</dd></div></dl></div><details class="sm-live-log" data-sm-disclosure="runtime-log" ${disclosures.has('runtime-log')?'open':''}><summary>최근 실행 관측 <span>${logs.length}건 · 이 화면을 연 이후</span></summary>${logs.length?`<ol>${logs.slice(0,8).map(e=>`<li><time>${E(clock(e.time))}</time><span>${E(e.text)}</span></li>`).join('')}</ol>`:'<p>새로 관측된 변화가 없습니다. 첫 조회와 과거 저장 결과는 새 처리 이벤트로 만들지 않습니다.</p>'}</details></section>`;
}
function flashDelay(id){return example||!graphFlashes.has(id)?'0s':Math.min(0,((graphFlashes.get(id)?.until||0)-Date.now()-2200)/1000)+'s';}
function graphPanel(d,services,visible,profiles,links){
 const m=graphModel(d,services,visible,profiles,!example&&serviceSelection==='*'),columns=['source','edge','server'],positions=new Map();
 const cardWidth=240,gapY=280;
 columns.forEach((kind,col)=>m.nodes.filter(n=>n.kind===kind).forEach((n,i)=>positions.set(n.id,{x:20+col*420,y:64+i*gapY})));
 const height=Math.max(360,...columns.map(k=>m.nodes.filter(n=>n.kind===k).length*gapY+64));
 // Three columns use a wider canvas; native scroll and zoom preserve legible labels.
 const canvasWidth=1120;
 const edgePaths=m.edges.map((e,i)=>{const a=positions.get(e.from),b=positions.get(e.to);if(!a||!b)return '';const forward=b.x>a.x,offset=e.kind==='response'?30:0,x1=a.x+(forward?cardWidth:0),x2=b.x+(forward?0:cardWidth),y1=a.y+82+offset,y2=b.y+82+offset;
 const dx=Math.max(60,Math.abs(x2-x1)/2),path=a.x===b.x?`M ${a.x+cardWidth} ${y1} C ${a.x+cardWidth+120} ${y1}, ${b.x+cardWidth+120} ${y2}, ${b.x+cardWidth} ${y2}`:`M ${x1} ${y1} C ${x1+(forward?dx:-dx)} ${y1}, ${x2+(forward?-dx:dx)} ${y2}, ${x2} ${y2}`;
 const mode=e.active?'active':e.fallback?'fallback':'configured';const o=e.service?runtimeObservation(e.service,d):null;const flash=highlightResults&&o?.confirmed&&(example||graphFlashes.get(e.service.service_id)?.until>Date.now());
 return `<g class="sm-graph-edge ${mode} ${flash?'result-flash':''} ${watchedService&&e.service?.service_id===watchedService?'watched':''}" data-graph-edge="${E(e.kind)}" style="--sm-flash-delay:${flashDelay(e.service?.service_id)}"><title>${E(e.service?.display_name||'물리 입력')} · ${E(e.text)}</title><path d="${path}" marker-end="url(#sm-arrow-${mode})"/><text x="${a.x===b.x?a.x+cardWidth+90:(x1+x2)/2}" y="${(y1+y2)/2-8}" text-anchor="middle">${E(e.kind==='input'?'수집 연결':e.kind==='request'?'추론 요청 →':'← 결과 반환')}</text></g>`;}).join('');
 const items=m.nodes.map(n=>{const p=positions.get(n.id),flashing=services.find(s=>{const o=runtimeObservation(s,d);return highlightResults&&o.confirmed&&o.source===n.resource?.node&&(example||graphFlashes.get(s.service_id)?.until>Date.now());});return `<article class="sm-graph-node ${n.kind} ${flashing?'result-flash':''}" style="left:${p.x}px;top:${p.y}px;width:${cardWidth}px;--sm-flash-delay:${flashDelay(flashing?.service_id)}"><small>${E(n.kind==='source'?'물리 입력 장비':n.kind==='server'?'추론·공용 서버':'현장 엣지')}</small><h3>${E(n.title)}</h3>${n.kind==='source'?`<span>${d.valid.devices?'EdgeX 등록 기능 '+n.group.devices.length+'개':'장비 관측 확인 불가'}</span>${n.group.nodes.length!==1?'<span>연결 노드 확인 필요</span>':''}${services.filter(s=>serviceDevices(s,n.group.devices).length).map(s=>`<button data-sm-service="${E(s.service_id)}" ${example?'disabled':''}>${E(s.display_name)} ↗</button>`).join('')}`:`<span>${E(d.valid.resources?label(n.resource.health):'노드 관측 확인 불가')} · ${d.valid.profiles?n.profiles.length:'—'}개 워크로드</span>${n.profiles.slice(0,2).map(w=>`<button data-sm-select="${E(key(w))}" data-sm-node="${E(n.resource.node)}" aria-pressed="${selected===key(w)}">${E(cardTitle(w,links.get(key(w))))} ↗</button>`).join('')}${n.profiles.length>2?`<small>외 ${n.profiles.length-2}개 · 장비 카드에서 확인</small>`:''}`}</article>`;}).join('');
 const routes=m.edges.filter(e=>e.kind==='request');
 return `${runtimePanel(d,services)}<section class="sm-graph" aria-label="장비 연결과 오프로딩 그래프"><header><div><h2>장비 연결 · 오프로딩</h2><p>입력 장비 → 현장 처리 → 서버 추론</p></div><div class="sm-graph-zoom"><button class="button" id="sm-zoom-out" data-sm-zoom="-1" aria-label="그래프 축소" ${graphZoom<=.5?'disabled':''}>−</button><button class="button" id="sm-zoom-reset" data-sm-zoom="0">${Math.round(graphZoom*100)}%</button><button class="button" id="sm-zoom-in" data-sm-zoom="1" aria-label="그래프 확대" ${graphZoom>=1.5?'disabled':''}>+</button></div></header><div class="sm-graph-key"><span class="active">실선: 원격 경로 관측</span><span>점선: 등록·설정 연결</span><span class="fallback">주황 점선: 로컬 복귀</span></div><div class="sm-graph-scroll" tabindex="0" role="region" aria-label="연결 그래프, 가로·세로 스크롤 가능"><div style="width:${canvasWidth*graphZoom}px;height:${height*graphZoom}px"><div class="sm-graph-stage" style="width:${canvasWidth}px;height:${height}px;transform:scale(${graphZoom})"><svg width="${canvasWidth}" height="${height}" aria-hidden="true"><defs>${['active','configured','fallback'].map(mode=>`<marker id="sm-arrow-${mode}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M 0 0 L 10 5 L 0 10 z"/></marker>`).join('')}</defs>${edgePaths}</svg>${columns.map((k,i)=>`<span class="sm-graph-column" style="left:${20+i*420}px">${['입력 장비','현장 엣지','서버'][i]}</span>`).join('')}${items}</div></div></div><div class="sm-graph-routes">${routes.map(e=>`<div class="${e.active?'active':e.fallback?'fallback':''}"><button class="text-button" data-sm-service="${E(e.service.service_id)}" ${example?'disabled':''}>${E(e.service.display_name)} ↗</button><span>${E(nodeTitle(e.from.slice(5)))} → ${E(nodeTitle(e.to.slice(5)))}</span><strong>${E(e.text)}</strong></div>`).join('')||'<p class="sm-caption">표시할 서버 연결 위치가 없습니다. 실행체 배치와 서비스 계약을 확인하세요.</p>'}</div><p class="sm-caption">화살표는 요청·결과 방향이며 패킷량이나 전송 속도가 아닙니다. 점선만으로 실행·통신 성공을 판단하지 않습니다.</p></section>`;
}
function details(p,a,d,active){
 if(!p&&active)return '<section class="sm-detail"><p class="sm-caption">서비스는 등록되어 있지만 연결된 Running 실행체가 현재 관측되지 않습니다.</p></section>';
 if(!p)return `<section class="sm-detail"><h3 id="sm-detail-heading" tabindex="-1">${selected?'선택한 실행체가 목록에 없습니다.':'실행체를 선택하세요.'}</h3><p class="sm-caption">장비 안의 카드를 누르면 처리 경로와 상태를 확인할 수 있습니다.</p></section>`;
 const svc=a?.services?.find(x=>x.service_id===contextService)||a?.service||active,valid=d.valid.profiles,perf=(svc?.service_id==='sensor-anomaly-demo'||example)&&d.valid.demo?d.demo?.performance:null;
 const chooser=a?.services?.length>1?`<div class="sm-service-context"><label for="sm-service-context">이용 서비스</label><select id="sm-service-context">${a.services.map(x=>`<option value="${E(x.service_id)}" ${svc.service_id===x.service_id?'selected':''}>${E(x.display_name)}</option>`).join('')}</select></div>`:'';
 return `${chooser}${svc?flow(svc,d):`<section class="sm-detail"><span class="eyebrow">선택한 실행체</span><h3 id="sm-detail-heading" tabindex="-1">${E(cardTitle(p,a))}</h3>${a?.role==='source'?`<p class="sm-caption">입력 장비 · ${E(a.sources.join(', '))}</p>`:''}</section>`}
 <section class="sm-detail sm-metrics"><dl class="sm-facts"><div><dt>CPU 합계</dt><dd>${valid?num(p.current_usage?.cpu_cores,3):'—'} <small>cores</small></dd></div><div><dt>메모리 합계</dt><dd>${valid?num(p.current_usage?.memory_working_set_mib):'—'} <small>MiB</small></dd></div><div><dt>지연 p95</dt><dd>${perf?.metrics_valid?num(perf.processing_latency_p95_ms)+' ms':'—'}</dd></div><div><dt>처리량</dt><dd>${perf?.metrics_valid?num(perf.throughput_per_second)+' 건/s':'—'}</dd></div></dl><p class="sm-caption">— : 유효한 관측 없음</p>
 ${svc&&!example?`<button class="button sm-detail-link" data-live-service="${E(svc.service_id)}">서비스 상세·결과 확인 ↗</button>`:''}
 <details class="sm-evidence" data-sm-disclosure="evidence" ${disclosures.has('evidence')?'open':''}><summary>식별자와 관측 근거</summary><dl class="sm-facts"><div><dt>실행 위치 · Running 관측</dt><dd>${E(p.nodes.join(', '))}</dd></div><div><dt>워크로드 식별자</dt><dd>${E(key(p))}</dd></div><div><dt>모델</dt><dd>${E(svc?.model_version||'모델 계약 미연결')}</dd></div><div><dt>배치 원 관측</dt><dd>${example?'예시 데이터':E(clock(p.generated_at||entries.profiles.data?.generated_at))}</dd></div></dl><p class="sm-caption">CPU·메모리는 이 워크로드의 전체 실행체 합계입니다. 노드별 분할값이 아닙니다.</p></details></section>`;
}
function historyPanel(keys){const shown=keys?events.filter(e=>keys.has(e.id)):events;return `<details class="sm-history" data-sm-disclosure="history" ${disclosures.has('history')?'open':''}><summary>배치 변화 이력 <span>${shown.length}건 · 이 화면을 연 이후</span></summary>${shown.length?`<ol>${shown.map(e=>`<li><time>${E(clock(e.time))}</time><div><strong>${E(e.text)}</strong><span>${E(e.id)}</span><small>${E((e.from||[]).join(', ')||'미관측')} → ${E((e.to||[]).join(', ')||'미관측')}</small></div></li>`).join('')}</ol>`:'<p class="sm-caption">아직 새로운 배치 변화가 관측되지 않았습니다. Pod 배치의 변화는 서비스 실행 권한 전환이나 무중단 이동을 증명하지 않습니다.</p>'}</details>`;}
function serviceList(d){
 return `<section class="sm-catalog" aria-label="서비스 목록"><div class="sm-catalog-head"><div><h2>서비스 목록 <span>${d.valid.services?d.services.length:'—'}</span></h2><p>서비스를 선택하면 연결된 장비와 실행 경로를 확인할 수 있습니다.</p></div><button class="button primary" data-workspace="designer">새 서비스 초안</button><button class="button" id="sm-refresh" data-sm-action="refresh" ${pending?'disabled':''}>${pending?'조회 중…':'새로고침'}</button></div>
 ${!d.valid.services?`<p class="sm-error" role="status">${entries.services.error?'서비스 목록 조회 실패 · '+E(entries.services.error)+' · 마지막 관측을 보존합니다.':entries.services.data?'서비스 관측 갱신이 지연됐습니다.':'서비스 목록을 조회하고 있습니다.'}</p>`:''}
 <div class="sm-catalog-labels" aria-hidden="true"><span>서비스</span><span>입력 / 모델</span><span>실행 위치</span><span></span></div>
 <div class="sm-service-list">${d.services.map(svc=>{const w=svc.descriptor?.workload,ps=d.profiles.filter(p=>key(p)===w?.namespace+'/'+w?.name),st=execution(svc,d.valid.services),ok=d.valid.services&&svc.mode==='live'&&!svc.observation_error;return `<div class="sm-service-row"><span class="sm-service-identity"><button class="text-button" data-sm-service="${E(svc.service_id)}"><strong>${E(svc.display_name||svc.service_id)}</strong></button><small>${E(svc.service_id)}</small>${pill(st.text,st.tone)}</span><span class="sm-service-health"><span>입력 <b>${ok?E(label(svc.input_state)):'확인 불가'}</b></span><span>모델 <b>${ok?E(label(svc.model_state)):'확인 불가'}</b></span></span><span class="sm-service-placement">${d.valid.profiles?ps.length?E([...new Set(ps.flatMap(p=>p.nodes))].map(nodeTitle).join(', ')):'Running 실행체 미관측':'배치 확인 불가'}<small>${E(svc.description||'Git 서비스 계약')}</small></span><span class="sm-service-open"><button class="button primary" data-sm-service="${E(svc.service_id)}">연결·배치</button><button class="button" data-live-service="${E(svc.service_id)}">상태·진단</button><button class="button" data-edit-service="${E(svc.service_id)}">구성 편집</button></span></div>`;}).join('')||(!entries.services.data?'<p class="sm-vacant">등록 목록을 기다리고 있습니다.</p>':'<p class="sm-vacant">등록된 서비스가 없습니다.</p>')}</div>
 <div class="sm-catalog-footer"><p>등록 서비스와 실행 Pod는 별도입니다. 실행체가 관측되지 않아도 등록 서비스는 목록에 유지됩니다.</p><div><button class="button" data-sm-overview>전체 장비 지도</button><button class="button" id="sm-example" data-sm-action="example">움직임 예시 보기</button></div></div></section>`;
}
function syncSelection(){
 if(example)return;
 const params=new URLSearchParams(root.location.search);viewMode=params.get('view')==='cards'?'cards':'graph';const next=params.get('service')||(params.get('workloads')==='all'?'*':null);
 if(next!==serviceSelection){serviceSelection=next;selected=null;contextService=next;showEmpty=next==='*';scope='linked';}
 if(next&&next!=='*')root.NexusLive?.setServiceId?.(next);
}
function chooseService(id){
 serviceSelection=id;graphScroll={left:0,top:0};selected=null;contextService=id;showEmpty=id==='*';scope='linked';
 const url=new URL(root.location.href);url.searchParams.delete('service');url.searchParams.delete('workloads');if(id==='*')url.searchParams.set('workloads','all');else if(id)url.searchParams.set('service',id);url.hash=id?'service-map':'services';root.history.pushState(null,'',url);root.NexusLive?.setServiceId?.(id==='*'?null:id);paint();root.NexusLive?.refreshView?.();
}
function html(){
 const d=data();const overview=!example&&serviceSelection==='*';if(!example&&!serviceSelection)return serviceList(d);
 const active=example?d.services[0]:d.services.find(s=>s.service_id===serviceSelection);
 if(!example&&serviceSelection!=='*'&&!active&&!entries.services.data)return '<p class="sm-vacant" role="status">선택한 서비스 정보를 조회하고 있습니다.</p>';
 if(!example&&serviceSelection!=='*'&&!active)return `<button class="button" data-sm-back>← 서비스 목록</button><section class="sm-detail"><h2>선택한 서비스 확인 불가</h2><p>${E(serviceSelection)}의 등록 정보를 현재 목록에서 확인할 수 없습니다.</p></section>`;
 const linkedDevices=active?serviceDevices(active,d.devices):d.devices;
 const links=associations(active?[active]:d.services,linkedDevices);
 const profiles=active?scopedProfiles(active,d.devices,d.profiles):d.profiles.filter(p=>scope==='all'||links.has(key(p)));
 if(!overview&&!selected&&profiles.length&&(example||entries.services.data))selected=key(profiles.find(p=>links.get(key(p))?.role==='service')||profiles[0]);
 const chosen=profiles.find(p=>key(p)===selected),a=links.get(selected);
 const nodes=new Map(d.resources.map(r=>[r.node,r]));if(overview)for(const g of sourceGroups(d.devices))if(g.nodes.length===1&&!nodes.has(g.nodes[0]))nodes.set(g.nodes[0],{node:g.nodes[0],health:'unknown',nodeType:'unknown'});for(const p of profiles)for(const node of p.nodes)if(!nodes.has(node))nodes.set(node,{node,health:'unknown',nodeType:'unknown'});
 const visible=[...nodes.values()].filter(r=>showEmpty||example||profiles.some(p=>p.nodes.includes(r.node))).sort((a,b)=>a.node.localeCompare(b.node));
 const edges=visible.filter(r=>r.nodeType!=='cloud_server'),servers=visible.filter(r=>r.nodeType==='cloud_server');
 const errors=example?[]:Object.entries(entries).filter(([k,e])=>e.error||e.data&&!d.valid[k]).map(([k,e])=>`${({profiles:'워크로드',services:'서비스',resources:'노드',devices:'장비',demo:'추론'})[k]}: ${e.error||'갱신 지연'}`);
 const board=(rows)=>rows.map(r=>nodePanel(r,profiles.filter(p=>p.nodes.includes(r.node)),links,d)).join('')||'<p class="sm-vacant">표시할 장비 없음</p>';
 return `${!example?`<div class="sm-service-navigation"><button class="button" data-sm-back>← 서비스 목록</button><label for="sm-service-picker">서비스 선택</label><select id="sm-service-picker">${serviceSelection==='*'?'<option value="">전체 장비 지도</option>':''}${d.services.map(s=>`<option value="${E(s.service_id)}" ${s.service_id===serviceSelection?'selected':''}>${E(s.display_name)}</option>`).join('')}</select>${active?pill(execution(active,d.valid.services).text,execution(active,d.valid.services).tone):''}</div>`:''} ${example?`<div class="sm-example-banner"><div><b>예시 ${step+1}/4 · ${scenarios[step].title}</b><p>${scenarios[step].note}</p></div><div><button class="button" id="sm-play" data-sm-action="play">${playing?'예시 일시정지':'예시 자동 재생'}</button><button class="button" id="sm-next" data-sm-action="next">다음 장면 →</button></div></div>`:''}
 <div class="sm-controls"><div class="sm-segment" aria-label="지도 표현"><button id="sm-view-graph" data-sm-view="graph" aria-pressed="${viewMode==='graph'}">연결 그래프</button><button id="sm-view-cards" data-sm-view="cards" aria-pressed="${viewMode==='cards'}">장비 카드</button></div>${active?`<span class="sm-service-scope">선택한 서비스의 실행체 <b>${d.valid.profiles?profiles.length:'—'}</b></span>`:`<div class="sm-segment" aria-label="지도 표시 범위">${[['linked','등록 서비스·수집기'],['all','전체 워크로드']].map(([k,t])=>`<button id="sm-scope-${k}" data-sm-scope="${k}" aria-pressed="${scope===k}">${t}</button>`).join('')}</div>`}<label><input id="sm-empty" type="checkbox" ${showEmpty?'checked':''}>빈 장비도 표시</label><button id="sm-example" class="button sm-example-button" data-sm-action="example">${example?'실제 관측으로 돌아가기':'움직임 예시 보기'}</button><span class="sm-refresh">${example?'예시 데이터':`15초 갱신 · 수신 ${clock(lastCycle)}`}</span><button class="button primary" data-workspace="designer">새 서비스 초안</button><button class="button" id="sm-refresh" data-sm-action="refresh" ${pending||example?'disabled':''}>${pending?'조회 중…':'새로고침'}</button></div>
 ${errors.length?`<div class="sm-error" role="status"><b>일부 관측을 확인할 수 없습니다.</b> ${E(errors.join(' / '))} · 이전 응답이 있으면 보존합니다.</div>`:''}
 <div class="sm-legend"><span><i class="service"></i>AI 서비스</span><span><i class="source"></i>센서 수집</span><span><i class="remote"></i>증강 실행체</span><span>${example?'예시 장비':d.valid.profiles?`${profiles.length}개 워크로드 · ${visible.length}개 장비 표시`:'워크로드 수 확인 불가'}</span></div>
 <div class="sm-layout ${overview?'sm-equipment-layout':''}"><div class="sm-canvas">${viewMode==='graph'?graphPanel(d,active?[active]:d.services,visible,profiles,links):`<div class="sm-board"><section class="sm-zone"><div class="sm-zone-label"><span>현장 엣지</span><small>수집 · 전처리 · 로컬 실행</small></div><div class="sm-edge-grid">${board(edges)}</div></section><section class="sm-zone server"><div class="sm-zone-label"><span>서버</span><small>추론 · 공용 서비스</small></div><div class="sm-server-grid">${board(servers)}</div></section></div>`}
 ${!profiles.length?`<p class="sm-caption">${entries.profiles.data?'Running 워크로드 관측이 비어 있습니다. 정지·삭제 또는 수집 실패 여부는 별도 확인이 필요합니다.':'워크로드 배치를 조회하고 있습니다.'}</p>`:''}
 ${overview?`<p class="sm-caption">엣지·서버 노드와 물리 입력 장비를 구분해 표시합니다. 센서의 등록 위치는 배선·통신 성공을 의미하지 않습니다.</p>${sourceGroups(d.devices).some(g=>g.nodes.length!==1)?`<section class="sm-unplaced-sources"><h3>연결 노드 확인 필요</h3>${sourceGroups(d.devices).filter(g=>g.nodes.length!==1).map(g=>sourcePanel(g,d)).join('')}</section>`:''}`:''}${example?'':historyPanel(active?serviceKeys(active,d.devices):null)}</div><aside ${overview&&!selected?'hidden':''} class="sm-inspector" aria-label="선택한 실행체 상세">${active&&!chosen?flow(active,d):''}${details(chosen,a,d,active)}</aside></div>
 <details class="sm-boundary" data-sm-disclosure="boundary" ${disclosures.has('boundary')?'open':''}><summary>이 지도에서 관측하는 범위</summary><p>Running Pod의 워크로드·노드별 배치입니다. Pending·정지된 Deployment 전체 목록은 포함하지 않습니다. 카탈로그에 연결되지 않은 워크로드는 AI 서비스로 분류하지 않습니다. 실행체가 준비됐다는 사실과 실제 서비스 처리 성공은 별도입니다. 배치 변화 기록은 이 브라우저에서 관측한 두 스냅샷의 차이이며 새로고침하면 초기화됩니다.</p></details>`;
}
function paint(){const el=root.document?.getElementById('service-placement-map');if(!el)return;const focused=root.document.activeElement,id=focused?.id,catalogId=focused?.dataset?.smService,sel=focused?.dataset?.smSelect,node=focused?.dataset?.smNode;
 const oldRects=new Map();for(const b of el.querySelectorAll('[data-sm-select]')){const k=b.dataset.smSelect;const rows=oldRects.get(k)||[];rows.push({node:b.dataset.smNode,rect:b.getBoundingClientRect()});oldRects.set(k,rows);}
 el.classList.toggle('is-example',example);el.classList.toggle('is-graph',viewMode==='graph');el.classList.toggle('is-equipment',!example&&serviceSelection==='*');el.innerHTML=html();const scroll=el.querySelector('.sm-graph-scroll');if(scroll){scroll.scrollLeft=graphScroll.left;scroll.scrollTop=graphScroll.top;}
 if(!root.matchMedia('(prefers-reduced-motion: reduce)').matches){const cards=[...el.querySelectorAll('[data-sm-select]')];for(const b of cards){const old=oldRects.get(b.dataset.smSelect);if(old?.length===1&&old[0].node!==b.dataset.smNode&&cards.filter(c=>c.dataset.smSelect===b.dataset.smSelect).length===1){const to=b.getBoundingClientRect(),from=old[0].rect,ghost=b.cloneNode(true);ghost.removeAttribute('data-sm-select');ghost.removeAttribute('data-sm-node');ghost.setAttribute('aria-hidden','true');ghost.tabIndex=-1;Object.assign(ghost.style,{position:'fixed',zIndex:'30',pointerEvents:'none',left:from.x+'px',top:from.y+'px',width:to.width+'px'});root.document.body.append(ghost);ghost.animate([{transform:'translate(0,0)',opacity:.9},{transform:`translate(${to.x-from.x}px,${to.y-from.y}px)`,opacity:.5}],{duration:260,easing:'cubic-bezier(.23,1,.32,1)'}).finished.finally(()=>ghost.remove());b.animate([{opacity:0},{opacity:1}],{duration:260});}}}
 if(id&&el.contains(root.document.getElementById(id)))root.document.getElementById(id).focus({preventScroll:true});
 else if(catalogId){[...el.querySelectorAll('[data-sm-service]')].find(b=>b.dataset.smService===catalogId)?.focus({preventScroll:true});}
 else if(sel){const replacement=[...el.querySelectorAll('[data-sm-select]')].find(b=>b.dataset.smSelect===sel&&b.dataset.smNode===node);replacement?.focus({preventScroll:true});}
}
function install(){if(installed)return;installed=true;
 root.document.addEventListener('scroll',e=>{if(e.target.matches?.('.sm-graph-scroll'))graphScroll={left:e.target.scrollLeft,top:e.target.scrollTop};},true);
 root.document.addEventListener('toggle',e=>{if(e.target.isConnected&&e.target.dataset?.smDisclosure){const k=e.target.dataset.smDisclosure;if(e.target.open)disclosures.add(k);else disclosures.delete(k);}},true);
 root.document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b||!b.closest('#service-placement-map'))return;
  if(b.dataset.smWatch){watchedService=b.dataset.smWatch;const d=data(),svc=d.services.find(s=>s.service_id===watchedService),w=svc?.descriptor?.workload;selected=w?w.namespace+'/'+w.name:null;contextService=watchedService;paint();}
  if(b.dataset.smService){chooseService(b.dataset.smService);}
  if(b.hasAttribute('data-sm-back'))chooseService(null);
  if(b.hasAttribute('data-sm-overview'))chooseService('*');
  if(b.dataset.smSelect){selected=b.dataset.smSelect;paint();if(root.matchMedia('(max-width: 900px)').matches){const heading=root.document.getElementById('sm-detail-heading');heading?.focus({preventScroll:true});heading?.scrollIntoView({block:'start',behavior:'instant'});}}
  if(b.dataset.smView){viewMode=b.dataset.smView;const url=new URL(root.location.href);url.searchParams.set('view',viewMode);root.history.replaceState(null,'',url);paint();}
  if(b.dataset.smZoom){graphZoom=b.dataset.smZoom==='0'?1:Math.max(.5,Math.min(1.5,graphZoom+Number(b.dataset.smZoom)*.25));paint();}
  if(b.dataset.smScope){scope=b.dataset.smScope;paint();}
  const action=b.dataset.smAction;if(action==='refresh')refresh();
  if(action==='highlight'){highlightResults=!highlightResults;paint();}
  if(action==='example'){example=!example;selected=null;step=0;playing=false;watchedService=null;graphFlashes.clear();observationPrevious=new Map();paint();if(!example)refresh();}
  if(action==='next'){step=(step+1)%scenarios.length;lastExampleTick=Date.now();paint();}
  if(action==='play'){playing=!playing;lastExampleTick=Date.now();paint();}
 });
 root.addEventListener('popstate',()=>{syncSelection();paint();});
 root.document.addEventListener('change',e=>{if(e.target.id==='sm-service-picker'&&e.target.value)chooseService(e.target.value);if(e.target.id==='sm-empty'){showEmpty=e.target.checked;paint();}if(e.target.id==='sm-service-context'){contextService=e.target.value;paint();}});
 root.setInterval(()=>{if(root.document.hidden||!root.document.getElementById('service-placement-map'))return;
  if(example){if(playing&&Date.now()-lastExampleTick>=3500){step=(step+1)%scenarios.length;lastExampleTick=Date.now();paint();}return;}
  if(Date.now()-lastCycle>=15000&&!pending)refresh();
 },1000);
}
function render(){if(root.document){install();syncSelection();root.queueMicrotask(()=>{paint();if(!example&&Date.now()-lastCycle>=15000)refresh();});}return '<section id="service-placement-map" class="service-map" aria-label="서비스 배치 지도"></section>';}
const api={render,runtimeObservation,runtimeChanges,graphModel,graphRoute,sourceGroups,isOverview:()=>new URLSearchParams(root.location.search).get('workloads')==='all',openOverview:()=>chooseService('*'),openCatalog:()=>chooseService(null),serviceDevices,serviceKeys,scopedProfiles,validate,associations,placements,changes,execution,routeState,advance,fresh,recent,escape:E};
if(typeof module!=='undefined'&&module.exports)module.exports=api;root.NexusServiceMap=api;
})(typeof window!=='undefined'?window:globalThis);
