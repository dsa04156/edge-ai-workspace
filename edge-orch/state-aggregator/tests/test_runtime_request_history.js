const test=require('node:test'),assert=require('node:assert/strict');
const H=require('../app/static/nexus/runtime-request-history.js');
const row={seq:1,uid:'u',requestId:'<request>',startedAt:100,state:'rejected',status:503,reason:'admission_timeout',admittedNode:'nano',node:null,gatewayQueueMilliseconds:30000,workerRoundTripMilliseconds:null,inferenceMilliseconds:null,totalMilliseconds:30001};
const value={items:[row],observedAt:100,retentionSeconds:604800,retainedPerOutcomeClass:10000};
test('failure record distinguishes no dispatch, missing inference and measured zero',()=>{
 let html=H.view('u','svc',{mode:'failures',value});
 assert.match(html,/gateway 대기 시간 초과/);assert.match(html,/미전송/);assert.match(html,/30,000 ms/);assert.match(html,/미측정/);
 assert.match(html,/&lt;request&gt;/);assert.doesNotMatch(html,/<request>/);
 html=H.view('u','svc',{value:{...value,items:[{...row,node:'orin',inferenceMilliseconds:0}]}});
 assert.match(html,/>0 ms</);assert.match(html,/orin/);
});
test('history shows loading, retry, bounded retention and explicit empty state',()=>{
 assert.match(H.view('u','svc',{loading:true}),/조회 중/);
 assert.match(H.view('u','svc',{error:true,value}),/마지막 조회/);
 assert.match(H.view('u','svc',{value:{...value,items:[]}}),/수집 전의 실패 사유는 복원되지 않습니다/);
 assert.match(H.view('u','svc',{value:{...value,nextBefore:1}}),/이전 기록 더 보기/);
 assert.match(H.view('u','svc',{value}),/각각 10000건/);
 assert.match(H.view('u','svc',{value:{...value,items:[{...row,replay:true}]}}),/저장된 결과 재조회/);
});
test('service history fetch never displays another UID and pagination keeps its filter',async()=>{
 const previous=global.fetch,calls=[];
 try{
  global.fetch=async url=>{calls.push(String(url));return {ok:true,json:async()=>({...value,nextBefore:1})};};
  await H.load('u','svc','failures');
  await H.load('u','svc','more');
  assert.match(calls[1],/before=1/);assert.match(calls[1],/failuresOnly=true/);
  global.fetch=async()=>({ok:true,json:async()=>({...value,items:[{...row,uid:'other'}]})});
  await H.load('different','svc','all');
  const html=H.render('different','svc');assert.match(html,/조회 실패/);assert.doesNotMatch(html,/&lt;request&gt;/);
 }finally{global.fetch=previous;}
});
