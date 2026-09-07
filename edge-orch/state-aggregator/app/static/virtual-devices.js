(() => {
  const stateLabels = {unknown: "확인 불가", no_instance: "실행체 없음", observed: "실행체 관측",
    terminating: "종료 중", not_ready: "준비 안 됨", ready: "요청 대기", processing: "처리 중",
    configured_unverified: "연결 설정만 등록 · 요청 미검증", not_configured: "연결 설정 없음",
    request_observed: "최근 요청 처리 관측", historical_request: "과거 요청 증거 · 현재 연결 미검증"};
  const esc = (value) => String(value ?? "N/A").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
  const ageFresh = (stamp, now = Date.now(), seconds = 30) => {
    const age = now - Date.parse(stamp);
    return Number.isFinite(age) && age >= -5000 && age <= seconds * 1000;
  };
  function displayState(snapshot, failed = false, now = Date.now()) {
    if (!snapshot) return {summary: {physicalNodes:null, definitions:null, observedInstances:null}, nodes: null, resources: []};
    const stale = failed || !ageFresh(snapshot.observedAt, now, snapshot.maxAgeSeconds);
    const resources = snapshot.resources.map(row => {
      if (stale || !ageFresh(row.observedAt, now)) return {...row, executionState:"unknown",
        connectionState:"unknown", observedInstances:null, instances:[],
        observationError: row.observationError || "관측 만료 또는 조회 실패"};
      const instances = row.instances.map(pod => {
        if (!ageFresh(pod.apiObservedAt, now)) return {...pod, modelReady:null, runtime:null,
          executionState:"unknown", apiError:pod.apiError || "API 관측 만료", usage:{cpuCores:null,memoryBytes:null}};
        return pod;
      });
      const apiUnknown = instances.some(pod => pod.executionState === "unknown");
      return {...row, instances, executionState:apiUnknown ? "unknown" : row.executionState,
        connectionState:apiUnknown ? "unknown" : row.connectionState};
    });
    return {...snapshot, resources, nodes: stale ? null : snapshot.nodes,
      summary: {...snapshot.summary, physicalNodes:stale ? null : snapshot.summary.physicalNodes,
        observedInstances:stale ? null : snapshot.summary.observedInstances}};
  }
  function filterRows(rows, search, node) {
    return rows.filter(row => (!node || row.instances.some(p => p.node === node))
      && JSON.stringify([row.id, row.definition.spec.displayName, row.definition.spec.capabilities, row.connections])
        .toLocaleLowerCase().includes(search.toLocaleLowerCase()));
  }
  function placements(snapshot) {
    const grouped = new Map((snapshot.nodes || []).map(node => [node.name, []]));
    for (const row of snapshot.resources) for (const pod of row.instances) {
      if (!pod.node) continue;
      if (!grouped.has(pod.node)) grouped.set(pod.node, []);
      grouped.get(pod.node).push({id:row.id, ...pod});
    }
    return grouped;
  }
  const label = state => stateLabels[state] || state;
  const pair = (key, value) => `<dt>${esc(key)}</dt><dd>${esc(value)}</dd>`;
  const json = value => JSON.stringify(value, null, 2);
  const readiness = value => value === true ? "준비 완료" : value === false ? "준비 안 됨" : "확인 불가";
  function detail(row) {
    const spec = row.definition.spec;
    let html = `<dl>${pair("논리 ID", row.id)}${pair("기능", spec.capabilities.join(", "))}
      ${pair("모델 계약", json(spec.model))}${pair("예정 노드 조건", json(row.plannedNodeSelector || spec.nodeSelector))}
      ${pair("실행 참조", json(spec.runtimeRef.workloadRef))}${pair("Namespace", spec.runtimeRef.namespace)}
      ${pair("원하는 실행 수", row.desiredReplicas)}${pair("실행 상태", label(row.executionState))}
      ${pair("연결 상태", label(row.connectionState))}
      ${pair("연결 대상", row.connections.map(c => c.spec.targetDevice.name).join(", ") || "없음")}
      ${pair("관측 시각", row.observedAt)}${pair("조회 시도", row.attemptedAt)}</dl>`;
    if (row.observationError) html += `<p class="vd-error">${esc(row.observationError)}</p>`;
    if (!row.instances.length) html += `<p class="vd-muted">${row.observedInstances === 0 ? "현재 실행체는 없습니다. 등록 정의는 유지됩니다." : "실행체 존재와 자원 반환 여부를 확인할 수 없습니다."}</p>`;
    for (const pod of row.instances) {
      const runtime = pod.runtime, usage = pod.usage || {};
      html += `<div class="vd-instance"><dl>
        ${pair("Pod", pod.name)}${pair("Pod UID", pod.podUid)}${pair("실제 노드", pod.node)}
        ${pair("Pod 상태", pod.phase)}${pair("Pod 준비", readiness(pod.podReady))}
        ${pair("모델 준비", readiness(pod.modelReady))}${pair("실행", label(pod.executionState))}
        ${pair("API 관측", pod.apiObservedAt)}${pair("처리 중", runtime?.inFlight)}
        ${pair("성공 / 실패", runtime ? runtime.succeeded + " / " + runtime.failed : null)}
        ${pair("입력 거절", runtime?.rejected)}${pair("마지막 처리", runtime?.lastProcessedAt)}
        ${pair("부팅 ID", runtime?.bootId)}
        ${pair("CPU 실측", usage.cpuCores == null ? "N/A" : usage.cpuCores.toFixed(4) + " cores")}
        ${pair("메모리 실측", usage.memoryBytes == null ? "N/A" : (usage.memoryBytes / 1048576).toFixed(1) + " MiB")}
        ${pair("측정 범위", "메인 프로세스 · Pod 전체 사용량 아님")}
        ${pair("사용량 관측", usage.observedAt)}
        ${pair("requests / limits", json(pod.resources))}</dl>
        <p class="vd-muted">처리 건수는 부팅 단위입니다. 연결 대상 ID는 클라이언트가 선언한 값입니다.</p>
        ${pod.apiError || runtime?.error || pod.podReasons?.length ? `<p class="vd-error">${esc(pod.apiError || runtime?.error || pod.podReasons.join(", "))}</p>` : ""}
        ${usage.error ? `<p class="vd-error">${esc(usage.error)}</p>` : ""}
        <details><summary>마지막 성공 요청 ID·결과 증거</summary><pre>${esc(runtime?.lastSuccess ? json(runtime.lastSuccess) : "관측된 요청 없음")}</pre></details></div>`;
    }
    if (row.terminalPods?.length) html += `<details><summary>종료된 Pod 기록 (실행체 수 제외)</summary><pre>${esc(json(row.terminalPods))}</pre></details>`;
    return html;
  }
  if (typeof module !== "undefined") module.exports = {displayState, filterRows, placements, detail, ageFresh};
  if (typeof document === "undefined") return;
  const $ = id => document.getElementById(id);
  if (!$("vdList")) return;
  let snapshot = null, failed = false, selected = null, loading = false;
  function render() {
    const view = displayState(snapshot, failed);
    const openDetails = [...$("vdDetail").querySelectorAll("details")].map(item => item.open);
    const focusedId = document.activeElement?.dataset?.vdId;
    $("vdSummary").innerHTML = [["물리 노드",view.summary.physicalNodes],["가상 디바이스 정의",view.summary.definitions],
      ["관측 실행체",view.summary.observedInstances]].map(([name,value]) => `<div><span>${name}</span><strong>${value ?? "확인 불가"}</strong></div>`).join("");
    const nodeFilter = $("vdNodeFilter").value;
    const nodeNames = [...placements(view).keys()];
    if (nodeFilter && !nodeNames.includes(nodeFilter)) nodeNames.push(nodeFilter);
    $("vdNodeFilter").innerHTML = '<option value="">전체 노드</option>' + nodeNames.map(name =>
      `<option value="${esc(name)}"${name === nodeFilter ? " selected" : ""}>${esc(name)}</option>`).join("");
    $("vdPlacement").innerHTML = [...placements(view)].filter(([name]) => !nodeFilter || name === nodeFilter).map(([name,pods]) =>
      `<div class="vd-node"><strong>${esc(name)}</strong>${pods.length ? pods.map(p =>
        `<span>${esc(p.id)} · ${esc(label(p.executionState))}</span><small>${esc(p.name)}</small>`).join("") : `<span class="vd-muted">${view.resources.some(row => row.observedInstances === null) ? "실행체 배치 확인 불가" : "관측 실행체 없음"}</span>`}</div>`).join("")
      || '<p class="vd-muted">배치를 확인할 수 없습니다.</p>';
    const rows = filterRows(view.resources, $("vdSearch").value, nodeFilter);
    if (!rows.some(row => row.id === selected)) selected = rows[0]?.id;
    $("vdList").innerHTML = rows.map(row => `<button type="button" class="vd-item" data-vd-id="${esc(row.id)}" aria-pressed="${row.id === selected}">
      <strong>${esc(row.id)}</strong><span>${esc(row.definition.spec.displayName)}</span>
      <span class="vd-state">실행: ${esc(label(row.executionState))}</span><span class="vd-state">연결: ${esc(label(row.connectionState))}</span></button>`).join("")
      || '<p class="vd-muted">일치하는 등록 정의가 없습니다.</p>';
    const row = rows.find(row => row.id === selected);
    $("vdDetail").innerHTML = row ? detail(row) : '<p class="vd-muted">목록에서 항목을 선택하세요.</p>';
    $("vdDetail").querySelectorAll("details").forEach((item, index) => { item.open = Boolean(openDetails[index]); });
    if (focusedId) [...$("vdList").querySelectorAll("[data-vd-id]")].find(item => item.dataset.vdId === focusedId)?.focus();
    const expired = snapshot && !ageFresh(snapshot.observedAt, Date.now(), snapshot.maxAgeSeconds);
    $("vdObservation").textContent = failed || expired ? "확인 불가 · 최근 조회 실패 또는 관측 만료" :
      snapshot ? `관측 ${snapshot.observedAt}${snapshot.nodeError ? " · 노드 조회 확인 불가" : ""}` : "관측 대기";
  }
  async function refresh() {
    if (loading) return;
    loading = true; $("vdRefresh").disabled = true;
    try {
      const response = await fetch("/api/virtual-devices", {cache:"no-store", signal:AbortSignal.timeout(20000)});
      if (!response.ok) throw new Error("query failed");
      const data = await response.json();
      if (!Array.isArray(data.resources) || !data.summary) throw new Error("invalid observation");
      snapshot = data; failed = false;
    } catch (_) { failed = true; }
    finally { loading = false; $("vdRefresh").disabled = false; render(); }
  }
  $("vdRefresh").addEventListener("click", refresh);
  $("refreshButton")?.addEventListener("click", () => { if (document.body.dataset.dashboardPage === "virtual-devices") refresh(); });
  $("vdSearch").addEventListener("input", render);
  $("vdNodeFilter").addEventListener("change", render);
  $("vdList").addEventListener("click", event => {
    const button = event.target.closest("[data-vd-id]");
    if (button) { selected = button.dataset.vdId; render(); }
  });
  globalThis.onVirtualDevicesVisible = refresh;
  setInterval(() => {
    if (document.body.dataset.dashboardPage === "virtual-devices") refresh();
  }, 10000);
  // Expire a visible snapshot even while a request is stalled.
  setInterval(() => {
    if (snapshot && !ageFresh(snapshot.observedAt, Date.now(), snapshot.maxAgeSeconds)) render();
  }, 1000);
  render();
  if (document.body.dataset.dashboardPage === "virtual-devices") refresh();
})();
