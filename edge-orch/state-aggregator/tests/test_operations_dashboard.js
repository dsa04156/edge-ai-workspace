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
