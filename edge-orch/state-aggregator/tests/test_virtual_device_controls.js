const test=require('node:test'),assert=require('node:assert/strict');
const {allowed,features}=require('../app/static/virtual-device-controls.js');
const row={id:'vd-demo-001',workloadExists:true,observedAt:new Date(1000).toISOString(),observationError:null,desiredReplicas:0,observedInstances:0,executionState:'no_instance'};
test('only stopped can start, ready model can infer, and running can stop',()=>{
 assert.deepEqual(allowed(row,true,false,1000),{start:true,stop:false,infer:false});
 assert.deepEqual(allowed({...row,desiredReplicas:1,observedInstances:1,executionState:'not_ready'},true,false,1000),{start:false,stop:true,infer:false});
 assert.equal(allowed({...row,desiredReplicas:1,observedInstances:1,executionState:'ready'},true,false,1000).infer,true);
});
test('disabled busy expired erroneous and foreign observations block actions',()=>{
 for(const args of [[row,false,false,1000],[row,true,true,1000],[row,true,false,32000],[{...row,observationError:'offline'},true,false,1000],[{...row,id:'other'},true,false,1000]])assert.deepEqual(allowed(...args),{start:false,stop:false,infer:false});
});
test('start waits until terminating instances disappear',()=>assert.equal(allowed({...row,observedInstances:1,executionState:'terminating'},true,false,1000).start,false));
test('Iris samples require four finite numbers in range',()=>{
 assert.deepEqual(features(['5.1','3.5','1.4','0.2']),[5.1,3.5,1.4,0.2]);
 for(const sample of [['1','2','3'],['1','','3','4'],['1','Infinity','3','4'],['1','31','3','4']])assert.throws(()=>features(sample));
});
