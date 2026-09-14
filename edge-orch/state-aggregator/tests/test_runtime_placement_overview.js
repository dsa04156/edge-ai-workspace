const test=require('node:test'),assert=require('node:assert/strict');
const P=require('../app/static/nexus/runtime-placement-overview.js');
const s={uid:'a',name:'vision-service',phase:'Serving',serving:true,checkedAt:99,active:{node:'node-a'},retiring:[],eligibleCandidates:[{node:'node-a',variant:'gpu'},{node:'node-b',variant:'cpu'}],excludedCandidates:[{node:'node-b',variant:'wrong-gpu',reasons:['selector_or_architecture_mismatch']},{node:'node-c',variant:'cpu',reasons:['insufficient:memory']}],augmentationStages:[{node:'node-a',variant:'gpu',qualifiedRps:4,qualifiedP95Milliseconds:100}],contractSummary:{model:'vision',candidateNodes:['node-a','node-b'],defaultNode:'node-a',inputType:'image',cpuRequest:'500m'}};
const resource={node:'node-c',kubernetesReady:true,schedulable:true,architecture:'amd64',available:{cpuCores:0,memoryBytes:1e9,acceleratorUnits:{'nvidia.com/gpu.shared':1}},allocatable:{cpuCores:4,memoryBytes:8e9},requested:{cpuCores:4,memoryBytes:7e9}};
const o={now:100,current:true,nodes:[{hostname:'node-a'},{hostname:'node-d'}],resources:[resource],resourcesCurrent:true,hardware:()=>({current:true,cpu:0,memory:.5,gpu:null})};
test('all node sources are merged and one rejected variant cannot exclude an accepted node',()=>{
 const rs=P.rows(s,o);assert.equal(rs.length,4);assert.equal(rs.find(r=>r.node==='node-b').status,'eligible');assert.equal(rs.find(r=>r.node==='node-c').status,'excluded');assert.equal(rs.find(r=>r.node==='node-d').status,'unassessed');assert.equal(rs[0].status,'active');
 const html=P.render(s,o);assert.match(html,/전체 노드 · 실행 후보/);assert.match(html,/CPU 0 cores/);assert.match(html,/GPU 미측정/);assert.doesNotMatch(html,/GPU 0%/);
 assert.match(html,/예약 자원 부족 · memory/);assert.doesNotMatch(html,/data-demo-start|data-service-action|data-augmentation-approve/);
});
test('stopped and stale service observations never turn old candidate outcomes into current claims',()=>{
 for(const stopped of [{...s,phase:'Suspended',active:null,serving:false},{...s,checkedAt:1}]){
  const rs=P.rows(stopped,o);assert.ok(rs.every(r=>['paused','unknown'].includes(r.status)));
  const html=P.render(stopped,{...o,selectedNode:'node-c'});assert.match(html,/현재 판단 아님/);
  assert.doesNotMatch(html,/placement-state eligible|placement-state excluded|placement-row active/);
 }
 const html=P.render({...s,phase:'Suspended'},o);assert.match(html,/재평가 대기/);assert.match(html,/4건\/s/);
});
test('missing and stale resource measurements are not usable capacity or inferred GPU zero',()=>{
 const html=P.render(s,{...o,resourcesCurrent:false,hardware:()=>({current:false,cpu:.1}),selectedNode:'node-c'});
 assert.match(html,/관측 확인 필요/);assert.doesNotMatch(html,/CPU 0 cores|CPU 4 cores|GPU 0%|10%/);
 const down=P.render(s,{...o,resources:[{...resource,kubernetesReady:false}]});assert.match(down,/현재 배치 제한/);
});
test('unmanaged service sees cluster inventory but no service suitability claim',()=>{
 const html=P.render({uid:'catalog:new',name:'unintegrated',managed:false},o);
 assert.match(html,/공통 자동 배치 미연결/);assert.match(html,/모델 정보 미연결/);assert.match(html,/node-d/);assert.doesNotMatch(html,/placement-state eligible|data-demo-start/);
});
test('filter and selected detail remain scoped to the selected service',()=>{
 const html=P.render(s,{...o,filter:'excluded',selectedNode:'node-c'});assert.match(html,/data-placement-node="node-c"/);assert.doesNotMatch(html,/data-placement-node="node-a"/);assert.match(html,/nvidia.com\/gpu.shared: 1/);
 const other=P.render({uid:'b',name:'service-b',checkedAt:99,serving:true,phase:'Serving'}, {...o,selectedNode:'node-c'});
 assert.doesNotMatch(other,/vision|wrong-gpu|4건\/s/);
});
test('unsafe text is escaped and prepare/drain/approval steps use current evidence',()=>{
 const html=P.render({...s,name:'<img onerror=bad>',contractSummary:{model:'<script>bad</script>'}},o);
 assert.match(html,/&lt;img/);assert.doesNotMatch(html,/<script>bad/);
 assert.equal(P.decision({...s,target:{node:'node-b'}},o).step,2);
 assert.equal(P.decision({...s,retiring:[{node:'old'}]},o).step,4);
 assert.equal(P.decision({...s,proposal:{node:'node-b',expiresAt:101}},o).step,1);
 assert.equal(P.decision({...s,proposal:{node:'node-b',expiresAt:99}},o).step,0);
 assert.equal(P.decision(s,{...o,current:false}).step,-1);
});
