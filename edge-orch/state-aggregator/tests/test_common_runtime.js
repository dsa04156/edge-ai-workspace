const test=require('node:test'),assert=require('node:assert/strict');
const R=require('../app/static/nexus/common-runtime.js');
const target={node:'new-edge',variant:'gpu',role:'edge',memoryOnlyRelease:true,observation:{at:99,health:{nodeState:'ACTIVE',ready:true,inFlight:1,modelVramMiB:1234}}};
const entry={data:{schema_version:'edgeai.common-runtime/v1',observed_at:99,services:[{name:'service-a',uid:'uid-a',phase:'Preparing',serving:true,active:target,target:{...target,node:'server-any'},retiring:[],excludedCandidates:[],reason:'waiting_for_pod_and_application_ready',lastRelease:{node:'old-edge',at:50,modelVramMiB:0,reservationRetained:true}}]}};
test('current route, preparing target and past memory release stay distinct',()=>{
 const html=R.renderState(entry,100);
 assert.match(html,/new-edge/);assert.match(html,/server-any/);assert.match(html,/1234.0 MiB/);
 assert.match(html,/마지막 모델 해제: old-edge/);assert.match(html,/GPU 예약 유지/);
});
test('stale browser cache and failed refresh do not show live model memory or health',()=>{
 for(const html of [R.renderState(entry,200),R.renderState({...entry,error:'offline'},100)]){
  assert.match(html,/현재 관측 확인 불가/);assert.doesNotMatch(html,/1234.0 MiB/);assert.doesNotMatch(html,/>ACTIVE/);
 }
});
test('loading, empty, malformed strings and absent measurements remain explicit',()=>{
 assert.match(R.renderState({data:null},100),/조회 중/);
 assert.match(R.renderState({data:{observed_at:99,services:[]}},100),/등록된 서비스가 없습니다/);
 assert.match(R.targetView({...target,node:'<img onerror=bad>',observation:null},100,true),/&lt;img/);
 assert.match(R.targetView({...target,observation:null},100,true),/메모리 —/);
});
