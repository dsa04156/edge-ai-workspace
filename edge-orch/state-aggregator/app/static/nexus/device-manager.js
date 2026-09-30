(function(root){
'use strict';
const E=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const types={cloud_server:'서버',edge_ai_server:'엣지 AI 서버',edge_ai_device:'엣지 AI 장비',edge_light_device:'경량 엣지 장비',edge_device:'엣지 장비'};
const labels={nodes:'장비 원본',resources:'예약 자원·사용률',sensors:'EdgeX 센서',runtime:'실행 서비스'};
let data=null,loading=false,error='',message='',tab='nodes',selected=null,query='',showForm=false,busy=false,setupDone=false;
let copyBase=null, editTarget=null;
const nodeDrafts=new Map();
const inGi=value=>{if(!value)return '';const units={Ki:1/1024**2,Mi:1/1024,Gi:1,Ti:1024};return String(Number(value.slice(0,-2))*units[value.slice(-2)]);};
let draft={name:'',version:'1.0',architecture:'',deviceClass:'compute-node',type:'unknown'};
const retainList=(value,original)=>original!==undefined&&(original||[]).join(', ')===(value||'')?original:list(value);
const retainedMemory=(value,original)=>original!==undefined&&inGi(original)===(value||'')?original:value?value+'Gi':null;
const list=value=>value?.trim()?value.split(',').map(v=>v.trim()).filter(Boolean):null;
const refKey=ref=>ref?ref.name+'@'+ref.version:'';
function profileFromFields(f,base=null){
  const accelerator=!f.accelerator?null:f.accelerator==='none'?[]:[{type:f.accelerator,vendor:f.vendor||'',model:f.model||'',memory:retainedMemory(f.acceleratorMemory,base?.spec.hardware.accelerators?.[0]?.memory),memoryMode:f.memoryMode||'unknown'},...(base?.spec.hardware.accelerators?.slice(1)||[])];
  return {apiVersion:'edgeai.etri/v1',kind:'DeviceProfile',metadata:{name:f.name,version:f.version},spec:{
    deviceClass:f.deviceClass||'compute-node',type:f.type||'unknown',hardware:{architecture:f.architecture||null,cpu:{cores:f.cpu?Number(f.cpu):null},memory:{capacity:retainedMemory(f.memory,base?.spec.hardware.memory.capacity)},accelerators:accelerator},
    runtime:{frameworks:retainList(f.frameworks,base?.spec.runtime.frameworks),backends:retainList(f.backends,base?.spec.runtime.backends)},capabilities:base?.spec.capabilities??null,communication:{protocols:retainList(f.protocols,base?.spec.communication.protocols)}}};
}
function fieldsFromProfile(d){
  const h=d.spec.hardware,a=h.accelerators?.[0];
  return {name:d.metadata.name,version:d.metadata.version,architecture:h.architecture||'',deviceClass:d.spec.deviceClass,type:d.spec.type,cpu:h.cpu.cores??'',memory:inGi(h.memory.capacity),frameworks:d.spec.runtime.frameworks?.join(', ')||'',backends:d.spec.runtime.backends?.join(', ')||'',protocols:d.spec.communication.protocols?.join(', ')||'',accelerator:h.accelerators===null?'':!h.accelerators.length?'none':a.type,vendor:a?.vendor||'',model:a?.model||'',acceleratorMemory:inGi(a?.memory),memoryMode:a?.memoryMode||'unknown'};
}
function nextVersion(name,profiles){
  const versions=profiles.map(p=>p.document.metadata).filter(m=>m.name===name).map(m=>m.version.split('.').map(BigInt));
  if(!versions.length)return '1.0';
  versions.sort((a,b)=>a[0]===b[0]?(a[1]>b[1]?-1:a[1]<b[1]?1:0):a[0]>b[0]?-1:1);
  return versions[0][0]+'.'+(versions[0][1]+1n);
}
function fieldsFromNode(n){
  const cpu=String(n.capacity?.cpu||''),ram=String(n.capacity?.memory||'');
  const cores=/^(?:[0-9]+)(?:\.[0-9]+)?m?$/.test(cpu)?Number(cpu.replace(/m$/,''))*(cpu.endsWith('m')?.001:1):NaN;
  const memory=/^(?:[0-9]+)(?:\.[0-9]+)?(?:Ki|Mi|Gi|Ti)$/.test(ram)?inGi(ram):'';
  return {name:'',version:'1.0',architecture:['arm64','amd64'].includes(n.architecture)?n.architecture:'',deviceClass:'compute-node',type:'unknown',cpu:Number.isFinite(cores)&&cores>0?String(cores):'',memory};
}
function suggestedDraft(n,profiles){
  const result=fieldsFromNode(n);
  result.name='compute-'+(result.architecture||'unknown');
  result.version=nextVersion(result.name,profiles);
  return result;
}
function rememberDraft(){if(editTarget)nodeDrafts.set(editTarget.uid,{draft:{...draft},copyBase,editTarget:{...editTarget}});}
function openNodeEditor(n,reset=false){
  if(!reset&&nodeDrafts.has(n.uid)){({draft,copyBase,editTarget}=nodeDrafts.get(n.uid));draft={...draft};}
  else{copyBase=profileFor(n.binding?.profileRef)||null;draft=copyBase?fieldsFromProfile(copyBase):suggestedDraft(n,data.profiles);if(copyBase)draft.version=nextVersion(draft.name,data.profiles);editTarget={uid:n.uid,name:n.name,revision:n.binding?.revision||0};}
  showForm=true;
}
function current(value,seconds=60,now=Date.now()){const age=now-Date.parse(value);return Number.isFinite(age)&&age>=0&&age<=seconds*1000;}
function number(v,unit=''){return typeof v==='number'&&Number.isFinite(v)?v.toLocaleString('ko-KR',{maximumFractionDigits:1})+unit:'미수집';}
function when(value){return value?new Date(value).toLocaleString('ko-KR'):'미수집';}
function profileFor(ref){return data.profiles.find(p=>refKey(p.document.metadata)===refKey(ref))?.document;}
async function api(path='',method='GET',body){
  const response=await fetch('/api/v1/device-manager'+path,{method,cache:'no-store',headers:method==='GET'?{}:{'Content-Type':'application/json','X-Device-Manager':'1'},...(body===undefined?{}:{body:JSON.stringify(body)})});
  const result=await response.json();
  if(!response.ok){const detail=result.detail;throw new Error(Array.isArray(detail)?detail.map(e=>e.path+': '+e.message).join('\n'):String(detail||'요청 실패'));}
  return result;
}
function redraw(){if(root.location.hash==='#device-manager'){const content=document.querySelector('#content');if(content)content.innerHTML=render();}}
async function refresh(){if(loading)return;loading=true;error='';redraw();try{data=await api();}catch(e){error=e.message;}finally{loading=false;redraw();}}
function canWrite(){return data?.writable&&!busy&&!loading&&!error;}
function fields(){
  const input=(name,title,extra='')=>`<label>${title}<input name="${name}" value="${E(draft[name]||'')}" ${extra}></label>`;
  const select=(name,title,choices)=>`<label>${title}<select name="${name}">${draft[name]&&!choices.some(([v])=>v===draft[name])?`<option value="${E(draft[name])}" selected>${E(draft[name])}</option>`:''}${choices.map(([v,t])=>`<option value="${v}" ${draft[name]===v?'selected':''}>${t}</option>`).join('')}</select></label>`;
  return `<form id="manager-profile-form"><fieldset ${canWrite()?'':'disabled'}><legend>${editTarget?'기본 사양 편집':'새 프로파일'}</legend>${editTarget?`<p class="manager-footnote">저장할 이름과 버전을 자동 제안했습니다. 필요할 때 고급 설정에서 변경하세요.</p><details class="manager-metadata"><summary>고급: 프로파일 이름·버전</summary><div class="manager-form-grid">${input('name','Profile 이름','required pattern="[a-z0-9](?:[a-z0-9.]|-){0,127}" placeholder="예: edge-arm64-small"')}${input('version','버전','required pattern="[0-9]+[.][0-9]+"')}</div></details>`:`<div class="manager-form-grid">${input('name','Profile 이름','required pattern="[a-z0-9](?:[a-z0-9.]|-){0,127}" placeholder="예: edge-arm64-small"')}${input('version','버전','required pattern="[0-9]+[.][0-9]+"')}</div>`}<div class="manager-form-grid">${select('deviceClass','장비 종류',[['compute-node','연산 노드'],['edge-ai-device','엣지 AI 장비'],['edge-ai-server','엣지 AI 서버']])}${select('type','하드웨어 확인',[['unknown','물리 여부 미확인'],['physical','물리 장비 확인됨']])}${select('architecture','CPU architecture',[['','미확인'],['arm64','ARM64'],['amd64','AMD64 / x86-64']])}${input('cpu','CPU cores','type="number" min="0.1" step="any" placeholder="미확인"')}${input('memory','메모리 (GiB)','type="number" min="0.01" step="any" placeholder="미확인"')}${select('accelerator','가속기',[['','미확인'],['none','가속기 없음 (확인됨)'],['gpu','GPU'],['npu','NPU']])}</div><details class="manager-accelerator" ${['gpu','npu'].includes(draft.accelerator)?'open':''}><summary>가속기 세부 사양</summary><div class="manager-form-grid">${input('vendor','제조사','placeholder="예: nvidia"')}${input('model','모델명')}${input('acceleratorMemory','가속기 메모리 (GiB)','type="number" min="0.01" step="any" placeholder="미확인"')}${select('memoryMode','메모리 방식',[['unknown','미확인'],['shared','호스트와 공유'],['dedicated','전용 메모리']])}</div></details><details class="manager-runtime"><summary>실행환경·통신 설정</summary><div class="manager-form-grid">${input('frameworks','지원 framework','placeholder="예: pytorch, onnxruntime"')}${input('backends','지원 backend','placeholder="예: cpu, cuda"')}${input('protocols','통신 protocol','placeholder="예: mqtt, grpc"')}</div></details><p class="note">${editTarget&&!copyBase?'architecture·CPU·RAM은 Kubernetes 보고값을 불러왔습니다. 제조사 총용량과 다를 수 있으니 확인하세요. ':''}빈 칸은 미확인입니다. 저장한 값은 수동 등록 사양으로 관리하며 자동 수집값이 덮어쓰지 않습니다. 다른 장비에는 적용되지 않습니다.</p><div class="manager-actions"><button class="button primary" type="submit" ${canWrite()?'':'disabled'}>${editTarget?'사양 저장':'Profile 추가'}</button><button class="button" type="button" data-manager-cancel>${editTarget?'취소':'닫기'}</button></div></fieldset></form>`;
}
function profileSummary(p){if(!p)return '<p>연결된 Profile이 없습니다.</p>';const h=p.spec.hardware;return `<dl class="manager-facts"><div><dt>architecture</dt><dd>${E(h.architecture||'미확인')}</dd></div><div><dt>정적 CPU / RAM</dt><dd>${number(h.cpu.cores,' cores')} / ${E(h.memory.capacity||'미확인')}</dd></div><div><dt>가속기</dt><dd>${h.accelerators===null?'미확인':h.accelerators.length?h.accelerators.map(a=>E([a.vendor,a.model,a.type,a.memory,a.memoryMode].filter(Boolean).join(' · '))).join('<br>'):'없음 (입력값)'}</dd></div><div><dt>framework / backend</dt><dd>${E(p.spec.runtime.frameworks?.join(', ')||'미확인')} / ${E(p.spec.runtime.backends?.join(', ')||'미확인')}</dd></div></dl><p class="manager-footnote">사용자가 등록한 정적 정의입니다. 실제 실행·성능 검증과 별도입니다. 공유 메모리는 RAM과 합산하지 않습니다.</p>`;}
function specification(n,p,record){
  const h=p?.spec.hardware, missing=p?'미확인':'미등록';
  const rows=[['아키텍처',n.architecture||'미수집',h?.architecture||missing],
    ['CPU',n.capacity.cpu?String(n.capacity.cpu)+' CPU':'미수집',h?.cpu.cores?number(h.cpu.cores,' cores'):missing],
    ['메모리',n.capacity.memory||'미수집',h?.memory.capacity||missing],
    ['가속기','미수집',!h||h.accelerators===null?missing:h.accelerators.length?h.accelerators.map(a=>[a.vendor,a.model,a.type,a.memory,a.memoryMode].filter(Boolean).join(' · ')).join(', '):'없음 (등록값)'],
    ['실행환경','미수집',p?[...(p.spec.runtime.frameworks||[]),...(p.spec.runtime.backends||[])].join(', ')||'미확인':'미등록']];
  return `<div class="manager-spec-table"><table><thead><tr><th>항목</th><th>자동 관측<small>Kubernetes 보고값</small></th><th>수동 등록<small>저장한 사양</small></th></tr></thead><tbody>${rows.map(([key,observed,declared])=>`<tr><th scope="row">${E(key)}</th><td>${E(observed)}</td><td>${E(declared)}</td></tr>`).join('')}</tbody></table></div><div class="manager-source-times"><p>자동 관측 조회<br><strong>${E(when(n.observedAt))}</strong></p><p>사양 등록<br><strong>${record?E(when(record.createdAt)):'등록 이력 없음'}</strong></p></div><p class="manager-footnote">보고 메모리는 제조사 총용량과 다를 수 있습니다. 등록 시각은 하드웨어 확인 시각이 아닙니다. 공유 메모리는 RAM과 합산하지 않습니다.</p>`;
}
function usage(n){const u=n.runtimeState?.utilization;return u&&current(u.observedAt)?`${number(u.cpuRatio===null?null:u.cpuRatio*100,'%')} / ${number(u.memoryRatio===null?null:u.memoryRatio*100,'%')}`:'미수집 / 오래된 관측';}
function nodeDetail(){
  const n=data.nodes.find(n=>n.uid===selected);
  if(!n)return '<section class="panel manager-detail manager-placeholder"><span class="manager-placeholder-icon" aria-hidden="true">↖</span><h2>관리할 장비를 선택하세요</h2><p>현재 상태와 실행 서비스를 먼저 확인하세요.<br>필요한 사양은 편집 버튼으로 보완할 수 있습니다.</p><p class="manager-footnote">선택 → 상태 확인 → 필요할 때 편집</p></section>';
  const binding=n.binding, bound=profileFor(binding?.profileRef), state=n.runtimeState;
  const fresh=!error&&current(data.observedAt);
  return `<section class="panel manager-detail" aria-labelledby="manager-detail-title"><div class="manager-heading"><div><p class="eyebrow">선택한 연산 장비</p><h2 id="manager-detail-title" tabindex="-1">${E(n.name)}</h2></div><span class="badge" data-manager-live>${fresh?(n.ready===true?'노드 준비됨':n.ready===false?'노드 준비 안 됨':'준비 미확인'):'관측 오래됨'}</span></div><p>${E(types[n.nodeType]||'연산 노드')} · ${E(n.architecture||'architecture 미확인')}</p>
    <h3>현재 자원 상태</h3><dl class="manager-facts"><div><dt>CPU 예약 여유</dt><dd data-manager-live>${fresh&&state?number(state.reservation.available.cpuCores,' cores'):'확인 불가'}</dd></div><div><dt>RAM 예약 여유</dt><dd data-manager-live>${fresh&&state?number(state.reservation.available.memoryBytes/1024**3,' GiB'):'확인 불가'}</dd></div><div><dt>실측 CPU / RAM 사용률</dt><dd data-manager-metric="${E(state?.utilization?.observedAt||'')}">${fresh?usage(n):'관측 오래됨'}</dd></div><div><dt>사용률 원래 시각</dt><dd>${E(when(state?.utilization?.observedAt))}</dd></div></dl><p class="manager-footnote">예약 여유는 allocatable에서 Pod requests를 뺀 값입니다. 현재 남은 실제 RAM과 구분합니다.</p>
    <div class="manager-heading manager-spec-heading"><div><h3>장비 사양</h3><p class="manager-footnote">자동 보고와 저장한 사양을 구분합니다.</p></div><button class="button" data-manager-edit ${canWrite()?'':'disabled'}>${nodeDrafts.has(n.uid)?'편집 계속':'사양 편집'}</button></div>
    ${specification(n,bound,data.profiles.find(p=>refKey(p.document.metadata)===refKey(binding?.profileRef)))}
    ${showForm&&editTarget?.uid===n.uid?fields():''}
    <h3>실행 서비스</h3>${n.services===null?'<p class="manager-warning">RuntimeService 원본 조회 실패 · 실행 여부 확인 불가</p>':!n.services.length?'<p>이 장비에 관측된 RuntimeService 실행 위치가 없습니다.</p>':`<ul class="manager-service-list">${n.services.map(s=>`<li><strong>${E(s.name)}</strong><span data-manager-service="${E(s.observedAt)}">${!s.current?'상태 미확인 · 마지막 위치':s.serving?'요청 처리 경로':s.role==='preparing'?'실행 준비 위치':s.role==='retiring'?'기존 요청 정리 위치':'서비스 중지/준비 상태'}</span></li>`).join('')}</ul>`}<p class="manager-footnote">공통 RuntimeService 기준입니다. 시스템 Pod나 일반 워크로드 전체를 AI 서비스로 집계하지 않습니다.</p>
    <details class="manager-advanced"><summary>고급: 프로파일 연결 관리</summary><p class="manager-footnote">${bound?E(bound.metadata.name)+' · v'+E(bound.metadata.version):'연결된 프로파일 없음'}</p><form id="manager-binding-form"><label for="manager-profile-choice">기존 프로파일 선택</label><div class="manager-binding"><select id="manager-profile-choice" name="profile"><option value="">연결 안 함 / 기존 연결 해제</option>${data.profiles.map(p=>{const ref=p.document.metadata,key=refKey(ref),arch=p.document.spec.hardware.architecture,mismatch=arch&&n.architecture&&arch!==n.architecture;return `<option value="${E(key)}" ${key===refKey(binding?.profileRef)?'selected':''} ${mismatch?'disabled':''}>${E(ref.name+' · v'+ref.version+(mismatch?' (architecture 불일치)':''))}</option>`;}).join('')}</select><button class="button primary" ${canWrite()?'':'disabled'}>연결 저장</button></div></form><div class="manager-actions"><button class="button" data-manager-new-node ${canWrite()?'':'disabled'}>새 Profile 추가</button><button class="button" data-manager-unbind ${canWrite()&&bound?'':'disabled'}>이 장비 연결 해제</button></div></details>
    <details><summary>식별·연결 근거</summary><dl class="manager-facts"><div><dt>원본</dt><dd>Kubernetes / KubeEdge</dd></div><div><dt>Node UID</dt><dd>${E(n.uid)}</dd></div><div><dt>연결 변경 시각</dt><dd>${E(when(binding?.updatedAt))}</dd></div></dl></details>
  </section>`;
}
function nodeList(){
  const rows=data.nodes.filter(n=>[n.name,n.architecture,types[n.nodeType],refKey(n.binding?.profileRef)].join(' ').toLowerCase().includes(query.toLowerCase()));
  const fresh=!error&&current(data.observedAt);
  return `<div class="manager-grid"><section class="panel manager-list-panel"><div class="manager-heading"><h2>연산 장비 <small>${data.sourceErrors.nodes?'확인 불가':data.nodes.length+'개'}</small></h2><label class="manager-search">장비 검색<input id="manager-search" type="search" value="${E(query)}" placeholder="장비명, architecture, Profile"></label></div><div class="table-wrap"><table class="data-table manager-table"><thead><tr><th>장비 / 종류</th><th>노드 상태</th><th>연결 Profile</th></tr></thead><tbody>${rows.map(n=>`<tr class="${n.uid===selected?'manager-selected':''}"><td data-label="장비 / 종류"><button class="text-button" data-manager-node="${E(n.uid)}" aria-pressed="${n.uid===selected}">${E(n.name)}</button><small>${E(types[n.nodeType]||'연산 노드')} · ${E(n.architecture||'미수집')}</small></td><td data-label="노드 상태" data-manager-live>${fresh?(n.ready===true?'준비됨':n.ready===false?'준비 안 됨':'미확인'):'관측 오래됨'}</td><td data-label="연결 Profile">${n.binding?.profileRef?E(n.binding.profileRef.name)+'<small>v'+E(n.binding.profileRef.version)+'</small>':'<span class="manager-unbound">미연결</span>'}</td></tr>`).join('')}</tbody></table></div>${!rows.length?`<p class="manager-empty">${data.sourceErrors.nodes?'장비 원본을 조회하지 못했습니다.':'검색에 맞는 장비가 없습니다.'}</p>`:''}<p class="manager-footnote">장비 선택 → 상태·사양·서비스 확인</p></section>${nodeDetail()}</div>`;
}
function sensors(){const fresh=!error&&current(data.observedAt);return `<section class="panel"><h2>센서·입력 장비 <small>${data.sourceErrors.sensors?'확인 불가':data.sensors.length+'개 등록 항목'}</small></h2><p>EdgeX Device 기준입니다. 같은 물리 source의 여러 기능을 별도 물리 장비 수로 합산하지 않습니다.</p><div class="table-wrap"><table class="data-table manager-table"><thead><tr><th>EdgeX Device / 물리 source</th><th>연결·수신 상태</th><th>EdgeX Profile</th><th>최근 Event</th></tr></thead><tbody>${data.sensors.map(s=>`<tr><td data-label="EdgeX Device / 물리 source"><strong>${E(s.name)}</strong><small>${E(s.physical_device_id||'물리 source 미지정')}</small></td><td data-label="연결·수신 상태" data-manager-live>${E(({connected:'연결됨',disconnected:'연결 끊김',unknown:'연결 미확인'})[fresh?s.connection_state:'unknown']||'연결 미확인')}<small>${E(({fresh:'최신 데이터 수신',stale:'수신 지연',no_events:'수신 이력 없음'})[fresh?s.telemetry_freshness:'unknown']||'수신 미확인')}</small></td><td data-label="EdgeX Profile">${E(s.profile_name)}<small>${E(s.device_service_name)}</small></td><td data-label="최근 Event">${E(when(s.latest_event_timestamp))}<small>${E(s.reason)}</small></td></tr>`).join('')}</tbody></table></div>${!data.sensors.length?`<p>${data.sourceErrors.sensors?'EdgeX 원본을 조회하지 못했습니다.':'등록된 센서가 없습니다.'}</p>`:''}<p class="note">센서 Profile의 등록·변경은 기존 EdgeX 관리 절차를 따릅니다. 연산 장비용 Profile로 대체하지 않습니다.</p></section>`;}
function profiles(){return `<section class="panel"><div class="manager-heading"><div><h2>장비 Profile <small>${data.profiles.length}개 버전</small></h2><p>동일한 능력표를 여러 장비에서 참조할 수 있습니다.</p></div><button class="button primary" data-manager-new ${canWrite()?'':'disabled'}>Profile 추가</button></div>${showForm&&!editTarget?fields():''}${data.profiles.length?data.profiles.map(p=>{const d=p.document;const linked=data.nodes.filter(n=>refKey(n.binding?.profileRef)===refKey(d.metadata)).length+data.detachedBindings.filter(b=>refKey(b.profileRef)===refKey(d.metadata)).length;return `<article class="manager-profile"><div class="manager-heading"><h3>${E(d.metadata.name)} <small>v${E(d.metadata.version)}</small></h3><div class="manager-actions"><button class="button" data-manager-copy="${E(refKey(d.metadata))}">새 버전 작성</button><button class="button" data-manager-delete="${E(refKey(d.metadata))}" ${!canWrite()||linked?'disabled':''}>미사용 버전 삭제</button></div></div><p>${linked}개 장비 참조 · ${E(when(p.createdAt))}</p>${profileSummary(d)}</article>`;}).join(''):'<p class="manager-empty">등록한 Profile이 없습니다. 장비의 확인된 능력부터 입력하세요.</p>'}</section>`;}
function detached(){return !data.detachedBindings.length?'':`<section class="panel manager-warning"><h2>원본 확인이 필요한 연결</h2><p>장비가 삭제·교체되었거나 원본을 읽지 못했습니다. 같은 이름의 새 장비로 연결을 자동 이전하지 않습니다.</p>${data.detachedBindings.map(b=>`<div class="manager-heading"><span>${E(b.nodeName)} · ${E(refKey(b.profileRef))}<small>UID ${E(b.nodeUid)}</small></span><button class="button" data-manager-detach="${E(b.nodeUid)}" ${canWrite()?'':'disabled'}>이 연결 해제</button></div>`).join('')}</section>`;}
function render(){
  if(!data&&!loading&&!error)queueMicrotask(refresh);
  if(!data)return `<section class="panel"><h2>Device Manager</h2><p role="status">${E(error||'장비 목록을 불러오는 중입니다…')}</p>${error?'<button class="button" data-manager-refresh>다시 조회</button>':''}</section>`;
  return `<div class="manager-workspace"><div class="manager-toolbar"><div class="manager-tabs" role="group" aria-label="장비 관리 보기">${[['nodes','연산 장비'],['sensors','센서·입력'],['profiles','공용 프로파일']].map(([id,name])=>`<button class="button" data-manager-tab="${id}" aria-pressed="${tab===id}">${name}${id==='profiles'?` <span class="manager-tab-count">${data.profiles.length}개 버전</span>`:''}</button>`).join('')}</div><button class="button" data-manager-refresh ${loading?'disabled':''}>${loading?'조회 중…':'새로고침'}</button></div><p class="manager-status" role="status">${E(error?'조회 실패: '+error:message||'장비를 선택해 현재 상태와 사양을 확인하세요.')}</p><p class="manager-footnote">조회 ${E(when(data.observedAt))} · <span id="manager-freshness">${current(data.observedAt)?'최근 응답':'오래된 응답 · 새로고침 필요'}</span>${!data.writable?' · 등록·연결 쓰기 비활성':''}</p>${Object.keys(data.sourceErrors).length?`<p class="manager-warning" role="alert">${E(Object.keys(data.sourceErrors).map(k=>labels[k]).join(' · '))} 조회 실패. 해당 상태와 개수는 확인 불가입니다.</p>`:''}${tab==='nodes'?nodeList():tab==='profiles'?profiles():sensors()}${detached()}</div>`;
}
async function write(path,method,body,success){
  if(busy)return;busy=true;message='저장 중…';redraw();
  try{
    await api(path,method,body);message=success;
    if(path.startsWith('/nodes/')){
      nodeDrafts.delete(body.nodeUid);
      if(editTarget?.uid===body.nodeUid){showForm=false;editTarget=null;copyBase=null;}
    }else if(method==='POST'&&!editTarget){showForm=false;copyBase=null;}
    await refresh();
  }catch(e){message=e.message;}finally{busy=false;redraw();}
}
function setup(){if(setupDone)return;setupDone=true;
  document.addEventListener('click',e=>{const b=e.target.closest('button');if(!b||busy)return;
    if(b.hasAttribute('data-manager-refresh'))refresh();
    if(b.dataset.managerTab){rememberDraft();tab=b.dataset.managerTab;message='';redraw();}
    if(b.dataset.managerNode&&!busy){rememberDraft();selected=b.dataset.managerNode;showForm=false;editTarget=null;copyBase=null;redraw();const target=document.getElementById('manager-detail-title');target?.focus({preventScroll:true});if(root.innerWidth<1000)target?.scrollIntoView({block:'start'});}
    if(b.hasAttribute('data-manager-new')){rememberDraft();editTarget=null;copyBase=null;draft={name:'',version:'1.0',architecture:'',deviceClass:'compute-node',type:'unknown'};showForm=true;redraw();document.querySelector('#manager-profile-form input')?.focus();}
    if(b.hasAttribute('data-manager-edit')){if(!(showForm&&editTarget?.uid===selected))openNodeEditor(data.nodes.find(n=>n.uid===selected));redraw();document.querySelector('#manager-profile-form [name="cpu"]')?.focus();}
    if(b.hasAttribute('data-manager-cancel')){if(editTarget)nodeDrafts.delete(editTarget.uid);showForm=false;editTarget=null;copyBase=null;redraw();}
    if(b.hasAttribute('data-manager-new-node')){const n=data.nodes.find(n=>n.uid===selected);openNodeEditor(n,true);copyBase=null;draft=suggestedDraft(n,data.profiles);redraw();document.querySelector('#manager-profile-form [name="cpu"]')?.focus();}
    if(b.hasAttribute('data-manager-unbind')){const n=data.nodes.find(n=>n.uid===selected);write('/nodes/'+encodeURIComponent(n.name)+'/profile','PUT',{nodeUid:n.uid,expectedRevision:n.binding?.revision||0,profileRef:null},'이 장비의 Profile 연결을 해제했습니다.');}
    if(b.dataset.managerCopy){rememberDraft();editTarget=null;const d=data.profiles.find(p=>refKey(p.document.metadata)===b.dataset.managerCopy).document;copyBase=d;draft=fieldsFromProfile(d);draft.version=nextVersion(draft.name,data.profiles);showForm=true;message='새 버전으로 저장합니다. 기존 장비 연결은 유지합니다.';redraw();document.querySelector('[name="version"]')?.focus();}
    if(b.dataset.managerDelete){const [name,version]=b.dataset.managerDelete.split('@');write('/profiles/'+encodeURIComponent(name)+'/'+encodeURIComponent(version),'DELETE',undefined,'미사용 Profile 버전을 삭제했습니다.');}
    if(b.dataset.managerDetach){const binding=data.detachedBindings.find(d=>d.nodeUid===b.dataset.managerDetach);write('/nodes/'+encodeURIComponent(binding.nodeName)+'/profile','PUT',{nodeUid:binding.nodeUid,expectedRevision:binding.revision,profileRef:null},'원본이 없는 연결을 해제했습니다.');}
  });
  document.addEventListener('input',e=>{if(e.target.closest('#manager-profile-form'))draft[e.target.name]=e.target.value;if(e.target.id==='manager-search'){query=e.target.value;const start=e.target.selectionStart;redraw();const next=document.getElementById('manager-search');next.focus();next.setSelectionRange(start,start);}});
  document.addEventListener('change',e=>{if(e.target.closest('#manager-profile-form')){draft[e.target.name]=e.target.value;if(e.target.name==='accelerator')document.querySelector('#manager-profile-form .manager-accelerator').open=['gpu','npu'].includes(e.target.value);}});
  document.addEventListener('invalid',e=>{if(e.target.closest('#manager-profile-form')){const details=e.target.closest('details');if(details)details.open=true;}},true);
  document.addEventListener('submit',e=>{
    if(e.target.id==='manager-profile-form'){e.preventDefault();if(!canWrite())return;const body=profileFromFields(Object.fromEntries(new FormData(e.target)),copyBase);if(editTarget)write('/nodes/'+encodeURIComponent(editTarget.name)+'/profile-document','PUT',{nodeUid:editTarget.uid,expectedRevision:editTarget.revision,document:body},'Profile을 저장하고 선택한 장비에 연결했습니다.');else write('/profiles','POST',body,'Profile을 추가했습니다.');}
    if(e.target.id==='manager-binding-form'){e.preventDefault();const n=data.nodes.find(n=>n.uid===selected);const value=new FormData(e.target).get('profile');const p=data.profiles.find(p=>refKey(p.document.metadata)===value);write('/nodes/'+encodeURIComponent(n.name)+'/profile','PUT',{nodeUid:n.uid,expectedRevision:n.binding?.revision||0,profileRef:p?p.document.metadata:null},value?'Profile 연결을 저장했습니다.':'Profile 연결을 해제했습니다.');}
  });
  setInterval(()=>{if(!data||root.location.hash!=='#device-manager')return;const stale=!current(data.observedAt)||Boolean(error);if(stale){document.querySelectorAll('[data-manager-live]').forEach(el=>el.textContent='오래된 응답 · 새로고침 필요');const stamp=document.getElementById('manager-freshness');if(stamp)stamp.textContent='오래된 응답 · 새로고침 필요';}document.querySelectorAll('[data-manager-metric]').forEach(el=>{if(stale||!current(el.dataset.managerMetric))el.textContent='미수집 / 오래된 관측';});document.querySelectorAll('[data-manager-service]').forEach(el=>{if(stale||!Number.isFinite(Number(el.dataset.managerService))||!(Date.now()/1000-Number(el.dataset.managerService)>=0&&Date.now()/1000-Number(el.dataset.managerService)<=15))el.textContent='현재 실행 상태 미확인';});},5000);
}
const exported={render,setup,profileFromFields,fieldsFromProfile,fieldsFromNode,suggestedDraft,specification,nextVersion,current};if(typeof module!=='undefined'&&module.exports)module.exports=exported;else root.NexusDeviceManager=exported;
})(typeof window!=='undefined'?window:globalThis);
