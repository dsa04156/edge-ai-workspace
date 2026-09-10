// Read-only playback of persisted worker observations. Never calls control APIs.
let recording=null, replaySeconds=0, replayPlaying=false, liveState=null;
function drawRecording(){
 if(!recording||!liveState)return;
 const r=recording,t=r.started+replaySeconds;
 const samples=r.samples.filter(v=>v.timestamp<=t);
 const observed=samples.at(-1)?.nodes||{};
 const visibleEvents=r.events.filter(e=>e.timestamp<=t);
 const nodeState={};
 for(const [key,n] of Object.entries(liveState.nodes)){
  // Never mix today's telemetry into yesterday's recording.
  nodeState[key]={label:n.label,physical:n.physical,...(observed[key]||{available:false,node_state:'UNKNOWN'})};
 }
 for(const e of visibleEvents){
  if(e.event==='released'&&e.observation)nodeState[e.node]={label:nodeState[e.node].label,physical:nodeState[e.node].physical,...e.observation};
 }
 const rows=r.requests.filter(q=>q.completed_timestamp<=t);
 const tally={};for(const q of rows)if(q.status==='ok')tally[q.selected_node]=(tally[q.selected_node]||0)+1;
 const done=t>=r.finished;
 const visible={...r,finished:done?r.finished:null,events:visibleEvents,samples,requests:rows,
  summary:{...r.summary,by_node:tally,checks:done?r.summary.checks:{}},status:done?r.status:'running'};
 render({...liveState,timestamp:t,nodes:nodeState},visible);
 $('gpu-status').textContent='REPLAY · GPU 제어 없음';
 $('gpu-events').innerHTML=(r.gpu_session?.events||[]).filter(e=>e.timestamp<=t).map(e=>`<li>${esc(gpuPhases[e.phase]||e.phase)}</li>`).join('');
 $('connection').textContent='▶ REPLAY · 실측 기록 · '+new Date(t*1000).toLocaleString('ko-KR');
 $('connection').className='replay-label';
 $('notice').textContent='실측 기록 재생입니다. 현재 장비 상태가 아니며, 요청 전송·모델 활성화는 실행하지 않습니다.';
 $('phase').textContent=names[r.method]+' · 실측 재생';
 $('start').disabled=true;$('stop').disabled=true;$('method').disabled=true;$('target').disabled=true;
 $('seek').value=replaySeconds;$('replay-time').textContent=`${fmt(replaySeconds)} / ${fmt(r.finished-r.started)}초`;
 $('playback').textContent=replayPlaying?'일시정지':'4배속 재생';
}
function updateRecordingChoices(s){
 const choices=s.runs.filter(r=>r.status==='completed'&&r.summary.completed>0);
 const key=choices.map(r=>r.id).join(',');
 if($('recording').dataset.key!==key){
  const selected=$('recording').value;
  $('recording').innerHTML=choices.map(r=>`<option value="${esc(r.id)}">${esc(names[r.method])} · ${new Date(r.started*1000).toLocaleTimeString('ko-KR')} · ${r.summary.completed}건</option>`).reverse().join('');
  if(choices.some(r=>r.id===selected))$('recording').value=selected;
  $('recording').dataset.key=key;
 }
 $('load-recording').disabled=!choices.length||s.busy;
}
async function openRecording(){
 try{
  const response=await fetch('/api/runs/'+encodeURIComponent($('recording').value));
  if(!response.ok)throw Error('기록을 읽지 못했습니다.');
  const r=await response.json();
  if(r.status!=='completed'||!r.samples.length)throw Error('완료된 실측 기록이 아닙니다.');
  recording=r;replaySeconds=0;replayPlaying=true;
  $('replay-controls').hidden=false;$('seek').step='any';$('seek').max=r.finished-r.started;drawRecording();
 }catch(e){$('notice').textContent=e.message;$('notice').className='fail';}
}
$('load-recording').onclick=openRecording;
$('playback').onclick=()=>{if(replaySeconds>=recording.finished-recording.started)replaySeconds=0;replayPlaying=!replayPlaying;drawRecording()};
$('seek').oninput=()=>{replaySeconds=Number($('seek').value);replayPlaying=false;drawRecording()};
$('live-view').onclick=()=>{recording=null;replayPlaying=false;$('replay-controls').hidden=true;if(liveState)render(liveState)};
setInterval(()=>{
 if(!recording||!replayPlaying)return;
 replaySeconds=Math.min(recording.finished-recording.started,replaySeconds+.8);
 if(replaySeconds>=recording.finished-recording.started)replayPlaying=false;
 drawRecording();
},200);
