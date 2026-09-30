const test=require('node:test');
const assert=require('node:assert/strict');
global.NexusData=require('../app/static/nexus/live-data.js');
global.VirtualDeviceView=require('../app/static/virtual-devices.js');
const M=require('../app/static/nexus/device-map.js');
const now=Date.parse('2026-09-15T06:00:00Z'),stamp=new Date(now).toISOString();
const entry=data=>({data,status:'ready',error:null,lastFetchFailed:false,receivedAt:now});
function fixture(){return {
 resources:entry([{node:'edge',nodeType:'edge_device'},{node:'worker',nodeType:'cloud_server'},{node:'empty'}]),
 serviceVirtual:entry({schema_version:'edgeai.service-virtual-devices/v1',observed_at:now/1000,total:0,running:0,devices:[]}),
 nodes:entry([]),devices:entry([{name:'temperature',physical_device_id:'sensor',node_name:'edge'},{name:'light',physical_device_id:'sensor',node_name:'edge'}]),
 profiles:entry({generated_at:stamp,service_resource_profiles:[{namespace:'test',service:'vd',nodes:['worker'],pod_count:1,ready_pod_count:1,pods_by_node:{worker:1}},{namespace:'infra',service:'collector',nodes:['edge'],pod_count:1,ready_pod_count:1,pods_by_node:{edge:1}}]}),
 virtual:entry({observedAt:stamp,maxAgeSeconds:30,nodes:[{name:'edge',ready:true},{name:'worker',ready:true},{name:'empty',ready:false}],summary:{physicalNodes:3,definitions:1,observedInstances:1},resources:[{
   id:'vd-1',observedAt:stamp,observedInstances:1,executionState:'ready',connectionState:'configured_unverified',connections:[],
   definition:{spec:{displayName:'CPU model',capabilities:['inference'],model:{id:'test'},nodeSelector:{'kubernetes.io/hostname':'edge'},runtimeRef:{namespace:'test',workloadRef:{kind:'Deployment',name:'vd'}}}},
   instances:[{name:'vd-pod',podUid:'uid-1',node:'worker',phase:'Running',podReady:true,modelReady:true,executionState:'ready',apiObservedAt:stamp,usage:{},resources:[]}]
 }]})};}
