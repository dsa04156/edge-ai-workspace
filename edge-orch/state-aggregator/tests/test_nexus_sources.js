const test=require('node:test');
const assert=require('node:assert/strict');
const S=require('../app/static/nexus/source-view.js');
const D=require('../app/static/nexus/live-data.js');
const devices=[
  {name:'temperature',physical_device_id:'arduino-001',profile_name:'temperature-profile'},
  {name:'light',physical_device_id:'arduino-001'},
  {name:'temperature',physical_device_id:'sensehat-001'},
  {name:'arduino-looking-name',node_name:'arduino-001'}
];
const twins=[
  {id:'t-a',name:'temperature',physical_device_id:'arduino-001',service_bindings:[{service_id:'s1',service_name:'품질'},{service_id:'s2',service_name:'이상감지'}]},
  {id:'t-b',name:'light',physical_device_id:'arduino-001',service_bindings:[{service_id:'s1'}]},
  {id:'t-c',name:'temperature',physical_device_id:'sensehat-001',service_bindings:[{service_id:'s3'}]},
  {id:'orphan',name:'unknown',physical_device_id:'arduino-001',service_bindings:[{service_id:'not-bound'}]}
];
test('physical identity and exact device name join twins without inventing links',()=>{
  const g=S.buildSources(devices,twins);
  assert.equal(g.sources.length,2);assert.equal(g.unassigned.length,1);
  const a=g.sources[0];assert.equal(a.functions.length,2);assert.equal(a.functions[0].twin.id,'t-a');
  assert.deepEqual([...a.services.keys()],['s1','s2']);assert.equal(a.services.get('s1').length,2);
  assert.equal(g.sources[1].functions[0].twin.id,'t-c');
});
test('search selects whole physical equipment, preserving sibling functions and N:M counts',()=>{
  const all=S.buildSources(devices,twins).sources;
  for(const query of ['LIGHT','이상감지','temperature-profile']){
    const rows=S.searchSources(all,query);assert.equal(rows.length,1);assert.equal(rows[0].functions.length,2);assert.equal(rows[0].services.size,2);
  }
  assert.equal(S.searchSources(all,'missing').length,0);
});
const render=overrides=>S.render({devices,twins,services:[],query:'',selected:'arduino-001',deviceCurrent:true,twinCurrent:true,serviceCurrent:true,escape:D.escape,status:(v,current)=>current?D.escape(v):'현재 확인 불가',date:v=>v||'시각 없음',...overrides});
test('missing and failed twin observations remain unknown, distinct from a confirmed empty binding',()=>{
  assert.match(render({twins:[],twinCurrent:false}),/연결 확인 불가/);
  assert.doesNotMatch(render({twins:[],twinCurrent:false}),/등록된 연결 없음/);
  assert.match(render({twins:[{id:'t-a',name:'temperature',physical_device_id:'arduino-001',service_bindings:[]}]}),/등록된 연결 없음/);
  assert.match(render({deviceCurrent:false}),/마지막으로 받은 등록/);
  assert.doesNotMatch(render({twins:[]}),/이 장비의 기능에 등록된 서비스 연결이 없습니다/);
  assert.match(render({twins:[]}),/연결 서비스 —개/);
});
test('source selection and untrusted identifiers render safely with no imaginary augmentation binding',()=>{
  const html=render({selected:'sensehat-001'});
  assert.match(html,/id="source-detail-title"[^>]*>sensehat-001/);
  assert.doesNotMatch(html,/id="source-detail-title"[^>]*>arduino-001/);
  assert.match(html,/별도 시험/);
  const malicious=render({devices:[{name:'<img src=x onerror=alert(1)>',physical_device_id:'<script>evil</script>'}],twins:[]});
  assert.doesNotMatch(malicious,/<script>|<img/);assert.match(malicious,/&lt;script&gt;/);
});
test('physical virtual identity survives readings, runtime changes and function reordering',()=>{
  const a=S.buildSources(devices,twins).sources[0];
  const changed=S.buildSources([...devices].reverse().map(d=>({...d,node_name:'new-node',latest_readings:[{resource_name:'temperature',value:999}]})),twins).sources[0];
  assert.deepEqual(S.virtualDevice(a),S.virtualDevice(changed));
  const vd=S.virtualDevice(a);assert.equal(vd.id,'physical-vd:arduino-001');assert.equal(vd.physicalSourceId,'arduino-001');
  assert.deepEqual(vd.serviceIds,['s1','s2']);assert.equal(vd.accessMode,'read-only');
  assert.notEqual(S.virtualDevice({...a,id:'a/b'}).id,S.virtualDevice({...a,id:'a%2Fb'}).id);
});
test('virtual view exposes distinct logical identity and exact original source navigation',()=>{
  const html=render({view:'virtual',selected:'sensehat-001'});
  assert.match(html,/가상 디바이스 선택/);assert.match(html,/id="physical-vd-id">physical-vd:sensehat-001/);
  assert.match(html,/data-live-source="sensehat-001">원본 장비 보기/);
  assert.match(render({selected:'arduino-001'}),/data-open-physical-vd="arduino-001"/);
  const groups=S.buildSources(devices,twins);
  assert.equal(S.searchSources(groups.sources,'physical-vd:sensehat-001')[0].id,'sensehat-001');
});
test('unassigned devices cannot manufacture a physical virtual device; unavailable source stays unknown',()=>{
  const g=S.buildSources([{name:'arduino-001',node_name:'arduino-001'}],[]);
  assert.equal(g.sources.length,0);assert.equal(g.unassigned.length,1);
  const html=render({view:'virtual',deviceCurrent:false,twinCurrent:false});
  assert.match(html,/physical-vd:arduino-001/);assert.match(html,/마지막으로 받은 등록/);assert.match(html,/연결 서비스 —개/);
});
