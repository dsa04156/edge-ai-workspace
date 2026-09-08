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
test("service scoping isolates same-name workloads, shared endpoints and exact input collectors",()=>{
 const a={service_id:"a",input_devices:["temperature"],descriptor:{workload:{namespace:"prod",name:"analysis"},runtime_offloading:{target_workload:{namespace:"shared",name:"inference"}}}};
 const b={...a,service_id:"b",input_devices:["vibration"],descriptor:{...a.descriptor,workload:{namespace:"test",name:"analysis"}}};
 const devices=[{name:"temperature",device_service_name:"serial",physical_device_id:"arduino"},{name:"vibration",device_service_name:"sensehat",physical_device_id:"pi"}];
 const profiles=[{namespace:"prod",service:"analysis"},{namespace:"test",service:"analysis"},{namespace:"shared",service:"inference"},{namespace:"edgex-edge",service:"serial"},{namespace:"edgex-edge",service:"sensehat"},{namespace:"other",service:"serial"}];
 assert.deepEqual(M.scopedProfiles(a,devices,profiles),[profiles[0],profiles[2],profiles[3]]);
 assert.deepEqual(M.scopedProfiles(b,devices,profiles),[profiles[1],profiles[2],profiles[4]]);
 assert.deepEqual(M.scopedProfiles(a,devices,[]),[]);
 assert.deepEqual(M.serviceDevices({...a,input_devices:["missing"]},devices),[]);
 assert.deepEqual(M.serviceDevices({device_service:"serial",physical_source:"another"},devices),[]);
 assert.deepEqual(M.serviceDevices({design_contract:{inputs:[{device_name:"vibration"}]}},devices),[devices[1]]);
});

test('physical source fanout keeps identity and ambiguous node mappings unassigned',()=>{
 const devices=[{name:'temperature',physical_device_id:'sensor-a',node_name:'edge-a'},{name:'vibration',physical_device_id:'sensor-a',node_name:'edge-a'},{name:'unknown-identity',node_name:'edge-a'},{name:'unassigned',physical_device_id:'sensor-b'},{name:'conflicting',physical_device_id:'sensor-a',node_name:'edge-b'}];
 const groups=M.sourceGroups(devices);assert.equal(groups.length,2);assert.deepEqual(groups[0].nodes,['edge-a','edge-b']);assert.equal(groups[0].devices.length,3);assert.deepEqual(groups[1].nodes,[]);
});

test('offloading graph requires fresh routing and exact source and remote identities',()=>{
 const now=new Date().toISOString(),s={service_id:'sensor-anomaly-demo',mode:'live'};
 const demo={mode:'live',input_state:'fresh',model_state:'ready',execution_ownership:{enabled:true,lease_valid:true,effective_mode:'ACTIVE'},inference_routing:{inference_mode:'REMOTE',observed_at:now,source_node:'edge',remote_node:'server'}};
 const d={demo,valid:{demo:true,profiles:true,services:true}};
 assert.equal(M.graphRoute(s,d,'edge','server').active,true);
 for(const [from,to] of [['other','server'],['edge','other']])assert.equal(M.graphRoute(s,d,from,to).active,false);
 assert.equal(M.graphRoute({...s,service_id:'another-service'},d,'edge','server').active,false);
 assert.equal(M.graphRoute(s,{...d,valid:{...d.valid,profiles:false}},'edge','server').active,false);
 assert.equal(M.graphRoute(s,{...d,demo:{...demo,execution_ownership:{enabled:true,lease_valid:false}}},'edge','server').active,false);
 assert.equal(M.graphRoute(s,{...d,demo:{...demo,inference_routing:{...demo.inference_routing,observed_at:'2000-01-01'}}},'edge','server').active,false);
 const fallback=M.graphRoute(s,{...d,demo:{...demo,inference_routing:{...demo.inference_routing,inference_mode:'LOCAL_FALLBACK'}}},'edge','server');assert.equal(fallback.active,false);assert.equal(fallback.fallback,true);
});
test('graph keeps idle nodes, separates source fanout and isolates selected-service inputs',()=>{
 const service={service_id:'a',input_devices:['t'],descriptor:{workload:{namespace:'prod',name:'main'},runtime_offloading:{target_workload:{namespace:'prod',name:'remote'}}}};
 const d={services:[service],devices:[{name:'t',physical_device_id:'sensor-a',node_name:'edge'},{name:'other',physical_device_id:'sensor-b',node_name:'idle'}],valid:{},demo:null};
 const resources=[{node:'edge'},{node:'server',nodeType:'cloud_server'},{node:'idle'}],profiles=[{namespace:'prod',service:'main',nodes:['edge']},{namespace:'prod',service:'remote',nodes:['server']}];
 const all=M.graphModel(d,d.services,resources,profiles,true),scoped=M.graphModel(d,d.services,resources,profiles);
 assert.equal(all.nodes.length,5);assert.equal(scoped.nodes.some(n=>n.id==='source:sensor-b'),false);
 assert.deepEqual(all.edges.filter(e=>e.kind!=='input').map(e=>[e.from,e.to]),[['node:edge','node:server'],['node:server','node:edge']]);assert.equal(all.edges.some(e=>e.active),false);
});
