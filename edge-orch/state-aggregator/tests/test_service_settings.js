const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const D=require('../app/static/nexus/live-data.js');
function harness(){
 const listeners={},calls=[],reply={mode:'ok'};
 const data={uid:'uid',name:'llama',specRevision:'a'.repeat(64),editable:true,settings:{mode:'preferred',preferredRole:'edge',nodeName:null,highWatermark:.8,lowWatermark:.2,pressureSeconds:10,returnSeconds:60,cooldownSeconds:30},constraints:{modes:['preferred'],roles:['edge'],nodes:['node-a'],nodeSelectionAllowed:true},variants:[]};
 const context=vm.createContext({NexusData:D,AbortSignal,document:{addEventListener:(name,fn)=>listeners[name]=fn},fetch:async(url,options)=>{calls.push({url,options});return {ok:reply.mode==='ok',status:reply.mode==='ok'?200:409,json:async()=>reply.mode==='ok'?JSON.parse(JSON.stringify(data)):{detail:'service_settings_changed'}};}});
 vm.runInContext(fs.readFileSync(require.resolve('../app/static/nexus/service-settings.js'),'utf8'),context);
 const S=context.NexusServiceSettings;S.setup(()=>{});return {S,data,calls,reply,listeners};
}
test('settings keep drafts while rendering and write exact UID/revision with no execution action',async()=>{
 const {S,calls,reply}=harness();await S.load('uid','llama');const entry=S.entries.get('uid');entry.draft.pressureSeconds=22;
 const html=S.render({service_uid:'uid',service_name:'llama'});assert.match(html,/value="22"/);assert.equal(entry.draft.pressureSeconds,22);
 reply.mode='conflict';await S.save('uid');assert.match(S.entries.get('uid').error,/다른 곳/);assert.equal(entry.draft.pressureSeconds,22);
 const body=JSON.parse(calls[1].options.body);assert.equal(body.serviceUid,'uid');assert.equal(body.specRevision,'a'.repeat(64));assert.equal(body.settings.pressureSeconds,22);
 assert.equal(calls[1].options.method,'PUT');assert.doesNotMatch(calls[1].url,/runs|\/service$/);
});
test('running or undeployed settings stay disabled and cannot issue writes',async()=>{
 const {S,data,calls}=harness();data.editable=false;data.reason='settings_backend_not_deployed';await S.load('uid','llama');
 assert.match(S.render({service_uid:'uid',service_name:'llama'}),/운영 배포/);await S.save('uid');assert.equal(calls.length,1);
});
