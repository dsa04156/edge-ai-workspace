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
test('latency sample shortage, request failure and stale observations are not SLO success',()=>{
 const s={latency:{at:99,valid:true,p95Milliseconds:123,maxP95Milliseconds:100,windowSeconds:60,successfulSamples:20,failures:0}};
 assert.match(R.latencyView(s,100,true),/p95 123.0 ms \/ 기준 100 ms/);
 assert.match(R.latencyView(s,200,true),/확인 불가/);
 assert.doesNotMatch(R.latencyView(s,200,true),/123/);
 s.latency.valid=false;s.latency.failures=1;
 assert.match(R.latencyView(s,100,true),/지연 판단 대기/);
 assert.doesNotMatch(R.latencyView(s,100,true),/요청 p95/);
});

test('only AI services expose fresh exact-candidate approval and real metric units',()=>{
 const s={name:'AI test',uid:'ai-uid',aiInference:true,approvalRequired:true,serving:true,active:target,checkedAt:99,
  load:{pending:5,inFlight:1,capacity:1,qualifiedRps:4.8},latency:{at:99,p95Milliseconds:1200,maxP95Milliseconds:900,arrivalRps:4.5,completedRps:4,failures:0,samples:30,valid:true,windowSeconds:20},
  proposal:{id:'a'.repeat(32),sourceNode:'edge',node:'server',reason:'sustained_pressure',expiresAt:160,qualifiedRps:6,qualifiedP95Milliseconds:456}};
 const html=R.augmentationView(s,100,true);
 assert.match(html,/1,200/);assert.match(html,/4.8/);assert.match(html,/증강 승인/);assert.doesNotMatch(html,/disabled/);
 assert.match(R.augmentationView(s,200,false),/disabled/);
 assert.doesNotMatch(R.augmentationView(s,200,false),/1,200/);
 assert.match(R.augmentationView({...s,target:{}},100,true),/disabled/);
 assert.equal(R.augmentationView({...s,aiInference:false},100,true),'');
});
