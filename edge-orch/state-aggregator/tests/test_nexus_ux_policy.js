const {test}=require('node:test');
const assert=require('node:assert/strict');
const UX=require('../app/static/nexus/ux-policy.js');
test('catalog navigation removes previous service and graph filters while preserving other context',()=>{
 const url=UX.catalogUrl('http://localhost/?service=one&view=graph&workloads=all&site=lab#overview');
 assert.equal(url.href,'http://localhost/?site=lab#services');
});
test('1000 devices paginate without duplication or loss, and clamp after filtering',()=>{
 const data=Array.from({length:1000},(_,id)=>({id}));
 const rendered=Array.from({length:40},(_,page)=>UX.pageItems(data,page).items).flat();
 assert.deepEqual(rendered,data);assert.equal(UX.pageItems(data,99).page,39);
 assert.equal(UX.pageItems(data.slice(0,3),39).page,0);
 assert.deepEqual(UX.pageItems([],39).items,[]);
});
test('successful zero sample is valid; failed, stale and future samples are not',()=>{
 const now=Date.parse('2026-09-09T06:00:00Z');
 const node={collected_at:new Date(now).toISOString(),node_health:'available',raw_metrics:{up:1,cpu_percent:0}};
 assert.equal(UX.validNodeSample(node,true,now),true);
 for(const change of [{node_health:'unavailable'},{raw_metrics:{up:0}},{collected_at:new Date(now-61000).toISOString()},{collected_at:new Date(now+6000).toISOString()}]) assert.equal(UX.validNodeSample({...node,...change},true,now),false);
 assert.equal(UX.validNodeSample(node,false,now),false);
});
test('event groups retain latest timestamp and separate services, states and reasons',()=>{
 const event={service_id:'a',type:'placement',state:'held',reasons:['input','model'],node:'x',timestamp:'latest'};
 const groups=UX.groupEvents([event,{...event,reasons:['model','input'],timestamp:'older'},{...event,service_id:'b'},{...event,state:'cleared'}]);
 assert.equal(groups.length,3);assert.equal(groups[0].count,2);assert.equal(groups[0].timestamp,'latest');
});
test('source filters combine node and health and stale data cannot be healthy',()=>{
 const sources=[{id:'a',functions:[{device:{node_name:'n1',overall_status:'available'}}]},{id:'b',functions:[{device:{node_name:'n2',overall_status:'unavailable'}}]}];
 assert.deepEqual(UX.filterSources(sources,{health:'healthy',node:'n1'}).map(x=>x.id),['a']);
 assert.equal(UX.filterSources(sources,{health:'healthy',current:false}).length,0);
 assert.equal(UX.filterSources(sources,{health:'unknown',current:false}).length,2);
});
