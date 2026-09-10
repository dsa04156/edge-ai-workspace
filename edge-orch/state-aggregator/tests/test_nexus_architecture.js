const test = require('node:test');
const assert = require('node:assert/strict');
const architecture = require('../app/static/nexus/architecture.js');
const snapshot = require('../app/static/nexus/service-architecture.json');
const catalog = require('../app/config/service_catalog.json');

test('workload selector preserves namespace identity without inventing service connections', () => {
  const now=Date.now(),generated_at=new Date(now).toISOString();
  const data={generated_at,service_resource_profiles:[
    {namespace:'a',service:'worker',nodes:['edge'],generated_at},
    {namespace:'b',service:'worker',nodes:['server'],generated_at},
  ]};
  const rows=architecture.workloadEntries(data);
  assert.deepEqual(rows.map(s=>s.id),['workload:a/worker','workload:b/worker']);
  for(const s of rows){assert.equal(s.kind,'workload');assert.deepEqual(s.inputs,[]);assert.deepEqual(s.links,[]);assert.equal(s.physicalSource,null);}
  assert.deepEqual(architecture.selectedLocations(rows[0],data,false,now).flatMap(w=>w.p.nodes),['edge']);
  assert.deepEqual(architecture.selectedLocations(rows[1],data,false,now).flatMap(w=>w.p.nodes),['server']);
  assert.deepEqual(architecture.selectedLocations(rows[0],data,true,now).flatMap(w=>w.p.nodes),[]);
  assert.deepEqual(architecture.selectedLocations(rows[0],{generated_at,service_resource_profiles:[]},false,now).map(w=>w.p.status),['absent']);
});

test('AI runtime observations are independent from Pod placement and expire', () => {
  const now=Date.now(),time=new Date(now).toISOString();
  const s=architecture.parse({generated_at:time,services:[{...snapshot.services[0],mode:'live',status:'normal',latest_observed_at:time,inference_target:'server1',execution_ownership:{observed_at:time,effective_mode:'STANDBY',reason_code:'execution_lease_expired'}}]})[0];
  assert.equal(architecture.runtimeSummary(s,now).label,'처리 대기');
  assert.match(architecture.runtimeSummary(s,now).detail,/lease 만료/);
  s.runtime.ownership.effective_mode='ACTIVE';
  assert.equal(architecture.runtimeSummary(s,now).label,'최근 정상 판정');
  s.runtime.latest=new Date(now-91000).toISOString();
  assert.equal(architecture.runtimeSummary(s,now).label,'최근 처리 미관측');
  assert.equal(architecture.runtimeSummary(s,now+91000).label,'처리 상태 미확인');
  s.runtime.mode='unavailable';
  assert.equal(architecture.runtimeSummary(s,now).label,'처리 상태 미확인');
});

test('hardware artwork is limited to known node identities', () => {
  assert.equal(architecture.hardware('etri-dev0001-jetorn').kind,'jetson');
  assert.equal(architecture.hardware('etri-dev0003-raspi5').kind,'raspberry-pi');
  assert.equal(architecture.hardware('etri-ser0002-cgnmsb').kind,'server');
  assert.equal(architecture.hardware('unregistered-jetson-server').src,null);
});

test('device arrows require contract dependencies and fresh exact workload observations', () => {
  const service=architecture.normalize({service_id:'test',workload:{namespace:'demo'},graph:{stages:[
    {stage_id:'input',executions:[{executor:'reader'}]},
    {stage_id:'result',depends_on:['input'],executions:[{executor:'model'}]},
  ]}});
  const now=Date.now(),generated_at=new Date(now).toISOString();
  const data={generated_at,service_resource_profiles:[
    {namespace:'demo',service:'reader',nodes:['edge'],generated_at},
    {namespace:'demo',service:'model',nodes:['server','server'],generated_at},
    {namespace:'another',service:'model',nodes:['unrelated'],generated_at},
  ]};
  assert.deepEqual(architecture.nodeLinks(service,data,false,now),[{from:'edge',to:'server',key:'input→result',label:'input → result'}]);
  assert.deepEqual(architecture.nodeLinks(service,data,true,now),[]);
  assert.deepEqual(architecture.nodeLinks(service,data,false,now+91000),[]);
  data.service_resource_profiles[1].nodes=['edge'];
  assert.deepEqual(architecture.nodeLinks(service,data,false,now),[]);
  data.service_resource_profiles[1].namespace='other';
  assert.deepEqual(architecture.nodeLinks(service,data,false,now),[]);
});

