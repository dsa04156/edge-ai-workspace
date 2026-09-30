(function (root) {
'use strict';
const E = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const kinds = {
  DeviceProfile: ['장비 능력', '기본 하드웨어와 지원 기능을 정의합니다.'],
  ServiceProfile: ['서비스 요구사항', '최소·권장·최대 자원과 실행 형태를 정의합니다.'],
  VirtualDeviceProfile: ['가상 디바이스', '서버 실행환경의 명세 초안입니다. 생성·바인딩은 후속 단계입니다.'],
  RuntimeState: ['현재 상태', '관측 시각·예약 여유·실제 사용률을 분리합니다.']
};
const reasons = {
  architecture_mismatch: '지원 architecture 불일치',
  node_unschedulable: '스케줄링이 중지된 노드',
  architecture_unreported: 'architecture 미수집', node_not_ready: '노드 준비 안 됨',
  node_readiness_unreported: '노드 준비 상태 미수집',
  insufficient_reserved_cpu_headroom: 'CPU 예약 여유 부족',
  insufficient_reserved_memory_headroom: '메모리 예약 여유 부족',
  runtime_model_qualification_unverified: 'runtime·모델 실행/성능 검증 필요',
  accelerator_capability_unverified: '가속기·메모리 호환성 확인 필요',
  network_capacity_unreported: '네트워크 가용 대역폭 미수집',
  utilization_stale_or_unreported: '사용률이 오래되었거나 미수집'
};
let catalog, loading = false, failure = '', selected = 'ServiceProfile', drafts = {}, setupDone = false;
let observationGeneration = 0;
async function api(path, document) {
  const response = await fetch('/api/v1/profile-spec' + path, {
    cache: 'no-store', ...(document === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:document})
  });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '입력 명세를 확인하세요.');
  return data;
}
function render() {
  if (!catalog && !loading && !failure) load();
  if (!catalog) return `<section class="panel profile-workspace"><h2>Profile v1</h2><p role="status">${E(failure || '명세를 불러오는 중입니다…')}</p>${failure ? '<button class="button" data-profile-retry>다시 불러오기</button>' : ''}</section>`;
  queueMicrotask(refreshObservations);
  return `<div class="profile-workspace">
    <div class="profile-intro"><span class="badge">v1 초안</span><p>장비의 능력과 서비스의 요구사항을 같은 기준으로 정리합니다. <strong>예제는 등록된 장비·서비스가 아닙니다.</strong></p></div>
    <section class="panel"><div class="profile-section-heading"><div><h2>명세 작성·검증</h2><p>종류를 선택해 예제를 수정하고 검증하세요. 입력은 이 화면에서만 유지됩니다.</p></div><label>명세 종류<select id="profile-kind">${Object.entries(kinds).map(([kind,[label]]) => `<option value="${kind}" ${kind===selected?'selected':''}>${label} · ${kind}</option>`).join('')}</select></label></div>
      <div class="profile-editor-grid"><div><h3 id="profile-kind-title">${E(kinds[selected][0])}</h3><p>${E(kinds[selected][1])}</p><dl class="profile-principles"><div><dt>능력 기반 매칭</dt><dd>장비명 목록 대신 architecture·runtime·자원 조건을 사용합니다.</dd></div><div><dt>요구량 구분</dt><dd>minimum은 최소, recommended는 권장, maximum은 최대입니다. 미확정 최대값은 null입니다.</dd></div><div><dt>다음 연결</dt><dd>검증한 명세를 버전 있는 파일로 정리한 뒤 Device Manager와 Workflow가 참조합니다.</dd></div></dl><button class="button" data-profile-example>이 종류의 예제로 되돌리기</button><details><summary>검증에 쓰는 JSON Schema</summary><pre>${E(JSON.stringify(catalog.schemas[selected],null,2))}</pre></details></div>
      <div><label for="profile-document">${E(selected)} · JSON</label><textarea id="profile-document" spellcheck="false" aria-describedby="profile-input-help">${E(draft())}</textarea><p id="profile-input-help" class="note">64 KiB 이하 · JSON과 YAML은 같은 Schema를 사용하며 웹 입력은 JSON부터 지원합니다.</p><div class="profile-actions"><button class="button primary" data-profile-validate>명세 검증</button><button class="button" data-profile-compare ${selected==='ServiceProfile'?'':'disabled'}>현재 장비와 비교</button><button class="button" data-profile-download>JSON 내려받기</button></div><div id="profile-validation" aria-live="polite"></div></div></div>
    </section>
    <section class="panel" aria-labelledby="profile-observation-heading"><div class="profile-section-heading"><div><h2 id="profile-observation-heading">현재 장비 관측</h2><p>Kubernetes 예약 여유와 Prometheus 사용률입니다. 하드웨어 총용량·지원 runtime은 별도 확인이 필요합니다.</p></div><button class="button" data-profile-refresh>관측 새로고침</button></div><div id="profile-observations" aria-live="polite">장비를 조회하는 중입니다…</div></section>
    <section class="panel"><h2>서비스 요구사항 비교</h2><p>ServiceProfile을 선택하고 ‘현재 장비와 비교’를 누르면 제외·추가 검증 사유를 보여줍니다. 실제 배치는 실행하지 않습니다.</p><div id="profile-comparison" aria-live="polite">아직 비교하지 않았습니다.</div></section>
  </div>`;
}
function draft() { return drafts[selected] ?? JSON.stringify(catalog.examples[selected],null,2); }
function redraw() { if (root.location.hash === '#profiles') document.querySelector('#content').innerHTML = render(); }
async function load() {
  loading = true; failure = '';
  try { catalog = await api(''); } catch (error) { failure = '명세를 불러오지 못했습니다. ' + error.message; }
  finally { loading = false; redraw(); }
}
function number(value, digits=1) { return typeof value === 'number' && Number.isFinite(value) ? value.toLocaleString('ko-KR',{maximumFractionDigits:digits}) : '미수집'; }
function ratio(value) { return typeof value === 'number' ? number(value*100)+'%' : '미수집'; }
function observationHTML(data, now=Date.now()) {
  if (data.observationError) return '<p class="profile-error" role="alert">장비 원본을 조회하지 못했습니다. 현재 상태를 판단할 수 없습니다.</p>';
  if (!data.devices.length) return '<p>조회된 연산 노드가 없습니다. 예제 장비를 실제 목록에 추가하지 않습니다.</p>';
  const states = new Map(data.states.map(s=>[s.metadata.deviceId,s.status]));
  const profiles = new Map(data.profiles.map(p=>[p.metadata.name,p]));
  return `<p class="note">조회 ${E(new Date(data.observedAt).toLocaleString('ko-KR'))} · ${data.devices.length}개 노드 · 읽기 전용 변환</p><div class="table-wrap"><table class="data-table"><thead><tr><th>노드 / architecture</th><th>Kubernetes 상태</th><th>CPU 예약 여유</th><th>메모리 예약 여유</th><th>실측 CPU / 메모리</th><th>관측 문서</th></tr></thead><tbody>${data.devices.map(d=>{
    const s=states.get(d.id), p=profiles.get(d.profileRef.name), u=s.utilization;
    const age=u ? now-Date.parse(u.observedAt) : NaN;
    const fresh=Number.isFinite(age)&&age>=0&&age<=data.maxAgeSeconds*1000;
    return `<tr><td><strong>${E(d.id)}</strong><small>${E(p.spec.hardware.architecture || '미수집')}</small></td><td>${E(s.phase)}</td><td>${number(s.reservation.available.cpuCores)} cores</td><td>${number(s.reservation.available.memoryBytes/1024**3)} GiB</td><td data-profile-usage-at="${E(u?.observedAt || '')}" data-profile-max-age="${E(data.maxAgeSeconds)}">${fresh ? ratio(u.cpuRatio)+' / '+ratio(u.memoryRatio) : '미수집 / 오래된 관측'}<small>${fresh ? E(new Date(u.observedAt).toLocaleTimeString('ko-KR')) : '사용률 판단 보류'}</small></td><td><details><summary>Profile·State 보기</summary><pre>${E(JSON.stringify({profile:p,device:d,runtimeState:data.states.find(v=>v.metadata.deviceId===d.id)},null,2))}</pre></details></td></tr>`;
  }).join('')}</tbody></table></div><p class="note">예약 여유 = allocatable − Pod requests. 실제 남은 RAM과 다릅니다. 관측 Profile은 등록 원장이 아니며 같은 알려진 능력의 노드는 공통 profileRef를 사용합니다.</p>`;
}
async function refreshObservations() {
  const target=document.querySelector('#profile-observations'); if(!target)return;
  const generation=++observationGeneration;
  target.textContent='장비를 조회하는 중입니다…';
  try { const data=await api('/observations'); if(generation===observationGeneration&&target.isConnected){target.innerHTML=observationHTML(data);} }
  catch(error) { if(target.isConnected)target.textContent='관측 조회 실패: '+error.message; }
}
async function validate(compareRequested, button) {
  const input=document.querySelector('#profile-document');
  const target=document.querySelector(compareRequested?'#profile-comparison':'#profile-validation');
  const submitted=input.value; drafts[selected]=submitted; button.disabled=true; target.textContent='검증 중입니다…';
  try {
    const validation=await api('/validate',submitted);
    if(!target.isConnected||input.value!==submitted)return;
    if(!validation.valid){target.innerHTML='<ul class="profile-error">'+validation.errors.map(e=>`<li><code>${E(e.path)}</code>: ${E(e.message)}</li>`).join('')+'</ul>';return;}
    if(!compareRequested){target.innerHTML='<p class="profile-valid">명세 형식 검증 통과</p><p>실행·성능 검증과 등록은 아직 수행하지 않았습니다.</p>';return;}
    const data=await api('/compare',submitted);
    if(!target.isConnected||input.value!==submitted)return;
    if(data.observationError){target.textContent='장비 원본 조회 실패로 비교할 수 없습니다.';return;}
    target.innerHTML=`<p>비교 시각 ${E(new Date(data.observedAt).toLocaleString('ko-KR'))} · ${E(data.notice)}</p>${data.candidates.length ? '<ul class="profile-candidates">'+data.candidates.map(c=>`<li><strong>${E(c.deviceId)}</strong><span class="badge">${c.status==='excluded'?'조건 미충족':'추가 검증 필요'}</span><p>${c.reasons.map(r=>E(reasons[r]||r)).join(' · ')}</p></li>`).join('')+'</ul>' : '<p>비교할 연산 노드가 없습니다.</p>'}`;
  } catch(error){if(target.isConnected&&input.value===submitted)target.textContent='검증 요청 실패: '+error.message;}
  finally { if(button.isConnected)button.disabled=false; }
}
function setup() {
  if(setupDone)return;setupDone=true;
  setInterval(()=>{if(document.hidden)return;document.querySelectorAll('[data-profile-usage-at]').forEach(cell=>{const age=Date.now()-Date.parse(cell.dataset.profileUsageAt);if((!Number.isFinite(age)||age<0||age>Number(cell.dataset.profileMaxAge)*1000)&&!cell.dataset.expired){cell.textContent='미수집 / 오래된 관측';cell.dataset.expired='true';}});},15000);
  document.addEventListener('change',e=>{if(e.target.id==='profile-kind'){selected=e.target.value;redraw();}});
  document.addEventListener('input',e=>{if(e.target.id==='profile-document'){drafts[selected]=e.target.value;document.querySelector('#profile-validation').textContent='입력이 변경되었습니다. 다시 검증하세요.';document.querySelector('#profile-comparison').textContent='입력이 변경되었습니다. 다시 비교하세요.';}});
  document.addEventListener('click',e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.hasAttribute('data-profile-retry'))load();
    if(b.hasAttribute('data-profile-refresh'))refreshObservations();
    if(b.hasAttribute('data-profile-example')){delete drafts[selected];redraw();document.querySelector('#profile-document')?.focus();}
    if(b.hasAttribute('data-profile-validate'))validate(false,b);
    if(b.hasAttribute('data-profile-compare'))validate(true,b);
    if(b.hasAttribute('data-profile-download')){const blob=new Blob([document.querySelector('#profile-document').value],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download=selected+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}
  });
}
const exported={render,setup,observationHTML};
if(typeof module!=='undefined'&&module.exports)module.exports=exported;
else root.NexusProfiles=exported;
})(typeof window!=='undefined'?window:globalThis);
