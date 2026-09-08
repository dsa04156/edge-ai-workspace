/* Physical source identity comes only from EdgeX mappings; views never bind or mutate. */
(function(root){
'use strict';
const resourceLabels={temperature_raw:'온도 원시값',light_raw:'조도 원시값',magnetic_raw:'자기 센서 원시값',acceleration_x_raw:'가속도 X축 원시값',acceleration_y_raw:'가속도 Y축 원시값',acceleration_z_raw:'가속도 Z축 원시값',temp_humidity:'습도 센서 온도',temp_pressure:'기압 센서 온도',humidity:'습도',pressure:'기압',compass:'방위',pitch:'피치',roll:'롤',yaw:'요',gyro_x:'각속도 X축',gyro_y:'각속도 Y축',gyro_z:'각속도 Z축'};
const resourceLabel=name=>resourceLabels[name]||name;
function functionLabel(d){const names=[...new Set((d.latest_readings||[]).map(r=>resourceLabel(r.resource_name)).filter(Boolean))];return names.length?names.join(' · '):d.name;}

function buildSources(devices,twins){
  const groups=new Map(),unassigned=[];
  for(const device of devices){
    const id=device.physical_device_id;
    if(typeof id!=='string'||!id.trim()){unassigned.push(device);continue;}
    if(!groups.has(id))groups.set(id,{id,functions:[],services:new Map()});
    const source=groups.get(id);
    const twin=twins.find(t=>t.physical_device_id===id&&t.name===device.name)||null;
    source.functions.push({device,twin});
    for(const binding of twin?.service_bindings||[]){
      if(typeof binding.service_id!=='string')continue;
      if(!source.services.has(binding.service_id))source.services.set(binding.service_id,[]);
      source.services.get(binding.service_id).push({device:device.name,binding});
    }
  }
  return {sources:[...groups.values()].sort((a,b)=>a.id.localeCompare(b.id)),unassigned};
}
function virtualDevice(source){
  return {id:'physical-vd:'+encodeURIComponent(source.id),kind:'physical-source-representation',
    physicalSourceId:source.id,authority:'edgex',accessMode:'read-only',
    deviceNames:source.functions.map(f=>f.device.name).sort(),
    twinIds:source.functions.filter(f=>f.twin).map(f=>f.twin.id).sort(),
    serviceIds:[...source.services.keys()].sort()};
}
function searchSources(sources,query){
  const q=query.trim().toLocaleLowerCase();
  return sources.filter(s=>[s.id,virtualDevice(s).id,...s.functions.flatMap(({device:d,twin:t})=>[d.name,d.profile_name,d.device_service_name,d.node_name,...(d.latest_readings||[]).map(r=>r.resource_name),...(t?.service_bindings||[]).flatMap(b=>[b.service_id,b.service_name])])].filter(Boolean).join(' ').toLocaleLowerCase().includes(q));
}
function render({devices,twins,services,query,selected,deviceCurrent,twinCurrent,serviceCurrent,escape:E,status,date,expanded=new Map(),view='physical'}){
  const logical=view==='virtual';
  const grouped=buildSources(devices,twins),sources=searchSources(grouped.sources,query);
  const source=sources.find(s=>s.id===selected)||sources[0];
  const count=(value,current)=>current?value:'—';
  const connectionsKnown=s=>deviceCurrent&&twinCurrent&&s.functions.every(f=>f.twin);
  const header=logical?`<div class="source-intro"><div><p class="eyebrow">물리 장비의 소프트웨어 표현</p><h2>가상 디바이스</h2><p>원본 장비의 식별 정보, 기능과 관측 상태를 하나의 논리 디바이스로 묶었습니다. 각 디바이스를 선택해 원본과 이용 서비스를 확인하세요.</p></div><span class="badge">EdgeX 기반 · 읽기 전용</span></div>`:`<div class="source-intro"><div><p class="eyebrow">물리 장비 → 가상 디바이스 → 기능·서비스</p><h2>장비 하나를 기준으로 연결을 살펴보세요.</h2><p>물리 장비에 대응하는 가상 디바이스에서 제공 기능과 최신 상태를 확인할 수 있습니다.</p></div><span class="badge">EdgeX 장비 기준</span></div>`;
  const chooser=`<nav class="source-picker ${logical?'physical-vd-picker':''}" aria-label="${logical?'가상 디바이스 선택':'물리 장비 선택'}">${sources.map(s=>`<button id="source-${E(encodeURIComponent(s.id))}" data-source-select="${E(s.id)}" aria-pressed="${s.id===source?.id}"><span class="source-kind">${logical?'가상 디바이스':'물리 장비'}</span><strong>${E(s.id)}${logical?' 가상 디바이스':''}</strong>${logical?`<code>${E(virtualDevice(s).id)}</code><span>원본 장비 · ${E(s.id)}</span>`:''}<span>등록 기능 ${count(s.functions.length,deviceCurrent)}개 · 연결 서비스 ${count(s.services.size,connectionsKnown(s))}개</span></button>`).join('')}</nav>`;
  let detail='';
  if(source){
    const nodes=[...new Set(source.functions.map(f=>f.device.node_name).filter(Boolean))];
    const adapters=[...new Set(source.functions.map(f=>f.device.device_service_name).filter(Boolean))];
    const bindings=[...source.services];
    const vd=virtualDevice(source);
    detail=`<section class="source-detail" aria-labelledby="source-detail-title">
      <div class="source-identity"><div><span class="source-kind">${logical?'선택한 가상 디바이스':'선택한 물리 장비'}</span><h3 id="source-detail-title" tabindex="-1">${E(source.id)}${logical?' 가상 디바이스':''}</h3>${logical?`<code id="physical-vd-id">${E(vd.id)}</code>`:''}</div><p>등록 기능 ${count(source.functions.length,deviceCurrent)}개 · 관측 트윈 ${count(source.functions.filter(f=>f.twin).length,deviceCurrent&&twinCurrent)}개</p></div>
      ${logical?`<div class="physical-vd-map" aria-label="원본 장비와 가상 디바이스 연결"><div><span>원본 물리 장비</span><strong>${E(source.id)}</strong><button class="text-button" data-live-source="${E(source.id)}">원본 장비 보기 ↗</button></div><span class="physical-vd-arrow" aria-hidden="true">→</span><div><span>가상 디바이스</span><strong>${E(vd.id)}</strong><p>원본의 등록 기능과 관측 상태를 함께 제공</p></div></div><dl class="physical-vd-contract"><div><dt>표현 방식</dt><dd>물리 장비의 읽기 전용 가상 표현</dd></div><div><dt>등록·데이터 원본</dt><dd>EdgeX Device·Profile·Event</dd></div><div><dt>원본 식별자</dt><dd>${E(source.id)}</dd></div><div><dt>논리 ID 유지 기준</dt><dd>원본 장비 ID가 같으면 유지</dd></div></dl><p class="physical-vd-boundary">장비별 기능·관측 트윈을 묶은 조회 객체입니다. 시뮬레이터나 별도로 실행되는 컨테이너가 아니며, 센서 제어·증강 실행은 제공하지 않습니다.</p>`:`<div class="physical-vd-entry"><div><span>이 장비의 가상 디바이스</span><strong>${E(vd.id)}</strong><p>원본 장비의 기능과 관측 상태를 묶은 논리 디바이스</p></div><button class="button" data-open-physical-vd="${E(source.id)}">가상 디바이스 열기 ↗</button></div>`}
      <dl class="source-context"><div><dt>연결·수집 담당</dt><dd>${E(adapters.join(', ')||'미지정')}</dd></div><div><dt>수집 실행 노드</dt><dd>${E(nodes.join(', ')||'미지정')} <button class="text-button" data-live-page="resources">노드 상태 보기 ↗</button></dd></div></dl>
      ${!deviceCurrent?'<p class="source-alert" role="status">장비 정보를 현재 확인할 수 없습니다. 아래는 마지막으로 받은 등록·관측 정보입니다.</p>':''}
      <ol class="source-flow" aria-label="장비의 기능과 서비스 연결 구조"><li><b>01</b><span>${logical?'가상 디바이스':'물리 장비'}<small>${E(logical?vd.id:source.id)}</small></span></li><li><b>02</b><span>제공 기능·관측 트윈<small>EdgeX 등록과 최근 데이터</small></span></li><li><b>03</b><span>이용 서비스<small>기능별 연결과 입력 계약</small></span></li></ol>
      <div class="source-section-title"><h3>제공 기능과 관측 트윈</h3><p>등록 Device별로 표시합니다. 최근 값은 아래 수신 시각의 관측입니다.</p></div>
      <div class="source-functions">${source.functions.map(({device:d,twin:t},index)=>{const key=source.id+' / '+d.name;return `<details class="source-function" data-source-function="${E(key)}" ${(expanded.has(key)?expanded.get(key):index===0)?'open':''}>
        <summary class="source-function-heading" id="function-${E(encodeURIComponent(key))}"><div><h4>${E(functionLabel(d))}</h4><p>${E(d.name)}</p><p>Profile · ${E(d.profile_name)}</p></div>${status(d.overall_status,deviceCurrent)}<span class="source-expand" aria-hidden="true">＋</span></summary>
        <div class="source-function-body"><div><p class="source-label">최근 관측값</p>${(d.latest_readings||[]).length?(d.latest_readings||[]).map(r=>`<div class="source-reading"><span>${E(resourceLabel(r.resource_name))} <small>${E(r.resource_name)}</small></span><strong>${E(typeof r.value==='object'?JSON.stringify(r.value):r.value)} <small>${E(r.units||'')}</small></strong><time>${E(date(r.timestamp||d.latest_event_timestamp))}</time></div>`).join(''):'<p class="note">관측값 없음 · Profile의 전체 기능 목록과 구분합니다.</p>'}
        <p class="source-freshness">수신 최신성 ${status(d.telemetry_freshness,deviceCurrent)}</p></div>
        <div><p class="source-label">관측 트윈</p>${t?`<p class="source-twin-id">${E(t.id)}</p>${status(t.health,deviceCurrent&&twinCurrent)}<p class="source-label">최근 Event · ${E(date(t.latest_event_timestamp))}</p>`:`<p class="note">${deviceCurrent&&twinCurrent?'이 등록 항목과 일치하는 트윈 없음':'트윈 확인 불가'}</p>`}<button class="text-button" data-live-device="${E(d.name)}">등록·수신 근거 보기 ↗</button></div>
        <div><p class="source-label">이 기능을 이용하는 서비스</p>${(t?.service_bindings||[]).length?t.service_bindings.map(b=>`<div class="source-binding"><button class="text-button" data-live-service="${E(b.service_id)}">${E(b.service_name||b.service_id)} ↗</button>${status(b.status,deviceCurrent&&twinCurrent)}<p>${E(b.input_contract||'입력 계약 미제공')}</p></div>`).join(''):`<p class="note">${deviceCurrent&&twinCurrent&&t?'등록된 연결 없음':'연결 확인 불가'}</p>`}</div></div>
      </details>`;}).join('')}</div>
      <section class="source-consumers"><div class="source-section-title"><h3>장비 데이터를 이용하는 서비스</h3><p>여러 기능을 사용하는 서비스도 한 번만 표시합니다.</p></div>
      ${!twinCurrent?'<p class="source-alert" role="status">서비스 연결을 현재 확인할 수 없습니다. 이전 연결이 있으면 참고용으로 표시합니다.</p>':''}
      ${bindings.length?bindings.map(([id,uses])=>{const service=services.find(s=>s.service_id===id);return `<article class="source-consumer"><div><button class="text-button" data-live-service="${E(id)}">${E(service?.display_name||uses[0].binding.service_name||id)} ↗</button><p>${E(id)} · 연결 기능 ${uses.length}개</p></div><div><span class="source-label">서비스 입력 상태</span>${status(service?.input_state,Boolean(service&&serviceCurrent&&service.mode==='live'&&!service.observation_error))}</div><p>${E(uses.map(u=>u.device).join(', '))}</p></article>`;}).join(''):`<p class="note">${connectionsKnown(source)?'이 장비의 기능에 등록된 서비스 연결이 없습니다.':'서비스 연결 확인 불가'}</p>`}</section>
      <aside class="source-extension"><div><h3>추가 실행 기능</h3><p>CPU Iris 가상 실행체는 별도 시험입니다. 이 장비의 센서 기능이나 서비스에 연결됐다는 근거는 아직 없습니다.</p></div><button class="button" data-workspace="virtual">독립 실행 기능 시험 ↗</button></aside>
    </section>`;
  }else detail=`<div class="empty">${query?`검색과 일치하는 ${logical?'가상 디바이스':'물리 장비'}가 없습니다.`:deviceCurrent?'물리 장비가 지정된 등록 항목이 없습니다.':'물리 장비 정보를 기다리고 있습니다. 조회 실패 여부는 위 관측 정보를 확인하세요.'}</div>`;
  const unknown=grouped.unassigned.filter(d=>!query||[d.name,d.profile_name].join(' ').toLowerCase().includes(query.toLowerCase()));
  return header+chooser+detail+(unknown.length?`<section class="source-unassigned"><h3>물리 장비 미지정 · ${unknown.length}개</h3><p>장비 ID 연결이 없어 특정 장비의 기능으로 묶지 않았습니다.</p>${unknown.map(d=>`<button class="text-button" data-live-device="${E(d.name)}">${E(d.name)} ↗</button>`).join('')}</section>`:'');
}
const api={buildSources,virtualDevice,searchSources,render};
if(typeof module!=='undefined'&&module.exports)module.exports=api;
root.NexusSources=api;
})(typeof window!=='undefined'?window:globalThis);
