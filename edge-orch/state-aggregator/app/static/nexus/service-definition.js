(function(root){
'use strict';
const E=root.NexusData.escape, drafts=new Map();let redraw=()=>{},registrationMessage='';
const errors={service_settings_changed:'다른 곳에서 설정이 바뀌었습니다. 최신 설정을 다시 조회하세요. 입력 중인 값은 보존했습니다.',service_identity_changed:'서비스 식별자가 바뀌었습니다. 목록을 다시 조회하세요.',service_name_exists:'같은 이름이 이미 등록되어 있습니다. 이름을 바꾸거나 기존 항목을 확인하세요.',settings_violate_registered_contract:'이미지 digest, 모델 입출력, 자원 요청과 제한을 확인하세요.',resident_definition_requires_deployment_contract:'상주 Llama의 모델·이미지 교체에는 별도 배포 계약이 필요합니다.',service_settings_owned_by_git:'Git에서 관리하는 서비스입니다. 원본 계약에서 변경하세요.',definition_requires_stopped_preferred_policy:'등록 정보 변경은 중지 상태와 선호 위치 정책에서만 가능합니다.',settings_not_applied:'저장 결과를 확인하지 못했습니다. 목록과 최신 설정을 조회한 뒤 다시 시도하세요.',runtime_snapshot_unavailable:'실행 제어기의 최신 상태를 확인할 수 없습니다.',service_must_be_stopped:'서비스 중지와 정리가 끝난 뒤 저장하세요.',settings_backend_not_deployed:'미리보기에서는 저장하지 않습니다. 설정 API 운영 배포가 필요합니다.',common_runtime_demo_disabled:'현재 배포에서 서비스 등록이 비활성화되어 있습니다.'};
function initial(){return {serviceKind:'service',execution:'http-json-v1',ioContract:'http-json-v1',port:8080,readyPath:'/ready',requestPath:'/infer',timeoutSeconds:30,suspended:true,policy:{mode:'preferred',preferredRole:'edge',allowedRoles:['edge','server']},variants:[{name:'default',image:'',architecture:'arm64',backend:'http',nodeSelector:{},requests:{cpu:'500m',memory:'512Mi'},limits:{cpu:'1',memory:'1Gi'},qualification:'dashboard-unqualified',maxInFlight:1}],demo:{label:'서비스 요청',payload:{}}};}
function begin(key,view){
 if(drafts.has(key))return;
 const spec=structuredClone(view?.spec||initial());
 drafts.set(key,{name:view?.name||'',view,spec,json:{inputs:JSON.stringify(spec.modelRuntime?.inputs||[],null,2),outputs:JSON.stringify(spec.modelRuntime?.outputs||[],null,2),payload:JSON.stringify(spec.demo?.payload||{},null,2)},busy:false,error:null});
}
function launcher(){return `<div class="vd-registration"><button id="vd-register-open" class="button" data-vd-register>가상 디바이스 등록</button>${registrationMessage?`<p role="status">${E(registrationMessage)}</p>`:''}${drafts.has('new')?editor('new'):''}</div>`;}
function render(view){
 if(!view.spec)return '';
 if(!view.definitionEditable)return `<p class="dm-notice">등록 정보: ${E(errors[view.definitionReason||view.reason]||'중지 상태를 확인한 뒤 수정할 수 있습니다.')}</p>`;
 return drafts.has(view.uid)?editor(view.uid):`<button class="button" data-vd-definition="${E(view.uid)}">모델·컨테이너 설정 수정</button>`;
}
function editor(key){
 const d=drafts.get(key),s=d.spec,isNew=key==='new',id='vd-definition-'+key;
 const input=(path,label,value,type='text',extra='')=>`<label>${label}<input id="${E(id+'-'+path)}" data-vd-path="${E(path)}" type="${type}" value="${E(value??'')}" ${extra}></label>`;
 const select=(path,label,value,values)=>`<label>${label}<select aria-label="${E(label)}" id="${E(id+'-'+path)}" data-vd-path="${E(path)}">${values.map(([v,l])=>`<option value="${v}" ${value===v?'selected':''}>${l}</option>`).join('')}</select></label>`;
 const json=(field,label)=>`<label class="vd-wide">${label}<textarea id="${E(id+'-'+field)}" data-vd-json="${field}" rows="5" spellcheck="false">${E(d.json[field])}</textarea></label>`;
 return `<form class="vd-settings" data-vd-definition-form="${E(key)}"><h3>${isNew?'새 가상 디바이스 등록':'모델·컨테이너 설정'}</h3><p>등록·수정 후 중지 상태로 유지합니다. 성능 검증은 초기화되며, 동시 요청 1개와 선호 위치 정책부터 적용합니다.</p><fieldset ${d.busy?'disabled':''}><div class="vd-settings-fields">${isNew?input('name','서비스 이름',d.name,'text','required pattern="[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?"'):`<p>서비스: <strong>${E(d.name)}</strong></p>`}${isNew?select('kind','서비스 종류',s.modelRuntime?'ai':'service',[['service','일반 HTTP 서비스'],['ai','AI 모델 서비스']]):''}${input('ioContract','입출력 계약 이름',s.ioContract,'text','required')}${input('port','서비스 포트',s.port,'number','min="1024" max="65535" required')}${input('readyPath','준비 상태 경로',s.readyPath,'text','required')}${!s.modelRuntime?input('requestPath','요청 경로',s.requestPath,'text','required'):''}</div>${s.modelRuntime?`<h4>모델</h4><div class="vd-settings-fields">${input('modelRuntime.modelName','모델 이름',s.modelRuntime.modelName,'text','required')}${input('modelRuntime.modelVersion','모델 버전 (SHA-256)',s.modelRuntime.modelVersion,'text','required pattern="[a-f0-9]{64}"')}${select('modelRuntime.inputKind','입력 종류',s.modelRuntime.inputKind,[['tensor','텐서'],['image','이미지'],['sensor-window','센서 구간']])}${json('inputs','입력 텐서 계약 (JSON)')}${json('outputs','출력 텐서 계약 (JSON)')}</div><p>예: [{"name":"input","datatype":"FP32","shape":[1,4]}]. 실제 컨테이너가 제공하는 계약을 입력하세요.</p>`:''}${s.variants.map((v,i)=>`<h4>컨테이너 · ${E(v.name)}</h4><div class="vd-settings-fields">${input('variants.'+i+'.image','이미지 (이름@sha256:digest)',v.image,'text','required pattern="[^\\s]+@sha256:[a-f0-9]{64}"')}${select('variants.'+i+'.architecture','CPU 구조',v.architecture,[['arm64','ARM64'],['amd64','AMD64']])}${input('node-'+i,'실행 후보 노드',v.nodeSelector?.['kubernetes.io/hostname'],'text','placeholder="비우면 조건에 맞는 후보에서 선택"')}${input('variants.'+i+'.requests.cpu','CPU 요청',v.requests.cpu,'text','required')}${input('variants.'+i+'.limits.cpu','CPU 제한',v.limits.cpu,'text','required')}${input('variants.'+i+'.requests.memory','메모리 요청',v.requests.memory,'text','required')}${input('variants.'+i+'.limits.memory','메모리 제한',v.limits.memory,'text','required')}</div>`).join('')}<h4>시험 입력</h4><p>실행 후 요청할 JSON입니다. 등록 시에는 요청을 전송하지 않습니다.</p><div class="vd-settings-fields">${json('payload','요청 본문 (JSON)')}</div></fieldset><div class="vd-settings-footer"><button class="button primary" type="submit" ${d.busy||root.NexusPreviewReadOnly?'disabled':''}>${d.busy?'저장 중…':isNew?'중지 상태로 등록':'등록 정보 저장'}</button><button class="button" type="button" data-vd-definition-close="${E(key)}" ${d.busy?'disabled':''}>닫기</button><span role="status">${E(d.error||d.message||(root.NexusPreviewReadOnly?'미리보기 · 입력값을 저장하지 않습니다.':'실행은 서비스 운영 화면에서 별도로 시작합니다.'))}</span></div></form>`;
}
function update(key,path,value){
 const d=drafts.get(key);if(!d||d.busy)return;
 d.error=null;d.message=null;
 if(path==='name'){d.name=value;return;}
 if(path==='kind'){
  d.spec.serviceKind=value;
  if(value==='ai')d.spec.modelRuntime={protocol:'inference-v2-json',modelName:'',modelVersion:'',inputKind:'tensor',inputs:[],outputs:[]};
  else {delete d.spec.modelRuntime;d.spec.requestPath='/infer';}
  redraw();return;
 }
 if(path.startsWith('node-')){const v=d.spec.variants[Number(path.slice(5))];v.nodeSelector||={};if(value)v.nodeSelector['kubernetes.io/hostname']=value;else delete v.nodeSelector['kubernetes.io/hostname'];return;}
 const parts=path.split('.'),last=parts.pop();let obj=d.spec;for(const p of parts)obj=obj[p];obj[last]=path==='port'?Number(value):value;
}
function payload(d){
 const spec=structuredClone(d.spec);spec.suspended=true;spec.policy={...spec.policy,mode:'preferred',approvalRequired:false,stages:[],latency:null};
 spec.demo={...(spec.demo||{label:'서비스 요청'}),payload:JSON.parse(d.json.payload)};
 if(spec.modelRuntime){spec.modelRuntime.inputs=JSON.parse(d.json.inputs);spec.modelRuntime.outputs=JSON.parse(d.json.outputs);spec.requestPath='/v2/models/'+spec.modelRuntime.modelName+'/infer';}
 return spec;
}
async function save(key){
 const d=drafts.get(key);if(!d||d.busy||root.NexusPreviewReadOnly)return;
 let spec;try{spec=payload(d);}catch{d.error='텐서 계약과 시험 입력의 JSON 형식을 확인하세요.';redraw();return;}
 const isNew=key==='new';d.busy=true;d.error=null;redraw();
 try{
  const response=await root.fetch('/api/service-virtual-devices/'+(isNew?'registration':encodeURIComponent(d.name)+'/definition'),{method:isNew?'POST':'PUT',headers:{'Content-Type':'application/json','X-Runtime-Demo':'1'},body:JSON.stringify(isNew?{name:d.name,spec}:{serviceUid:key,specRevision:d.view.specRevision,spec}),signal:AbortSignal.timeout(10000)});
  let data;try{data=await response.json();}catch{throw Error('설정 API에 연결하지 못했습니다. 저장 결과를 다시 확인하세요.');}
  if(!response.ok)throw Error(errors[data.detail]||'등록 계약을 확인하거나 설정 API 연결 상태를 확인하세요.');
  if(!data.uid||data.name!==d.name||(!isNew&&data.uid!==key)||!data.spec)throw Error('저장 응답의 서비스 식별자를 확인하지 못했습니다.');
  if(isNew){registrationMessage=d.name+' 등록 완료 · 중지 상태입니다. 목록 반영을 기다리고 있습니다.';d.registered=true;}
  else{const entry=root.NexusServiceSettings.entries.get(key);if(entry){entry.data=data;entry.draft={...data.settings};}d.view=data;d.spec=structuredClone(data.spec);d.message='등록 정보를 저장했습니다. 성능 검증 전 상태입니다.';}
  root.NexusLive?.store.refreshServiceDevices();
 }catch(error){d.error=error.message;}finally{d.busy=false;if(d.registered)drafts.delete(key);redraw();}
}
function setup(callback){redraw=callback;root.document.addEventListener('click',event=>{
 const open=event.target.closest('[data-vd-register]');if(open){registrationMessage='';begin('new');redraw();root.document.getElementById('vd-definition-new-name')?.focus();}
 const edit=event.target.closest('[data-vd-definition]');if(edit){const key=edit.dataset.vdDefinition,view=root.NexusServiceSettings.entries.get(key)?.data;if(view?.definitionEditable){begin(key,view);redraw();}}
 const close=event.target.closest('[data-vd-definition-close]');if(close&&!close.disabled){drafts.delete(close.dataset.vdDefinitionClose);redraw();}
 });root.document.addEventListener('input',event=>{const f=event.target.closest('[data-vd-definition-form]');if(!f)return;const key=f.dataset.vdDefinitionForm,d=drafts.get(key);if(!d||d.busy)return;if(event.target.dataset.vdJson)d.json[event.target.dataset.vdJson]=event.target.value;else if(event.target.dataset.vdPath)update(key,event.target.dataset.vdPath,event.target.value);});root.document.addEventListener('submit',event=>{const f=event.target.closest('[data-vd-definition-form]');if(f){event.preventDefault();save(f.dataset.vdDefinitionForm);}});}
root.NexusServiceDefinition={launcher,render,setup,begin,update,payload,save,drafts};
})(typeof window!=='undefined'?window:globalThis);
