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
