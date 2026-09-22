const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const D=require('../app/static/nexus/live-data.js');
function harness(){
 const calls=[],reply={conflict:false};const context=vm.createContext({NexusData:D,AbortSignal,structuredClone,document:{addEventListener(){}},fetch:async(url,options)=>{calls.push({url,options});const body=JSON.parse(options.body);return {ok:!reply.conflict,json:async()=>reply.conflict?{detail:'service_settings_changed'}:{uid:'uid-1',name:body.name||'model',spec:body.spec}};}});
 vm.runInContext(fs.readFileSync(require.resolve('../app/static/nexus/service-definition.js'),'utf8'),context);
 return {S:context.NexusServiceDefinition,calls,reply};
}
test('new registration preserves typed draft over render and sends only suspended preferred definition',async()=>{
 const {S,calls}=harness();S.begin('new');S.update('new','name','model');S.update('new','variants.0.image','example/model@sha256:'+'a'.repeat(64));
 assert.match(S.launcher(),/value="model"/);assert.equal(S.drafts.get('new').name,'model');
 await S.save('new');assert.equal(calls.length,1);assert.equal(calls[0].options.method,'POST');
 assert.equal(calls[0].url,'/api/service-virtual-devices/registration');
 const body=JSON.parse(calls[0].options.body);assert.equal(body.spec.suspended,true);assert.equal(body.spec.policy.mode,'preferred');
 assert.equal(S.drafts.has('new'),false);
});
test('model contract derives inference path and invalid JSON does not issue a request',async()=>{
 const {S,calls}=harness();S.begin('new');S.update('new','kind','ai');S.update('new','modelRuntime.modelName','digits');
 const d=S.drafts.get('new');d.json.inputs='bad';await S.save('new');assert.equal(calls.length,0);assert.match(d.error,/JSON/);
 d.json.inputs='[{"name":"input","datatype":"FP32","shape":[1,4]}]';
 assert.equal(S.payload(d).requestPath,'/v2/models/digits/infer');
});
test('editing conflicts retain draft and exact original UID/spec revision',async()=>{
 const {S,calls,reply}=harness();S.begin('new');const spec=S.payload(S.drafts.get('new'));
 S.begin('uid-1',{uid:'uid-1',name:'model',specRevision:'a'.repeat(64),spec});S.update('uid-1','variants.0.requests.memory','2Gi');
 reply.conflict=true;await S.save('uid-1');const d=S.drafts.get('uid-1');assert.match(d.error,/다른 곳/);assert.equal(d.spec.variants[0].requests.memory,'2Gi');
 const body=JSON.parse(calls[0].options.body);assert.equal(body.serviceUid,'uid-1');assert.equal(body.specRevision,'a'.repeat(64));
 assert.equal(body.spec.suspended,true);assert.doesNotMatch(calls[0].url,/start|runs/);
});
