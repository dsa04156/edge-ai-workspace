const state = {
  data: null,
  refreshMs: 5000,
  selectedDeviceName: null,
  selectedNodeName: null,
  selectedNodeFilterValues: [],
  selectedTopologyService: null,
  chat: {
    loading: false,
    messages: [],
  },
};

const $ = (id) => document.getElementById(id);



function pct(value) {
  return `${Math.round((value || 0) * 100)}%`;
}

function oneDecimal(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "0";
  return numeric.toLocaleString(undefined, { maximumFractionDigits: 1 });
}

function threeDecimal(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "0";
  return numeric.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

function ratio(value) {
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return 0;
  return Math.max(0, Math.min(1, numeric));
}

function escapeHtml(value) {
  return text(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function statusPill(value) {
  const safe = text(value, "unknown");
  return `<span class="pill ${escapeHtml(safe)}">${escapeHtml(safe)}</span>`;
}

function boolText(value) {
  return value ? "true" : "false";
}

function text(value, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function timestampAge(value) {
  if (!value) return "이벤트 없음";
  const timestamp = new Date(value).getTime();
  if (!Number.isFinite(timestamp)) return text(value);
  const seconds = Math.max(0, Math.floor((Date.now() - timestamp) / 1000));
  const minutes = Math.floor(seconds / 60);
  if (minutes === 0) return `${seconds}초 전`;
  return `${minutes}분 ${seconds % 60}초 전`;
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
}

function setPercentStyle(id, value) {
  const el = $(id);
  if (el) el.style.width = pct(ratio(value));
}

function setStatusRing(id, parts) {
  const el = $(id);
  if (!el) return;
  el.style.setProperty("--ok", pct(parts.ok));
  el.style.setProperty("--warn", pct(parts.warn));
  el.style.setProperty("--bad", pct(parts.bad));
  el.style.setProperty("--unknown", pct(parts.unknown));
}


function displayValue(value, fallback = "데이터 없음") {
  if (value === null || value === undefined || value === "") return fallback;
  if (typeof value === "boolean") return value ? "true" : "false";
  return String(value);
}

function isRawInstance(value) {
  const safe = text(value, "");
  return /^\d{1,3}(\.\d{1,3}){3}(:\d+)?$/.test(safe) || /^[\w.-]+:\d+$/.test(safe);
}

function cleanNodeLabel(value, fallback = "node pending") {
  const safe = text(value, fallback).trim();
  if (isRawInstance(safe)) return fallback;
  return safe;
}

function nodeDisplayName(node, index) {
  const candidates = [node?.hostname, node?.name, node?.node_name, node?.label]
    .map((value) => text(value, "").trim())
    .filter(Boolean);
  const readableLabel = candidates.find((value) => !isRawInstance(value));
  return cleanNodeLabel(readableLabel, `Unmapped node ${index + 1}`);
}

function nodeFilterValues(node, index) {
  const values = [nodeDisplayName(node, index), node?.hostname, node?.name, node?.node_name, node?.label]
    .map((value) => text(value, "").trim())
    .filter(Boolean)
    .flatMap((value) => [value, cleanNodeLabel(value, value)]);
  return [...new Set(values)];
}

function deviceStatus(device) {
  if (["available", "degraded", "unavailable"].includes(device?.overall_status)) return device.overall_status;
  const adminState = text(device?.admin_state, "UNKNOWN").toUpperCase();
  const operatingState = text(device?.operating_state, "UNKNOWN").toUpperCase();
  if (adminState === "LOCKED" || operatingState === "DOWN" || device?.connection_state === "disconnected") return "unavailable";
  if (adminState === "UNKNOWN" || operatingState === "UNKNOWN" || device?.connection_state === "unknown") return "degraded";
  if (operatingState === "UP" && device?.connection_state === "connected" && device?.telemetry_freshness === "fresh") return "available";
  return "degraded";
}

function deviceReason(device) {
  if (device?.reason) return device.reason;
  const status = deviceStatus(device);
  if (status === "unavailable") return `${text(device?.admin_state, "UNKNOWN")} / ${text(device?.operating_state, "UNKNOWN")} · ${text(device?.connection_state, "unknown")}`;
  if (status === "available") return "EdgeX Device Service가 연결되어 있고 최신 Core Data 이벤트가 fresh입니다.";
  if (text(device?.operating_state, "UNKNOWN").toUpperCase() === "UNKNOWN" || device?.connection_state === "unknown") return "EdgeX operating/connection state를 확인할 수 없습니다.";
  return `Core Data event freshness: ${text(device?.telemetry_freshness, "no_events")}`;
}

function isOperationalDevice(device) {
  return deviceStatus(device) === "available";
}

function sortDevicesStatusFirst(devices = []) {
  return [...devices].sort((left, right) => {
    const statusDelta = Number(isOperationalDevice(right)) - Number(isOperationalDevice(left));
    if (statusDelta !== 0) return statusDelta;
    return text(left?.name, "").localeCompare(text(right?.name, ""));
  });
}

function deviceNodeLabel(device) {
  return cleanNodeLabel(device?.node_name || device?.nodeName, "미할당");
}

function renderConnectionBadge(device) {
  const connection = text(device?.connection_state, "unknown");
  return `<span class="pill connection-${escapeHtml(connection)}">${escapeHtml(connection)}</span>`;
}

function deviceMatchesNodeFilter(device) {
  if (!state.selectedNodeName) return true;
  const labels = [text(device?.node_name, "").trim(), text(device?.nodeName, "").trim(), deviceNodeLabel(device)].filter(Boolean);
  return labels.some((label) => state.selectedNodeFilterValues.includes(label));
}

function filteredDevices(devices = []) {
  return sortDevicesStatusFirst(devices.filter((device) => deviceMatchesNodeFilter(device)));
}

function renderDeviceFilterSummary(totalCount, visibleCount) {
  const label = $("deviceFilterLabel");
  const clear = $("clearNodeFilter");
  if (label) {
    const parts = [];
    if (state.selectedNodeName) parts.push(`node ${state.selectedNodeName}`);
    label.textContent = parts.length ? `${visibleCount}/${totalCount} - ${parts.join(" / ")}` : "EdgeX Devices";
  }
  if (clear) clear.hidden = !state.selectedNodeName;
}


function refreshSelectedNodeFilterValues(nodes = []) {
  if (!state.selectedNodeName) return;
  const selected = nodes
    .map((node, index) => ({ node, index, displayName: nodeDisplayName(node, index) }))
    .find((item) => item.displayName === state.selectedNodeName);
  if (selected) state.selectedNodeFilterValues = nodeFilterValues(selected.node, selected.index);
}

function explainDeviceRules(device) {
  const rules = [{
    id: "EdgeX Owner",
    title: `${text(device.device_service_name, "unknown service")} · ${text(device.profile_name, "unknown profile")}`,
    text: `이 source는 EdgeX Device Service ${text(device.device_service_name, "unknown")}가 profile ${text(device.profile_name, "unknown")} 및 protocol ${Array.isArray(device.protocol_names) && device.protocol_names.length ? device.protocol_names.join(", ") : "unknown"}로 소유합니다. Core Data sourceName: ${[...new Set((device.latest_readings || []).map((reading) => reading.source_name).filter(Boolean))].join(", ") || "event 없음"}.`,
  }];
  const status = deviceStatus(device);
  if (status === "available") {
    rules.push({ id: "Available", title: "service connected and event fresh", text: "operatingState=UP이고 EdgeX Device Service가 연결되어 있으며 최신 Core Data event가 freshness 기준을 만족합니다." });
  } else if (status === "unavailable") {
    rules.push({ id: "Unavailable", title: "device locked or disconnected", text: "adminState=LOCKED, operatingState=DOWN 또는 connectionState=disconnected 상태입니다. EdgeX Device Service와 장치 연결을 확인합니다." });
  } else if (device.telemetry_freshness === "stale") {
    rules.push({ id: "Event Stale", title: "latest Core Data event is stale", text: "EdgeX Core Data의 최신 event가 freshness 기준을 벗어나 degraded로 표시됩니다." });
  } else if (device.telemetry_freshness === "no_events") {
    rules.push({ id: "No Events", title: "Core Data event not observed", text: "이 device의 Core Data event가 아직 없어 degraded로 표시됩니다." });
  } else {
    rules.push({ id: "Unknown", title: "EdgeX state unknown", text: "operating state 또는 connection state를 확인할 수 없어 degraded로 표시됩니다." });
  }
  return rules;
}

const KPI_EXPLANATIONS = {
  active_node_count: "현재 사용 가능한 node 수입니다.",
  registered_device_count: "EdgeX Core Metadata에 등록된 device 수입니다.",
  available_device_count: "EdgeX state와 Core Data event freshness 기준으로 available인 device 수입니다.",
  degraded_device_count: "EdgeX source가 UP이지만 event가 없거나 stale이거나 state가 unknown인 device 수입니다.",
  unavailable_device_count: "adminState=LOCKED 또는 operatingState=DOWN인 device 수입니다.",
  edgex_connected_device_count: "EdgeX connection_state가 connected인 device 수입니다.",
  edgex_connection_ratio: "connected EdgeX device 수 / 전체 registered device 수입니다.",
  edgex_operating_up_count: "Core Metadata operatingState=UP device 수입니다.",
  edgex_operating_down_count: "Core Metadata operatingState=DOWN device 수입니다.",
  edgex_operating_unknown_count: "operatingState가 UP/DOWN이 아닌 device 수입니다.",
  edgex_admin_unlocked_count: "Core Metadata adminState=UNLOCKED device 수입니다.",
  edgex_admin_locked_count: "Core Metadata adminState=LOCKED device 수입니다.",
  device_service_available_count: "operatingState=UP인 EdgeX Device Service device 수입니다.",
  device_service_availability_ratio: "Device Service available device 수 / 전체 registered device 수입니다.",
  core_data_event_device_count: "Core Data event가 하나 이상 관측된 device 수입니다.",
  fresh_core_data_event_device_count: "최신 Core Data event가 fresh인 device 수입니다.",
  stale_core_data_event_device_count: "최신 Core Data event가 stale인 device 수입니다.",
  core_data_freshness_ratio: "fresh Core Data event device 수 / 전체 registered device 수입니다.",
  operator_focus_count: "운영자가 먼저 볼 degraded/unavailable physical device 수입니다.",
  service_resource_profile_count: "현재 Running Pod를 서비스 단위로 묶어 만든 자원 요구량 프로파일 수입니다.",
  service_resource_profile_pod_count: "프로파일링 대상 Running Pod 수입니다.",
  service_resource_request_cpu_cores: "실행 서비스들이 Kubernetes requests.cpu로 선언한 CPU core 합계입니다.",
  service_resource_request_memory_mib: "실행 서비스들이 Kubernetes requests.memory로 선언한 memory MiB 합계입니다.",
  service_resource_current_cpu_usage_cores: "전체 노드 사용량이 아니라 Prometheus/cAdvisor에서 가져온 서비스 Pod 컨테이너 CPU 사용량(core) 합계입니다.",
  service_resource_current_memory_working_set_mib: "전체 노드 메모리가 아니라 Prometheus/cAdvisor에서 가져온 서비스 Pod 컨테이너 memory working set(MiB) 합계입니다.",
  service_resource_usage_coverage_ratio: "Prometheus/cAdvisor current usage 샘플이 붙은 서비스 Pod 컨테이너 비율입니다.",
  service_resource_limit_gpu_units: "실행 서비스들이 limits의 GPU 리소스로 선언한 GPU 단위 합계입니다.",
  service_resource_profile_container_count: "서비스 프로파일에 포함된 Running Pod container 수입니다.",
  service_resource_fully_declared_profile_count: "requests/limits가 모두 선언된 서비스 프로파일 수입니다.",
  service_resource_partially_declared_profile_count: "requests/limits가 일부 또는 전체 누락된 서비스 프로파일 수입니다.",
};

function explainKpi(key, kpis = {}) {
  const value = Object.prototype.hasOwnProperty.call(kpis, key)
    ? kpis[key]
    : "현재 API payload에 없음";
  return {
    key,
    value,
    text: KPI_EXPLANATIONS[key] || "현재 dashboard에 정의된 KPI 설명이 없습니다.",
  };
}

function issueExplanation(alert) {
  if (!alert) return ["선택한 Issue 항목 데이터가 없습니다."];
  if (alert.kind === "node") {
    return ["node-exporter/Prometheus 관측, Kubernetes Ready, edgecore/cloudcore 연결을 확인합니다."];
  }
  const device = alert.device || {};
  const messages = [];
  if (device.connection_state === "disconnected") messages.push(`EdgeX Device Service ${text(device.device_service_name, "unknown")}와 source 연결을 확인합니다.`);
  if (device.telemetry_freshness === "stale") messages.push("EdgeX Core Data 최신 event가 stale입니다. Device Service의 event 발행 경로를 확인합니다.");
  if (device.telemetry_freshness === "no_events") messages.push("EdgeX Core Data event가 없습니다. profile의 device resource와 sourceName을 확인합니다.");
  if (!messages.length) messages.push(deviceReason(device));
  return messages;
}

function renderRuleList(rules) {
  return `<ul class="explain-rules">${rules
    .map((rule) => `<li><strong>${escapeHtml(rule.id)} · ${escapeHtml(rule.title)}</strong><p>${escapeHtml(rule.text)}</p></li>`)
    .join("")}</ul>`;
}

function renderExplainFields(fields) {
  return `<dl class="explain-fields">${fields
    .map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(displayValue(value, "현재 API payload에 없음"))}</dd></div>`)
    .join("")}</dl>`;
}

function renderDeviceFactList(fields) {
  return `<dl class="explain-facts">${fields
    .map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(displayValue(value, "현재 API payload에 없음"))}</dd></div>`)
    .join("")}</dl>`;
}

function renderDeviceReasonList(rules) {
  return `<ul class="explain-reasons">${rules
    .map((rule) => `<li><strong>${escapeHtml(rule.title)}</strong><p>${escapeHtml(rule.text)}</p></li>`)
    .join("")}</ul>`;
}


function numericValue(value) {
  if (value === null || value === undefined || value === "") return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function formatChartTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function renderTelemetryChart(points = []) {
  const numericPoints = points
    .map((point) => ({
      ...point,
      at: new Date(point.timestamp).getTime(),
      numeric: numericValue(point.value),
      property: point.source_name && point.resource_name ? `${point.source_name}.${point.resource_name}` : point.resource_name || point.source_name || point.property || "value",
    }))
    .filter((point) => Number.isFinite(point.at) && point.numeric !== null)
    .sort((a, b) => a.at - b.at);

  if (!points.length) {
    return `<div class="telemetry-chart empty">Core Data latest readings가 없습니다.</div>`;
  }

  if (!numericPoints.length) {
    const recent = points.slice(-8).reverse();
    return `
      <div class="telemetry-chart">
        <div class="chart-head"><strong>Core Data readings</strong><span>non-numeric values</span></div>
        <ul class="telemetry-values">${recent
          .map((point) => `<li><span>${escapeHtml(formatChartTime(point.timestamp))}</span><strong>${escapeHtml(text(point.resource_name || point.source_name || point.property, "value"))}=${escapeHtml(text(point.value))}</strong></li>`)
          .join("")}</ul>
      </div>
    `;
  }

  const width = 560;
  const height = 230;
  const pad = { left: 54, right: 22, top: 24, bottom: 42 };
  const minTime = Math.min(...numericPoints.map((point) => point.at));
  const maxTime = Math.max(...numericPoints.map((point) => point.at));
  const minValue = Math.min(...numericPoints.map((point) => point.numeric));
  const maxValue = Math.max(...numericPoints.map((point) => point.numeric));
  const timeSpan = Math.max(1, maxTime - minTime);
  const valueSpan = Math.max(1, maxValue - minValue);
  const x = (time) => pad.left + ((time - minTime) / timeSpan) * (width - pad.left - pad.right);
  const y = (value) => height - pad.bottom - ((value - minValue) / valueSpan) * (height - pad.top - pad.bottom);
  const baselineY = height - pad.bottom;
  const colors = ["#087c8f", "#0f8b5f", "#b7791f", "#c2410c", "#365fd8", "#7c3aed", "#be185d", "#4d7c0f"];
  const grouped = numericPoints.reduce((acc, point) => {
    acc[point.property] = acc[point.property] || [];
    acc[point.property].push(point);
    return acc;
  }, {});
  const series = Object.entries(grouped).slice(0, 8);
  const latestPoint = numericPoints.at(-1);
  const avgValue = numericPoints.reduce((sum, point) => sum + point.numeric, 0) / numericPoints.length;
  const yTicks = [maxValue, minValue + valueSpan * 0.66, minValue + valueSpan * 0.33, minValue];
  const xTicks = [minTime, minTime + timeSpan / 2, maxTime];
  const summary = [
    ["Latest", `${latestPoint.property} ${latestPoint.numeric.toFixed(2)}`],
    ["Range", `${minValue.toFixed(2)} - ${maxValue.toFixed(2)}`],
    ["Avg", avgValue.toFixed(2)],
    ["Series", String(series.length)],
  ];
  const summaryCards = summary
    .map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`)
    .join("");
  const gridlines = yTicks
    .map((tick) => {
      const tickY = y(tick);
      return `<g class="chart-gridline"><line x1="${pad.left}" y1="${tickY.toFixed(1)}" x2="${width - pad.right}" y2="${tickY.toFixed(1)}" /><text class="chart-tick" x="10" y="${(tickY + 3).toFixed(1)}">${escapeHtml(tick.toFixed(2))}</text></g>`;
    })
    .join("");
  const timeTicks = xTicks
    .map((tick) => `<text class="chart-time-tick" x="${x(tick).toFixed(1)}" y="${height - 14}" text-anchor="middle">${escapeHtml(formatChartTime(tick))}</text>`)
    .join("");
  const polylines = series
    .map(([property, values], index) => {
      const coordinates = values.map((point) => `${x(point.at).toFixed(1)},${y(point.numeric).toFixed(1)}`).join(" ");
      const areaCoordinates = [
        `${x(values[0].at).toFixed(1)},${baselineY.toFixed(1)}`,
        ...values.map((point) => `${x(point.at).toFixed(1)},${y(point.numeric).toFixed(1)}`),
        `${x(values.at(-1).at).toFixed(1)},${baselineY.toFixed(1)}`,
      ].join(" ");
      return `
        <polygon class="chart-area" points="${areaCoordinates}" fill="${colors[index]}" />
        <polyline class="chart-line" points="${coordinates}" fill="none" stroke="${colors[index]}" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" />
      `;
    })
    .join("");
  const dots = series
    .flatMap(([property, values], index) => {
      const recent = values.slice(-18).map((point) => `<circle class="chart-dot" cx="${x(point.at).toFixed(1)}" cy="${y(point.numeric).toFixed(1)}" r="2.3" fill="${colors[index]}" />`);
      const latest = values.at(-1);
      recent.push(`<circle class="chart-latest-marker" cx="${x(latest.at).toFixed(1)}" cy="${y(latest.numeric).toFixed(1)}" r="5.4" fill="${colors[index]}" />`);
      return recent;
    })
    .join("");
  const legend = series
    .map(([property, values], index) => `<span><i style="background:${colors[index]}"></i><b>${escapeHtml(property)}</b><em>${escapeHtml(values.at(-1).numeric.toFixed(2))}</em></span>`)
    .join("");

  return `
    <div class="telemetry-chart">
      <div class="chart-head"><strong>Core Data latest source readings</strong><span>${numericPoints.length} readings · ${escapeHtml(formatChartTime(numericPoints[0].timestamp))}</span></div>
      <div class="telemetry-summary-strip">${summaryCards}</div>
      <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Core Data latest source readings chart">
        <rect class="chart-plot-bg" x="${pad.left}" y="${pad.top}" width="${width - pad.left - pad.right}" height="${height - pad.top - pad.bottom}" rx="6" />
        ${gridlines}
        <line class="chart-axis" x1="${pad.left}" y1="${baselineY}" x2="${width - pad.right}" y2="${baselineY}" />
        <line class="chart-axis" x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${baselineY}" />
        ${polylines}
        ${dots}
        ${timeTicks}
      </svg>
      <div class="chart-legend">${legend}</div>
    </div>
  `;
}

function showDeviceExplanation(device) {
  const panel = $("explainPanel");
  if (!panel || !device) return;
  state.selectedDeviceName = device.name;
  const status = deviceStatus(device);
  panel.innerHTML = `
    <div class="explain-header">
      <span class="explain-badge">EdgeX Device</span>
      <strong>${escapeHtml(displayValue(device.name))}</strong>
    </div>
    <div class="explain-status-strip">
      <div>
        <span>Status</span>
        <strong>${escapeHtml(status)}</strong>
      </div>
      <div>
        <span>Connection</span>
        <strong>${escapeHtml(text(device.connection_state, "unknown"))}</strong>
      </div>
      <div>
        <span>Event freshness</span>
        <strong>${escapeHtml(text(device.telemetry_freshness, "no_events"))}</strong>
      </div>
    </div>
    ${renderDeviceFactList([
      ["source", device.source],
      ["EdgeX Device Service", device.device_service_name],
      ["Device Service available", boolText(device.device_service_available)],
      ["profile", device.profile_name],
      ["protocols", Array.isArray(device.protocol_names) ? device.protocol_names.join(", ") : null],
      ["admin / operating", `${text(device.admin_state, "UNKNOWN")} / ${text(device.operating_state, "UNKNOWN")}`],
      ["Core Data sourceName", [...new Set((device.latest_readings || []).map((reading) => reading.source_name).filter(Boolean))].join(", ") || "event 없음"],
      ["latest Core Data event", device.latest_event_timestamp || "event 없음"],
      ["event age", timestampAge(device.latest_event_timestamp)],
      ["optional node placement", deviceNodeLabel(device)],
    ])}
    <div id="telemetryChart">${renderTelemetryChart(device.latest_readings || [])}</div>
    ${renderDeviceReasonList(explainDeviceRules(device))}
  `;
}

function kpiKeysForCard(key) {
  const groups = {
    registered_device_count: ["registered_device_count", "available_device_count"],
    core_data_freshness_ratio: ["fresh_core_data_event_device_count", "core_data_freshness_ratio"],
    device_service_availability_ratio: ["device_service_available_count", "device_service_availability_ratio"],
    service_resource_current_cpu_usage_cores: ["service_resource_current_cpu_usage_cores", "service_resource_request_cpu_cores"],
    service_resource_current_memory_working_set_mib: ["service_resource_current_memory_working_set_mib", "service_resource_request_memory_mib"],
    service_resource_usage_coverage_ratio: ["service_resource_profile_container_count", "service_resource_usage_coverage_ratio"],
  };
  return groups[key] || [key];
}

function showKpiExplanation(key) {
  const panel = $("explainPanel");
  if (!panel) return;
  const kpis = state.data?.kpis || {};
  const explanations = kpiKeysForCard(key).map((item) => explainKpi(item, kpis));
  panel.innerHTML = `
    <div class="explain-header">
      <span class="explain-badge">KPI Explain</span>
      <strong>${escapeHtml(key)}</strong>
    </div>
    ${renderExplainFields(explanations.flatMap((explanation) => [
      [`${explanation.key} 현재 값`, explanation.value],
    ]))}
    <ul class="explain-rules">${explanations
      .map((explanation) => `<li><strong>${escapeHtml(explanation.key)}</strong><p>${escapeHtml(explanation.text)}</p></li>`)
      .join("")}</ul>
  `;
}

function showIssueExplanation(index) {
  const panel = $("explainPanel");
  if (!panel) return;
  const alert = state.alerts[index];
  panel.innerHTML = `
    <div class="explain-header">
      <span class="explain-badge">Issue / Focus Explain</span>
      <strong>${escapeHtml(alert?.title || "Issue 항목")}</strong>
    </div>
    <p class="explain-text">${escapeHtml(alert?.text || "데이터 없음")}</p>
    <ul class="explain-rules">${issueExplanation(alert)
      .map((message) => `<li><p>${escapeHtml(message)}</p></li>`)
      .join("")}</ul>
  `;
}

async function loadDashboard() {
  const response = await fetch("/state/dashboard", { cache: "no-store" });
  if (!response.ok) throw new Error(`dashboard api failed: ${response.status}`);
  state.data = await response.json();
  render();
}

function renderChatTranscript() {
  const transcript = $("chatTranscript");
  if (!transcript) return;
  if (!state.chat.messages.length) {
    transcript.innerHTML = `<div class="chat-empty">상태 원인, 점검 순서, KPI 의미를 질문하세요.</div>`;
    return;
  }
  transcript.innerHTML = state.chat.messages
    .map((message) => {
      const meta = message.meta || [];
      const metaHtml = meta.length ? `<div class="chat-meta">${meta.map((item) => `<span class="pill">${escapeHtml(item)}</span>`).join("")}</div>` : "";
      return `
        <article class="chat-message ${escapeHtml(message.role)} ${message.loading ? "loading" : ""}">
          <span>${escapeHtml(message.label)}</span>
          <p>${escapeHtml(message.text)}</p>
          ${metaHtml}
        </article>
      `;
    })
    .join("");
  transcript.scrollTop = transcript.scrollHeight;
}

function setChatLoading(loading) {
  state.chat.loading = loading;
  const submit = $("operatorChatSubmit");
  const input = $("operatorChatInput");
  if (submit) submit.disabled = loading;
  if (input) input.disabled = loading;
  setText("chatStatus", loading ? "Qwen 응답 대기 중" : "읽기 전용 모드");
}

function chatResponseMeta(payload) {
  const meta = [text(payload.assistant_name, "qwen operator"), `mode=${text(payload.mode, "read_only")}`, `model=${text(payload.model, "unknown")}`, `upstream=${text(payload.upstream_status, "unknown")}`];
  if (Array.isArray(payload.source_endpoints) && payload.source_endpoints.length) meta.push(`${payload.source_endpoints.length} source endpoints`);
  if (Array.isArray(payload.guardrails) && payload.guardrails.length) meta.push(`${payload.guardrails.length} guardrails`);
  return meta;
}

async function submitOperatorChat(message) {
  state.chat.messages.push({ role: "user", label: "운영자", text: message });
  const loadingMessage = { role: "assistant", label: "Qwen 읽기 전용", text: "현재 dashboard 상태를 기준으로 답변을 생성 중입니다.", loading: true };
  state.chat.messages.push(loadingMessage);
  renderChatTranscript();
  setChatLoading(true);
  try {
    const response = await fetch("/state/operator-chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    let payload = {};
    try {
      payload = await response.json();
    } catch (error) {
      payload = {};
    }
    if (!response.ok) {
      const detail = payload.detail || `operator chat api failed: ${response.status}`;
      throw new Error(Array.isArray(detail) ? detail.map((item) => item.msg || item.type || "request error").join(", ") : detail);
    }
    Object.assign(loadingMessage, {
      role: "assistant",
      label: "Qwen 읽기 전용",
      text: text(payload.answer, "응답이 비어 있습니다."),
      loading: false,
      meta: chatResponseMeta(payload),
    });
  } catch (error) {
    Object.assign(loadingMessage, {
      role: "error",
      label: "채팅 오류",
      text: error.message || "Qwen chat 요청에 실패했습니다.",
      loading: false,
    });
  } finally {
    setChatLoading(false);
    renderChatTranscript();
  }
}

function render() {
  const data = state.data;
  const kpis = data.kpis || {};
  const devices = data.devices || [];
  const nodes = data.nodes || [];
  const resourceState = data.resource_profiles || {};
  const deviceObservationFailed = deviceObservationUnavailable(data);
  const deviceObservationError = text(
    data.device_observation_error,
    "EdgeX device 관측 불가",
  );
  const telemetryEnabled = Number(kpis.registered_device_count) || devices.length;
  const freshTelemetry = Number(kpis.fresh_core_data_event_device_count) || devices.filter((device) => device.telemetry_freshness === "fresh").length;
  const unavailableDevices = devices.filter((device) => deviceStatus(device) === "unavailable").length;
  const degradedDevices = devices.filter((device) => deviceStatus(device) === "degraded").length;
  const boundDevices = Number(kpis.device_service_available_count) || 0;
  const registeredDevices = Number(kpis.registered_device_count) || devices.length;
  const profiledContainers = Number(kpis.service_resource_profile_container_count) || 0;
  const sampledContainers = Math.round(profiledContainers * ratio(kpis.service_resource_usage_coverage_ratio));
  setText("updatedAt", `갱신 ${new Date(data.generated_at).toLocaleString()}`);
  setText("activeNodeCount", text(kpis.active_node_count, 0));
  setText("nodeRatio", `${pct(kpis.node_online_ratio)} online`);
  setText("deviceCount", deviceObservationFailed ? "관측 불가" : text(kpis.registered_device_count, 0));
  setText("deviceHealthRatio", deviceObservationFailed ? "EdgeX Core Metadata 연결 필요" : `${pct(kpis.device_service_availability_ratio)} service available · ${text(kpis.available_device_count, 0)} data available`);
  setText("telemetryFreshnessRatio", deviceObservationFailed ? "관측 불가" : pct(kpis.core_data_freshness_ratio));
  setText("telemetryFreshnessCaption", deviceObservationFailed ? deviceObservationError : `${freshTelemetry}/${telemetryEnabled}개 Core Data event fresh`);
  setText("resourceProfileCount", text(kpis.service_resource_profile_count, 0));
  setText("placementFitCaption", `${text(kpis.service_resource_profile_pod_count, 0)}개 pod · ${text(kpis.service_resource_partially_declared_profile_count, 0)}개 spec 누락`);
  setText("serviceCpuUsage", threeDecimal(kpis.service_resource_current_cpu_usage_cores));
  setText("serviceCpuUsageCaption", `${threeDecimal(kpis.service_resource_request_cpu_cores)} core request`);
  setText("serviceMemoryUsage", `${oneDecimal(kpis.service_resource_current_memory_working_set_mib)} MiB`);
  setText("serviceMemoryUsageCaption", `${oneDecimal(kpis.service_resource_request_memory_mib)} MiB request`);
  setText("usageCoverageRatio", pct(kpis.service_resource_usage_coverage_ratio));
  setText("usageCoverageCaption", `${sampledContainers}/${profiledContainers}개 컨테이너 수집`);
  setText("serviceBindingRatio", deviceObservationFailed ? "관측 불가" : pct(kpis.device_service_availability_ratio));
  setText("serviceBindingCaption", deviceObservationFailed ? "EdgeX device 관측 불가" : `${boundDevices}/${registeredDevices}개 device 연결`);
  setText("assetCount", deviceObservationFailed ? `${nodes.length} node assets · EdgeX 관측 불가` : `${nodes.length + devices.length} assets`);
  setText("riskCount", deviceObservationFailed ? "EdgeX 관측 불가" : `${unavailableDevices}개 unavailable · ${degradedDevices}개 degraded`);
  renderOverviewVisuals(data, kpis, devices);
  renderKpiCatalog(kpis, deviceObservationFailed);
  renderNodeMetricMatrix(nodes);
  renderResourceProfiles(resourceState, kpis);
  renderScenario(devices, kpis);

  renderNodes(nodes);
  renderDevices(devices, data);
  renderAlerts(data);
  renderTopology(resourceState, kpis);
}

function renderOverviewVisuals(data, kpis, devices) {
  const nodes = data?.nodes || [];
  const deviceObservationFailed = deviceObservationUnavailable(data);
  const total = devices.length || 0;
  const available = devices.filter((device) => isOperationalDevice(device)).length;
  const degraded = devices.filter((device) => deviceStatus(device) === "degraded").length;
  const unavailable = devices.filter((device) => deviceStatus(device) === "unavailable").length;
  const unknown = Math.max(0, total - available - degraded - unavailable);
  const deviceRatio = total ? available / total : ratio(kpis.device_service_availability_ratio);
  const telemetryRatio = ratio(kpis.core_data_freshness_ratio);
  const nodeRatioValue = ratio(kpis.node_online_ratio);
  const bindingRatio = ratio(kpis.device_service_availability_ratio);
  const coverageRatio = ratio(kpis.service_resource_usage_coverage_ratio);
  const cpuCurrent = Number(kpis.service_resource_current_cpu_usage_cores) || 0;
  const cpuRequest = Number(kpis.service_resource_request_cpu_cores) || 0;
  const memoryCurrent = Number(kpis.service_resource_current_memory_working_set_mib) || 0;
  const memoryRequest = Number(kpis.service_resource_request_memory_mib) || 0;
  const statusTotal = total || 1;
  const nodeNames = nodes.map((node, index) => nodeDisplayName(node, index));
  const nodeScope = nodeNames.length
    ? `대상 노드 ${nodeNames.length}개: ${nodeNames.slice(0, 3).join(", ")}${nodeNames.length > 3 ? ` 외 ${nodeNames.length - 3}개` : ""}`
    : "대상 노드 없음";
  setStatusRing("overallHealthRing", deviceObservationFailed
    ? { ok: 0, warn: 0, bad: 0, unknown: 1 }
    : {
        ok: available / statusTotal,
        warn: degraded / statusTotal,
        bad: unavailable / statusTotal,
        unknown: unknown / statusTotal,
      });
  setText("overallHealthPercent", deviceObservationFailed ? "관측 불가" : pct(deviceRatio));
  setText("overviewMetricScope", `${nodeScope} · Kubernetes/Prometheus nodes · EdgeX devices`);
  setText("overviewHealthCaption", deviceObservationFailed ? "EdgeX device 관측 불가 · node 상태는 계속 표시합니다." : `${available}/${total}개 device 사용 가능 · ${degraded + unavailable}개 주의 필요`);
  setText("nodeOnlineValue", pct(nodeRatioValue));
  setText("deviceAvailableValue", deviceObservationFailed ? "관측 불가" : pct(deviceRatio));
  setText("telemetryFreshValue", deviceObservationFailed ? "관측 불가" : pct(telemetryRatio));
  setPercentStyle("nodeOnlineBar", nodeRatioValue);
  setPercentStyle("deviceAvailableBar", deviceObservationFailed ? 0 : deviceRatio);
  setPercentStyle("telemetryFreshBar", deviceObservationFailed ? 0 : telemetryRatio);
  setText("bindingValue", deviceObservationFailed ? "관측 불가" : pct(bindingRatio));
  setText("coverageValue", pct(coverageRatio));
  setPercentStyle("bindingBar", deviceObservationFailed ? 0 : bindingRatio);
  setPercentStyle("coverageBar", coverageRatio);
  setText("cpuResourceValue", `${threeDecimal(cpuCurrent)} / ${threeDecimal(cpuRequest)} core`);
  setText("memoryResourceValue", `${oneDecimal(memoryCurrent)} / ${oneDecimal(memoryRequest)} MiB`);
  setText("gpuResourceValue", `${threeDecimal(kpis.service_resource_limit_gpu_units)} units`);
  setPercentStyle("cpuResourceBar", cpuRequest > 0 ? cpuCurrent / cpuRequest : 0);
  setPercentStyle("memoryResourceBar", memoryRequest > 0 ? memoryCurrent / memoryRequest : 0);
  setText("statusAvailableCount", deviceObservationFailed ? "-" : available);
  setText("statusDegradedCount", deviceObservationFailed ? "-" : degraded);
  setText("statusUnavailableCount", deviceObservationFailed ? "-" : unavailable);
  setText("statusUnknownCount", deviceObservationFailed ? "-" : unknown);
  setPercentStyle("statusStackAvailable", deviceObservationFailed ? 0 : available / statusTotal);
  setPercentStyle("statusStackDegraded", deviceObservationFailed ? 0 : degraded / statusTotal);
  setPercentStyle("statusStackUnavailable", deviceObservationFailed ? 0 : unavailable / statusTotal);
  setPercentStyle("statusStackUnknown", deviceObservationFailed ? 1 : unknown / statusTotal);
}

function formatKpiValue(key, value) {
  if (key.endsWith("_ratio")) return pct(value);
  if (key.includes("memory") && Number.isFinite(Number(value))) return `${oneDecimal(value)} MiB`;
  if (key.includes("cpu") && Number.isFinite(Number(value))) return `${threeDecimal(value)} core`;
  if (key.includes("gpu") && Number.isFinite(Number(value))) return `${threeDecimal(value)} units`;
  if (typeof value === "boolean") return value ? "true" : "false";
  return displayValue(value);
}

function formatDashboardKpiValue(key, value, deviceObservationFailed = false) {
  const dependsOnDeviceObservation =
    key === "operator_focus_count" ||
    key.includes("device") ||
    key.includes("edgex") ||
    key.includes("core_data");
  if (deviceObservationFailed && dependsOnDeviceObservation) return "관측 불가";
  return formatKpiValue(key, value);
}

function kpiCategory(key) {
  if (key.startsWith("service_resource")) return "서비스 리소스";
  if (key.includes("core_data") || key.includes("event")) return "EdgeX Event";
  if (key.includes("device_service") || key.includes("edgex")) return "EdgeX Device";
  if (key.includes("device")) return "디바이스";
  if (key.includes("node")) return "노드";
  if (key.includes("workflow") || key.includes("sla")) return "Workflow";
  return "운영";
}

function renderKpiCatalog(kpis = {}, deviceObservationFailed = false) {
  const catalog = $("kpiCatalog");
  if (!catalog) return;
  const hiddenKeys = new Set([]);
  const entries = Object.entries(kpis).filter(([key]) => !hiddenKeys.has(key)).sort(([left], [right]) => {
    const groupDelta = kpiCategory(left).localeCompare(kpiCategory(right));
    return groupDelta || left.localeCompare(right);
  });
  setText("kpiCatalogCount", `${entries.length} metrics`);
  catalog.innerHTML = entries.length
    ? entries
        .map(([key, value]) => `
          <article class="kpi-catalog-row explainable" data-explain-type="kpi" data-kpi-key="${escapeHtml(key)}" tabindex="0" role="button" aria-label="${escapeHtml(key)} KPI 설명 보기">
            <span>${escapeHtml(kpiCategory(key))}</span>
            <strong>${escapeHtml(formatDashboardKpiValue(key, value, deviceObservationFailed))}</strong>
            <code>${escapeHtml(key)}</code>
          </article>
        `)
        .join("")
    : `<div class="empty">KPI payload가 없습니다.</div>`;
}

function renderNodeMetricMatrix(nodes = []) {
  const matrix = $("nodeMetricMatrix");
  if (!matrix) return;
  const nodeNames = nodes.map((node, index) => nodeDisplayName(node, index));
  setText(
    "nodeMetricScope",
    nodeNames.length
      ? `${nodeNames.slice(0, 2).join(", ")}${nodeNames.length > 2 ? ` 외 ${nodeNames.length - 2}개` : ""}`
      : "노드 없음",
  );
  matrix.innerHTML = nodes.length
    ? nodes
        .map((node, index) => {
          const metrics = node.raw_metrics || {};
          const cpu = ratio(metrics.cpu_utilization);
          const memory = ratio(metrics.memory_usage_ratio);
          const gpu = metrics.gpu_utilization === null || metrics.gpu_utilization === undefined ? null : ratio(metrics.gpu_utilization);
          const networkRx = Number(metrics.network_rx_rate) || 0;
          const networkTx = Number(metrics.network_tx_rate) || 0;
          const displayName = nodeDisplayName(node, index);
          return `
            <article class="node-metric-card">
              <div class="node-metric-title">
                <strong>${escapeHtml(displayName)}</strong>
                ${statusPill(node.node_health)}
              </div>
              <div class="node-metric-row"><span>CPU</span><strong>${pct(cpu)}</strong><div class="metric-bar"><i style="width:${pct(cpu)}"></i></div></div>
              <div class="node-metric-row"><span>Memory</span><strong>${pct(memory)}</strong><div class="metric-bar"><i style="width:${pct(memory)}"></i></div></div>
              <div class="node-metric-row"><span>GPU</span><strong>${gpu === null ? "N/A" : pct(gpu)}</strong><div class="metric-bar muted-bar"><i style="width:${gpu === null ? "0%" : pct(gpu)}"></i></div></div>
              <div class="node-metric-foot">
                <span>load ${escapeHtml(threeDecimal(metrics.load_average))}</span>
                <span>rx ${escapeHtml(oneDecimal(networkRx / 1024))} KiB/s</span>
                <span>tx ${escapeHtml(oneDecimal(networkTx / 1024))} KiB/s</span>
              </div>
            </article>
          `;
        })
        .join("")
    : `<div class="empty">Prometheus node metrics가 없습니다.</div>`;
}

function renderNodes(nodes) {
  refreshSelectedNodeFilterValues(nodes);
  $("nodeList").innerHTML = nodes.length
    ? nodes
        .map((node, index) => {
          const cpu = Math.round((node.raw_metrics?.cpu_utilization || 0) * 100);
          const mem = Math.round((node.raw_metrics?.memory_usage_ratio || 0) * 100);
          const gpuValue = node.raw_metrics?.gpu_utilization;
          const gpu = gpuValue === null || gpuValue === undefined ? null : Math.round(gpuValue * 100);
          const gpuMeta = gpu === null ? "" : `<span>gpu ${gpu}%</span>`;
          const displayName = nodeDisplayName(node, index);
          const mappingMeta = isRawInstance(node.hostname) ? `<span>hostname 매핑 대기</span>` : "";
          return `
            <article class="item node-card ${state.selectedNodeName === displayName ? "selected" : ""}" data-node-filter="${escapeHtml(displayName)}" data-node-index="${index}" tabindex="0" role="button" aria-label="${escapeHtml(displayName)} node device filter">
              <div class="item-title">
                <strong class="node-name">${escapeHtml(displayName)}</strong>
                ${statusPill(node.node_health)}
              </div>
              <div class="meta">
                <span>${escapeHtml(text(node.node_type, "node"))}</span>
                <span>cpu ${cpu}%</span>
                <span>mem ${mem}%</span>
                ${gpuMeta}
                ${mappingMeta}
              </div>
            </article>
          `;
        })
        .join("")
    : `<div class="empty">아직 node 상태가 없습니다.</div>`;
}

function deviceObservationUnavailable(data = state.data) {
  return Boolean(data?.device_observation_error);
}

function deviceFilterEmptyText(data = state.data) {
  if (deviceObservationUnavailable(data)) return "EdgeX device 관측 불가";
  if (state.selectedNodeName) return `${state.selectedNodeName}에 맞는 EdgeX device가 없습니다.`;
  return "EdgeX Core Metadata device가 없습니다.";
}

function renderDevices(devices, data = state.data) {
  const visibleDevices = filteredDevices(devices);
  renderDeviceFilterSummary(devices.length, visibleDevices.length);
  $("deviceList").innerHTML = visibleDevices.length
    ? visibleDevices
        .map((device) => `
          <article class="item device-row explainable ${state.selectedDeviceName === device.name ? "selected" : ""}" data-explain-type="device" data-device-name="${escapeHtml(device.name)}" tabindex="0" role="button" aria-label="${escapeHtml(device.name)} 설명 보기">
            <div class="item-title">
              <strong>${escapeHtml(device.name)}</strong>
              <div class="item-pills">${statusPill(deviceStatus(device))}${renderConnectionBadge(device)}</div>
            </div>
            <div class="meta">
              <span>service: ${escapeHtml(text(device.device_service_name, "unknown"))}</span>
              <span>profile: ${escapeHtml(text(device.profile_name, "unknown"))}</span>
              <span>protocol: ${escapeHtml(Array.isArray(device.protocol_names) ? device.protocol_names.join(", ") : "unknown")}</span>
              <span>Core Data event: ${escapeHtml(timestampAge(device.latest_event_timestamp))} · ${escapeHtml(text(device.telemetry_freshness, "no_events"))}</span>
              <span>node placement: ${escapeHtml(deviceNodeLabel(device))}</span>
            </div>
          </article>
        `)
        .join("")
    : `<div class="empty">${escapeHtml(deviceFilterEmptyText(data))}</div>`;
}

function renderResourceProfiles(resourceState, kpis) {
  const profiles = resourceState.service_resource_profiles || [];
  const rows = profiles.slice(0, 8).map((profile) => {
    const req = profile.resource_requirements?.requests || {};
    const usage = profile.current_usage || {};
    const missing = profile.resource_requirements?.missing || {};
    const missingTotal = [
      missing.cpu_request_containers,
      missing.memory_request_containers,
      missing.cpu_limit_containers,
      missing.memory_limit_containers,
    ].reduce((sum, value) => sum + (Number(value) || 0), 0);
    const badge = profile.requirements_declared ? "declared" : `missing ${missingTotal}`;
    return `
      <li>
        <strong>${escapeHtml(profile.namespace)}/${escapeHtml(profile.service)}</strong>
        <span>${escapeHtml(text(profile.pod_count, 0))} pods · use ${escapeHtml(text(usage.cpu_cores, 0))} core / ${escapeHtml(text(usage.memory_working_set_mib, 0))} MiB · req ${escapeHtml(text(req.cpu_cores, 0))} core / ${escapeHtml(text(req.memory_mib, 0))} MiB · ${escapeHtml(badge)}</span>
      </li>
    `;
  });
  $("resourceProfileList").innerHTML = profiles.length
    ? `
      <div class="relation-summary">recording=${resourceState.recorded_at ? "snapshot available" : "pending"} · scope=current usage + declared requests · total_use=${text(kpis.service_resource_current_cpu_usage_cores, 0)} core / ${text(kpis.service_resource_current_memory_working_set_mib, 0)} MiB · total_req=${text(kpis.service_resource_request_cpu_cores, 0)} core / ${text(kpis.service_resource_request_memory_mib, 0)} MiB</div>
      <ul class="compact-list">${rows.join("")}</ul>
    `
    : `<div class="empty">Running service resource requirement profile pending</div>`;
}


function formatResourceValue(value, unit) {
  const numeric = numericValue(value);
  if (numeric === null) return "없음";
  return `${numeric} ${unit}`;
}

function missingResourceTotal(profile) {
  const missing = profile.resource_requirements?.missing || {};
  return [
    missing.cpu_request_containers,
    missing.memory_request_containers,
    missing.cpu_limit_containers,
    missing.memory_limit_containers,
  ].reduce((sum, value) => sum + (Number(value) || 0), 0);
}

function renderPodsByNode(profile) {
  const entries = Object.entries(profile.pods_by_node || {});
  const rows = entries.length ? entries : (profile.nodes || []).map((node) => [node, "observed"]);
  return rows.length
    ? rows
        .map(([node, count]) => `<span>${escapeHtml(cleanNodeLabel(node, "unknown node"))}: ${count === "observed" ? "pods observed" : `${escapeHtml(text(count))} pods observed`}</span>`)
        .join("")
    : `<span>node observation pending</span>`;
}

function renderContainerRows(profile) {
  const containers = profile.containers || [];
  if (!containers.length) return `<li class="empty">Container-level observed config pending</li>`;
  return containers
    .slice(0, 6)
    .map((container) => {
      const requests = container.requests || {};
      const limits = container.limits || {};
      const usage = container.current_usage || {};
      return `
        <li>
          <strong>${escapeHtml(text(container.pod, "pod pending"))}/${escapeHtml(text(container.container, "container"))}</strong>
          <span>node=${escapeHtml(cleanNodeLabel(container.node, "unknown"))} · declared req ${escapeHtml(formatResourceValue(requests.cpu_cores, "core"))} / ${escapeHtml(formatResourceValue(requests.memory_mib, "MiB"))} · declared limit ${escapeHtml(formatResourceValue(limits.cpu_cores, "core"))} / ${escapeHtml(formatResourceValue(limits.memory_mib, "MiB"))} · current ${escapeHtml(formatResourceValue(usage.cpu_cores, "core"))} / ${escapeHtml(formatResourceValue(usage.memory_working_set_mib, "MiB"))}</span>
        </li>
      `;
    })
    .join("");
}

function renderPodPlacement(resourceState, kpis) {
  const profiles = resourceState.service_resource_profiles || [];
  const summary = `<div class="relation-summary">read-only observed pods=${text(kpis.service_resource_profile_pod_count, 0)} · current=${text(kpis.service_resource_current_cpu_usage_cores, 0)} core / ${text(kpis.service_resource_current_memory_working_set_mib, 0)} MiB · declared requests=${text(kpis.service_resource_request_cpu_cores, 0)} core / ${text(kpis.service_resource_request_memory_mib, 0)} MiB · missing profiles=${text(kpis.service_resource_partially_declared_profile_count, 0)}</div>`;
  const rows = profiles.slice(0, 8).map((profile) => {
    const req = profile.resource_requirements?.requests || {};
    const limits = profile.resource_requirements?.limits || {};
    const usage = profile.current_usage || {};
    const usageProfile = profile.usage_profile || {};
    const missingTotal = missingResourceTotal(profile);
    const declaration = missingTotal ? `missing ${missingTotal}` : "declared";
    return `
      <details class="pod-placement-card" open>
        <summary>
          <span>
            <strong>${escapeHtml(profile.namespace)}/${escapeHtml(profile.service)}</strong>
            <small>${escapeHtml(text(profile.pod_count, 0))} pods · ${escapeHtml(text(profile.container_count, 0))} containers · ${escapeHtml(declaration)}</small>
          </span>
          ${statusPill(missingTotal ? "missing" : "declared")}
        </summary>
        <div class="placement-node-map" aria-label="observed pod placement by node">
          ${renderPodsByNode(profile)}
        </div>
        <dl class="placement-config-grid">
          <div><dt>declared requests</dt><dd>${escapeHtml(formatResourceValue(req.cpu_cores, "core"))} / ${escapeHtml(formatResourceValue(req.memory_mib, "MiB"))}</dd></div>
          <div><dt>declared limits</dt><dd>${escapeHtml(formatResourceValue(limits.cpu_cores, "core"))} / ${escapeHtml(formatResourceValue(limits.memory_mib, "MiB"))} · gpu ${escapeHtml(formatResourceValue(limits.gpu_units, "units"))}</dd></div>
          <div><dt>current usage</dt><dd>${escapeHtml(formatResourceValue(usage.cpu_cores, "core"))} / ${escapeHtml(formatResourceValue(usage.memory_working_set_mib, "MiB"))} · coverage ${pct(usage.usage_coverage_ratio)}</dd></div>
          <div><dt>observed profile</dt><dd>window ${escapeHtml(text(usageProfile.window, "current"))} · p95 ${escapeHtml(formatResourceValue(usageProfile.p95_cpu_usage_cores, "core"))} / ${escapeHtml(formatResourceValue(usageProfile.p95_memory_working_set_mib, "MiB"))}</dd></div>
        </dl>
        <ul class="compact-list placement-containers">${renderContainerRows(profile)}</ul>
        <p class="placement-note">${escapeHtml(text(profile.interpretation, "observed/current/declared resource config only"))}</p>
      </details>
    `;
  });
  $("placementList").innerHTML = profiles.length ? summary + rows.join("") : `<div class="empty">Running service pod placement/configuration pending</div>`;
}

function renderTopology(resourceState, kpis) {
  const profiles = resourceState.service_resource_profiles || [];
  if (!profiles.length) {
    $("topologyMap").innerHTML = `<div class="empty">실행 중인 서비스 토폴로지가 아직 없습니다.</div>`;
    return;
  }
  const svcMap = {};
  profiles.forEach((p) => {
    const key = `${p.namespace}/${p.service}`;
    if (!svcMap[key]) svcMap[key] = { namespace: p.namespace, service: p.service, pod_count: 0, nodes: [], pods: [], containers: [], cpu_req: 0, mem_req: 0, cpu_cur: 0, mem_cur: 0 };
    const s = svcMap[key];
    s.pod_count = Math.max(s.pod_count, Number(p.pod_count) || 0);
    if (p.nodes) s.nodes = [...new Set([...s.nodes, ...p.nodes])];
    Object.entries(p.pods_by_node || {}).forEach(([node, count]) => { s.pods.push({ node, count: String(count) }); });
    if (p.resource_requirements?.requests) { s.cpu_req += Number(p.resource_requirements.requests.cpu_cores) || 0; s.mem_req += Number(p.resource_requirements.requests.memory_mib) || 0; }
    if (p.current_usage) { s.cpu_cur += Number(p.current_usage.cpu_cores) || 0; s.mem_cur += Number(p.current_usage.memory_working_set_mib) || 0; }
    if (p.containers) s.containers = [...s.containers, ...p.containers];
  });
  const services = Object.values(svcMap).sort((a, b) => b.pod_count - a.pod_count);
  const selected = state.selectedTopologyService;
  $("topologyMap").innerHTML = services.map((svc) => {
    const key = `${svc.namespace}/${svc.service}`;
    const open = key === selected;
    const nodes = svc.nodes.length ? svc.nodes : [`node-${svc.pod_count}`];
    const podCountForNode = (nodeName, index) => {
      const observed = svc.pods.find((pod) => pod.node === nodeName);
      if (observed) return Number(observed.count) || 0;
      if (nodes.length <= 1) return svc.pod_count;
      if (index === nodes.length - 1) return Math.max(1, svc.pod_count - Math.max(1, Math.ceil(svc.pod_count / nodes.length)) * (nodes.length - 1));
      return Math.max(1, Math.ceil(svc.pod_count / nodes.length));
    };
    const podsPerNode = nodes.map((nodeName, index) => {
      const podNames = [...new Set(svc.containers.filter((container) => container.node === nodeName).map((container) => container.pod).filter(Boolean))];
      return { name: nodeName, count: Math.max(podNames.length, podCountForNode(nodeName, index)), podNames };
    });
    return `
      <details class="topo-service ${open ? "open" : ""}" data-topology-key="${escapeHtml(key)}" ${open ? "open" : ""}>
        <summary>
          <div class="topo-svc-header">
            <span class="topo-svc-name"><span class="topo-ns">${escapeHtml(svc.namespace)}</span> / <strong>${escapeHtml(svc.service)}</strong></span>
            <span class="topo-svc-meta">${svc.pod_count} pods · ${svc.nodes.length} nodes · ${svc.containers.length} containers</span>
          </div>
        </summary>
        <div class="topo-detail">
          <div class="topo-service-flow">
            <div class="topo-service-origin"><span>service</span><strong>${escapeHtml(svc.service)}</strong><em>${escapeHtml(svc.namespace)}</em></div>
            <div class="topo-node-lanes">
              ${podsPerNode.map((node) => `
                <div class="topo-node-lane">
                  <span>node</span>
                  <strong>${escapeHtml(node.name)}</strong>
                  <b class="topo-pod-count">${node.count} pods</b>
                  ${node.podNames.length ? `<div class="topo-pod-pills">${node.podNames.slice(0, 4).map((podName) => `<span class="topo-pod-pill">${escapeHtml(podName)}</span>`).join("")}</div>` : ""}
                </div>
              `).join("")}
            </div>
          </div>
          <div class="topo-resource-bar"><div class="topo-resource-item"><span>declared requests</span><span>${formatResourceValue(svc.cpu_req, "core")} / ${formatResourceValue(svc.mem_req, "MiB")}</span></div><div class="topo-resource-item"><span>current usage</span><span>${formatResourceValue(svc.cpu_cur, "core")} / ${formatResourceValue(svc.mem_cur, "MiB")}</span></div></div>
          ${svc.containers.length ? `<div class="topo-containers"><span class="topo-sec-title">containers</span>${svc.containers.slice(0, 8).map((c) => `<div class="topo-container-row"><span class="topo-pod-ref">${escapeHtml(c.pod || "-")}/${escapeHtml(c.container || "-")}</span><span>${escapeHtml(c.node ? `node:${cleanNodeLabel(c.node, "")}` : "")}</span><span>request ${formatResourceValue(c.requests?.cpu_cores, "core")}/${formatResourceValue(c.requests?.memory_mib, "MiB")}</span><span>usage ${formatResourceValue(c.current_usage?.cpu_cores, "core")}/${formatResourceValue(c.current_usage?.memory_working_set_mib, "MiB")}</span></div>`).join("")}</div>` : ""}
        </div>
      </details>`;
  }).join("");
  document.querySelectorAll(".topo-service").forEach((details) => {
    details.addEventListener("toggle", () => {
      const key = details.dataset.topologyKey;
      details.classList.toggle("open", details.open);
      if (details.open) {
        state.selectedTopologyService = key || null;
        return;
      }
      if (state.selectedTopologyService === key) state.selectedTopologyService = null;
    });
  });
}

function buildDashboardAlerts(data = {}) {
  const alerts = [];
  if (data.device_observation_error) {
    alerts.push({
      kind: "source",
      level: "high",
      title: "EdgeX device observation unavailable",
      text: data.device_observation_error,
    });
  }
  for (const [index, node] of (data.nodes || []).entries()) {
    if (node.node_health !== "healthy") {
      const displayName = nodeDisplayName(node, index);
      alerts.push({
        kind: "node",
        level: node.node_health === "unavailable" ? "high" : "medium",
        title: `${displayName}: non-healthy node`,
        text: `${displayName}: non-healthy node (${node.node_health})`,
        node,
      });
    }
  }
  for (const device of data.devices || []) {
    const status = deviceStatus(device);
    const reasons = [];
    if (status === "degraded" || status === "unavailable") reasons.push(status);
    if (device.connection_state !== "connected") reasons.push(`connection=${text(device.connection_state, "unknown")}`);
    if (device.telemetry_freshness !== "fresh") reasons.push(`event=${text(device.telemetry_freshness, "no_events")}`);
    if (reasons.length) {
      const level = status === "unavailable" ? "high" : "medium";
      alerts.push({
        kind: "device",
        level,
        title: `${device.name}: ${reasons.join(", ")}`,
        text: `${device.name}: ${reasons.join(", ")} · ${deviceReason(device)}`,
        device,
      });
    }
  }
  return alerts.slice(0, 12);
}

function renderAlerts(data) {
  state.alerts = buildDashboardAlerts(data);
  $("alertList").innerHTML = state.alerts.length
    ? state.alerts
        .map((alert, index) => `<article class="item alert ${escapeHtml(alert.level)} explainable" data-explain-type="issue" data-alert-index="${index}" tabindex="0" role="button" aria-label="Issue 설명 보기"><strong>${escapeHtml(alert.text)}</strong></article>`)
        .join("")
    : `<div class="empty">No active alerts</div>`;
}

function renderScenario(devices, kpis) {
  const unavailable = devices.filter((device) => deviceStatus(device) === "unavailable").length;
  const degraded = devices.filter((device) => deviceStatus(device) === "degraded").length;
  const byNode = devices.reduce((acc, device) => {
    const key = deviceNodeLabel(device);
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const busiestNode = Object.entries(byNode).sort((a, b) => b[1] - a[1])[0];
  setText("responseKpi", busiestNode ? `${busiestNode[0]} (${busiestNode[1]})` : "no devices");
  setText("interventionKpi", `${kpis.operator_focus_count || 0} focus`);
  setText("handlingKpi", unavailable ? `${unavailable} risk` : degraded ? `${degraded} watch` : "normal");
  $("deviceStatusList").innerHTML = devices.length
    ? sortDevicesStatusFirst(devices)
        .slice(0, 8)
        .map((device) => `
          <article class="item">
            <div class="item-title">
              <strong>${escapeHtml(device.name)}</strong>
              ${statusPill(deviceStatus(device))}
            </div>
            <div class="meta">
              <span>EdgeX Device Service: ${escapeHtml(text(device.device_service_name, "unknown"))}</span>
              <span>Profile: ${escapeHtml(text(device.profile_name, "unknown"))}</span>
              <span>Protocols: ${escapeHtml(Array.isArray(device.protocol_names) ? device.protocol_names.join(", ") : "unknown")}</span>
              <span>Connection: ${escapeHtml(text(device.connection_state, "unknown"))}</span>
              <span>Core Data event: ${escapeHtml(text(device.telemetry_freshness, "no_events"))} · ${escapeHtml(timestampAge(device.latest_event_timestamp))}</span>
              <span>Readings: ${escapeHtml((device.latest_readings || []).map((reading) => `${reading.resource_name || reading.source_name}=${text(reading.value)}`).join(", ") || "none")}</span>
            </div>
          </article>
        `)
        .join("")
    : `<div class="empty">No device status received</div>`;
}


function applyNodeDeviceFilter(nodeName, nodeIndex = null) {
  const numericIndex = Number(nodeIndex);
  const node = Number.isInteger(numericIndex) ? (state.data?.nodes || [])[numericIndex] : null;
  state.selectedNodeName = nodeName || null;
  state.selectedNodeFilterValues = nodeName && node ? nodeFilterValues(node, numericIndex) : [];
  renderNodes(state.data?.nodes || []);
  renderDevices(state.data?.devices || []);
}



function markSelectedExplain(target) {
  if (typeof document === "undefined" || !target) return;
  document.querySelectorAll(".explainable.selected").forEach((item) => item.classList.remove("selected"));
  target.classList.add("selected");
}

function handleNodeFilterSelection(target) {
  const nodeTarget = target.closest?.("[data-node-filter]");
  if (!nodeTarget) return false;
  applyNodeDeviceFilter(nodeTarget.dataset.nodeFilter, nodeTarget.dataset.nodeIndex);
  return true;
}


function handleExplainSelection(target) {
  const explainTarget = target.closest?.("[data-explain-type]");
  if (!explainTarget) return;
  const type = explainTarget.dataset.explainType;
  if (type === "device") {
    const deviceName = explainTarget.dataset.deviceName;
    const device = (state.data?.devices || []).find((item) => item.name === deviceName);
    showDeviceExplanation(device);
    renderDevices(state.data?.devices || []);
    const selectedRow = Array.from(document.querySelectorAll('[data-explain-type="device"]')).find((item) => item.dataset.deviceName === deviceName);
    markSelectedExplain(selectedRow);
  }
  if (type === "kpi") {
    showKpiExplanation(explainTarget.dataset.kpiKey);
    markSelectedExplain(explainTarget);
  }
  if (type === "issue") {
    showIssueExplanation(Number(explainTarget.dataset.alertIndex));
    markSelectedExplain(explainTarget);
  }
}

if (typeof document !== "undefined") {
  document.addEventListener("click", (event) => {
    if (handleNodeFilterSelection(event.target)) return;
    handleExplainSelection(event.target);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const target = event.target?.closest?.("[data-explain-type], [data-node-filter]");
    if (!target) return;
    event.preventDefault();
    if (handleNodeFilterSelection(target)) return;
    handleExplainSelection(target);
  });
}

if (typeof document !== "undefined" && $("clearNodeFilter")) {
  $("clearNodeFilter").addEventListener("click", () => applyNodeDeviceFilter(null));
}

if (typeof document !== "undefined" && $("refreshButton")) {
  $("refreshButton").addEventListener("click", () => {
    loadDashboard().catch((error) => {
      $("alertList").innerHTML = `<article class="item alert high"><strong>${escapeHtml(error.message)}</strong></article>`;
    });
  });
}

if (typeof document !== "undefined" && $("operatorChatForm")) {
  $("operatorChatForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const input = $("operatorChatInput");
    const message = input?.value.trim();
    if (!message || state.chat.loading) return;
    input.value = "";
    submitOperatorChat(message);
  });
}

function scheduleDashboardRefresh() {
  loadDashboard()
    .catch((error) => {
      $("alertList").innerHTML = `<article class="item alert high"><strong>${escapeHtml(error.message)}</strong></article>`;
    })
    .finally(() => {
      window.setTimeout(scheduleDashboardRefresh, state.refreshMs);
    });
}

if (typeof document !== "undefined") {
  scheduleDashboardRefresh();
}

if (typeof module !== "undefined") {
  module.exports = {
    buildDashboardAlerts,
    deviceFilterEmptyText,
    deviceObservationUnavailable,
    formatDashboardKpiValue,
    explainDeviceRules,
    renderTelemetryChart,
    explainKpi,
    issueExplanation,
    deviceStatus,
    deviceReason,
    isOperationalDevice,
    sortDevicesStatusFirst,
    filteredDevices,
    nodeFilterValues,
    missingResourceTotal,
    cleanNodeLabel,
    nodeDisplayName,
    chatResponseMeta,
    submitOperatorChat,
    renderTopology,
    state,
  };
}
