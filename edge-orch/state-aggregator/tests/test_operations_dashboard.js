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

test('node panel separates Kubernetes Ready, metric health, missing GPU and stale observations',()=>{
 const now=Date.parse('2026-09-08T00:00:00Z');
 const r=[{node:'node-a',kubernetesReady:true,reasonCodes:[]}];
 const nodes=[{hostname:'node-a',collected_at:new Date(now).toISOString(),node_health:'degraded',network_pressure:'high',raw_metrics:{cpu_utilization:0,memory_usage_ratio:.2,up:1}}];
 const html=O.nodePanel(r,nodes,true,true,now);
 assert.match(html,/Ready/);assert.match(html,/네트워크 높음/);assert.match(html,/0%/);assert.match(html,/GPU 사용률<\/span><b>미관측/);
 const failed=O.nodePanel(r,nodes,false,false,now);
 assert.match(failed,/node-a/);assert.doesNotMatch(failed,/<b>Ready<\/b>/);assert.doesNotMatch(failed,/<b>0%<\/b>/);
 const stale=O.nodePanel(r,nodes,true,true,now+120000);assert.doesNotMatch(stale,/네트워크 높음/);
});

test('usage meters retain measured zero and omit meter values for missing or invalid samples',()=>{
 assert.match(O.usageMeter('CPU',0,'node'),/aria-valuenow="0.0"/);
 assert.match(O.usageMeter('CPU',.42,'node'),/width:42.0%/);
 for(const value of [null,undefined,NaN,-1,2]){const html=O.usageMeter('GPU',value,'node');assert.match(html,/미관측/);assert.doesNotMatch(html,/aria-valuenow/);}
 assert.match(O.usageMeter('CPU',.2,'<node>'),/&lt;node&gt;/);
});


test('node status temperatures preserve component identity and hide failed or stale readings',()=>{
 const now=Date.parse('2026-09-11T06:00:00Z');
 const node={hostname:'agx',collected_at:new Date(now).toISOString(),node_health:'healthy',raw_metrics:{up:1,cpu_temperature_celsius:42.56,gpu_temperature_celsius:0}};
 let html=O.nodePanel([], [node],true,true,now);
 assert.match(html,/CPU 온도<\/span><b>42.6 °C/);assert.match(html,/GPU 온도<\/span><b>0.0 °C/);assert.match(html,/시스템 온도<\/span><b>미수집/);
 for(const invalid of [NaN,Infinity,null,'37']){node.raw_metrics.gpu_temperature_celsius=invalid;assert.match(O.nodePanel([],[node],true,true,now),/GPU 온도<\/span><b>미수집/);}
 for(const [sample,current,at] of [[node,false,now],[node,true,now+61000],[{...node,raw_metrics:{...node.raw_metrics,up:0}},true,now]]){
  html=O.nodePanel([],[sample],true,current,at);assert.doesNotMatch(html,/42.6 °C/);assert.match(html,/CPU 온도<\/span><b>—/);
 }
});
