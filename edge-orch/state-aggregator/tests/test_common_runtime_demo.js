const test=require('node:test'),assert=require('node:assert/strict');
const D=require('../app/static/nexus/common-runtime-demo.js');
const data={enabled:true,observedAt:99,items:[{uid:'u',name:'svc',label:'Synthetic',available:true,maxRequests:512,concurrency:6}],runs:[]};
test('actions are tied to opted-in identity and disabled on stale/pending/running state',()=>{
 assert.equal(D.actions(data,'unknown',true,false),'');
 assert.match(D.actions(data,'u',true,false),/시험 요청 1건/);
 assert.doesNotMatch(D.actions(data,'u',true,false),/disabled|token|토큰 입력/);
 assert.match(D.actions(data,'u',false,false),/disabled/);
 assert.match(D.actions(data,'u',true,true),/disabled/);
 assert.match(D.actions({...data,runs:[{uid:'u',phase:'Running'}]},'u',true,false),/disabled/);
});
test('unknown acceptance retains same-ID action; failed round trip does not claim success',()=>{
 const run={id:'run',name:'<svc>',label:'synthetic',mode:'round-trip',phase:'Incomplete',createdAt:99,
  sent:2,succeeded:2,failed:0,unknown:0,returned:false,retiring:0,routeHistory:[],lastResult:'<script>bad</script>'};
 const html=D.panel({...data,runs:[run]},null,[{name:'svc',uid:'u'}],100);
 assert.match(html,/같은 실행 ID로 확인·재접수/);
 assert.match(html,/검증 미완료/);assert.match(html,/역할 복귀 미확인/);
 assert.match(html,/&lt;script&gt;/);assert.doesNotMatch(html,/<script>/);
});
test('plain HTTP UUID fallback needs no secure-context randomUUID',()=>{
 let count=0;const crypto={getRandomValues:bytes=>{bytes.fill(++count);return bytes;}};
 const first=D.newId(crypto),second=D.newId(crypto);
 assert.match(first,/^[0-9a-f]{32}$/);assert.notEqual(first,second);
});

test('approval-mode AI load is distinct from automatic round-trip',()=>{
 const html=D.actions(data,'u',true,false,true);
 assert.match(html,/data-demo-mode="load"/);assert.match(html,/AI 추론 부하 주기/);
 assert.doesNotMatch(html,/왕복 시험/);
 const run={id:'load',name:'AI',label:'fixed AI',mode:'load',phase:'Completed',createdAt:99,
 sent:20,succeeded:20,failed:0,unknown:0,returned:false,retiring:0,routeHistory:[]};
 assert.match(D.panel({...data,runs:[run]},null,[],100),/부하 시험 완료/);
 assert.doesNotMatch(D.panel({...data,runs:[run]},null,[],100),/검증 통과/);
});

test('running load has immediate local controls and honest indeterminate progress',()=>{
 const run={uid:'u',id:'r',name:'AI',mode:'load',phase:'Running',stage:'pressure',createdAt:90,sent:20,succeeded:18,failed:1,unknown:0};
 const buttons=D.actions({...data,runs:[run]},'u',true,false,true);assert.match(buttons,/실행 중…/);assert.match(buttons,/aria-busy="true"/);
 const html=D.runStatus({current:true,run},100);assert.match(html,/집중 부하 실행 중/);assert.match(html,/10초/);assert.match(html,/새 시험 요청 중단/);assert.match(html,/role="progressbar"/);assert.doesNotMatch(html,/aria-valuenow/);
 const stale=D.runStatus({current:false,run},200);assert.match(stale,/실행 상태 확인 불가/);assert.doesNotMatch(stale,/runtime-spinner|data-demo-stop|data-runtime-elapsed/);
 const stopping=D.runStatus({current:true,run:{...run,phase:'Stopping'}},100);assert.match(stopping,/요청 마무리/);assert.match(stopping,/disabled/);
 const sending=D.runStatus({current:true,sending:{mode:'load'}},100);assert.match(sending,/시작 요청 접수 중/);
 const failed=D.runStatus({current:true,run:{...run,phase:'Incomplete',finishedAt:98}},100);assert.match(failed,/검증 미완료/);assert.doesNotMatch(failed,/runtime-spinner|부하 시험 완료/);
});

