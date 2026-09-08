(() => {
  'use strict';
  const labels={start:'시작',stop:'정지',infer:'시험 요청',running:'처리 중',accepted:'요청 접수',succeeded:'결과 확인',rejected:'실행 전 거절',unknown:'결과 확인 불가'};
  const esc=v=>String(v??'—').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  function allowed(row,enabled,busy,now=Date.now()) {
    const age=now-Date.parse(row?.observedAt);
    const fresh=Number.isFinite(age)&&age>=-5000&&age<=30000&&!row?.observationError;
    const base=enabled&&!busy&&fresh&&row?.id==='vd-demo-001'&&row.workloadExists===true;
    return {start:base&&row.desiredReplicas===0&&row.observedInstances===0,
      stop:base&&(row.desiredReplicas===1||row.observedInstances>0),
      infer:base&&row.desiredReplicas===1&&row.observedInstances===1&&row.executionState==='ready'};
  }
  function features(values){const result=values.map(v=>v.trim()===''?NaN:Number(v));if(result.length!==4||result.some(v=>!Number.isFinite(v)||v<0||v>30))throw Error('입력은 0~30cm 범위의 숫자 4개여야 합니다.');return result;}
  if(typeof module!=='undefined')module.exports={allowed,features,esc};
  if(typeof document==='undefined')return;
  const host=document.getElementById('vdControls');if(!host)return;
  const $=id=>document.getElementById(id);
  let row=null,enabled=false,busy=false,pending=null,loading=false,lastReceipt=null;
  host.innerHTML=`<div class="vd-control-heading"><div><p class="section-kicker">가상 디바이스 운영</p><h3>실행하고, 요청하고, 반환하기</h3><p>CPU Iris 시험 모델 · 실행 위치와 자원은 등록 계약을 따릅니다.</p></div><span id="vdControlAvailability">연결 확인 중</span></div>
    <ol class="vd-lifecycle"><li>01 <strong>등록 정의</strong><span>vd-demo-001</span></li><li>02 <strong>실행체 시작</strong><span>Pod·모델 준비 확인</span></li><li>03 <strong>시험 요청</strong><span>입력·결과 영수증</span></li><li>04 <strong>정지·반환</strong><span>정의와 이력 유지</span></li></ol>
    <details class="vd-auth"><summary>운영 권한</summary><label for="vdControlToken">기존 실행 운영 토큰</label><input id="vdControlToken" type="password" autocomplete="off" placeholder="X-Execution-Token" aria-describedby="vdTokenNote"><button id="vdClearToken" type="button">지우기</button><p id="vdTokenNote">이 화면에만 유지합니다. 브라우저 저장소에는 저장하지 않습니다.</p></details>
    <div class="vd-control-actions"><button type="button" id="vdStart" data-vd-action="start" disabled>시작</button><button type="button" id="vdStop" data-vd-action="stop" disabled>정지</button><span id="vdLiveState">관측 대기</span></div>
    <form id="vdInferForm"><fieldset><legend>Iris 분류 시험 · 길이 단위 cm</legend><div class="vd-feature-inputs">${[['꽃받침 길이',5.1],['꽃받침 너비',3.5],['꽃잎 길이',1.4],['꽃잎 너비',0.2]].map(([name,value],i)=>`<label>${name}<input id="vdFeature${i}" type="number" min="0" max="30" step="any" required value="${value}"></label>`).join('')}</div><div class="vd-control-actions"><button id="vdInfer" type="submit" disabled>시험 요청 보내기</button><span>대시보드 발신 · Jetson 요청과 구분</span></div></fieldset></form>
    <p id="vdActionMessage" role="status" aria-live="polite">운영 토큰을 입력하면 현재 상태에 맞는 작업이 활성화됩니다.</p><button id="vdRetryAction" type="button" hidden>같은 요청 키로 재전송</button>
    <div id="vdActionResult"></div><details class="vd-journal"><summary>작업 이력 · 정지 후에도 유지</summary><div id="vdActionHistory">조회 중</div></details>`;
  function render(){
    const permitted=allowed(row,enabled&&Boolean($('vdControlToken').value.trim()),busy||Boolean(pending));
    for(const [id,action] of [['vdStart','start'],['vdStop','stop'],['vdInfer','infer']])$(id).disabled=!permitted[action];
    $('vdControlAvailability').textContent=enabled?'운영 기능 연결':'조회 전용 · 운영 기능 비활성';
    const state=!row||row.observationError||!Number.isFinite(Date.parse(row.observedAt))||Date.now()-Date.parse(row.observedAt)>30000?'관측 확인 불가':row.desiredReplicas===0&&row.observedInstances===0?'정지 확인 · 실행체 0개':row.desiredReplicas===0?'종료 중 · 자원 반환 확인 대기':row.executionState==='ready'?'모델 준비 완료':row.executionState==='processing'?'요청 처리 중':'시작 요청 상태 · 모델 준비 확인 중';
    $('vdLiveState').textContent=state;
    $('vdRetryAction').hidden=!pending;$('vdRetryAction').disabled=busy;
  }
  function receipt(item){
    const result=item?.evidence?.result;
    if(!result)return;
    lastReceipt=item.id;
    $('vdActionResult').innerHTML=`<section class="vd-result"><h4>저장된 시험 결과 · ${esc(result.result?.label)}</h4><p>${esc(result.completedAt)} · ${esc(result.processingMs?.toFixed(2))}ms</p><dl><dt>요청 ID</dt><dd>${esc(result.requestId)}</dd><dt>발신자</dt><dd>${esc(result.clientId)}</dd><dt>실행체</dt><dd>${esc(result.podUid)}</dd><dt>모델</dt><dd>${esc(result.model?.id)} / ${esc(result.model?.version)}</dd></dl><details><summary>입력 해시·모델 해시·원 결과</summary><pre>${esc(JSON.stringify(result,null,2))}</pre></details></section>`;
  }
  async function history(){
    if(loading)return;loading=true;
    try{const response=await fetch('/api/virtual-devices/vd-demo-001/control',{cache:'no-store',signal:AbortSignal.timeout(10000)});if(!response.ok)throw Error('HTTP '+response.status);const data=await response.json();enabled=data.enabled===true;
      $('vdActionHistory').innerHTML=data.history.length?`<div class="vd-history-table"><table><thead><tr><th>시각</th><th>작업</th><th>결과</th><th>근거</th></tr></thead><tbody>${data.history.map(item=>`<tr><td>${esc(item.createdAt)}</td><td>${labels[item.action]||esc(item.action)}</td><td>${labels[item.state]||esc(item.state)}</td><td>${esc(item.evidence.reason||item.evidence.message||item.evidence.result?.result?.label||'—')}</td></tr>`).join('')}</tbody></table></div>`:'아직 작업 이력이 없습니다.';
      const latest=data.history.find(item=>item.evidence?.result);if(latest&&latest.id!==lastReceipt)receipt(latest);
    }catch(error){enabled=false;$('vdActionHistory').textContent='이력 조회 실패 · 이전 작업의 성공 여부를 추정하지 않습니다.';}finally{loading=false;render();}
  }
  async function send(action,retry=false){
    if(busy)return;
    let request,answered=false;
    try{request=retry?pending:{key:crypto.randomUUID?crypto.randomUUID():uuid(),body:{action,...(action==='infer'?{features:features([0,1,2,3].map(i=>$('vdFeature'+i).value))}:{})}};if(!request) return;}catch(error){$('vdActionMessage').textContent=error.message;return;}
    busy=true;render();$('vdActionMessage').textContent='요청 처리 중…';
    try{const response=await fetch('/api/virtual-devices/vd-demo-001/actions',{method:'POST',headers:{'Content-Type':'application/json','X-Execution-Token':$('vdControlToken').value.trim(),'Idempotency-Key':request.key},body:JSON.stringify(request.body),signal:AbortSignal.timeout(25000)});
      const data=await response.json();
      if(!response.ok){if(response.status>=500){pending=request;throw Error('서버 응답을 확인하지 못했습니다. 자동 재실행하지 않습니다.');}answered=true;pending=null;throw Error(response.status===403?'운영 토큰을 확인하세요.':String(data.detail||'요청을 처리할 수 없습니다.'));}
      if(data.id!==request.key||!['running','accepted','succeeded','rejected','unknown'].includes(data.state))throw Error('잘못된 작업 응답');
      answered=true;pending=data.state==='running'?request:null;$('vdActionMessage').textContent=`${labels[data.action]} · ${labels[data.state]||data.state}${data.evidence?.reason?' · '+data.evidence.reason:''}${data.state==='accepted'?' — 실제 준비·정지는 관측 상태에서 확인합니다.':''}`;receipt(data);
    }catch(error){if(!answered)pending=request;$('vdActionMessage').textContent=pending?'응답 확인 불가 · 자동 재실행하지 않습니다. 같은 요청 키로 결과를 확인할 수 있습니다.':error.message;
    }finally{busy=false;await history();globalThis.refreshVirtualDevices?.();render();}
  }
  function uuid(){const bytes=crypto.getRandomValues(new Uint8Array(16));bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;const hex=Array.from(bytes,b=>b.toString(16).padStart(2,'0')).join('');return `${hex.slice(0,8)}-${hex.slice(8,12)}-${hex.slice(12,16)}-${hex.slice(16,20)}-${hex.slice(20)}`;}
  $('vdControlToken').addEventListener('input',render);
  $('vdClearToken').onclick=()=>{$('vdControlToken').value='';render();};
  $('vdStart').onclick=()=>send('start');$('vdStop').onclick=()=>send('stop');
  $('vdInferForm').onsubmit=e=>{e.preventDefault();if(!$('vdInfer').disabled)send('infer');};
  $('vdRetryAction').onclick=()=>send(null,true);
  globalThis.VirtualDeviceControls={observe(value){row=value;render();if(!document.hidden&&document.body.dataset.dashboardPage==='virtual-devices')history();}};
  setInterval(()=>{render();if(!document.hidden&&document.body.dataset.dashboardPage==='virtual-devices')history();},10000);
  history();render();
})();
