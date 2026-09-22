(function(root){
'use strict';
const E=root.NexusData.escape,state={selected:null,registration:false,profile:false,busy:false,message:'',error:'',history:new Map(),form:{prefix:'vd',count:1,profileId:'',name:''},profileForm:{id:'',name:'',architecture:'amd64',cpu:'100m',memory:'64Mi',cpuLimit:'1',memoryLimit:'256Mi',gpu:'0',templateServiceUid:''}};let redraw=()=>{};
const labels={running:'동작·실행 중',stopped:'정지',unknown:'확인 불가',starting:'실행 준비',stopping:'정리 중',blocked:'실행 조건 미충족',unavailable:'사용 불가'};
const reasons={logical_device_management_disabled:'현재 배포에서 논리 디바이스 변경이 비활성입니다.',logical_device_revision_changed:'설정이 변경되었습니다. 최신 상태를 조회한 뒤 다시 요청하세요.',profile_has_no_execution_contract:'자원 프로파일에 실행할 서비스가 연결되지 않았습니다.',runtime_snapshot_unavailable:'실행 제어기의 최신 관측을 확인할 수 없습니다.',logical_device_id_exists:'이미 사용 중인 디바이스 ID입니다.',profile_id_exists_immutable:'프로파일 ID가 이미 있습니다. 새 ID로 등록하세요.',resident_runtime_is_not_an_independent_virtual_device:'상주 Llama 서버는 이 독립 실행 프로파일에 연결할 수 없습니다.'};
function view(entry,now=Date.now()){
 const data=entry?.data,expired=!data||entry.lastFetchFailed||now-entry.receivedAt>=15000;
 const rows=(data?.devices||[]).map(d=>expired?{...d,state:'unknown',locations:[],reason:'source_unavailable'}:d);
 const s={registered:expired?null:data.summary.registered,knownRegistered:rows.length,stateQueryable:0,running:0,stopped:0,unknown:0,other:0,inventoryComplete:!expired&&data.summary.inventoryComplete};
 for(const d of rows){if(d.state!=='unknown')s.stateQueryable++;if(['running','stopped','unknown'].includes(d.state))s[d.state]++;else s.other++;}
 return {rows,summary:s,data,expired};
}
function field(key,label,value,type='text',extra=''){return `<label>${label}<input id="managed-${key}" data-managed-field="${key}" type="${type}" value="${E(value)}" ${extra}></label>`;}
function forms(data,entries){
 const disabled=state.busy||!data?.mutationEnabled||root.NexusPreviewReadOnly;
 const p=state.profileForm,f=state.form,templates=entries.serviceVirtual?.data?.devices||[];
 return `<div class="vd-registration"><button class="button" data-managed-open="device">가상 디바이스 등록</button> <button class="button" data-managed-open="profile">자원 프로파일 등록</button></div>${state.profile?`<form class="vd-settings" data-managed-form="profile"><h3>자원 프로파일</h3><p>실행 시 요청할 자원입니다. 등록만으로 CPU·GPU·메모리를 예약하거나 Pod를 만들지 않습니다.</p><div class="vd-settings-fields">${field('profile.id','프로파일 ID',p.id,'text','required')}${field('profile.name','프로파일 이름',p.name,'text','required')}<label>CPU 구조<select aria-label="CPU 구조" id="managed-profile-architecture" data-managed-field="profile.architecture"><option value="amd64" ${p.architecture==='amd64'?'selected':''}>AMD64</option><option value="arm64" ${p.architecture==='arm64'?'selected':''}>ARM64</option></select></label>${field('profile.cpu','CPU 요청',p.cpu)}${field('profile.cpuLimit','CPU 제한',p.cpuLimit)}${field('profile.memory','메모리 요청',p.memory)}${field('profile.memoryLimit','메모리 제한',p.memoryLimit)}${field('profile.gpu','NVIDIA GPU 개수',p.gpu,'number','min="0" max="16" step="1"')}<label>실행할 서비스 정의<select aria-label="실행할 서비스 정의" id="managed-profile-template" data-managed-field="profile.templateServiceUid"><option value="">자원만 정의 · 실행 서비스 미연결</option>${templates.map(t=>`<option value="${E(t.service_uid)}" ${p.templateServiceUid===t.service_uid?'selected':''}>${E(t.service_name)}</option>`).join('')}</select></label></div><p>프로파일은 등록 후 고정합니다. 사양이나 서비스를 바꾸려면 새 프로파일로 등록하세요.</p><button class="button" ${disabled?'disabled':''}>프로파일 저장</button> <button class="button" type="button" data-managed-close="profile">닫기</button></form>`:''}${state.registration?`<form class="vd-settings" data-managed-form="device"><h3>가상 디바이스 등록</h3><div class="vd-settings-fields">${field('device.prefix','ID 접두어',f.prefix,'text','required pattern="[a-z0-9](?:[a-z0-9]|-){0,49}"')}${field('device.count','생성 개수',f.count,'number','required min="1" max="1000"')}<label>자원 프로파일<select aria-label="자원 프로파일" id="managed-device-profile" data-managed-field="device.profileId" required><option value="">선택하세요</option>${(data?.profiles||[]).map(p=>`<option value="${E(p.id)}" ${f.profileId===p.id?'selected':''}>${E(p.name)} · ${E(p.requests.cpu)} / ${E(p.requests.memory)}</option>`).join('')}</select></label></div><p>각 객체에 독립 ID를 부여하고 정지 상태로 등록합니다. 등록 개수와 동시 실행 개수는 별개입니다.</p><button class="button" ${disabled?'disabled':''}>정지 상태로 등록</button> <button class="button" type="button" data-managed-close="device">닫기</button></form>`:''}`;
}
function row(d){return `<button class="dm-container" data-managed-select="${E(d.id)}" aria-pressed="${state.selected===d.id}"><span class="dm-identity"><strong>${E(d.name)}</strong><small>${E(d.id)}</small></span><span class="dm-row-state">${E(labels[d.state]||d.state)}</span><span class="dm-location"><small>${E(d.profileId||d.type)}</small><small>${E(d.node||(d.locations||[]).map(l=>l.node).filter(Boolean).join(', ')||'실행 위치 없음 또는 미확인')}</small></span></button>`;}
function detail(d,data){
 if(!d)return '';
 const history=state.history.get(d.id),disabled=state.busy||!data?.mutationEnabled||root.NexusPreviewReadOnly;
 let actions='';
 if(d.type==='logical')actions=`<button class="button" data-managed-action="start" ${disabled||d.state!=='stopped'||!d.profile?.executionSpec?'disabled':''}>실행</button> <button class="button" data-managed-action="stop" ${disabled?'disabled':''}>정지</button> <button class="button" data-managed-history>이력 조회</button><form class="vd-settings" data-managed-form="connection">${field('device.name','표시 이름',state.form.name||d.name,'text','required')}<label>연결 관계 (JSON)<textarea id="managed-connections" data-managed-connections rows="3">${E(state.form.connections??JSON.stringify(d.connections||[],null,2))}</textarea></label><p>예: [{"kind":"EdgeXDevice","targetId":"센서 ID","resource":"temperature"}]. 설정과 실제 통신 성공은 별도로 확인합니다.</p><button class="button" ${disabled?'disabled':''}>이름·연결 저장</button></form>`;
 else if(d.type==='sensor')actions=`<button class="button" data-live-device="${E(d.sourceId)}">측정값 상세</button> <button class="button" data-workspace="management">기존 장비 등록·개별 제어 열기 ↗</button>`;
 else if(d.type==='legacy')actions='<button class="button" data-workspace="virtual">기존 가상 디바이스 제어 열기 ↗</button>';
 return `<section class="dm-detail"><h3>${E(d.name)}</h3><dl><dt>고유 ID</dt><dd>${E(d.id)} · ${E(d.uid||d.sourceId)}</dd><dt>상태</dt><dd>${E(labels[d.state])} · ${E(d.reason||'관측 가능')}</dd><dt>요청 자원</dt><dd>${E(d.profile?JSON.stringify(d.profile.requests):'해당 없음')}</dd><dt>실행체 연결</dt><dd>${E(d.binding?JSON.stringify(d.binding):'아직 실행 자원을 할당하지 않았거나 해당 없음')}</dd></dl>${actions}${history?`<details open><summary>상태·제어 이력 ${history.length}건</summary><div class="dm-scroll">${history.map(h=>`<p>${E(new Date(h.at*1000).toLocaleString())} · ${E(h.event)}</p>`).join('')}</div></details>`:''}</section>`;
}
function render(entries,options={},now=Date.now()){
 const v=view(entries.managed,now),q=(options.query||'').toLowerCase(),rows=v.rows.filter(d=>JSON.stringify(d).toLowerCase().includes(q)),physical=rows.filter(d=>d.kind==='physical'),virtual=rows.filter(d=>d.kind==='virtual'),s=v.summary;
 state.current=v.rows.find(d=>d.id===state.selected);
 const counts=[['등록 수',s.registered??'확인 불가'],['상태 조회 가능',s.stateQueryable],['동작·실행 중',s.running],['정지',s.stopped],['확인 불가',s.unknown]];
 const section=(id,title,items)=>`<section class="dm-section"><div class="dm-section-heading"><h2>${title} · ${v.rows.filter(d=>d.kind===id).length}개${q?' / 검색 '+items.length+'개':''}</h2></div><div class="dm-scroll" id="dm-${id}-scroll" data-dm-scroll="${id==='physical'?'physical':'virtual'}" role="region" aria-label="${title} 목록" tabindex="0"><div class="dm-list-head"><span>이름 / 고유 ID</span><span>상태</span><span>프로파일 / 실행 위치</span></div>${items.map(row).join('')||'<p>표시할 등록 객체가 없습니다.</p>'}</div></section>`;
 return `<div class="dm-map"><div class="dm-summary managed-summary">${counts.map(([k,n])=>`<div><span>${k}</span><strong>${E(n)}</strong></div>`).join('')}</div><p>정지 객체 포함 · Pod·관측 트윈 제외 · 준비/정리/사용 불가 ${s.other}개</p>${!s.inventoryComplete?`<p class="dm-notice">일부 등록 원천을 확인할 수 없습니다. 보존한 ${s.knownRegistered}개 기준이며 전체 등록 수와 목표 달성은 확정하지 않습니다.</p>`:''}${v.expired?'<p class="dm-notice">최신 상태 조회에 실패했거나 응답이 오래됐습니다. 정지로 판정하지 않습니다.</p>':''}${forms(v.data,entries)}${state.error||state.message?`<p role="status">${E([state.message,state.error].filter(Boolean).join(" · "))}</p>`:''}${root.NexusPreviewReadOnly?'<p>미리보기 · 변경 요청 비활성</p>':''}${detail(state.current,v.data)}${section('physical','물리 디바이스',physical)}${section('virtual','가상 디바이스',virtual)}${root.NexusDeviceMap?.workloads?.(entries,options,now)||''}<details data-dm-disclosure="managed-terms" ${options.opened?.has('managed-terms')?'open':''}><summary>집계 기준</summary><p>컴퓨팅 노드·EdgeX 등록 디바이스·독립 가상 디바이스를 각각 한 번 집계합니다. 센서 조회용 트윈과 서비스 정의, 실행 Pod를 추가로 세지 않습니다. 등록 100개는 상태 조회·개별 제어·이력·재시작 보존 시험과 함께 검증해야 합니다. 물리 디바이스의 정지는 EdgeX 관리 잠금이며 전원 꺼짐을 뜻하지 않습니다.</p></details><a class="button" href="#runtime-services">기존 서비스 실행·관측 보기 ↗</a></div>`;
}
async function request(path,method='GET',body,key){
 const r=await root.fetch('/api/managed-devices'+path,{method,cache:'no-store',headers:{'Content-Type':'application/json','X-Runtime-Demo':'1',...(key?{'Idempotency-Key':key}:{})},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(20000)});
 const d=await r.json();if(!r.ok)throw Error(reasons[d.detail]||String(typeof d.detail==='string'?d.detail:'등록 계약과 API 연결 상태를 확인하세요.'));return d;
}
async function perform(kind){
 if(state.busy||root.NexusPreviewReadOnly)return;state.busy=true;state.error='';state.message='';redraw();
 try{
  if(kind==='profile'){
   const p=state.profileForm,requests={cpu:p.cpu,memory:p.memory},limits={cpu:p.cpuLimit,memory:p.memoryLimit};if(Number(p.gpu)>0){requests['nvidia.com/gpu']=String(p.gpu);limits['nvidia.com/gpu']=String(p.gpu);}
   await request('/profiles','POST',{id:p.id,name:p.name,architecture:p.architecture,requests,limits,templateServiceUid:p.templateServiceUid||null});state.profile=false;state.message='자원 프로파일을 등록했습니다.';
  }else if(kind==='device'){
   const f=state.form,total=Number(f.count);if(!Number.isInteger(total)||total<1||total>1000)throw Error('생성 개수는 1~1000 사이 정수여야 합니다.');
   for(let i=1;i<=total;i++){const id=f.prefix+'-'+String(i).padStart(3,'0');await request('/virtual','POST',{id,name:id,profileId:f.profileId,connections:[]});state.message=i+' / '+total+'개 등록 확인';redraw();}
   state.registration=false;
  }else if(kind==='connection'){
   const d=state.current;await request('/virtual/'+encodeURIComponent(d.sourceId),'PATCH',{expectedRevision:d.revision,name:state.form.name||d.name,connections:JSON.parse(state.form.connections??JSON.stringify(d.connections))});state.message='이름과 연결 설정을 저장했습니다.';
  }else{
   const d=state.current,key=root.crypto.randomUUID();const result=await request('/virtual/'+encodeURIComponent(d.sourceId)+'/actions','POST',{action:kind,expectedRevision:d.revision},key);
   state.message=result.status==='accepted'?'요청을 접수했습니다. 실제 상태 전환은 관측으로 확인합니다.':result.status==='unknown'?'실행 결과 확인 불가. 이력을 확인하고 자동 재시도하지 마세요.':'요청이 거부되었습니다: '+(reasons[result.reason]||result.reason);
  }
  await root.NexusLive.store.refreshManagedDevices();
 }catch(e){state.error=e.message;}finally{state.busy=false;redraw();}
}
function setup(callback){redraw=callback;root.document.addEventListener('click',async event=>{
 const t=event.target.closest('button');if(!t)return;
 if(t.dataset.managedOpen){state[t.dataset.managedOpen==='profile'?'profile':'registration']=true;redraw();}
 if(t.dataset.managedClose){state[t.dataset.managedClose==='profile'?'profile':'registration']=false;redraw();}
 if(t.dataset.managedSelect){state.selected=t.dataset.managedSelect;state.form.name='';delete state.form.connections;redraw();}
 if(t.dataset.managedAction&&!t.disabled)perform(t.dataset.managedAction);
 if(t.hasAttribute('data-managed-history')&&state.current){try{const d=state.current,r=await request('/virtual/'+encodeURIComponent(d.sourceId)+'/history?limit=500');state.history.set(d.id,r.events);redraw();}catch(e){state.error=e.message;redraw();}}
 });root.document.addEventListener('input',event=>{const t=event.target;if(t.hasAttribute('data-managed-connections'))state.form.connections=t.value;if(t.dataset.managedField){const [group,key]=t.dataset.managedField.split('.');(group==='profile'?state.profileForm:state.form)[key]=t.value;}});root.document.addEventListener('submit',event=>{if(event.target.dataset.managedForm){event.preventDefault();perform(event.target.dataset.managedForm);}});}
root.NexusManagedDevices={render,view,setup,state,perform};
})(typeof window!=='undefined'?window:globalThis);
