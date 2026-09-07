(function operationsOverview(global) {
  "use strict";

  const state = {dashboard: null, dashboardError: null, twins: null, twinsError: null};
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[char]));
  const list = (value) => Array.isArray(value) ? value : [];
  const badge = (label, status = "unknown") => `<span class="workspace-badge" data-status="${escape(status)}">${escape(label)}</span>`;

  function observationTime(value) {
    const date = new Date(value);
    return value && Number.isFinite(date.getTime()) ? date.toLocaleString("ko-KR") : "관측 시각 없음";
  }

  function deviceNeedsAttention(device) {
    return !["available", "healthy"].includes(device.overall_status)
      || device.connection_state !== "connected" || device.telemetry_freshness !== "fresh";
  }

  // Counts preserve each API's authority. No new freshness thresholds or health inference.
  function buildOverviewModel(snapshot = {}) {
    const data = snapshot.dashboard;
    const twins = snapshot.twins;
    const errors = list(twins?.observation_errors);
    const devicesKnown = Boolean(data && !snapshot.dashboardError && !data.device_observation_error);
    const bindingsKnown = Boolean(twins && !snapshot.twinsError && errors.length === 0);
    const devices = list(data?.devices);
    const attention = devices.filter(deviceNeedsAttention);
    const names = new Set(attention.map((item) => item.name));
    const mappedNames = new Set(list(twins?.twins).map((twin) => twin.name));
    const impactKnown = bindingsKnown && attention.every((device) => mappedNames.has(device.name));
    const impacted = new Set(list(twins?.twins).filter((twin) => names.has(twin.name))
      .flatMap((twin) => list(twin.service_bindings).map((binding) => binding.service_id)).filter(Boolean));
    const nodes = list(data?.nodes);
    const servers = nodes.filter((node) => ["cloud_server", "server"].includes(node.node_type));
    const edgeNodes = nodes.filter((node) => !["cloud_server", "server"].includes(node.node_type));
    return {
      devicesKnown, bindingsKnown, attention,
      attentionCount: devicesKnown ? attention.length : null,
      impactCount: devicesKnown && impactKnown ? impacted.size : null,
      sourceCount: devicesKnown ? new Set(devices.map((device) => device.physical_device_id).filter(Boolean)).size : null,
      unknownSourceCount: devices.filter((device) => !device.physical_device_id).length,
      servers, edgeNodes,
      nodesKnown: Boolean(data && !snapshot.dashboardError),
      nodeAttention: nodes.filter((node) => !["healthy", "available"].includes(node.node_health)),
      bindingsByDevice: new Map(list(twins?.twins).map((twin) => [twin.name, list(twin.service_bindings)])),
    };
  }

  function metric(label, value, caption, status) {
    return `<div><span class="workspace-metric-label">${escape(label)}</span><strong class="workspace-metric-value" data-status="${escape(status || "")}">${escape(value ?? "—")}</strong><small>${escape(caption)}</small></div>`;
  }

  function attentionMarkup(model, snapshot) {
    const data = snapshot.dashboard;
    const parts = [];
    if (!data && !snapshot.dashboardError) return '<p class="empty">운영 상태를 확인하고 있습니다.</p>';
    if (!model.devicesKnown) {
      parts.push(`<article class="workspace-issue" data-status="unavailable"><div>${badge("관측 불가", "unavailable")}<h3>디바이스 상태를 확인할 수 없습니다</h3><p>${escape(snapshot.dashboardError || data?.device_observation_error || "응답 대기")}</p><small>관측 실패는 장비 없음이나 모든 장비 정상과 구분합니다.</small></div></article>`);
    }
    if (model.devicesKnown) {
      for (const device of model.attention.slice(0, 6)) {
        const bindings = model.bindingsByDevice.get(device.name) || [];
        const resources = [...new Set(list(device.latest_readings).map((reading) => reading.resource_name).filter(Boolean))];
        const label = device.physical_device_id || device.name;
        const freshness = {fresh: "최신 Event", stale: "입력 지연", no_events: "Event 없음"}[device.telemetry_freshness] || "입력 상태 미확인";
        parts.push(`<article class="workspace-issue" data-status="${escape(device.overall_status)}"><div>${badge(freshness, device.overall_status)}<h3>${escape(label)}${resources.length ? ` · ${escape(resources.join(", "))}` : ""}</h3><p>${escape(device.reason || "EdgeX 연결 상태와 최신 Event를 확인하세요.")}</p><small>영향 확인 대상: ${model.bindingsKnown && model.bindingsByDevice.has(device.name) ? escape(bindings.length ? [...new Set(bindings.map((binding) => binding.service_name || binding.service_id))].join(", ") : "연결 서비스 없음") : "서비스 연결 근거 미확인"}</small><small>최신 Event · ${escape(observationTime(device.latest_event_timestamp))}</small></div><button type="button" class="workspace-text-button" data-workspace-device="${escape(device.name)}" aria-label="${escape(label)} 관측 근거 보기">근거 ↗</button></article>`);
      }
      if (model.attention.length > 6) parts.push(`<button type="button" class="workspace-text-button" data-workspace-attention="true">점검 대상 ${model.attention.length}개 전체 보기 ↗</button>`);
    }
    if (!snapshot.dashboardError && model.nodeAttention.length) {
      parts.push(`<article class="workspace-issue"><div>${badge("노드 관측 확인", "degraded")}<h3>노드 ${model.nodeAttention.length}개 점검 필요</h3><p>센서 입력 상태와 별도로 노드·자원에서 확인하세요.</p></div><button type="button" class="workspace-text-button" data-workspace-page="nodes">노드 보기 ↗</button></article>`);
    }
    if (!parts.length) return `<div class="workspace-clear">${badge(data?.devices?.length ? "입력 점검 대상 없음" : "등록 디바이스 없음", "ready")}<p>${data?.devices?.length ? "현재 디바이스 관측에서 점검 대상이 없습니다. 서비스 결과는 별도로 확인하세요." : "EdgeX 등록 현황을 장비 연결·관리에서 확인하세요."}</p></div>`;
    return parts.join("");
  }

  function sourceRow(title, label, detail, status = "unknown") {
    return `<div class="workspace-source-row"><div><strong>${escape(title)}</strong>${badge(label, status)}</div><small>${escape(detail)}</small></div>`;
  }

  function render() {
    if (typeof document === "undefined") return;
    const setHtml = (id, html) => { const el = document.getElementById(id); if (el) el.innerHTML = html; };
    const model = buildOverviewModel(state);
    const data = state.dashboard;
    const fleet = document.getElementById("overviewFleetStatus");
    if (fleet) {
      fleet.textContent = !model.devicesKnown ? "관측 확인 필요" : model.attentionCount ? "입력 점검 필요" : model.nodeAttention.length ? "노드 점검 필요" : !list(data?.devices).length ? "등록 관측 없음" : "입력 관측 정상";
      fleet.dataset.status = !model.devicesKnown ? "unknown" : model.attentionCount || model.nodeAttention.length ? "degraded" : "available";
    }
    const nodeCount = model.nodesKnown ? `${model.edgeNodes.filter((node) => ["healthy", "available"].includes(node.node_health)).length} / ${model.edgeNodes.length}` : null;
    setHtml("workspaceSummary", [
      metric("우선 점검 디바이스", model.attentionCount, model.devicesKnown ? "연결·최신 Event 기준" : data ? "관측 불가" : "관측 대기", model.attentionCount ? "degraded" : ""),
      metric("영향 확인 서비스", model.impactCount, model.impactCount !== null ? "중복 제외 · 실행 실패와 별개" : "바인딩 관측 대기 / 연결 근거 확인"),
      metric("물리 source", model.sourceCount, model.unknownSourceCount ? `source 미지정 등록 ${model.unknownSourceCount}개 별도` : "등록 Device 수와 구분"),
      metric("현장 엣지 노드", nodeCount, model.nodesKnown ? "정상 관측 / 전체 노드" : "관측 대기 / 확인 필요"),
    ].join(""));
    setHtml("workspaceAttentionList", attentionMarkup(model, state));
    setHtml("workspaceAttentionCount", model.attentionCount === null ? "관측 확인 필요" : `디바이스 ${model.attentionCount}개`);
    const errors = list(state.twins?.observation_errors);
    const twinsUnavailable = !state.twins || state.twinsError || errors.some((error) => /EdgeX/i.test(error));
    const sortedTwins = [...list(state.twins?.twins)].sort((left, right) =>
      Number(right.health !== "ready") - Number(left.health !== "ready")
      || Number(Boolean(right.service_bindings?.length)) - Number(Boolean(left.service_bindings?.length))
      || String(left.name).localeCompare(String(right.name), "ko"));
    const seenSources = new Set();
    const preview = sortedTwins.filter((twin) => {
      if (seenSources.has(twin.physical_device_id)) return false;
      seenSources.add(twin.physical_device_id);
      return true;
    }).slice(0, 4);
    for (const twin of sortedTwins) {
      if (preview.length >= 4) break;
      if (!preview.includes(twin)) preview.push(twin);
    }
    let connectionHtml = global.EdgeDeviceTwins?.connectionCards(preview, {bindingsKnown: model.bindingsKnown}) || "";
    if (twinsUnavailable) connectionHtml = `<p class="workspace-inline-notice">${state.twinsError || errors.length ? "연결 관측 불가. 이전 성공 데이터가 있으면 참고용으로 표시합니다." : "EdgeX 관측 트윈을 확인하고 있습니다."}</p>${state.twins ? connectionHtml : ""}`;
    else if (!model.bindingsKnown) connectionHtml = `<p class="workspace-inline-notice">서비스 관측이 불완전합니다. 연결 없음으로 판단하지 마세요.</p>${connectionHtml}`;
    else if (!sortedTwins.length) connectionHtml = '<p class="empty">source identity가 있는 관측 트윈이 없습니다. 등록 디바이스 목록을 확인하세요.</p>';
    setHtml("workspaceConnections", connectionHtml);
    const resourceError = data?.resource_profiles?.observation_error;
    setHtml("workspaceSources", [
      sourceRow("디바이스 · EdgeX", model.devicesKnown ? "응답 수신" : "확인 필요", data?.device_observation_error || "Metadata / Core Data", model.devicesKnown ? "ready" : "unknown"),
      sourceRow("노드 관측", model.nodesKnown && list(data.nodes).length ? "sample 수신" : "관측 없음", "Prometheus node snapshot · 노드 상세에서 시각 확인", model.nodesKnown && list(data.nodes).length ? "ready" : "unknown"),
      sourceRow("서비스 자원", data && !state.dashboardError && !resourceError ? "응답 수신" : "확인 필요", resourceError || "Kubernetes / Prometheus 자원 관측", data && !state.dashboardError && !resourceError ? "ready" : "unknown"),
      sourceRow("서비스 연결", model.bindingsKnown ? "응답 수신" : "확인 필요", state.twins ? `관측 시각 · ${observationTime(state.twins.generated_at)}` : "EdgeX 트윈 / 서비스 바인딩", model.bindingsKnown ? "ready" : "unknown"),
    ].join(""));
    setHtml("workspaceNodes", sourceRow("현장 엣지 노드", model.nodesKnown ? `${model.edgeNodes.length}개` : "—", "Jetson · Raspberry Pi 등 현장 노드")
      + sourceRow("엣지 AI 서버", model.nodesKnown ? `${model.servers.length}개` : "—", "중앙 서버 관측"));
    const notice = document.getElementById("dashboardObservationNotice");
    if (notice) {
      notice.hidden = !state.dashboardError;
      notice.textContent = state.dashboardError ? `대시보드 관측 실패 · ${state.dashboardError}${data ? ` · 아래는 이전 관측 (${observationTime(data.generated_at)})입니다.` : " · 응답을 다시 기다리고 있습니다."}` : "";
    }
  }

  global.EdgeOperationsOverview = {
    updateDashboard(data, error = null) { if (data) state.dashboard = data; state.dashboardError = error; render(); },
    updateTwins(data, error = null) { if (data) state.twins = data; state.twinsError = error; render(); },
  };
  if (typeof document !== "undefined") {
    document.addEventListener("click", (event) => {
      const target = event.target.closest?.("[data-workspace-page], [data-workspace-attention]");
      if (!target) return;
      const page = target.dataset.workspacePage || "connections";
      global.showDashboardPage?.(page);
      global.location.hash = page;
      if (target.dataset.workspaceAttention) global.EdgeDeviceTwins?.setHealthFilter("attention");
    });
  }
  if (typeof module !== "undefined") module.exports = {buildOverviewModel, deviceNeedsAttention, attentionMarkup, observationTime};
})(typeof globalThis !== "undefined" ? globalThis : window);
