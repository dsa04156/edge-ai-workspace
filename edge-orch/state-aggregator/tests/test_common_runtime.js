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

test('node map distinguishes idle, observed traffic, recommendation, preparation and stale state',()=>{
 const s={uid:'map',name:'AI',serving:true,checkedAt:99,active:target,retiring:[],eligibleCandidates:[{node:'candidate',role:'server',variant:'gpu'}],load:{at:99,pending:0,inFlight:0}};
 let m=R.serviceMotion(s,100,true);assert.equal(m.title,'요청 대기 중');
 assert.equal(R.mapNodes(s,m,100).find(n=>n.node==='candidate').state,'candidate');
 assert.doesNotMatch(R.runtimeMap(s,m,100),/flowing/);
 s.load.inFlight=1;m=R.serviceMotion(s,100,true);assert.equal(m.title,'AI 추론 실행 중');assert.match(R.runtimeMap(s,m,100),/flowing/);
 s.proposal={node:'candidate',role:'server',expiresAt:160};m=R.serviceMotion(s,100,true);assert.equal(m.title,'추천 도착 · 승인 대기');
 assert.equal(R.mapNodes(s,m,100).find(n=>n.node==='candidate').state,'recommended');
 s.target={node:'candidate',role:'server'};m=R.serviceMotion(s,100,true);assert.equal(m.title,'모델 준비 중');assert.equal(R.mapNodes(s,m,100).find(n=>n.node==='candidate').state,'preparing');
 m=R.serviceMotion(s,200,true);assert.equal(m.ok,false);assert.doesNotMatch(R.runtimeMap(s,m,200),/flowing|runtime-spinner|1234/);
});

test('hardware meters use node telemetry freshness and distinguish missing GPU from zero',()=>{
 const node={hostname:'server',collected_at:new Date(99000).toISOString(),node_health:'healthy',raw_metrics:{up:1,cpu_utilization:.25,memory_usage_ratio:.5,gpu_utilization:0}};
 const entry={data:[node],receivedAt:99,error:null};
 let m=R.nodeMetrics('server',100,entry);assert.equal(m.cpu,.25);assert.equal(m.gpu,0);assert.equal(m.current,true);
 let html=R.nodeMetricsView('server',100,entry);assert.match(html,/25.0%/);assert.match(html,/50.0%/);assert.match(html,/0.0%/);
 delete node.raw_metrics.gpu_utilization;html=R.nodeMetricsView('server',100,entry);assert.match(html,/미수집/);assert.doesNotMatch(html,/aria-label="노드 GPU 사용률"/);
 for(const e of [{...entry,error:'offline'},{...entry,receivedAt:10},{...entry,data:[{...node,collected_at:new Date(1000).toISOString()}]},{...entry,data:[{...node,raw_metrics:{...node.raw_metrics,up:0}}]}]){
  m=R.nodeMetrics('server',100,e);assert.equal(m.current,false);assert.equal(m.cpu,null);assert.doesNotMatch(R.nodeMetricsView('server',100,e),/25.0%|role="meter"/);
 }
});
