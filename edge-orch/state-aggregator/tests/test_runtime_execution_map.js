const test=require('node:test'),assert=require('node:assert/strict');
const M=require('../app/static/nexus/runtime-execution-map.js');
const s={uid:'service-one',name:'vision',phase:'Serving',serving:true,active:{name:'a',node:'edge-a'},retiring:[]};
const m={ok:true,title:'요청 대기 중',busy:false,load:{pending:0,inFlight:0}};
const decision={at:99,generation:1,status:'Preparing',reason:'sustained_pressure',basis:'smallest_sufficient_capacity',sourceNode:'edge-a',selectedRevision:'b',candidates:[{rank:1,node:'server-b',variant:'fast',capacity:2,qualifiedRps:5,qualifiedP95Milliseconds:90},{rank:2,node:'server-c',variant:'fast',capacity:2,qualifiedRps:5,qualifiedP95Milliseconds:90}]};
const options={nodes:[{node:'edge-a',state:'active',title:'요청 대기 중'},{node:'server-b',state:'candidate',title:'배치 후보'}],hardware:()=>({current:true,cpu:0,memory:.2,gpu:null})};
test('running map shows service location without invented ranks or idle animation',()=>{
 const html=M.render(s,m,100,options);assert.match(html,/● 요청 대기 · vision/);assert.match(html,/후보 순위 대기/);assert.doesNotMatch(html,/execution-rank"|flowing/);assert.match(html,/GPU <b>미수집/);
 assert.match(M.render(s,{...m,busy:true},100,options),/flowing/);
});
test('controller ranks match nodes and target revision while preparation can exceed observation age',()=>{
 const x={...s,target:{name:'b',node:'server-b'},placementDecision:decision};
 assert.equal(M.view(x,m,130).step,3);
 const html=M.render(x,m,130,options);assert.match(html,/<b>1위<\/b> fast · 선택/);assert.match(html,/<b>2위<\/b>/);assert.match(html,/data-execution-node="server-c"/);assert.match(html,/현재보다 큰 검증 용량 중 작은 순/);
 assert.doesNotMatch(M.render({...x,target:{name:'other',node:'elsewhere'}},m,130,options),/execution-rank"/);
});
test('stopped stale and historical decisions cannot claim live ranks or paths',()=>{
 for(const [x, motion] of [[{...s,phase:'Suspended',serving:false,placementDecision:decision},m],[{...s,placementDecision:decision},{...m,ok:false}]]){
  const html=M.render(x,motion,100,options);assert.doesNotMatch(html,/execution-rank"|flowing|● 처리 중/);assert.equal(M.view(x,motion,100).step,-1);
 }
 const html=M.render({...s,placementDecision:{...decision,status:'Historical'}},m,100,options);assert.doesNotMatch(html,/execution-rank"/);
});
test('detection, candidate exhaustion, approval, switch and drain are distinct states',()=>{
 assert.equal(M.view({...s,policyObservation:{at:99,pressureElapsedSeconds:3}},m,100).step,1);
 assert.equal(M.view({...s,placementDecision:{...decision,status:'Evaluated',candidates:[]}},m,100).step,2);
 assert.equal(M.view(s,{...m,p:{node:'server-b'}},100).step,2);
 const switched={...s,active:{name:'b',node:'server-b'},placementDecision:{...decision,status:'Applied',appliedAt:99}};
 assert.equal(M.view(switched,m,100).step,4);assert.match(M.render(switched,m,100,options),/전환 당시 1위/);
 assert.equal(M.view({...switched,retiring:[{node:'edge-a'}]},m,100).step,5);
});
test('selected service scope escaping and existing node actions are preserved',()=>{
 const calls=[];globalThis.NexusRuntimeDemo={renderNodeActions:(uid,node)=>{calls.push([uid,node]);return '<button>부하 제거</button>';}};
 const html=M.render({...s,aiInference:true,name:'<script>bad</script>'},m,100,options);
 assert.deepEqual(calls,[['service-one','edge-a'],['service-one','server-b']]);assert.match(html,/부하 제거/);assert.doesNotMatch(html,/<script>/);assert.match(html,/&lt;script&gt;/);
 delete globalThis.NexusRuntimeDemo;
});

test('generic suspended model keeps execution-verified nodes without fabricated stages',()=>{
 const C=require('../app/static/nexus/common-runtime.js');
 const x={...s,phase:'Suspended',serving:false,active:null,contractSummary:{candidateNodes:['raspi','server']}};
 const ns=C.mapNodes(x,m,100);assert.deepEqual(ns.map(n=>n.node),['raspi','server']);assert.ok(ns.every(n=>n.state==='stopped'));
});
