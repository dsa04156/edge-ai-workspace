const {test}=require('node:test');
const assert=require('node:assert/strict');
const M=require('../app/static/nexus/service-map.js');
test('workload identity includes namespace and only exact catalog identities become services',()=>{
 const s={service_id:'s',display_name:'서비스',descriptor:{workload:{namespace:'prod',name:'analysis'},runtime_offloading:{target_workload:{namespace:'prod',name:'remote'}}}};
 const a=M.associations([s],[{device_service_name:'serial',physical_device_id:'a'},{device_service_name:'serial',physical_device_id:'a'}]);
 assert.equal(a.get('prod/analysis').role,'service');assert.equal(a.get('prod/remote').role,'remote');assert.equal(a.has('test/analysis'),false);assert.deepEqual(a.get('edgex-edge/serial').sources,['a']);
 const shared=M.associations([s,{...s,service_id:'second',display_name:'다른 서비스'}],[]);assert.deepEqual(shared.get('prod/remote').services.map(x=>x.service_id),['s','second']);
});
test('node changes compare full sets: additions are not collapsed to migration and first fetch has no events',()=>{
 const p=(nodes,namespace='prod')=>({namespace,service:'a',nodes});
 const first=M.placements([p(['b','a'])]);
 assert.deepEqual(M.changes(null,first),[]);assert.deepEqual(M.changes(first,M.placements([p(['a','b'])])),[]);
 const events=M.changes(first,M.placements([p(['b','c']),p(['a'],'test')]));
 assert.equal(events.length,2);assert.equal(events[0].text,'배치 관측 변경');assert.deepEqual(events[0].from,['a','b']);assert.deepEqual(events[0].to,['b','c']);
 assert.equal(M.changes(first,new Map())[0].text,'Running 목록에서 사라짐');
});
test('a ready Pod cannot imply application execution when its Lease is expired',()=>{
 const s={mode:'live',status:'healthy',execution_ownership:{enabled:true,lease_valid:false,effective_mode:'STANDBY'}};
 assert.equal(M.execution(s,true).text,'대기 · 실행 권한 없음');assert.equal(M.execution(s,false).tone,'unknown');
});
test('flow pulses require a fresh, increasing result and valid input, model and ownership',()=>{
 const now=Date.now(),old={latest:{observed_at:new Date(now-1000).toISOString()}};
 const d={mode:'live',input_state:'fresh',model_state:'ready',inference_routing:{inference_mode:'REMOTE',observed_at:new Date(now).toISOString()},execution_ownership:{enabled:true,lease_valid:true,effective_mode:'ACTIVE'},latest:{observed_at:new Date(now).toISOString(),execution_mode:'remote'}};
 assert.equal(M.advance(old,d,now),true);assert.equal(M.advance(null,d,now),false);assert.equal(M.advance(d,d,now),false);
 for(const change of [{input_state:'stale'},{model_state:'warming_up'},{execution_ownership:{enabled:true,lease_valid:false,effective_mode:'STANDBY'}},{observation_error:'unavailable'},{latest:old.latest}])assert.equal(M.advance(old,{...d,...change},now),false);
 assert.equal(M.routeState(d,false,now).mode,'UNKNOWN');assert.equal(M.routeState({...d,inference_routing:{inference_mode:'REMOTE',observed_at:new Date(now-120000).toISOString()}},true,now).canFlow,false);
 assert.equal(M.advance(old,{...d,latest:{...d.latest,execution_mode:'local'}},now),false);
});
test('invalid observations and stale or future timestamps fail closed',()=>{
 assert.throws(()=>M.validate('profiles',{service_resource_profiles:[{namespace:'a',service:'b',nodes:'node'}]}));
 assert.throws(()=>M.validate('demo',{}));assert.equal(M.recent('invalid'),false);
 const now=Date.now();assert.equal(M.recent(new Date(now+100000).toISOString(),now),false);
 assert.equal(M.fresh({data:{},receivedAt:now,error:'HTTP 503'},now),false);
 assert.equal(M.escape('<img src=x onerror="bad">'),'&lt;img src=x onerror=&quot;bad&quot;&gt;');
});
