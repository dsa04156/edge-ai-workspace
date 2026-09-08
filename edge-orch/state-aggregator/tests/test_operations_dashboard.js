const test=require('node:test'),assert=require('node:assert/strict');
global.NexusData=require('../app/static/nexus/live-data.js');
const O=require('../app/static/nexus/operations.js');
const X=require('../app/static/nexus/data-explorer.js');
test('telemetry preserves zero but rejects missing boolean empty and nonfinite values',()=>{
 assert.equal(X.numeric(0),0);for(const x of [null,undefined,true,false,'',' ',Infinity,'NaN',{}])assert.equal(X.numeric(x),null);
});
test('series separates devices/resources and detects duplicates before statistics',()=>{
 const p={device_name:'d',resource_name:'x',event_id:'e',timestamp:'2026-09-08T00:00:00Z',value:0};
 const gs=X.series([p,p,{...p,event_id:'e2',value:10,timestamp:'2026-09-08T00:00:01Z'},{...p,resource_name:'y',value:4},{...p,event_id:'bad',value:null}]);
 assert.equal(gs.length,2);assert.equal(gs[0].count,2);assert.equal(gs[0].avg,5);assert.equal(gs[0].duplicates,1);assert.equal(gs[0].invalid,1);assert.equal(gs[0].intervalMs,1000);
});
test('failed or aged integration response cannot retain Applied or live metrics',()=>{
 const data={generated_at:'2026-09-08T00:00:00Z',services:[{observation_state:'Observed',quality:{valid:true,backlog:0},application:{state:'Applied'},bindings:[],stages:[{state:'PROCESSING_OBSERVED',executors:[{state:'Observed',observed_nodes:['edge'],pods:['pod'],resources:{}}]}]}]};
 const out=O.observedData({data,lastFetchFailed:true},Date.parse(data.generated_at)+1);
 assert.equal(out.services[0].application.state,'Unknown');assert.equal(out.services[0].quality.backlog,null);assert.deepEqual(out.services[0].stages[0].executors[0].observed_nodes,[]);
 assert.equal(data.services[0].application.state,'Applied');
 assert.equal(O.observedData({data},Date.parse(data.generated_at)+61000).services[0].observation_state,'Unknown');
});
test('timeline escapes payloads and never upgrades failed operation to applied',()=>{
 const html=O.timeline({events:[{service_id:'svc',type:'<script>alert(1)</script>',state:'FAILED',timestamp:'2026-09-08T00:00:00Z',reasons:['<img>'],source:'/api/executions'}]});
 assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>'));assert.ok(html.includes('FAILED'));assert.ok(!html.includes('Applied'));
});
test('unloaded operations do not claim absence of issues; KPI goals have no measurements',()=>{
 assert.match(O.issues(null),/현재 문제 여부 미확인/);
 const html=O.validation();assert.equal((html.match(/NOT_MEASURED/g)||[]).length,8);assert.match(html,/250 ms/);assert.match(html,/99.99 %/);
});

test('service summary distinguishes ready pods, active processing and missing observation',()=>{
 const svc={observation_state:'Observed',execution_ownership:{effective_mode:'STANDBY',reason_code:'execution_lease_expired'},bindings:[{state:'available'}],application:{state:'NOT_APPLIED'},quality:{valid:false},latest_result:null};
 assert.match(O.serviceSummary(svc),/AI 처리가 중단/);
 assert.match(O.serviceSummary(svc),/센서 데이터 수신 정상/);
 assert.match(O.serviceSummary(svc),/실행 권한/);
 assert.match(O.serviceSummary({...svc,observation_state:'Unknown'}),/AI 처리 상태를 확인할 수 없습니다/);
 assert.match(O.serviceSummary({...svc,execution_ownership:{effective_mode:'ACTIVE'}}),/AI 처리 여부를 확인해야/);
 assert.match(O.serviceSummary({...svc,execution_ownership:{effective_mode:'ACTIVE'},quality:{valid:true,throughput_per_second:2}}),/AI 서비스의 처리가 관측됩니다/);
});
test('stage locations describe workload observation without claiming AI execution',()=>{
 const html=O.stageView({label:'추론',state:'STANDBY',stage_id:'inference',depends_on:[],evidence:'공유 지표',executors:[{state:'Observed',observed_nodes:['node-a'],configured_node:'node-b',pod_ready_count:1,workload:'svc',pods:['pod-a']}]});
 assert.match(html,/관측된 배포 노드/);assert.match(html,/AI 처리 상태와 별도/);assert.match(html,/AI 처리 중단/);assert.doesNotMatch(html,/실행 위치/);
});