test('observed placement uses namespace and workload identity, never configured node as fallback', () => {
  const service=architecture.normalize(snapshot.services[0]),stage=service.stages[1],execution=stage.executions[0],now=Date.now();
  const profile={namespace:service.workload.namespace,service:execution.executor,nodes:['observed-other-node'],generated_at:new Date(now).toISOString()};
  const data={generated_at:profile.generated_at,service_resource_profiles:[profile]};
  assert.deepEqual(architecture.placement(service,stage,execution,data,false,now).nodes,['observed-other-node']);
  assert.equal(architecture.placement(service,stage,execution,data,true,now).status,'unknown');
  assert.equal(architecture.placement(service,stage,execution,data,false,now+91000).status,'stale');
  profile.namespace='unrelated';
  assert.equal(architecture.placement(service,stage,execution,data,false,now).status,'absent');
  profile.namespace=service.workload.namespace;profile.generated_at=new Date(now-91000).toISOString();
  assert.equal(architecture.placement(service,stage,execution,data,false,now).status,'stale');
});

test('Git preview preserves registered stages, inputs and configured targets', () => {
  assert.deepEqual(snapshot.services.map(s => s.service_id), catalog.services.map(s => s.service_id));
  for (const item of snapshot.services) {
    const original = catalog.services.find(s => s.service_id === item.service_id);
    assert.deepEqual(item.descriptor.graph, original.graph);
    assert.deepEqual(item.descriptor.design_contract, original.design_contract);
    assert.equal(item.descriptor.runtime_offloading?.endpoint_base_url, undefined);
    assert.deepEqual(item.descriptor.runtime_offloading?.target_workload, original.runtime_offloading?.target_workload);
    const service = architecture.normalize(item);
    assert.equal(service.links.length, original.graph.stages.reduce((n, s) => n + s.depends_on.length, 0));
    assert.equal(service.inputs.length, original.design_contract.inputs.length);
  }
});

test('multiple services retain their own graph and shared inputs without mixing contracts', () => {
  const one = structuredClone(snapshot.services[0]);
  const two = structuredClone(one);
  two.service_id = 'test-second-service';
  two.descriptor.graph.stages = [
    {stage_id:'output', label:'출력', depends_on:['input'], executions:[]},
    {stage_id:'input', label:'입력', depends_on:[], executions:[]},
  ];
  const result = architecture.parse({services:[one,two]});
  assert.equal(result[0].stages.length, 5);
  assert.deepEqual(result[1].stages.map(s => s.stage_id), ['input','output']);
  assert.deepEqual(result[0].inputs, result[1].inputs);
  assert.equal(result[1].links[0].key, 'input→output');
});

test('invalid, dangling and cyclic contracts fail instead of drawing invented paths', () => {
  assert.throws(() => architecture.parse({}), /응답 형식/);
  assert.deepEqual(architecture.parse({services:[]}), []);
  for (const stages of [
    [{stage_id:'a',depends_on:['missing']}],
    [{stage_id:'a',depends_on:['b']},{stage_id:'b',depends_on:['a']}],
    [{stage_id:'a'},{stage_id:'a'}],
  ]) assert.throws(() => architecture.normalize({service_id:'test',graph:{stages}}));
});

test('runtime payload design contract is used and operation link preserves service identity', () => {
  const item = structuredClone(snapshot.services[0]);
  item.design_contract = {inputs:[{device_name:'live-device',resource_name:'temperature'}]};
  delete item.descriptor.design_contract;
  assert.equal(architecture.normalize(item).inputs[0].device_name, 'live-device');
  const link = architecture.serviceLink({id:'service/a?b&c'});
  const url = new URL(link, 'http://localhost');
  assert.equal(url.searchParams.get('service'), 'service/a?b&c');
  assert.equal(url.hash, '#service-detail');
});
