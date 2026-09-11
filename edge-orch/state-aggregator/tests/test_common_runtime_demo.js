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
