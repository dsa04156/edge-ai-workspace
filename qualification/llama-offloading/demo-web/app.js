const $=id=>document.getElementById(id);
const names={nano_only:'Nano-only',cached_on_demand:'Cached On-Demand',always_on:'Always-On',cold_on_demand:'Cold On-Demand'};
names.compare='Nano-only → Cached 비교';
const stages={preparing:'모델 준비 중',running:'부하 실행 중',releasing:'유휴 자원 반환 대기',completed:'완료',failed:'실패',stopped:'중단',interrupted:'서버 재시작으로 중단'};
const events={setup_started:'모델과 초기 상태 준비',workload_started:'같은 요청 스케줄 시작',pressure_detected:'Nano 과부하 지속 · 이득 조건 통과',activation_started:'원격 모델 활성화 시작',ready:'원격 READY 확인',drained:'모든 전송 요청 완료',released:'원격 모델 반환 확인',cleanup:'원격 모델 정리',activation_failed:'원격 활성화 실패',failed:'실행 실패'};
const checks={all_requests_accounted:'요청 누락 없음',no_request_errors:'요청 오류 없음',unique_request_ids:'요청 ID 유일',worker_identity_verified:'노드·모델 응답 검증',ready_before_dispatch:'READY 후 전달',forwarded_once:'요청당 한 번 전달',remote_processing_observed:'원격 처리 관측',idle_release_observed:'유휴 반환 관측'};
events.first_remote_response='첫 원격 응답 · 실제 노드·모델 검증';
events.nano_returned='부하 감소 · 신규 요청 Nano 복귀';
const gpuPhases={idle:'시연 대기',reserving:'GPU 임시 사용 기록 중',sensor_stopping:'센서 서버 후보 중지 · GPU 확보 중',worker_starting:'RTX 5080 Pod 시작 중',prepared:'GPU 준비 완료 · 실측 실행',restoring:'원격 요청 정리 · Pod 종료 중',sensor_restoring:'기존 센서 서버 후보 복원 중',restored:'GPU 반환 · 센서 복원 완료',recovery_failed:'복원 미완료 · 자동 재시도 중'};
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=(v,d=1)=>v===null||v===undefined?'—':Number(v).toLocaleString('ko-KR',{maximumFractionDigits:d});
let latest=null;
function chart(id,series,limit=null){
  const el=$(id),max=Math.max(limit||1,...series.flatMap(s=>s.values.filter(Number.isFinite)))*1.1;
  const lines=[0,.5,1].map(t=>`<line x1="40" x2="588" y1="${154-t*132}" y2="${154-t*132}" stroke="#dce3e8"/><text x="34" y="${158-t*132}" text-anchor="end" fill="#536575" font-size="10">${fmt(max*t,0)}</text>`).join('');
  const plots=series.map(s=>{const points=s.values.map((v,i)=>`${40+i/Math.max(1,s.values.length-1)*548},${154-v/max*132}`).join(' ');return `<polyline fill="none" stroke="${s.color}" stroke-width="2" points="${points}"/>`}).join('');
  el.innerHTML=lines+plots+(limit?`<line x1="40" x2="588" y1="${154-limit/max*132}" y2="${154-limit/max*132}" stroke="#a25c12" stroke-dasharray="4 4"/>`:'')+`<text x="40" y="175" fill="#536575" font-size="10">시작</text><text x="588" y="175" text-anchor="end" fill="#536575" font-size="10">최근</text>`;
}
function render(s,selectedRun=null){
 latest=s;const r=selectedRun||s.runs.at(-1);const tally=r?.summary.by_node||{};
 const cached=s.runs.slice().reverse().find(v=>v.method==='cached_on_demand'&&v.status==='completed'&&s.runs.some(b=>b.group===v.group&&b.method==='nano_only'&&b.status==='completed'));
 const baseline=cached&&s.runs.find(v=>v.group===cached.group&&v.method==='nano_only');
 $('comparison').textContent=baseline?`같은 회차 비교 · p95 지연 ${fmt(baseline.summary.p95_latency_ms/1000,2)}초 → ${fmt(cached.summary.p95_latency_ms/1000,2)}초 (${fmt(100*(1-cached.summary.p95_latency_ms/baseline.summary.p95_latency_ms))}% 감소) · 처리량 ${fmt(baseline.summary.throughput_rps,2)} → ${fmt(cached.summary.throughput_rps,2)} req/s · 오류 ${baseline.summary.errors} / ${cached.summary.errors}건. 반복 전체의 일반화된 결론은 아닙니다.`:'';
 $('connection').textContent='● LIVE · '+new Date(s.timestamp*1000).toLocaleTimeString('ko-KR');
 const prepared=s.nodes.nano?.available&&(s.gpu_automation||s.nodes[$('target').value]?.available);
 const session=s.gpu_session;
 $('gpu-status').textContent=s.gpu_automation?`${gpuPhases[session?.phase||'idle']}${session?.preparation_ms?' · GPU 준비 '+fmt(session.preparation_ms/1000)+'초':''}${session?.error&&session.phase==='recovery_failed'?' · '+session.error:''}`:'수동 GPU 준비 모드';
 $('gpu-status').className=session?.phase==='recovery_failed'?'fail':'gpu-status';
 $('gpu-events').innerHTML=(session?.events||[]).map(e=>`<li>+${fmt(e.timestamp-session.started)}s · ${esc(gpuPhases[e.phase]||e.phase)}</li>`).join('');
 if(s.gpu_automation)$('target').value='spark';
 $('connection').className='pass';$('start').disabled=s.busy||!prepared;$('stop').disabled=!s.busy;$('method').disabled=s.busy;$('target').disabled=s.busy||s.gpu_automation;
 $('phase').textContent=r?`${names[r.method]} · ${stages[r.status]||r.status}`:'시연 대기';
 if(s.busy&&session&&session.phase!=='prepared')$('phase').textContent=gpuPhases[session.phase]||session.phase;
 $('notice').textContent=r?.error||r?.cleanup_error||r?.warning||(r?.status==='releasing'?`원격 마지막 처리 후 30초 유휴를 확인합니다. ${fmt(r.idle_remaining)}초 남음`:'부하만 시작하면 컨트롤러가 활성화와 요청 전환을 판단합니다.');
 $('notice').className=r?.error?'fail':'';
 if(!s.busy&&!prepared)$('notice').textContent='Nano 관리 API 연결을 확인하세요. 미준비 상태에서는 실행하지 않습니다.';
 if(s.busy&&session&&session.phase!=='prepared')$('notice').textContent='GPU 준비·복원 중에는 새 부하를 실행하지 않습니다. 브라우저를 닫아도 서버가 정리를 계속합니다.';
 $('nodes').innerHTML=Object.entries(s.nodes).map(([key,n])=>{const state=n.available?n.node_state:'연결 끊김';return `<article class="node ${esc(state?.toLowerCase())}"><div class="node-head"><div><h3>${esc(n.label)}</h3><small>${esc(n.physical)}</small></div><span class="state">${esc(state||'확인 중')}</span></div><div class="big">${fmt(tally[key]||0,0)}<span>검증된 완료 요청</span></div><dl><dt>처리 중 / 대기</dt><dd>${fmt(n.active_requests,0)} / ${fmt(n.queue_length,0)}</dd><dt>GPU 사용률</dt><dd>${fmt(n.gpu_utilization_percent)} %</dd><dt>모델 GPU 메모리</dt><dd>${fmt(n.model_vram_mib)} MiB</dd><dt>첫 토큰 EWMA</dt><dd>${fmt(n.ewma_ttft_ms)} ms</dd><dt>로컬 모델 파일</dt><dd>${n.model_cached===true?'보관됨':n.model_cached===false?'없음':'—'}</dd><dt>CPU / RAM</dt><dd>${fmt(n.cpu_utilization_percent)} / ${fmt(n.ram_utilization_percent)} %</dd></dl></article>`}).join('');
 const samples=r?.samples||[];chart('queue-chart',[{color:'#1767bb',values:samples.map(v=>v.nano_outstanding)},{color:'#a25c12',values:samples.map(v=>v.queue)}]);
 chart('ttft-chart',[{color:'#1767bb',values:(r?.requests||[]).filter(v=>v.status==='ok').map(v=>v.ttft_ms)}],1500);
 if(r){
  $('elapsed').textContent=fmt((r.finished||s.timestamp)-r.started,0)+'초';
  const important=r.events.filter(e=>e.event!=='dispatch');
  $('events').innerHTML=important.map(e=>`<li><time>+${fmt(e.timestamp-r.started)}s</time><span>${esc(events[e.event]||e.event)}${e.node?' · '+esc(s.nodes[e.node]?.label||e.node):''}${e.activation_ms?' · '+fmt(e.activation_ms/1000)+'초':''}${e.event==='pressure_detected'?` · 미완료+대기 ${fmt(e.queue,0)}건 · 2초 지속 · 예상 이득 ${fmt(100*e.gain)}%`:''}${e.error?' · '+esc(e.error):''}</span></li>`).join('')||'<li class="empty">초기 상태 확인 중…</li>';
  $('requests').innerHTML=r.requests.slice(-8).reverse().map(q=>`<tr><td>${esc(q.request_id.slice(-7))}</td><td>${esc(q.actual_node?s.nodes[q.selected_node]?.label:q.selected_node||'—')}</td><td>${fmt(q.latency_ms)} ms</td><td class="${q.identity_verified?'pass':'fail'}">${q.identity_verified?'확인됨':esc(q.status)}</td></tr>`).join('')||'<tr><td colspan="4">완료 응답을 기다리고 있습니다.</td></tr>';
  $('downloads').innerHTML=`<a href="/api/runs/${r.id}" target="_blank" rel="noopener">전체 로그 JSON ↗</a><a href="/api/runs/${r.id}.csv" download>요청 CSV ↓</a>`;
  $('checks').innerHTML=Object.entries(r.summary.checks).filter(([,v])=>v!==null).map(([k,v])=>`<span class="check ${v?'pass':r.status==='completed'?'fail':''}">${v?'✓':r.status==='completed'?'!':'·'} ${esc(checks[k])}</span>`).join('');
 }
 $('results').innerHTML=s.runs.slice().reverse().map(run=>`<tr><td>${esc(names[run.method])}</td><td>${esc(stages[run.status]||run.status)}</td><td>${run.summary.completed} / ${run.planned}</td><td>${fmt(run.summary.p95_latency_ms)} ms</td><td>${fmt(run.summary.p95_ttft_ms)} ms</td><td>${fmt(run.summary.throughput_rps,2)} req/s</td><td>${run.summary.errors}</td></tr>`).join('')||'<tr><td colspan="7">시연을 시작하면 실측 비교 결과가 기록됩니다.</td></tr>';
}
async function control(path,body={}){try{const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-Demo-Control':'1'},body:JSON.stringify(body)});const result=await response.json();if(!response.ok)throw Error(result.error);await refresh()}catch(e){$('notice').textContent=e.message;$('notice').className='fail'}}
$('method').value='cached_on_demand';
$('start').onclick=()=>{if(latest?.gpu_automation&&!confirm('실제 GPU 시연을 시작할까요? RTX 5080 센서 서버 추론 후보가 잠시 중지됩니다. 센서 수집은 유지되며 종료·중단 후 자동 복원합니다.'))return;$('start').disabled=true;control('/api/start',{method:$('method').value,target:$('target').value})};$('stop').onclick=()=>control('/api/stop');
async function refresh(){try{const response=await fetch('/api/state',{signal:AbortSignal.timeout(5000)});if(!response.ok)throw Error('상태 조회 실패');liveState=await response.json();updateRecordingChoices(liveState);if(recording)drawRecording();else render(liveState)}catch(e){if(!recording){$('connection').textContent='연결 끊김 · 마지막 값';$('connection').className='fail';$('start').disabled=true}}}
window.addEventListener('DOMContentLoaded',async()=>{while(true){await refresh();await new Promise(r=>setTimeout(r,1000))}});
