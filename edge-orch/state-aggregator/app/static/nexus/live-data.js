/* Existing read APIs only. No mutation, fallback inventory, or client health policy. */
(function(root){
'use strict';
const endpoints={benchmarks:'/api/benchmarks',virtual:'/api/virtual-devices',operations:'/state/operations',devices:'/state/devices',twins:'/state/device-twins',services:'/state/services',results:'/state/service-demo/results?limit=12',resources:'/api/resources',recommendations:'/api/runtime-recommendations'};
const escape=value=>String(value??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function validate(key,data){
 if(key==='benchmarks'){if(!Array.isArray(data?.items))throw new Error('시험 원장 응답 형식 확인 필요');return data;}
 if(key==='virtual'){if(!Array.isArray(data?.resources)||!data?.summary)throw new Error('가상 실행체 응답 형식 확인 필요');return data;}
 if(key==='operations'){if(data?.schema_version!=='edgeai.operations/v1'||!Array.isArray(data.services)||!Array.isArray(data.events)||!Array.isArray(data.issues)||!data.sources)throw new Error('통합 운영 응답 형식 확인 필요');return data;}
 const items=['devices','resources'].includes(key)?data:key==='recommendations'?data?.items:data?.[key];
 if(!Array.isArray(items))throw new Error('API 응답 형식 확인 필요');
 const id=key==='resources'?'node':key==='recommendations'?'serviceId':key==='devices'?'name':key==='twins'?'id':key==='services'?'service_id':'observed_at';
 if(items.some(x=>!x||typeof x!=='object'||typeof x[id]!=='string'))throw new Error('API 항목 식별자 확인 필요');
 return data;
}
function errors(data){return [...(data?.nodeError?[data.nodeError]:[]),...(Array.isArray(data?.resources)?data.resources.filter(r=>r.observationError).map(r=>r.observationError):[]),...(Array.isArray(data?.observation_errors)?data.observation_errors:[]),...(data?.observation_error?[data.observation_error]:[]),...(data?.mode==='unavailable'?['관측 원천 사용 불가']:[])].filter(Boolean).map(String);}
function createStore(fetchFn,now=Date.now,onSettled=()=>{}){
 const entries=Object.fromEntries(Object.keys(endpoints).map(k=>[k,{status:'idle',data:null,error:null,receivedAt:null,refreshing:false}]));let pending=null;
 function refresh(){if(pending)return pending;Object.values(entries).forEach(e=>{e.refreshing=true;if(e.status==='idle')e.status='loading';});
 pending=Promise.all(Object.entries(endpoints).map(async([key,url])=>{const e=entries[key],controller=new AbortController();const timer=setTimeout(()=>controller.abort(),20000);try{const r=await fetchFn(url,{method:'GET',headers:{Accept:'application/json'},cache:'no-store',signal:controller.signal});if(!r.ok)throw new Error('HTTP '+r.status);const data=validate(key,await r.json());e.data=data;e.receivedAt=now();e.error=errors(data).join(' / ')||null;e.status=e.error?'error':'ready';e.lastFetchFailed=false;}catch(error){e.lastFetchFailed=true;e.status='error';e.error=error.name==='AbortError'?'관측 요청 시간 초과':String(error.message||error);}finally{clearTimeout(timer);e.refreshing=false;onSettled(key);}})).finally(()=>{pending=null;});return pending;}
 return {entries,refresh};
}
function items(entry,key){const data=entry?.data;return ['devices','resources'].includes(key)?(Array.isArray(data)?data:[]):key==='recommendations'?(Array.isArray(data?.items)?data.items:[]):(Array.isArray(data?.[key])?data[key]:[]);}
function isCurrent(e,now=Date.now()){return Boolean(e&&e.status==='ready'&&e.receivedAt!==null&&now-e.receivedAt<90000&&!e.error);}
function groupSources(devices,twins){const groups=new Map();const unassigned=[];for(const d of devices){if(!d.physical_device_id){unassigned.push(d);continue;}const id=d.physical_device_id;if(!groups.has(id))groups.set(id,{id,devices:[],bindings:new Map()});groups.get(id).devices.push(d);}for(const t of twins){const g=groups.get(t.physical_device_id);if(!g)continue;for(const b of t.service_bindings||[])if(typeof b.service_id==='string')g.bindings.set(b.service_id,b);}return {sources:[...groups.values()].sort((a,b)=>a.id.localeCompare(b.id)),unassigned};}
function resultLabel(result){return result.anomaly===true?'이상 감지':result.anomaly===false?'정상 범위':'판정 확인 불가';}
function executionLabel(service,current=true){
 const o=service.execution_ownership;
 if(!current||service.observation_error||service.mode!=='live'||!o)return '실행 소유권 확인 불가';
 if(o.enabled&&o.lease_valid===false&&o.reason_code==='execution_lease_expired')return '실행 Lease 만료로 추론 중단 ('+o.effective_mode+')';
 return '실행 모드 '+o.effective_mode+(o.reason_code?' · '+o.reason_code:'');
}
const api={executionLabel,endpoints,escape,validate,errors,createStore,items,isCurrent,groupSources,resultLabel};if(typeof module!=='undefined'&&module.exports)module.exports=api;root.NexusData=api;
})(typeof window!=='undefined'?window:globalThis);
