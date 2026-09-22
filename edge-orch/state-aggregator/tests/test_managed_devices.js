const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const D=require('../app/static/nexus/live-data.js');
function harness(){const root=vm.createContext({NexusData:D,document:{addEventListener(){}}});vm.runInContext(fs.readFileSync(require.resolve('../app/static/nexus/managed-devices.js'),'utf8'),root);return root.NexusManagedDevices;}
test('100 logical and physical rows report dormant count separately from running and unknown',()=>{
 const M=harness(),rows=Array.from({length:100},(_,i)=>({id:'vd-'+i,kind:i<20?'physical':'virtual',type:i<20?'sensor':'logical',name:'device '+i,state:i<20?'running':'stopped'}));
 const e={receivedAt:100,data:{devices:rows,summary:{registered:100,inventoryComplete:true}}};
 assert.equal(M.view(e,101).summary.stopped,80);assert.equal(M.view(e,101).summary.running,20);
 const expired=M.view(e,16000);assert.equal(expired.summary.stopped,0);assert.equal(expired.summary.unknown,100);assert.equal(expired.summary.registered,null);
 const html=M.render({managed:e},{query:'vd-99'},101);assert.match(html,/등록 수/);assert.match(html,/상태 조회 가능/);assert.match(html,/검색 1개/);assert.match(html,/관측 트윈 제외/);
});
test('physical twins and service templates never create rows from other stores',()=>{
 const M=harness(),entry={receivedAt:100,data:{devices:[],summary:{registered:0,inventoryComplete:true}}};
 const html=M.render({managed:entry,twins:{data:{twins:[{id:'fake'}]}},serviceVirtual:{data:{devices:[{service_name:'template',service_uid:'uid'}]}}},{},100);
 assert.doesNotMatch(html,/data-managed-select="fake"|data-managed-select="uid"/);
});
test('registration prefix uses a valid HTML Unicode Sets pattern and rejects invalid IDs',()=>{
 const M=harness();M.state.registration=true;
 const html=M.render({managed:{receivedAt:100,data:{devices:[],summary:{registered:0,inventoryComplete:true}}}},{},100);
 const pattern=html.match(/pattern="([^"]+)"/)[1];
 const re=new RegExp('^(?:'+pattern+')$','v');
 for(const value of ['vd','ui-check','a'.repeat(50)])assert.equal(re.test(value),true,value);
 for(const value of ['Bad','-vd','vd_1','vd 1','a'.repeat(51)])assert.equal(re.test(value),false,value);
});