test('all physical nodes remain visible and actual placement wins over planned selector',()=>{
 const m=M.model(fixture(),now);
 assert.equal(m.nodes.length,3);assert.equal(m.nodes.find(n=>n.name==='edge').registered.length,0);
 assert.equal(m.nodes.find(n=>n.name==='worker').registered[0].pods[0].podUid,'uid-1');
 assert.equal(m.nodes.find(n=>n.name==='worker').workloads.length,0); // exact registry/workload deduplication
 assert.equal(m.nodes.find(n=>n.name==='edge').workloads.length,1);
 assert.equal(m.totals.sensors,2);assert.equal(m.nodes.find(n=>n.name==='edge').sensors.length,2);
});
test('stopped definitions remain as a dashed plan, never as an observed instance',()=>{
 const f=fixture(),row=f.virtual.data.resources[0];row.instances=[];row.observedInstances=0;row.executionState='no_instance';f.virtual.data.summary.observedInstances=0;
 const m=M.model(f,now),planned=m.nodes.find(n=>n.name==='edge').registered[0];
 assert.equal(planned.planned,true);assert.equal(planned.pods.length,0);assert.equal(m.totals.instances,0);
 const html=M.render(f,{},now);assert.match(html,/dm-container planned/);assert.match(html,/현재 실행 위치는 확인되지 않았습니다/);
});
test('unknown planned node never creates a physical inventory node',()=>{
 const f=fixture(),r=f.virtual.data.resources[0];r.instances=[];r.definition.spec.nodeSelector={'kubernetes.io/hostname':'invented'};
 const m=M.model(f,now);assert.equal(m.nodes.length,3);assert.equal(m.loose.length,1);
});
test('expired and failed virtual reads retain definitions but not current placement or zero counts',()=>{
 for(const fail of [true,false]){
  const f=fixture();if(fail){f.virtual.status='error';f.virtual.lastFetchFailed=true;}else f.virtual.data.observedAt='2000-01-01T00:00:00Z';
  const m=M.model(f,now);assert.equal(m.totals.definitions,1);assert.equal(m.totals.instances,null);
  assert.equal(m.nodes.find(n=>n.name==='worker').registered.length,0);
  assert.equal(m.nodes.find(n=>n.name==='edge').registered[0].row.executionState,'unknown');
  assert.equal(m.valid.resources,true);
 }
});
test('API probe failure preserves actual Pod placement and makes model readiness unknown',()=>{
 const f=fixture();f.virtual.data.resources[0].instances[0].apiObservedAt=null;
 const pod=M.model(f,now).nodes.find(n=>n.name==='worker').registered[0].pods[0];
 assert.equal(pod.podReady,true);assert.equal(pod.modelReady,null);assert.equal(pod.executionState,'unknown');
});
test('independent virtual rows survive partial observation errors',()=>{
 const f=fixture();f.virtual.status='error';f.virtual.error='other row failed';
 f.virtual.data.resources.push({...f.virtual.data.resources[0],id:'broken',instances:[],observedInstances:null,observedAt:null,observationError:'failed'});
 assert.equal(M.model(f,now).nodes.find(n=>n.name==='worker').registered[0].row.executionState,'ready');
});
test('profile expiry and failure show unknown placement without claiming current Pod readiness',()=>{
 const f=fixture();f.profiles.data.generated_at='2000-01-01T00:00:00Z';
 assert.equal(M.model(f,now).valid.profiles,false);
 const html=M.render(f,{selected:'workload:infra/collector'},now);
 assert.match(html,/배치 확인 불가/);assert.match(html,/현재 확인 불가 · 마지막 응답/);
});
test('sensor rows retain their own identity and node despite shared or absent hardware IDs',()=>{
 const f=fixture();f.devices.data[1].node_name='worker';
 f.devices.data.push({name:'unassigned',node_name:'missing'});
 const m=M.model(f,now);assert.equal(m.totals.sensors,3);assert.equal(m.nodes.length,3);
 assert.equal(m.nodes.find(n=>n.name==='edge').sensors[0].name,'temperature');
 assert.equal(m.nodes.find(n=>n.name==='worker').sensors[0].name,'light');
 const html=M.render(f,{},now);
 for(const name of ['temperature','light','unassigned'])assert.equal(html.split('data-live-device="'+name+'"').length-1,1);
 assert.doesNotMatch(html,/data-live-source=/);
 const filtered=M.render(f,{query:'temperature'},now);
 assert.match(filtered,/data-live-device="temperature"/);assert.match(filtered,/data-dm-node="edge"/);
 assert.doesNotMatch(filtered,/data-live-device="light"/);
});
test('individual sensor status is independent of node readiness and becomes unknown on fetch failure',()=>{
 const f=fixture();f.virtual.data.nodes[0].ready=false;
 Object.assign(f.devices.data[0],{overall_status:'available',telemetry_freshness:'fresh'});
 Object.assign(f.devices.data[1],{overall_status:'unavailable',telemetry_freshness:'stale'});
 const sensorRows=html=>html.match(/<button class="dm-sensor"[\s\S]*?<\/button>/g).join('');
 const current=sensorRows(M.render(f,{},now));
 assert.match(current,/사용 가능/);assert.match(current,/사용 불가/);assert.match(current,/수신 지연/);
 f.devices.status='error';f.devices.lastFetchFailed=true;
 assert.equal(M.model(f,now).totals.sensors,null);
 const failed=sensorRows(M.render(f,{},now));
 assert.match(failed,/현재 확인 불가/);assert.doesNotMatch(failed,/사용 가능|사용 불가|최신 수신/);
});
test('search preserves node context, selection is stable, and untrusted fields are escaped',()=>{
 const f=fixture();f.virtual.data.resources[0].definition.spec.displayName='<img src=x onerror=alert(1)>';
 const html=M.render(f,{query:'vd-1',selected:'vd:vd-1'},now);
 assert.match(html,/worker/);assert.match(html,/aria-pressed="true"/);assert.doesNotMatch(html,/<img/);assert.match(html,/&lt;img/);
 assert.match(M.render(f,{selected:'vd:removed'},now),/선택한 항목 확인 불가/);
});
// Retired local prototype contract; production baseline is preserved for this release.
test('new profiles GET contract rejects malformed rows', {skip:'철회한 로컬 VD 프로토타입 계약 — 운영 기준선에 미연결'},()=>{
 assert.throws(()=>global.NexusData.validate('profiles',{service_resource_profiles:[{service:'a',namespace:'test',nodes:null}]}));
 assert.deepEqual(global.NexusData.validate('profiles',{service_resource_profiles:[]}),{service_resource_profiles:[]});
});
test('physical and virtual inventories are separate flat lists, with one card per definition',()=>{
 const f=fixture();f.virtual.data.resources[0].instances.push({...f.virtual.data.resources[0].instances[0],podUid:'uid-2',node:'edge'});
 const html=M.render(f,{},now);
 const section=html.slice(html.indexOf('<section class="dm-section dm-physical-section"'),html.indexOf('<section class="dm-section dm-virtual-section"'));
 assert.equal((section.match(/data-dm-node=/g)||[]).length,3);
 assert.doesNotMatch(section,/data-dm-select=/);
 assert.equal((html.match(/data-dm-select="vd:vd-1"/g)||[]).length,1);
 assert.equal((html.match(/data-dm-select="workload:infra\/collector"/g)||[]).length,1);
 assert.match(html,/실행 위치 · worker, edge/);
});
test('selecting a physical node highlights related containers while retaining all inventories',()=>{
 const html=M.render(fixture(),{selected:'node:worker'},now);
 assert.match(html,/data-dm-node="worker" aria-pressed="true"/);
 assert.match(html,/dm-container  related/);
 assert.equal((html.match(/data-dm-node=/g)||[]).length,3);
 assert.match(html,/data-dm-select="workload:infra\/collector"/);
 assert.doesNotMatch(html,/선택한 항목 확인 불가/);
});

