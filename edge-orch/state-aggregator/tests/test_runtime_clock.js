const test=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs'),path=require('node:path');
function harness(){
 const clock={wall:100000,mono:10000};
 const service={uid:'llama',name:'llama',aiInference:true,approvalRequired:true,phase:'Serving',serving:true,checkedAt:99,active:{name:'route',node:'orin',variant:'orin'},retiring:[],excludedCandidates:[],load:{at:99,pending:0,inFlight:0}};
 const runtime={schema_version:'edgeai.common-runtime/v1',observed_at:100,services:[service]};
 const demo={enabled:true,observedAt:100,items:[{uid:'llama',name:'llama',available:true,nodes:[{node:'orin',label:'Orin',available:true,currentRoute:true}],serviceControl:{phase:'Running',canStop:true}}],runs:[]};
 const network={runtime},intervals=[];
 const context=vm.createContext({document:{addEventListener(){}},setInterval:fn=>{intervals.push(fn);return intervals.length;},clearInterval(){},Date:class extends Date{static now(){return clock.wall;}},performance:{now:()=>clock.mono},setTimeout,clearTimeout,AbortController,fetch:async url=>({ok:true,json:async()=>url==='/state/runtime-services'?network.runtime:url==='/state/nodes'?[]:demo}),localStorage:{setItem(){}}});
 for(const name of ['common-runtime-demo.js','common-runtime.js']) vm.runInContext(fs.readFileSync(path.join(__dirname,'../app/static/nexus',name),'utf8'),context);
 return {clock,runtime,demo,network,intervals,R:context.NexusCommonRuntime,D:context.NexusRuntimeDemo};
}
test('new observations stay current across PC clock skew and jumps; monotonic age still expires them',async()=>{
 const {clock,runtime,R,D}=harness();
 await D.refresh();
 const entry={data:runtime,error:null,receivedMonotonic:10};
 for(const wall of [99500,101000,4000000,-4000000]){
  clock.wall=wall;
  const html=R.renderState(entry);
  assert.match(html,/요청 대기 중/);assert.doesNotMatch(html,/최신 관측 확인 불가/);
  assert.equal(D.context('llama').current,true);
  assert.doesNotMatch(D.renderNodeActions('llama','orin','Orin',true),/data-demo-mode="node-load"[^>]*disabled/);
 }
 clock.mono=26000;
 assert.match(R.renderState(entry),/최신 관측 확인 불가/);
 assert.equal(D.context('llama').current,false);
 assert.match(D.renderNodeActions('llama','orin','Orin',true),/data-demo-mode="node-load"[^>]*disabled/);
});
test('actual service staleness and request errors remain visible despite fresh transport',()=>{
 const {runtime,R}=harness();
 runtime.services[0].checkedAt=70;
 runtime.services[0].observation_error='runtime_service_observation_stale';
 let html=R.renderState({data:runtime,receivedMonotonic:10});
 assert.match(html,/서비스 상태 갱신이 지연/);assert.match(html,/마지막 서비스 관측/);
 assert.doesNotMatch(html,/관측 연결 확인 중/);
 html=R.renderState({data:runtime,receivedMonotonic:10,error:'조회 시간 초과'});
 assert.ok(html.indexOf('조회 시간 초과')<html.indexOf('runtime-diagnostics'));
});

test('source outage retains last service identity, shows error and recovers on next successful poll',async()=>{
 const {R,network,runtime,intervals}=harness();
 R.activate(true);await new Promise(setImmediate);
 assert.match(R.render(),/요청 대기 중/);
 network.runtime={schema_version:'edgeai.common-runtime/v1',observed_at:100,observation_error:'runtime_source_unavailable',services:[]};
 intervals[1]();await new Promise(setImmediate);
 const failed=R.render();assert.match(failed,/data-augmentation-service="llama"/);assert.match(failed,/제어기 응답을 받지 못했습니다/);assert.match(failed,/마지막 확인 상태: 요청 처리 가능/);assert.match(failed,/최신 관측 확인 불가/);
 network.runtime=runtime;intervals[1]();await new Promise(setImmediate);
 assert.match(R.render(),/요청 대기 중/);assert.doesNotMatch(R.render(),/제어기 응답을 받지 못했습니다/);
 R.activate(false);
});