test('load stop is always visible beside start, gated by exact running identity',()=>{
 let html=D.actions(data,'u',true,false,true);assert.match(html,/부하 제거/);assert.doesNotMatch(html,/data-demo-stop=/);
 const run={uid:'u',id:'exact-run',name:'svc',mode:'load',phase:'Running'};
 html=D.actions({...data,runs:[run]},'u',true,false,true);assert.match(html,/data-demo-stop="exact-run"/);assert.match(html,/id="demo-stop-control-u"/);
 const stop=html.match(/<button class="button runtime-stop"[^>]*>/)[0];assert.doesNotMatch(stop,/disabled/);
 html=D.actions({...data,runs:[{...run,phase:'Stopping'}]},'u',true,false,true);assert.match(html,/부하 제거 중/);assert.match(html.match(/<button class="button runtime-stop"[^>]*>/)[0],/disabled/);
 html=D.runStatus({current:true,inlineControls:true,run:{...run,createdAt:90,sent:2,succeeded:1,failed:0,unknown:0}},100);assert.doesNotMatch(html,/data-demo-stop=/);assert.match(html,/부하 제거:/);
});


test('service start and stop are explicit lifecycle controls, separate from node load',()=>{
 const item={...data.items[0],serviceControl:{phase:'Running',canStart:false,canStop:true}};
 let html=D.actions({...data,items:[item]},'u',true,false,true);
 assert.match(html,/서비스 실행/);assert.match(html,/서비스 중지/);assert.doesNotMatch(html,/data-demo-mode="load"/);
 assert.match(html.match(/<button id="service-start-u"[^>]*>/)[0],/disabled/);
 assert.doesNotMatch(html.match(/<button id="service-stop-u"[^>]*>/)[0],/disabled/);
 item.serviceControl={phase:'Stopped',canStart:true,canStop:false};
 html=D.serviceActions({...data,items:[item]},'u',true);
 assert.doesNotMatch(html.match(/<button id="service-start-u"[^>]*>/)[0],/disabled/);
 assert.match(html,/서비스 중지됨/);
 html=D.serviceActions({...data,items:[item]},'u',false);
 assert.match(html,/서비스 상태 확인 불가/);assert.match(html.match(/<button id="service-start-u"[^>]*>/)[0],/disabled/);
});

test('each node has its own paired controls and only the current route accepts load',()=>{
 const value={...data,items:[{...data.items[0],nodes:[{node:'nano',label:'Nano',available:true,currentRoute:true},{node:'orin',label:'Orin',available:false,currentRoute:false}]}]};
 let nano=D.nodeActions(value,'u','nano','Nano',true),orin=D.nodeActions(value,'u','orin','Orin',true);
 assert.match(nano,/Nano에 부하 주기/);assert.match(nano,/Nano 부하 제거/);assert.match(nano,/data-demo-target-node="nano"/);
 assert.doesNotMatch(nano.match(/<button id="node-load-u-nano"[^>]*>/)[0],/disabled/);
 assert.match(orin.match(/<button id="node-load-u-orin"[^>]*>/)[0],/disabled/);
 assert.match(orin,/서비스가 이 노드에서 실행되면 사용/);
 value.runs=[{uid:'u',id:'nano-run',name:'svc',targetNode:'nano',phase:'Running',sent:3,succeeded:1,cancelled:0,failed:0}];
 nano=D.nodeActions(value,'u','nano','Nano',true);orin=D.nodeActions(value,'u','orin','Orin',true);
 assert.match(nano,/data-demo-stop="nano-run"/);assert.doesNotMatch(orin,/data-demo-stop=/);
 assert.match(nano,/Nano 부하 중/);assert.match(nano,/role="progressbar"/);
 value.runs[0]={...value.runs[0],phase:'Stopped',cancelled:2,reason:'node_route_changed'};
 nano=D.nodeActions(value,'u','nano','Nano',true);assert.match(nano,/실행 노드 이동/);assert.match(nano,/취소 2/);
 const stale=D.nodeActions(value,'u','nano','Nano',false);assert.doesNotMatch(stale,/runtime-spinner|role="progressbar"/);assert.match(stale,/상태 확인 불가/);
});
