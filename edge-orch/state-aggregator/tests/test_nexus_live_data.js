const test=require('node:test');
const assert=require('node:assert/strict');
const D=require('../app/static/nexus/live-data.js');
const payloads={resources:[{node:'edge-1'}],recommendations:{items:[{serviceId:'svc-1'}]},devices:[{name:'temperature',physical_device_id:'source-1'}],twins:{twins:[{id:'twin:temperature',physical_device_id:'source-1',service_bindings:[{service_id:'svc-1'}]}],observation_errors:[]},services:{services:[{service_id:'svc-1'}]},results:{results:[{observed_at:'2026-09-07T10:00:00Z',anomaly:false}]}};
function key(url){return Object.keys(D.endpoints).find(k=>D.endpoints[k]===url);}
const response=data=>({ok:true,json:async()=>data});
test('independent endpoints preserve successful data when another endpoint fails',async()=>{
 const store=D.createStore(async url=>url===D.endpoints.twins?{ok:false,status:503}:response(payloads[key(url)]));await store.refresh();assert.equal(store.entries.twins.status,'error');assert.equal(store.entries.devices.status,'ready');assert.equal(store.entries.services.status,'ready');assert.equal(store.entries.twins.data,null);
});
test('failed refresh retains previous data and receipt time but is not current',async()=>{
 let fail=false,clock=1000;const store=D.createStore(async url=>{if(fail)throw new Error('offline');return response(payloads[key(url)]);},()=>clock);await store.refresh();const before=store.entries.devices.data;fail=true;clock=2000;await store.refresh();assert.equal(store.entries.devices.data,before);assert.equal(store.entries.devices.receivedAt,1000);assert.equal(D.isCurrent(store.entries.devices,2000),false);
});
test('200 response with observation errors is not treated as successful current observation',async()=>{
 const store=D.createStore(async url=>response(key(url)==='twins'?{...payloads.twins,observation_errors:['AI service unavailable']}:payloads[key(url)]));await store.refresh();assert.equal(store.entries.twins.status,'error');assert.equal(D.isCurrent(store.entries.twins),false);assert.equal(store.entries.twins.data.twins.length,1);
});
test('malformed response is rejected instead of becoming a valid empty list',async()=>{
 const store=D.createStore(async()=>response({}));await store.refresh();assert.equal(store.entries.devices.status,'error');assert.equal(store.entries.services.data,null);assert.throws(()=>D.validate('twins',{twins:[null]}));
});
test('concurrent refreshes share one shared request operation; GET only',async()=>{
 let release;const gate=new Promise(r=>release=r);let count=0;const store=D.createStore(async(url,options)=>{count++;assert.equal(options.method,'GET');assert.ok(options.signal);await gate;return response(payloads[key(url)]);});const a=store.refresh(),b=store.refresh();assert.equal(a,b);release();await a;assert.equal(count,Object.keys(D.endpoints).length);
});
test('old response cannot continue to present current health',()=>{
 assert.equal(D.isCurrent({status:'ready',receivedAt:1000,error:null},92000),false);assert.equal(D.isCurrent({status:'ready',receivedAt:1000,error:null},2000),true);
});
test('fanout and N:M bindings do not create extra physical sources or merge unknown devices',()=>{
 const g=D.groupSources([{name:'a',physical_device_id:'one'},{name:'b',physical_device_id:'one'},{name:'c',physical_device_id:null}],[{physical_device_id:'one',service_bindings:[{service_id:'s1'},{service_id:'s2'}]},{physical_device_id:'one',service_bindings:[{service_id:'s1'}]}]);assert.equal(g.sources.length,1);assert.equal(g.sources[0].devices.length,2);assert.equal(g.sources[0].bindings.size,2);assert.equal(g.unassigned.length,1);
});
test('API identifiers and values cannot insert HTML; absent anomaly is unknown',()=>{
 assert.equal(D.escape('<img src=x onerror="x">'), '&lt;img src=x onerror=&quot;x&quot;&gt;');assert.equal(D.resultLabel({}), '판정 확인 불가');assert.equal(D.resultLabel({anomaly:false}), '정상 범위');
});