test('device totals count definitions once and exclude other workloads even while searching',()=>{
 const f=fixture();f.virtual.data.resources[0].instances.push({...f.virtual.data.resources[0].instances[0],podUid:'uid-2',node:'edge'});
 const html=M.render(f,{query:'temperature'},now);
 assert.match(html,/전체 디바이스 총 6개/);
 assert.match(html,/물리 디바이스 <span class="dm-count">총 5개 · 검색 결과 2개/);
 assert.match(html,/가상 디바이스 <span class="dm-count">총 1개 · 검색 결과 0개/);
 const full=M.render(f,{},now);
 const virtual=full.slice(full.indexOf('<section class="dm-section dm-virtual-section"'),full.indexOf('<details class="dm-workloads-section"'));
 assert.match(virtual,/data-dm-select="vd:vd-1"/);assert.doesNotMatch(virtual,/workload:infra/);
 assert.match(full,/<details class="dm-workloads-section" data-dm-disclosure="workloads" >/);
 assert.match(full,/기타 워크로드 <span class="dm-count">총 1개/);
 f.devices.status='error';assert.match(M.render(f,{},now),/전체 디바이스 전체 수 확인 불가/);
 f.devices.status='ready';f.virtual.lastFetchFailed=true;
 const failed=M.render(f,{},now);assert.match(failed,/전체 디바이스 전체 수 확인 불가/);assert.match(failed,/아래 항목의 등록 여부는 확인 불가/);
});

test('runtime service is one device through multiple locations, stop and observation expiry',()=>{
 const f=fixture();f.serviceVirtual.data={schema_version:'edgeai.service-virtual-devices/v1',observed_at:now/1000,total:1,running:1,devices:[{
  id:'runtime:uid',service_uid:'uid',service_name:'llama-inference',service_kind:'ai',state:'running',serving:true,checked_at:now/1000-1,
  locations:[{role:'active',node:'edge',revision:'rev-a',ready:true,observed_at:now/1000-1},{role:'preparing',node:'worker',revision:'rev-b',ready:null}],contract:{model:'llama'}}]};
 const html=M.render(f,{},now);assert.match(html,/전체 디바이스 총 7개/);
 assert.equal(html.split('data-dm-select="runtime:uid"').length-1,1);assert.match(html,/실행 위치 · edge/);assert.match(html,/준비 위치 · worker/);
 assert.match(M.render(f,{selected:'runtime:uid'},now),/서비스 UID/);
 const row=f.serviceVirtual.data.devices[0];row.state='stopped';row.serving=false;row.locations=[];
 assert.match(M.render(f,{},now),/llama-inference/);assert.match(M.render(f,{},now),/>중지</);
 const expired=M.serviceView(f.serviceVirtual,now+16000);assert.equal(expired.rows[0].state,'unknown');assert.equal(expired.total,null);
 f.serviceVirtual.lastFetchFailed=true;assert.equal(M.serviceView(f.serviceVirtual,now).rows[0].locations.length,0);
});
