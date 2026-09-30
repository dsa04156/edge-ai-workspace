const test=require('node:test');
const assert=require('node:assert/strict');
const {profileFromFields,current}=require('../app/static/nexus/device-manager.js');
test('basic form produces static capability and retains unknowns',()=>{
 const doc=profileFromFields({name:'arm64-small',version:'1.0',architecture:'arm64'});
 assert.equal(doc.kind,'DeviceProfile');assert.equal(doc.spec.hardware.cpu.cores,null);
 assert.equal(doc.spec.hardware.accelerators,null);assert.equal(doc.spec.runtime.backends,null);
 assert.equal(doc.spec.capabilities,null);assert.equal(doc.spec.type,'unknown');
});
test('shared accelerator memory remains separate from host RAM',()=>{
 const doc=profileFromFields({name:'edge-gpu',version:'1.0',memory:'8',cpu:'6',accelerator:'gpu',vendor:'nvidia',model:'orin',acceleratorMemory:'8',memoryMode:'shared',frameworks:'pytorch, onnxruntime'});
 assert.equal(doc.spec.hardware.memory.capacity,'8Gi');assert.equal(doc.spec.hardware.accelerators[0].memoryMode,'shared');
 assert.deepEqual(doc.spec.runtime.frameworks,['pytorch','onnxruntime']);
});
test('known absence is different from unknown acceleration',()=>{
 assert.deepEqual(profileFromFields({accelerator:'none'}).spec.hardware.accelerators,[]);
});
test('stale invalid and future observations fail freshness',()=>{
 const now=Date.now();assert.equal(current(new Date(now).toISOString(),60,now),true);
 assert.equal(current(new Date(now-61000).toISOString(),60,now),false);
 assert.equal(current(new Date(now+1000).toISOString(),60,now),false);assert.equal(current('bad'),false);
});
test('new version preserves unedited units, explicit empty runtimes and extra capabilities',()=>{
 const base=profileFromFields({name:'base',version:'1.0',accelerator:'gpu',vendor:'nvidia',model:'one'});
 base.spec.hardware.memory.capacity='4096Mi';
 base.spec.hardware.accelerators.push({type:'npu',vendor:'other',model:'two',memory:null,memoryMode:'unknown'});
 base.spec.runtime.frameworks=[];base.spec.capabilities={gpio:true};
 const next=profileFromFields({name:'base',version:'1.1',memory:'4',frameworks:'',accelerator:'gpu',vendor:'nvidia',model:'one'},base);
 assert.equal(next.spec.hardware.memory.capacity,'4096Mi');
 assert.deepEqual(next.spec.runtime.frameworks,[]);assert.deepEqual(next.spec.capabilities,{gpio:true});
 assert.equal(next.spec.hardware.accelerators.length,2);
});

const {fieldsFromNode,fieldsFromProfile,nextVersion}=require('../app/static/nexus/device-manager.js');
test('node draft uses reported capacity, never current free resources or inferred GPU',()=>{
 const draft=fieldsFromNode({architecture:'arm64',capacity:{cpu:'6000m',memory:'4096Mi'},runtimeState:{available:1}});
 assert.equal(draft.cpu,'6');assert.equal(draft.memory,'4');assert.equal(draft.name,'');
 assert.equal(draft.type,'unknown');assert.equal(draft.accelerator,undefined);
 assert.equal(fieldsFromNode({capacity:{cpu:'bad',memory:'bad'}}).cpu,'');
});
test('version suggestion and editor round trip preserve the original spec',()=>{
 const original=profileFromFields({name:'shared',version:'1.9',cpu:'6',memory:'8',accelerator:'none'});
 assert.deepEqual(profileFromFields(fieldsFromProfile(original),original),original);
 assert.equal(nextVersion('shared',[{document:original},{document:{metadata:{name:'shared',version:'1.10'}}}]),'1.11');
 assert.equal(nextVersion('new',[]),'1.0');
});

const {suggestedDraft,specification}=require('../app/static/nexus/device-manager.js');
test('suggested metadata chooses an unused version without inventing hardware identity',()=>{
 const node={architecture:'arm64',capacity:{cpu:'6',memory:'7802740Ki'}};
 const draft=suggestedDraft(node,[{document:{metadata:{name:'compute-arm64',version:'2.9'}}}]);
 assert.equal(draft.name,'compute-arm64');assert.equal(draft.version,'2.10');
 assert.equal(draft.type,'unknown');assert.equal(draft.accelerator,undefined);
 assert.equal(suggestedDraft({capacity:{}},[]).name,'compute-unknown');
});
test('specification keeps reported and declared quantities and dates separate and escaped',()=>{
 const profile=profileFromFields({name:'manual',version:'1.0',cpu:'4',memory:'8'});
 const html=specification({capacity:{cpu:'6',memory:'7802740Ki'},architecture:'<unsafe>',observedAt:'2026-09-30T08:00:00Z'},profile,{createdAt:'2026-09-29T08:00:00Z'});
 assert.match(html,/자동 관측/);assert.match(html,/수동 등록/);
 assert.match(html,/7802740Ki/);assert.match(html,/8Gi/);assert.match(html,/6 CPU/);assert.match(html,/4 cores/);
 assert.match(html,/&lt;unsafe&gt;/);assert.ok(!html.includes('<unsafe>'));assert.match(html,/하드웨어 확인 시각이 아닙니다/);
});
