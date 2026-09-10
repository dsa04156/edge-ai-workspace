/* Service-specific contract diagrams. No runtime actions or inferred live status. */
(function(root){
  "use strict";
  const icons={physical:'<path d="M4 8h16v12H4zM8 4v4m8-4v4M8 12v4m4-4v4m4-4v4"/>',collector:'<path d="M4 5h16v5H4zM4 14h16v5H4zM8 7.5h.01M8 16.5h.01M15 10v4"/>',edgecore:'<rect x="4" y="4" width="16" height="16" rx="3"/><path d="M8 9l3 3-3 3m5 0h3"/>',ai:'<path d="M8 4h8v4h4v8h-4v4H8v-4H4V8h4zM9 9h6v6H9z"/>',edgex:'<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v14c0 4 16 4 16 0V5M4 12c0 4 16 4 16 0"/>',kube:'<path d="M12 2l9 5v10l-9 5-9-5V7zM3 7l9 5 9-5m-9 5v10"/>',results:'<path d="M6 3h9l4 4v14H6zM10 11h5m-5 4h5M15 3v5h4"/>',aggregator:'<path d="M3 5h5v5H3zM3 14h5v5H3zM16 9h5v6h-5zM8 7h4v5h4M8 17h4v-5"/>',prometheus:'<path d="M3 19h18M5 15V9m5 6V4m5 11v-5m5 5V7"/>',dashboard:'<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4M7 8h3v5H7m6-5h4m-4 4h4"/>',search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 5 5"/>',fit:'<path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/>',plus:'<path d="M12 5v14M5 12h14"/>',minus:'<path d="M5 12h14"/>',close:'<path d="m6 6 12 12M6 18 18 6"/>',arrow:'<path d="M4 12h16m-6-6 6 6-6 6"/>',route:'<circle cx="5" cy="5" r="2"/><circle cx="19" cy="19" r="2"/><path d="M5 7v8a4 4 0 0 0 4 4h8M5 5h10a4 4 0 0 1 0 8H9"/>'};
  const icon=id=>`<svg viewBox="0 0 24 24" aria-hidden="true">${icons[id]||icons[({metadata:'edgex',coredata:'edgex',command:'edgecore',bus:'collector',postgres:'edgex',keeper:'kube'})[id]]||icons.route}</svg>`;
  const E=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state={services:[],workloads:[],id:null,stage:null,link:null,source:null,loading:false,loaded:false,error:null,query:'',profiles:null,profileError:true,expired:false,zoom:null,auto:true,checkedAt:null,results:new Map()};
  const descriptions={
    Input:'Device Service가 센서 입력을 읽어 서비스가 사용할 데이터로 제공합니다.',
    Alignment:'입력 표본의 시각과 형식을 맞추고 처리 가능한 입력으로 정리합니다.',
    Features:'전처리한 표본에서 모델이 사용할 특징을 계산합니다.',
    Inference:'특징을 모델에 전달해 판정합니다. 실행 대상은 아래 설정을 확인하세요.',
    Result:'판정 결과를 서비스가 저장하고 조회할 수 있게 제공합니다.'
  };
  const stageIcon=stage=>({source:'collector',transform:'edgecore',features:'prometheus',inference:'ai',sink:'results'})[stage.kind]||'route';
  function normalize(item){
    if(!item||typeof item.service_id!=='string')throw Error('서비스 계약 형식을 확인할 수 없습니다.');
    const d=item.descriptor||item,g=d.graph||{},raw=Array.isArray(g.stages)?g.stages:[];
    const ids=new Set(),stages=[];
    for(const s of raw){if(!s||typeof s.stage_id!=='string'||ids.has(s.stage_id))throw Error('중복되거나 잘못된 서비스 단계입니다.');ids.add(s.stage_id);stages.push({...s,label:String(s.label||s.stage_id),depends_on:Array.isArray(s.depends_on)?s.depends_on:[],executions:Array.isArray(s.executions)?s.executions:[]});}
    const links=stages.flatMap(s=>s.depends_on.map(from=>({from,to:s.stage_id,key:from+'→'+s.stage_id})));
    if(links.some(l=>!ids.has(l.from)))throw Error('연결 대상이 없는 서비스 계약입니다.');
    const ordered=[],pending=[...stages];
    while(pending.length){const index=pending.findIndex(s=>s.depends_on.every(id=>ordered.some(n=>n.stage_id===id)));if(index<0)throw Error('서비스 단계에 순환 연결이 있습니다.');ordered.push(pending.splice(index,1)[0]);}
    const contract=item.design_contract||d.design_contract||{};
    const observability=d.observability||{};
    return {id:item.service_id,kind:'registered',observability,title:String(item.display_name||d.display_name||item.service_id),description:String(item.description||d.description||''),physicalSource:item.physical_source&&item.physical_source!=='unobserved'?String(item.physical_source):null,stages:ordered,links,targets:Array.isArray(g.targets)?g.targets:[],inputs:Array.isArray(contract.inputs)?contract.inputs:[],sourceMode:contract.source_mode||null,workload:d.workload||{},remoteWorkload:d.runtime_offloading?.target_workload||null,ownership:recent(item.execution_ownership?.observed_at)?item.execution_ownership?.effective_mode||null:null,runtime:{mode:item.mode,status:item.status,latest:item.latest_observed_at,target:item.inference_target,ownership:item.execution_ownership},contract};
  }
  function parse(data){if(!data||!Array.isArray(data.services))throw Error('서비스 목록 응답 형식이 올바르지 않습니다.');const ids=new Set();return data.services.map(item=>{const s=normalize(item);s.observedAt=data.generated_at;if(ids.has(s.id))throw Error('서비스 ID가 중복되었습니다.');ids.add(s.id);return s;});}
  const entries=()=>[...state.services,...state.workloads];
  const selected=()=>entries().find(s=>s.id===state.id);
  function workloadEntries(data){
    const seen=new Set();return (data?.service_resource_profiles||[]).filter(p=>{const key=p.namespace+'/'+p.service;if(seen.has(key))return false;seen.add(key);return true;}).map(p=>{
      const s=normalize({service_id:'workload:'+p.namespace+'/'+p.service,display_name:p.service,description:p.namespace+' · Kubernetes 실행 워크로드',workload:{namespace:p.namespace,name:p.service},graph:{stages:[{stage_id:'runtime',label:'Pod 실행',kind:'runtime',executions:[{namespace:p.namespace,executor:p.service}]}]}});
      s.kind='workload';s.observedAt=data.generated_at;return s;
    }).sort((a,b)=>(a.workload.namespace+'/'+a.title).localeCompare(b.workload.namespace+'/'+b.title));
  }
  function runtimeSummary(s,now=Date.now()){
    if(s.kind==='workload')return {label:'처리 상태 미연동',tone:'neutral',detail:'워크로드의 Pod 위치만 관측합니다. 서비스 입출력 연결 계약은 없습니다.'};
    const r=s.runtime||{},owner=r.ownership;
    if(r.mode!=='live'||!recent(s.observedAt,now))return {label:'처리 상태 미확인',tone:'neutral',detail:'유효한 서비스 처리 관측이 없습니다.'};
    if(recent(owner?.observed_at,now)&&owner.effective_mode==='STANDBY')return {label:'처리 대기',tone:'waiting',detail:owner.reason_code==='execution_lease_expired'?'실행 lease 만료 · STANDBY':'서비스 실행 권한 대기 · STANDBY'};
    if(!recent(r.latest,now))return {label:'최근 처리 미관측',tone:'waiting',detail:'Pod 실행 위치와 최근 AI 처리 결과는 별도입니다.'};
    return {label:({normal:'최근 정상 판정',anomaly:'최근 이상 판정',warming_up:'모델 준비 중',starting:'서비스 시작 중',degraded:'처리 상태 저하'})[r.status]||'처리 상태 미확인',tone:r.status==='normal'?'observed':'waiting',detail:'최근 결과 '+(r.target==='server1'?'서버':r.target==='edge-local'?'엣지':'대상 미확인')+' · '+r.latest};
  }
  function selectedLocations(s,data=state.profiles,failed=state.profileError,now=Date.now()){
    const seen=new Set(),rows=[];for(const n of s.stages)for(const x of n.executions){const key=executionKey(s,n,x);if(!key||seen.has(key))continue;seen.add(key);rows.push({key,n,x,p:placement(s,n,x,data,failed,now)});}return rows;
  }
  const stamp=value=>Number.isFinite(Date.parse(value))?new Date(value).toLocaleTimeString('ko-KR',{hour12:false}):'—';
  function currentMarkup(s){const rows=selectedLocations(s),nodes=[...new Set(rows.flatMap(w=>w.p.nodes))],runtime=runtimeSummary(s);return `<div class="sa-current-state"><div><span>현재 Pod 실행 위치</span><strong>${nodes.length?nodes.map(E).join(' · '):'확인 불가'}</strong></div><div data-tone="${runtime.tone}"><span>${E(runtime.label)}</span><small>${E(runtime.detail)}</small></div></div>`;}
  function selectorOptions(){return [{label:'등록 서비스',rows:state.services},{label:'실행 워크로드 · 연결 계약 별도',rows:state.workloads}].filter(g=>g.rows.length).map(g=>`<optgroup label="${g.label} (${g.rows.length})">${g.rows.map(s=>`<option value="${E(s.id)}" ${s.id===state.id?'selected':''}>${E(s.kind==='workload'?s.workload.namespace+' / '+s.title:s.title)}</option>`).join('')}</optgroup>`).join('');}
  function rememberSelection(){const url=new URL(root.location.href);url.searchParams.set('service',state.id);root.history.replaceState(null,'',url);}
  const stageById=(s,id)=>s.stages.find(n=>n.stage_id===id);
  const targetFor=(s,slot)=>s.targets.find(t=>t.slot===slot);
  const targetTitle=(s,x)=>{const t=targetFor(s,x.target_slot);return t?.node||t?.label||x.target_slot||'대상 미지정';};
  const recent=(value,now=Date.now())=>Number.isFinite(Date.parse(value))&&now-Date.parse(value)>=-5000&&now-Date.parse(value)<90000;
  function resultsPath(s){
    const o=s?.observability;
    return s?.kind==='registered'&&s.id==='sensor-anomaly-demo'&&o?.adapter==='sensor-anomaly-v1'&&/^\/state\/service-demo\/results(?:\?limit=(?:[1-9]|[1-9]\d))?$/.test(o.results_path||'')?o.results_path:null;
  }
  const resultKey=r=>JSON.stringify([r.origin,r.observed_at,r.request_id||null]);
  function parseResults(data,now=Date.now()){
    if(data?.mode!=='live'||data.observation_error||!recent(data.generated_at,now)||!Array.isArray(data.results))throw Error('처리 결과 조회 실패');
    const seen=new Set(),rows=[];
    for(const r of data.results){
      if(!r||!Number.isFinite(Date.parse(r.observed_at))||Date.parse(r.observed_at)>now+5000||!Number.isFinite(r.origin)||!Number.isFinite(r.score)||typeof r.anomaly!=='boolean')throw Error('처리 결과 형식 오류');
      const key=resultKey(r);if(!seen.has(key)){seen.add(key);rows.push(r);}
    }
    return {generatedAt:data.generated_at,rows:rows.sort((a,b)=>Date.parse(b.observed_at)-Date.parse(a.observed_at)).slice(0,12)};
  }
  function mergeResults(previous,data,now=Date.now()){
    const known=new Set((previous?.rows||[]).map(resultKey)),last=Date.parse(previous?.rows?.[0]?.observed_at);
    const added=Number.isFinite(last)?data.rows.filter(r=>Date.parse(r.observed_at)>last&&!known.has(resultKey(r))).length:0;
    return {...data,checkedAt:new Date(now).toISOString(),error:false,loading:false,added};
  }
  function resultSummary(feed,now=Date.now()){
    if(!feed)return {label:'처리 결과 불러오는 중',tone:'neutral'};
    if(feed.error)return {label:'결과 조회 실패',tone:'waiting'};
    if(!feed.checkedAt)return {label:'처리 결과 불러오는 중',tone:'neutral'};
    if(!recent(feed.checkedAt,now)||!recent(feed.generatedAt,now))return {label:'결과 관측 오래됨',tone:'waiting'};
    if(!feed.rows?.length)return {label:'저장된 결과 없음',tone:'neutral'};
    if(!recent(feed.rows[0].observed_at,now))return {label:'최근 처리 미관측',tone:'waiting'};
    return {label:feed.added?'새 결과 수신 · +'+feed.added:'최근 결과 확인',tone:'observed'};
  }
  const number=value=>typeof value==='number'&&Number.isFinite(value)?value.toLocaleString('ko-KR',{maximumFractionDigits:3}):'—';
  const resultTime=value=>Number.isFinite(Date.parse(value))?new Date(value).toLocaleString('ko-KR',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',second:'2-digit',hour12:false}):'—';
  function resultMarkup(s,feed=state.results.get(s.id),now=Date.now()){
    if(!resultsPath(s)||state.source==='git')return `<section class="sa-results sa-results-empty" aria-label="최근 처리 결과"><strong>처리 결과 미연동</strong><span>이 항목에는 연결된 결과 조회 계약이 없습니다.</span></section>`;
    const status=resultSummary(feed,now),latest=feed?.rows?.[0];
    const age=latest?Math.max(0,Math.floor((now-Date.parse(latest.observed_at))/1000)):null;
    const elapsed=age===null?'':age<60?age+'초 전':age<3600?Math.floor(age/60)+'분 전':age<86400?Math.floor(age/3600)+'시간 전':Math.floor(age/86400)+'일 전';
    const old=feed?.error||status.tone==='waiting',target=r=>r.inference_target==='server1'?'서버':r.inference_target==='edge-local'?'엣지':'미확인';
    return `<section class="sa-results" aria-label="최근 처리 결과" data-result-state="${feed?.error?'error':latest?'available':'empty'}"><div class="sa-results-heading"><h2>${icon('results')}최근 처리 결과</h2><span class="sa-result-status" data-tone="${status.tone}" role="status">${E(status.label)}</span><small>${feed?.checkedAt?'결과 조회 '+stamp(feed.checkedAt):'15초 자동 갱신'}</small></div>
      ${latest?`<div class="sa-result-metrics"><div><span>${old?'마지막 저장 판정':'최근 판정'}</span><strong data-anomaly="${latest.anomaly}">${latest.anomaly?'이상 감지':'정상'}</strong><small>${E(resultTime(latest.observed_at))} · ${elapsed}</small></div><div><span>통합 이상 점수</span><strong>${number(latest.score)}</strong><small>진동 ${number(latest.component_scores?.vibration)} · 온도 ${number(latest.component_scores?.temperature)}</small></div><div><span>처리된 특징값</span><strong>${number(latest.vibration_features?.rms)}<small>진동 RMS</small></strong><small>온도 평균 ${number(latest.temperature_features?.mean)} · raw 기준</small></div><div><span>처리 경로 · 소요 시간</span><strong>${target(latest)}<small>${number(latest.total_latency_ms)} ms</small></strong><small>${E(latest.model_version||'모델 버전 미제공')}</small></div></div>
      <div class="sa-results-note">${old?'마지막으로 확인한 저장값입니다. 현재 처리 중이라는 의미는 아닙니다.':feed.added?'이전 조회 이후 더 새로운 처리 결과를 받았습니다.': '같은 결과는 새 처리로 집계하지 않습니다. 새 결과가 오면 수신 표시가 바뀝니다.'}</div>
      <details class="sa-result-history"><summary>최근 결과 ${feed.rows.length}건 보기</summary><div class="sa-result-table"><table><caption class="sa-sr-only">서비스에 저장된 최근 처리 결과</caption><thead><tr><th>처리 시각</th><th>판정</th><th>점수</th><th>경로</th><th>소요 시간</th></tr></thead><tbody>${feed.rows.map(r=>`<tr><td>${E(resultTime(r.observed_at))}</td><td>${r.anomaly?'이상':'정상'}</td><td>${number(r.score)}</td><td>${target(r)}</td><td>${number(r.total_latency_ms)} ms</td></tr>`).join('')}</tbody></table></div></details>`:`<p class="sa-results-note">${feed?.error?'결과 서비스가 응답하지 않아 처리값을 확인할 수 없습니다. 다음 갱신 때 다시 조회합니다.':feed?.checkedAt?'서비스가 결과를 저장하면 판정값·점수·처리 시각이 여기에 표시됩니다.':'실제 서비스에 저장된 결과를 조회하고 있습니다.'}</p>`}
    </section>`;
  }
  async function loadResults(s){
    const path=resultsPath(s);if(!path||state.source!=='api')return;
    const before=state.results.get(s.id);if(before?.loading)return;
    state.results.set(s.id,{...before,loading:true});
    try{const data=await read(path,parseResults);state.results.set(s.id,mergeResults(before,data));}
    catch(_){state.results.set(s.id,{...before,loading:false,error:true,added:0,checkedAt:new Date().toISOString()});}
    if(selected()?.id===s.id)paintLive();
  }
  function parseProfiles(data){if(!data||!Array.isArray(data.service_resource_profiles)||data.service_resource_profiles.some(p=>!p||typeof p.namespace!=='string'||typeof p.service!=='string'||!Array.isArray(p.nodes)))throw Error('배치 응답 형식 오류');return data;}
  function executionKey(s,n,x){const remote=s.remoteWorkload;const namespace=x.namespace||(x.executor===remote?.name?remote.namespace:n.kind==='source'?'edgex-edge':s.workload.namespace);return namespace&&x.executor?namespace+'/'+x.executor:null;}
  function placement(s,n,x,data=state.profiles,failed=state.profileError,now=Date.now()){
    const key=executionKey(s,n,x),profile=data?.service_resource_profiles?.find(p=>p.namespace+'/'+p.service===key);
    if(failed||!data||!key)return {status:'unknown',label:'실행 위치 확인 불가',nodes:[]};
    if(!recent(data.generated_at,now)||profile&&!recent(profile.generated_at||data.generated_at,now))return {status:'stale',label:'관측 오래됨 · 새로고침 필요',nodes:[]};
    if(!profile)return {status:'absent',label:'Running Pod 미관측',nodes:[]};
    const nodes=profile.nodes.filter(n=>typeof n==='string'&&n&&n!=='unknown');
    return {status:nodes.length?'observed':'unknown',label:nodes.length?nodes.join(' · '):'노드 확인 불가',nodes,profile};
  }
  function hardware(node){
    const kind=({'etri-dev0001-jetorn':'jetson','etri-dev0002-raspi5':'raspberry-pi','etri-dev0003-raspi5':'raspberry-pi','etri-ser0002-cgnmsb':'server','etri-ser0001-CG0MSB':'server','etri-ser0001-cg0msb':'server'})[node];
    return kind?{kind,label:({jetson:'Jetson · 엣지 AI','raspberry-pi':'Raspberry Pi · 현장 엣지',server:'서버 · 추론 실행체'})[kind],src:'/static/nexus/assets/hardware/'+kind+'.png'}:{kind:'unknown',label:'관측 노드',src:null};
  }
  function nodeLinks(s,data=state.profiles,failed=state.profileError,now=Date.now()){
    const result=[],seen=new Set();
    for(const link of s.links){const a=stageById(s,link.from),b=stageById(s,link.to);
      const observed=n=>[...new Set(n.executions.flatMap(x=>placement(s,n,x,data,failed,now).nodes))];
      for(const from of observed(a))for(const to of observed(b)){
        const key=JSON.stringify([from,to,link.key]);if(from===to||seen.has(key))continue;seen.add(key);
        result.push({from,to,key:link.key,label:a.label+' → '+b.label});
      }
    }return result;
  }
  function fitCanvas(){
    const viewport=root.document?.querySelector('.sa-map-viewport'),scene=viewport?.querySelector('.sa-unified-map'),sizer=viewport?.querySelector('.sa-map-sizer');if(!scene)return;
    const zoom=state.zoom??(viewport.clientWidth<600?0.85:Math.min(1,viewport.clientWidth/scene.offsetWidth));
    scene.style.transform=`scale(${zoom})`;sizer.style.width=scene.offsetWidth*zoom+'px';sizer.style.height=scene.offsetHeight*zoom+'px';
    root.document.querySelector('[data-sa-scale]').textContent=Math.round(zoom*100)+'%';
    root.requestAnimationFrame(paintNodeLinks);
  }
  function paintNodeLinks(){
    const grid=root.document?.querySelector('.sa-unified-map'),svg=grid?.querySelector('.sa-node-wires'),labels=grid?.querySelector('.sa-wire-labels'),s=selected();if(!svg||!s)return;
    const bounds=grid.getBoundingClientRect(),scale=bounds.width/grid.offsetWidth;
    const rect=el=>{if(!el)return null;const r=el.getBoundingClientRect();return {left:(r.left-bounds.left)/scale,right:(r.right-bounds.left)/scale,top:(r.top-bounds.top)/scale,bottom:(r.bottom-bounds.top)/scale};};
    const ports=[...grid.querySelectorAll('[data-sa-port]')],edges=[];
    for(const link of s.links){const from=ports.filter(p=>p.dataset.saStage===link.from),to=ports.filter(p=>p.dataset.saStage===link.to);for(const a of from)for(const b of to)edges.push({a,b,key:link.key,label:stageById(s,link.from).label+' → '+stageById(s,link.to).label});}
    for(const p of ports.filter(p=>stageById(s,p.dataset.saStage)?.kind==='source'))edges.push({a:grid.querySelector('.sa-map-input'),b:p,input:true,label:'센서 입력'});
    const paths=[],chips=[];
    svg.setAttribute('viewBox',`0 0 ${grid.offsetWidth} ${grid.offsetHeight}`);
    for(const e of edges){const a=rect(e.a),b=rect(e.b);if(!a||!b)continue;const sameNode=e.a.closest('[data-sa-node]')===e.b.closest('[data-sa-node]');
      let path,x,y;
      if(sameNode){const ax=a.left+18,bx=b.left+18;path=`M${ax} ${a.bottom} L${ax} ${(a.bottom+b.top)/2} L${bx} ${(a.bottom+b.top)/2} L${bx} ${b.top}`;}
      else{const forward=a.left<b.left,x1=forward?a.right:a.left,x2=forward?b.left:b.right,y1=(a.top+a.bottom)/2+(forward?0:8),y2=(b.top+b.bottom)/2+(forward?0:8);x=(x1+x2)/2;y=(y1+y2)/2;path=`M${x1} ${y1} C${x} ${y1} ${x} ${y2} ${x2} ${y2}`;
        const label=e.input?'센서 입력':stageById(s,s.links.find(l=>l.key===e.key).to).slot==='Inference'?'추론 입력':stageById(s,s.links.find(l=>l.key===e.key).from).slot==='Inference'?'판정 결과':e.label;
        chips.push(`<button class="sa-wire-label" style="left:${x}px;top:${y}px" ${e.input?'data-sa-stage="inputs"':`data-sa-link="${E(e.key)}"`} aria-haspopup="dialog" aria-controls="sa-detail-dialog" aria-label="${E(e.label+' 상세 보기')}">${E(label)}</button>`);
      }
      paths.push(`<path class="${sameNode?'sa-wire-internal':e.input?'sa-wire-input':'sa-wire-cross'}" d="${path}" marker-end="url(#sa-wire-arrow)"/>`);
    }
    svg.innerHTML='<defs><marker id="sa-wire-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M 1 1 L 9 5 L 1 9"/></marker></defs>'+paths.join('');labels.innerHTML=chips.join('');
  }
  function placementMarkup(s){
    const workloads=new Map();
    for(const n of s.stages)for(const x of n.executions){const key=executionKey(s,n,x);if(!key)continue;if(!workloads.has(key))workloads.set(key,{n,x,stages:[]});workloads.get(key).stages.push(n);}
    const nodes=new Map(),missing=[];
    for(const [key,w] of workloads){const p=placement(s,w.n,w.x);if(p.status!=='observed'){missing.push({...w,p,key});continue;}for(const node of p.nodes){if(!nodes.has(node))nodes.set(node,[]);nodes.get(node).push({...w,p,key});}}
    const stageButtons=(stages,node,key)=>stages.map(n=>`<button data-sa-stage="${E(n.stage_id)}" ${node?`data-sa-port="${E(JSON.stringify([node,key,n.stage_id]))}"`:''} aria-haspopup="dialog" aria-controls="sa-detail-dialog"><span>${icon(stageIcon(n))}${E(n.label)}</span><small>${String(s.stages.indexOf(n)+1).padStart(2,'0')}</small></button>`).join('');
    const observed=workloads.size-missing.length,showInput=s.kind!=='workload'&&(s.inputs.length>0||!!s.physicalSource),count=Math.max(1,nodes.size);const podCount=selectedLocations(s).filter(w=>w.p.status==='observed').reduce((sum,w)=>sum+(Number.isInteger(w.p.profile.pod_count)?w.p.profile.pod_count:0),0);
    return `${currentMarkup(s)}<div class="sa-observation-bar"><div><span>관측 노드</span><strong>${nodes.size}</strong></div><div><span>관측 실행체</span><strong>${observed}<small> / ${workloads.size}</small></strong></div><div><span>${s.kind!=='workload'?'처리 단계':'Running Pod'}</span><strong>${s.kind!=='workload'?s.stages.length:observed?podCount:'—'}</strong></div><div class="sa-ownership"><span>위치 응답</span><strong>${state.profileError?'조회 실패':stamp(state.profiles?.generated_at)}</strong></div></div>
      ${resultMarkup(s)}<div class="sa-map-toolbar"><div>${icon('route')}<strong>서비스 토폴로지</strong><span>단계와 연결을 선택해 상세 확인</span></div><div class="sa-map-tools"><button data-sa-zoom="out" aria-label="축소">${icon('minus')}</button><span data-sa-scale>100%</span><button data-sa-zoom="in" aria-label="확대">${icon('plus')}</button><button data-sa-zoom="fit" aria-label="화면에 맞춤">${icon('fit')}</button></div></div>
      <div class="sa-map-viewport" tabindex="0" role="region" aria-label="서비스 배치 지도, 작은 화면에서는 가로로 스크롤"><div class="sa-map-sizer"><div class="sa-unified-map" style="--sa-nodes:${count};grid-template-columns:${showInput?'160px ':''}repeat(${count},320px);width:${(showInput?208:-64)+count*432}px"><svg class="sa-node-wires" aria-hidden="true"></svg><div class="sa-wire-labels"></div>
        ${showInput?`<div class="sa-input-lane"><div class="sa-lane-label"><span>01</span>데이터 입력</div><button class="sa-map-input" data-sa-stage="inputs" aria-haspopup="dialog" aria-controls="sa-detail-dialog"><span class="sa-input-symbol">${icon('physical')}</span><strong>${E(s.physicalSource||'EdgeX 등록 입력')}</strong><span>${s.inputs.length}개 입력 항목</span><small>물리 source</small></button></div>`:''}
        <div class="sa-node-grid">${[...nodes].map(([node,items],i)=>`<article class="sa-node-place" data-sa-node="${E(node)}" data-hardware="${hardware(node).kind}"><div class="sa-lane-label"><span>${String(i+(showInput?2:1)).padStart(2,'0')}</span>${E(hardware(node).kind==='server'?'서버 실행 영역':hardware(node).kind==='unknown'?'관측 실행 영역':'현장 엣지')}</div><div class="sa-hardware">${hardware(node).src?`<img src="${hardware(node).src}" alt="" width="64" height="64">`:icon('kube')}<div><span>${E(hardware(node).label.split(' · ')[0])}</span><strong>${E(node)}</strong></div><span class="sa-node-observed" title="Running Pod 위치 관측">Running</span></div>
          ${items.map(w=>`<div class="sa-placed-workload" data-kind="${E(w.n.kind)}"><div class="sa-workload-name"><span>${icon(stageIcon(w.n))}<b>${E(w.x.executor)}</b></span><small>${Number.isInteger(w.p.profile.pods_by_node?.[node])?w.p.profile.pods_by_node[node]:'—'} Pod</small></div>${targetFor(s,w.x.target_slot)?.node&&targetFor(s,w.x.target_slot).node!==node?`<p class="sa-location-diff">설정 위치와 다름 · ${E(targetFor(s,w.x.target_slot).node)}</p>`:''}<div class="sa-workload-stages">${stageButtons(w.stages,node,w.key)}</div></div>`).join('')}</article>`).join('')}</div>
        ${!nodes.size?'<div class="sa-map-unobserved">현재 실행 위치를 확인할 수 없습니다.<small>아래 실행체의 관측 상태를 확인하세요.</small></div>':''}
      </div></div></div>
      ${missing.length?`<div class="sa-placement-missing">${missing.map(w=>`<div><strong>${E(w.x.executor)}</strong><span>${E(w.p.label)}</span>${s.kind==='workload'?'':`<small>설정: ${E(targetTitle(s,w.x))}</small>`}<div class="sa-workload-stages">${stageButtons(w.stages)}</div></div>`).join('')}</div>`:''}
      ${s.stages.some(n=>!n.executions.length)?`<div class="sa-workload-stages">${stageButtons(s.stages.filter(n=>!n.executions.length))}</div>`:''}
      <div class="sa-map-legend"><span><i></i>계약상 데이터 연결</span><span>장비 그림은 유형 예시 · Pod 실행과 AI 처리 성공은 별도</span><span>${state.auto?'15초 자동 갱신':'자동 갱신 일시정지'}</span></div>`;
  }
  function stagePlacement(s,n){return [...new Set(n.executions.map(x=>placement(s,n,x).label))].join(' / ')||'실행 대상 미지정';}
  function updatePlacements(){const resultEl=root.document.querySelector('.sa-results');if(selected()&&resultEl){const open=!!resultEl.querySelector('details')?.open;resultEl.outerHTML=resultMarkup(selected());const history=root.document.querySelector('.sa-result-history');if(history)history.open=open;}if(!selected()||!root.document.querySelector('.architecture')||state.expired)return;if(state.profiles&&recent(state.profiles.generated_at)&&state.profiles.service_resource_profiles.every(p=>recent(p.generated_at||state.profiles.generated_at)))return;state.expired=true;paintLive();}
  const sourceLabel=()=>state.source==='api'?'등록 서비스 계약':state.source==='git'?'Git 계약 미리보기':'서비스 계약';
  function serviceLink(s){return '/?service='+encodeURIComponent(s.id)+'#service-detail';}
  function podDetails(s,n,x){const p=placement(s,n,x);if(!p.profile)return '';return `<details class="sa-pod-detail"><summary>Pod · 관측 시각</summary>${[...new Set((p.profile.containers||[]).filter(c=>typeof c.pod==='string').map(c=>c.pod+' · '+c.node))].map(v=>`<code>${E(v)}</code>`).join('')||'<p>Pod 이름 미제공</p>'}<p>${E(p.profile.generated_at||state.profiles?.generated_at)}</p></details>`;}
  function detail(s){
    if(state.link){const l=s.links.find(l=>l.key===state.link);if(l){const a=stageById(s,l.from),b=stageById(s,l.to);return `<span class="sa-eyebrow">단계 연결</span><h3 id="sa-detail-title">${E(a.label)} → ${E(b.label)}</h3><div class="sa-endpoints"><button data-sa-stage="${E(a.stage_id)}"><small>출발</small><strong>${E(a.label)}</strong>${icon(stageIcon(a))}</button><button data-sa-stage="${E(b.stage_id)}"><small>도착</small><strong>${E(b.label)}</strong>${icon(stageIcon(b))}</button></div><p class="sa-detail-copy">${E(a.slot==='Input'&&s.sourceMode==='local_recent'?'Device Service의 로컬 데이터 API를 읽어 전처리 입력으로 사용합니다. 중앙 Core Data 저장 경로와 별개입니다.':a.label+' 단계를 거친 출력이 '+b.label+' 단계의 입력이 됩니다.')}</p><p class="sa-detail-note">서비스 계약의 단계 의존 관계입니다. 실제 트래픽이나 실행 성공을 표시하지 않습니다.</p>`;}}
    if(state.stage==='inputs')return `<span class="sa-eyebrow">서비스 입력</span><h3 id="sa-detail-title">${E(s.physicalSource||'등록 입력 장비')}</h3><p class="sa-detail-copy">${E(s.sourceMode==='local_recent'?'Device Service의 로컬 입력을 읽습니다.':'등록 계약에 지정된 입력을 사용합니다.')}</p><div class="sa-input-list">${s.inputs.length?s.inputs.map(x=>`<div><strong>${E(x.resource_name)}</strong><span>EdgeX Device</span><code>${E(x.device_name)}</code></div>`).join(''):'<p>입력 매핑이 지정되지 않았습니다.</p>'}</div><p class="sa-detail-note">EdgeX 등록 이름과 물리 source ID는 다른 식별자입니다.</p>`;
    const n=stageById(s,state.stage)||s.stages[0];if(!n)return '<h3 id="sa-detail-title">단계 계약 없음</h3><p class="sa-detail-copy">이 서비스에는 표시할 단계 구성이 등록되지 않았습니다.</p>';
    return `<span class="sa-eyebrow">${E(n.slot||n.kind||'서비스 단계')}</span><h3 id="sa-detail-title">${E(n.label)}</h3><p class="sa-detail-copy">${E(s.kind==='workload'?'선택한 namespace/workload의 실제 Running Pod 위치입니다. 다른 서비스와의 연결은 추정하지 않습니다.':descriptions[n.slot]||'서비스 계약에 정의된 처리 단계입니다.')}</p><h4>${s.kind==='workload'?'관측 실행체':'설정된 실행체'}</h4><div class="sa-executors">${n.executions.length?n.executions.map(x=>{const t=targetFor(s,x.target_slot);return `<div><span>${E(s.kind==='workload'?s.workload.namespace:t?.mode==='edge-local'?'엣지 처리':t?.mode==='approval-gated'?'승인 조건이 있는 서버 경로':'설정 대상')}</span><strong>${E(x.executor||'실행체 미지정')}</strong>${s.kind==='workload'?'':`<code>설정: ${E(targetTitle(s,x))}</code>`}<code>관측: ${E(placement(s,n,x).label)}</code>${podDetails(s,n,x)}</div>`;}).join(''):'<p>실행체가 지정되지 않았습니다.</p>'}</div>${n.slot==='Result'&&s.id==='sensor-anomaly-demo'?'<p class="sa-detail-note">이 데모의 판정·알림은 자체 SQLite에 저장합니다. EdgeX의 원시 Event·Reading 저장과 구분합니다.</p>':''}<h4>이 단계의 연결</h4><div class="sa-detail-links">${s.links.filter(l=>l.from===n.stage_id||l.to===n.stage_id).map(l=>`<button data-sa-link="${E(l.key)}">${E(stageById(s,l.from).label)} → ${E(stageById(s,l.to).label)} ${icon('arrow')}</button>`).join('')||'<p>연결이 없습니다.</p>'}</div>`;
  }
  function render(){
    const s=selected(),filtered=state.services.filter(s=>(s.title+' '+s.id).toLocaleLowerCase().includes(state.query.toLocaleLowerCase()));
    return `<section class="architecture sa-product" data-sa-selected="${E(s?.id)}" aria-label="서비스별 구성도"><div class="sa-service-heading"><div><span class="sa-eyebrow">서비스 구성도${s?' / '+E(s.id):''}</span><h1>${E(s?.title||'서비스 구성도')}</h1><p>${E(s?.description||'등록 서비스의 실행 위치와 연결을 확인합니다.')}</p></div><div class="sa-header-actions">${s&&s.kind!=='workload'?`<a class="button" href="${E(serviceLink(s))}">운영 상세 ${icon('arrow')}</a>`:''}<button class="button" data-sa-action="refresh" ${state.loading?'disabled':''}>${state.loading?'불러오는 중…':'새로고침'}</button></div></div>
      ${state.error?`<div class="sa-error" role="alert">${E(state.error)}</div>`:''}${state.source==='git'?'<p class="sa-fallback">운영 API를 조회하지 못해 Git 계약 미리보기를 표시합니다.</p>':''}
      <div class="sa-service-selector"><label for="sa-select">서비스 / 워크로드</label><select id="sa-select" ${!entries().length?'disabled':''}>${selectorOptions()||'<option>목록을 불러오는 중</option>'}</select><span id="sa-catalog-count">등록 서비스 ${state.services.length} · 워크로드 ${state.workloads.length}</span><button data-sa-auto aria-pressed="${state.auto}">${state.auto?'자동 갱신 켜짐 · 15초':'자동 갱신 꺼짐'}</button><small id="sa-refresh-status">${state.checkedAt?'확인 '+stamp(state.checkedAt):'조회 중'}</small></div>
      ${s?`<section id="sa-placement" class="sa-placement" aria-label="서비스 실행 위치">${placementMarkup(s)}</section><dialog id="sa-detail-dialog" class="sa-detail-dialog" aria-labelledby="sa-detail-title"><button class="sa-detail-close" data-sa-close aria-label="상세 닫기">${icon('close')}</button><div id="sa-detail" class="sa-detail">${detail(s)}</div></dialog><p class="sa-provenance">${s.id==='sensor-anomaly-demo'?'테스트베드 기준선 서비스 · 옥동 실공장 AI 서비스의 구현 완료를 뜻하지 않습니다.':''}</p>`:state.loading?'<div class="sa-empty" role="status">서비스 구성을 불러오고 있습니다.</div>':'<div class="sa-empty">등록된 서비스 계약을 확인하거나 새로고침해 주세요.</div>'}<p id="sa-announcement" class="sa-sr-only" role="status"></p></section>`;
  }
  function paint(){const el=root.document?.querySelector('.architecture');if(el){el.outerHTML=render();root.requestAnimationFrame(fitCanvas);}}
  function paintSelection(){const s=selected();if(!s)return;root.document.querySelector('#sa-detail').innerHTML='<p class="sa-detail-snapshot">상세 기준 '+stamp(state.checkedAt)+'</p>'+detail(s);root.document.querySelectorAll('[data-sa-stage]').forEach(b=>b.setAttribute('aria-pressed',String(!state.link&&b.dataset.saStage===state.stage)));root.document.querySelectorAll('[data-sa-link]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.saLink===state.link)));const dialog=root.document.querySelector('#sa-detail-dialog'),h=root.document.querySelector('#sa-detail-title');h.tabIndex=-1;if(!dialog.open)dialog.showModal();h.focus({preventScroll:true});root.document.querySelector('#sa-announcement').textContent=h.textContent+' 상세';}
  async function read(url,parser=parse){const controller=new AbortController(),timer=root.setTimeout(()=>controller.abort(),5000);try{const r=await root.fetch(url,{signal:controller.signal,cache:'no-store'});if(!r.ok)throw Error('HTTP '+r.status);return parser(await r.json());}finally{root.clearTimeout(timer);}}
  function paintLive(){
    const s=selected(),el=root.document.querySelector('.architecture');if(!el)return;
    if(!s||el.dataset.saSelected!==s.id){paint();return;}
    const historyOpen=!!el.querySelector('.sa-result-history')?.open;
    const viewport=el.querySelector('.sa-map-viewport'),scroll={x:viewport?.scrollLeft||0,y:viewport?.scrollTop||0};
    el.querySelector('.sa-service-heading h1').textContent=s.title;el.querySelector('.sa-service-heading p').textContent=s.description;const placementEl=el.querySelector('#sa-placement');placementEl.innerHTML=placementMarkup(s);if(historyOpen&&placementEl.querySelector('.sa-result-history'))placementEl.querySelector('.sa-result-history').open=true;
    const select=el.querySelector('#sa-select'),desired=entries().map(s=>s.id);
    if(JSON.stringify([...select.options].map(o=>o.value))!==JSON.stringify(desired))select.innerHTML=selectorOptions();
    select.value=state.id;select.disabled=!desired.length;
    el.querySelector('#sa-catalog-count').textContent='등록 서비스 '+state.services.length+' · 워크로드 '+state.workloads.length;
    el.querySelector('#sa-refresh-status').textContent=(state.profileError?'위치 조회 실패 · ':'확인 ')+stamp(state.checkedAt);
    const auto=el.querySelector('[data-sa-auto]');auto.setAttribute('aria-pressed',String(state.auto));auto.textContent=state.auto?'자동 갱신 켜짐 · 15초':'자동 갱신 꺼짐';
    const refresh=el.querySelector('[data-sa-action]');refresh.disabled=state.loading;refresh.textContent=state.loading?'불러오는 중…':'새로고침';
    el.querySelectorAll('.sa-error,.sa-fallback').forEach(note=>note.remove());
    if(state.error||state.source==='git'){const note=root.document.createElement('p');note.className='sa-fallback sa-refresh-error';note.textContent=state.error||'운영 API를 조회하지 못해 Git 계약 미리보기를 표시합니다.';el.querySelector('.sa-service-selector').after(note);}
    root.requestAnimationFrame(()=>{fitCanvas();const next=el.querySelector('.sa-map-viewport');next.scrollLeft=scroll.x;next.scrollTop=scroll.y;});
  }
  async function load(background=false){
    if(state.loading)return;state.loading=true;state.error=null;state.expired=false;
    if(!background)paint();else{const button=root.document.querySelector('[data-sa-action]');if(button)button.disabled=true;}
    const oldSelected=selected();
    const profileTask=read('/state/service-resource-profiles',parseProfiles).then(data=>({data}),()=>({error:true}));
    let rows=[],source=null;
    try{try{rows=await read('/state/services');source='api';}catch(_){rows=await read('/static/nexus/service-architecture.json');source='git';}}
    catch(_){state.error='서비스 계약을 불러오지 못했습니다. 다시 시도해 주세요.';}
    const profile=await profileTask;
    state.profiles=profile.data||null;state.profileError=!!profile.error;
    if(profile.data){const current=selected()||oldSelected;state.workloads=workloadEntries(profile.data);if(current?.kind==='workload'&&!state.workloads.some(s=>s.id===current.id))state.workloads.push(current);}
    state.services=rows;state.source=source;
    const requested=state.id||new URLSearchParams(root.location.search).get('service');
    state.id=entries().some(s=>s.id===requested)?requested:entries()[0]?.id||null;
    if(state.id!==oldSelected?.id){state.stage=null;state.link=null;state.zoom=null;}
    else if(state.stage&&state.stage!=='inputs'&&!selected()?.stages.some(n=>n.stage_id===state.stage)){state.stage=null;state.link=null;}
    state.checkedAt=new Date().toISOString();state.loading=false;state.loaded=true;
    if(background)paintLive();else paint();
    if(selected())loadResults(selected());
  }
  function draw(){if(!state.loaded&&!state.loading)load();else root.requestAnimationFrame(fitCanvas);}
  function setup(){root.setInterval(()=>{if(!root.document.querySelector('.architecture'))return;updatePlacements();if(state.auto&&!root.document.hidden)load(true);},15000);root.document.addEventListener('click',e=>{if(!e.target.closest('.architecture'))return;const service=e.target.closest('[data-sa-service]'),stage=e.target.closest('[data-sa-stage]'),link=e.target.closest('[data-sa-link]'),action=e.target.closest('[data-sa-action]');if(service){state.id=service.dataset.saService;state.stage=null;state.link=null;state.zoom=null;paint();root.document.querySelector(`[data-sa-service="${root.CSS.escape(state.id)}"]`)?.focus({preventScroll:true});}if(stage){state.stage=stage.dataset.saStage;state.link=null;paintSelection();}if(link){state.link=link.dataset.saLink;paintSelection();}const zoom=e.target.closest('[data-sa-zoom]');if(zoom){const viewport=root.document.querySelector('.sa-map-viewport'),scene=root.document.querySelector('.sa-unified-map');const current=scene.getBoundingClientRect().width/scene.offsetWidth;state.zoom=zoom.dataset.saZoom==='fit'?Math.min(1,viewport.clientWidth/scene.offsetWidth):Math.max(0.35,Math.min(1.5,current+(zoom.dataset.saZoom==='in'?0.15:-0.15)));fitCanvas();}if(e.target.closest('[data-sa-close]'))root.document.querySelector('#sa-detail-dialog')?.close();if(e.target.closest('[data-sa-auto]')){state.auto=!state.auto;paintLive();if(state.auto)load(true);}if(action)load(true);});
    root.document.addEventListener('change',e=>{if(e.target.id!=='sa-select')return;state.id=e.target.value;state.stage=null;state.link=null;state.zoom=null;rememberSelection();paint();loadResults(selected());root.document.querySelector('#sa-select')?.focus({preventScroll:true});});
    root.document.addEventListener('visibilitychange',()=>{if(!root.document.hidden&&state.auto&&root.document.querySelector('.architecture'))load(true);});
    root.document.addEventListener('close',e=>{if(e.target.id!=='sa-detail-dialog')return;const area=root.document.querySelector('#sa-placement');const selector=state.link?'[data-sa-link="'+root.CSS.escape(state.link)+'"]':'[data-sa-stage="'+root.CSS.escape(state.stage||'inputs')+'"]';area?.querySelector(selector)?.focus({preventScroll:true});},true);
    root.addEventListener('resize',()=>root.requestAnimationFrame(fitCanvas));
    root.document.addEventListener('toggle',e=>{if(e.target.closest('.sa-node-grid'))root.requestAnimationFrame(fitCanvas);},true);
    root.document.addEventListener('input',e=>{if(e.target.id==='sa-search'){const pos=e.target.selectionStart;state.query=e.target.value;paint();const input=root.document.querySelector('#sa-search');input.focus();if(input.type!=='search')input.setSelectionRange(pos,pos);}});
  }
  const api={render,draw,setup,normalize,parse,serviceLink,executionKey,placement,parseProfiles,hardware,nodeLinks,workloadEntries,runtimeSummary,selectedLocations,resultsPath,parseResults,mergeResults,resultSummary,resultMarkup};
  if(typeof module!=='undefined'&&module.exports)module.exports=api;
  root.NexusArchitecture=api;
})(typeof window!=='undefined'?window:globalThis);
