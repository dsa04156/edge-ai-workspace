(function(root){
'use strict';
const E=root.NexusData.escape,entries=new Map();let redraw=()=>{};
const modes={preferred:'선호 위치 유지',automatic:'자동 배치·복귀',approval:'승인 후 배치'};
const errors={service_settings_owned_by_git:'Git에서 관리하는 서비스입니다. 원본 계약에서 변경하세요.',automatic_policy_requires_qualification:'새 모델·이미지의 성능 검증을 마친 뒤 자동 배치를 사용할 수 있습니다.',service_must_be_stopped:'서비스를 중지하고 정리가 끝난 뒤 설정을 저장할 수 있습니다.',service_settings_changed:'다른 곳에서 설정이 변경됐습니다. 최신 설정을 다시 불러오세요.',service_identity_changed:'서비스가 삭제되거나 다시 등록됐습니다. 목록을 새로고침하세요.',settings_violate_registered_contract:'등록된 모델·배치 조건에 맞지 않는 설정입니다.',node_outside_registered_contract:'등록된 실행 후보 노드만 선택할 수 있습니다.',runtime_snapshot_unavailable:'실행 제어기의 최신 상태를 확인할 수 없습니다.',settings_not_applied:'설정 반영을 확인하지 못했습니다. 최신 설정을 다시 불러오세요.',common_runtime_demo_disabled:'현재 배포에서 서비스 설정 변경이 비활성화되어 있습니다.',settings_source_unavailable:'설정 API 연결을 확인할 수 없습니다.',settings_backend_not_deployed:'현재 설정을 조회했습니다. 저장하려면 새 설정 API를 운영 배포해야 합니다.'};
function endpoint(d){return '/api/service-virtual-devices/'+encodeURIComponent(d.service_name)+'/settings';}
function render(d){
 const e=entries.get(d.service_uid);
 if(!e)return `<button class="button" data-vd-settings="${E(d.service_uid)}" data-vd-name="${E(d.service_name)}">서비스 설정</button>`;
 const view=e.data,p=e.draft,disabled=e.busy||!view?.editable;
 if(!view)return `<section class="vd-settings"><h3>서비스 설정</h3><p role="status">${E(e.busy?'설정 조회 중…':e.error)}</p><button class="button" data-vd-settings="${E(d.service_uid)}" data-vd-name="${E(d.service_name)}" ${e.busy?'disabled':''}>최신 설정 불러오기 · 입력 초기화</button></section>`;
 const options=(values,value,labels={})=>[...new Set([value,...values].filter(v=>v!=null))].map(v=>`<option value="${E(v)}" ${v===value?'selected':''}>${E(labels[v]||v)}</option>`).join('');
 const number=(name,label,min,max,scale=1)=>`<label>${label}<input id="vd-setting-${E(d.service_uid)}-${name}" name="${name}" type="number" min="${min}" max="${max}" step="any" required value="${E(p[name]*scale)}"></label>`;
 return `<section class="vd-settings" aria-label="${E(d.service_name)} 설정"><div class="section-heading"><h3>서비스 설정</h3><button class="button" data-vd-settings="${E(d.service_uid)}" data-vd-name="${E(d.service_name)}" ${e.busy?'disabled':''}>최신 설정 불러오기 · 입력 초기화</button></div><p>설정을 저장한 뒤 실행 화면에서 서비스를 시작하세요.</p>${!view.editable?`<p class="dm-notice">${E(errors[view.reason]||'서비스를 중지한 뒤 설정을 변경할 수 있습니다.')}</p>`:''}<form data-vd-settings-form="${E(d.service_uid)}"><fieldset ${disabled?'disabled':''}><div class="vd-settings-fields"><label>배치 방식<select id="vd-setting-${E(d.service_uid)}-mode" name="mode">${options(view.constraints.modes,p.mode,modes)}</select></label><label>선호 노드 종류<select id="vd-setting-${E(d.service_uid)}-preferredRole" name="preferredRole">${options(view.constraints.roles,p.preferredRole,{edge:'엣지',server:'서버'})}</select></label><label>실행 노드<select id="vd-setting-${E(d.service_uid)}-nodeName" name="nodeName" ${!view.constraints.nodeSelectionAllowed?'disabled':''}><option value="" ${p.nodeName==null?'selected':''}>등록된 후보에서 선택</option>${options(view.constraints.nodes,p.nodeName)}</select><small>${view.constraints.nodeSelectionAllowed?'설정한 노드의 등록 조건을 실행 전에 다시 확인합니다.':'단계형 정책은 등록된 노드 순서를 따릅니다.'}</small></label>${number('highWatermark','부하 증가 기준 (%)',1,100,100)}${number('lowWatermark','부하 감소 기준 (%)',0,99,100)}${number('pressureSeconds','부하 증가 유지 시간 (초)',1,3600)}${number('returnSeconds','복귀 관찰 시간 (초)',1,86400)}${number('cooldownSeconds','재배치 대기 시간 (초)',1,86400)}</div></fieldset><div class="vd-settings-footer"><button class="button primary" type="submit" ${disabled||root.NexusPreviewReadOnly?'disabled':''}>${e.busy?'저장 중…':'설정 저장'}</button><span role="status">${E(e.error||e.message||(root.NexusPreviewReadOnly?'미리보기 · 입력값을 저장하지 않습니다.':'저장해도 자동으로 실행하지 않습니다.'))}</span></div></form><details><summary>모델·컨테이너 등록 정보</summary><p>모델과 컨테이너 이미지는 등록 계약에 따라 표시됩니다.</p>${view.variants.map(v=>`<dl><dt>실행 형태</dt><dd>${E(v.name)} · ${E(v.architecture)}</dd><dt>컨테이너 이미지</dt><dd>${E(v.image)}</dd><dt>요청 / 제한 자원</dt><dd>${E(JSON.stringify(v.requests))} / ${E(JSON.stringify(v.limits))}</dd></dl>`).join('')}</details>${root.NexusServiceDefinition?.render(view)||''}</section>`;
}
async function request(d,method,body){
 const response=await root.fetch(endpoint(d)+(method==='GET'?'?serviceUid='+encodeURIComponent(d.service_uid):''),{method,cache:'no-store',headers:{'Content-Type':'application/json','X-Runtime-Demo':'1'},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(10000)});
 let data;try{data=await response.json();}catch{throw Error('설정 API가 아직 연결되지 않았습니다.');}if(!response.ok)throw Error(errors[data.detail]||(response.status===404?'설정 API가 아직 연결되지 않았습니다.':'설정을 확인하지 못했습니다. 다시 조회하세요.'));
 if(data.uid!==d.service_uid||data.name!==d.service_name||!data.settings||!data.constraints||!Array.isArray(data.variants))throw Error('설정 응답의 서비스 식별자를 확인할 수 없습니다.');return data;
}
async function load(uid,name){
 const prior=entries.get(uid);if(prior?.busy)return;
 const e={...prior,busy:true,error:null,message:null,device:{service_uid:uid,service_name:name}};entries.set(uid,e);redraw();
 try{e.data=await request(e.device,'GET');e.draft={...e.data.settings};root.NexusServiceDefinition?.drafts.delete(uid);}catch(error){e.error=error.message;}finally{e.busy=false;redraw();}
}
async function save(uid){
 const e=entries.get(uid);if(!e||e.busy||!e.data.editable||root.NexusPreviewReadOnly)return;
 if(e.draft.lowWatermark>=e.draft.highWatermark){e.error='부하 감소 기준은 증가 기준보다 작아야 합니다.';redraw();return;}
 e.busy=true;e.error=null;e.message=null;redraw();
 try{e.data=await request(e.device,'PUT',{serviceUid:uid,specRevision:e.data.specRevision,settings:e.draft});e.draft={...e.data.settings};e.message='설정을 저장했습니다. 실행은 별도입니다.';root.NexusLive?.store.refreshServiceDevices();}
 catch(error){e.error=error.message;}finally{e.busy=false;redraw();}
}
function setup(callback){redraw=callback;root.document.addEventListener('click',event=>{const b=event.target.closest('[data-vd-settings]');if(b&&!b.disabled)load(b.dataset.vdSettings,b.dataset.vdName);});root.document.addEventListener('input',event=>{const form=event.target.closest('[data-vd-settings-form]');if(!form)return;const e=entries.get(form.dataset.vdSettingsForm),key=event.target.name;if(!e||e.busy||!Object.hasOwn(e.draft,key))return;const raw=event.target.value;e.draft[key]=key==='mode'||key==='preferredRole'?raw:key==='nodeName'?raw||null:Number(raw)/(['highWatermark','lowWatermark'].includes(key)?100:1);e.message=null;});root.document.addEventListener('submit',event=>{const form=event.target.closest('[data-vd-settings-form]');if(form){event.preventDefault();save(form.dataset.vdSettingsForm);}});}
const api={render,setup,load,save,entries};root.NexusServiceSettings=api;if(typeof module!=='undefined')module.exports=api;
})(typeof window!=='undefined'?window:globalThis);
