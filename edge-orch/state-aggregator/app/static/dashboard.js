function createDeviceTelemetryHistoryState(overrides = {}) {
  return {
    deviceName: null,
    window: "-30m",
    points: [],
    loading: false,
    error: null,
    requestId: 0,
    ...overrides,
  };
}

const state = {
  data: null,
  refreshMs: 5000,
  selectedResourceCategory: "sensor",
  selectedResourceId: null,
  selectedDeviceName: null,
  deviceTelemetryHistory: createDeviceTelemetryHistoryState(),
  selectedNodeName: null,
  selectedNodeFilterValues: [],
  selectedTopologyService: null,
  chat: {
    loading: false,
    messages: [],
  },
};

const $ = (id) => document.getElementById(id);

const DEVICE_TELEMETRY_LIMIT = 1000;
const DEVICE_TELEMETRY_WINDOWS = [
  {value: "-5m", label: "5분"},
  {value: "-30m", label: "30분"},
  {value: "-1h", label: "1시간"},
  {value: "-24h", label: "24시간"},
];

const RESOURCE_CATEGORY_VIEWS = {
  server: {
    label: "엣지 AI 서버",
    countId: "serverCategoryCount",
    latestLabel: "최신 관측",
    emptyLabel: "관측된 엣지 AI 서버가 없습니다.",
  },
  physical: {
    label: "현장 엣지 노드",
    countId: "physicalCategoryCount",
    latestLabel: "최신 관측",
    emptyLabel: "관측된 현장 엣지 노드가 없습니다.",
  },
  sensor: {
    label: "EdgeX 등록 디바이스",
    countId: "sensorCategoryCount",
    latestLabel: "최신 이벤트",
    emptyLabel: "EdgeX에 등록된 디바이스가 없습니다.",
  },
};
const RESOURCE_CATEGORY_ORDER = ["server", "physical", "sensor"];

function resourceCategoryView(category = "sensor") {
  return RESOURCE_CATEGORY_VIEWS[category] || RESOURCE_CATEGORY_VIEWS.sensor;
}

function isServerNode(node = {}) {
  return ["cloud_server", "server"].includes(
    text(node.node_type, "").toLowerCase(),
  );
}

function resourceAvailabilityStatus(value) {
  const normalized = text(value, "unknown").toLowerCase();
  if (["healthy", "available", "idle", "allocated"].includes(normalized)) {
    return "available";
  }
  if (["degraded", "partially_available", "configured_not_running"].includes(normalized)) {
    return "degraded";
  }
  if (["unavailable", "down", "failed"].includes(normalized)) {
    return "unavailable";
  }
  return "unknown";
}

function resourceStatusLabel(status) {
  return {
    available: "Available",
    degraded: "Degraded",
    unavailable: "Unavailable",
    unknown: "Unknown",
  }[status] || "Unknown";
}

function normalizeNodeResourceItem(node, index, kind) {
  const name = nodeDisplayName(node, index);
  const status = resourceAvailabilityStatus(node.node_health);
  return {
    id: name,
    name,
    kind,
    status,
    statusLabel: resourceStatusLabel(status),
    observedAt: node.collected_at,
    nodeName: name,
    raw: node,
  };
}

function sensorResourceDisplayName(device = {}) {
  const physicalDevice = text(device.physical_device_id, "");
  const resources = [...new Set((device.latest_readings || [])
    .map((reading) => text(reading.resource_name || reading.source_name, ""))
    .filter(Boolean))];
  if (physicalDevice && resources.length) {
    return `${physicalDevice} · ${resources.join(", ")}`;
  }
  return physicalDevice || text(device.name, "등록 ID 없음");
}

function normalizeSensorResourceItem(device) {
  const status = deviceStatus(device);
  return {
    id: text(device.name),
    name: sensorResourceDisplayName(device),
    kind: "sensor",
    status,
    statusLabel: resourceStatusLabel(status),
    observedAt: device.latest_event_timestamp,
    nodeName: deviceNodeLabel(device),
    raw: device,
  };
}

function sortResourceItems(items = []) {
  const rank = {available: 0, degraded: 1, unknown: 2, unavailable: 3};
  return [...items].sort((left, right) => (
    (rank[left.status] ?? 2) - (rank[right.status] ?? 2)
    || text(left.name, "").localeCompare(text(right.name, ""))
  ));
}

function resourceCategoryItems(data = {}, category = "sensor") {
  let items = [];
  if (category === "server" || category === "physical") {
    items = (data.nodes || [])
      .map((node, index) => ({node, index}))
      .filter(({node}) => (
        category === "server" ? isServerNode(node) : !isServerNode(node)
      ))
      .map(({node, index}) => normalizeNodeResourceItem(node, index, category));
  } else {
    items = (data.devices || []).map(normalizeSensorResourceItem);
  }
  return sortResourceItems(items);
}

function buildGlobalSearchResults(query, data = {}, limit = 10) {
  const normalized = String(query || "").trim().toLocaleLowerCase();
  if (!normalized) return [];
  const includesQuery = (...values) => values
    .flat()
    .filter((value) => value !== null && value !== undefined)
    .some((value) => String(value).toLocaleLowerCase().includes(normalized));
  const results = [];

  (data.nodes || []).forEach((node, index) => {
    const name = nodeDisplayName(node, index);
    if (includesQuery(name, node.hostname, node.name, node.node_name, node.node_type)) {
      results.push({
        kind: "node",
        id: name,
        label: name,
        category: isServerNode(node) ? "server" : "physical",
        detail: isServerNode(node) ? "엣지 AI 서버" : "현장 엣지 노드",
        index,
      });
    }
  });
  (data.devices || []).forEach((device) => {
    if (includesQuery(
      device.name,
      device.profile_name,
      device.device_service_name,
      device.protocol_names,
      device.node_name,
    )) {
      results.push({
        kind: "device",
        id: device.name,
        label: sensorResourceDisplayName(device),
        detail: `EdgeX 등록 디바이스 · ${text(device.device_service_name, "서비스 미확인")}`,
      });
    }
  });
  const profiles = data.resource_profiles?.service_resource_profiles || [];
  const seenServices = new Set();
  profiles.forEach((profile) => {
    const id = `${text(profile.namespace, "default")}/${text(profile.service, "unknown")}`;
    if (seenServices.has(id) || !includesQuery(
      id,
      profile.namespace,
      profile.service,
      profile.nodes,
      (profile.containers || []).flatMap((container) => [
        container.pod,
        container.container,
        container.node,
      ]),
    )) return;
    seenServices.add(id);
    results.push({
      kind: "service",
      id,
      label: id,
      detail: `서비스 · ${text(profile.pod_count, 0)}개 Pod`,
    });
  });
  return results.slice(0, Math.max(1, Number(limit) || 10));
}



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

function sensorDeviceStatusLabel(device) {
  const labels = {
    available: "Available",
    degraded: "Degraded",
    unavailable: "Unavailable",
    unknown: "Unknown",
  };
  const status = deviceStatus(device);
  return labels[status] || "Unknown";
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
  if (status === "available") return "수집 서비스가 연결되어 있고 최신 이벤트가 fresh입니다.";
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
  if (label) {
    const parts = [];
    if (state.selectedNodeName) parts.push(`노드 ${state.selectedNodeName}`);
    label.textContent = parts.length
      ? `${visibleCount}/${totalCount}개 · ${parts.join(" / ")}`
      : `전체 ${totalCount}개`;
  }
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
    id: "수집 서비스",
    title: `${text(device.device_service_name, "unknown service")} · ${text(device.profile_name, "unknown profile")}`,
    text: `수집 서비스 ${text(device.device_service_name, "unknown")}가 센서 프로필 ${text(device.profile_name, "unknown")}과 ${Array.isArray(device.protocol_names) && device.protocol_names.length ? device.protocol_names.join(", ") : "unknown"} 프로토콜로 데이터를 수집합니다.`,
  }];
  const status = deviceStatus(device);
  if (status === "available") {
    rules.push({ id: "Available", title: "수집 정상", text: "동작 상태가 UP이고 수집 서비스와 최신 이벤트가 freshness 기준을 만족합니다." });
  } else if (status === "unavailable") {
    rules.push({ id: "Unavailable", title: "센서 연결 확인", text: "관리 상태가 LOCKED이거나 동작 상태가 DOWN 또는 연결이 끊긴 상태입니다. 수집 서비스와 장치 연결을 확인합니다." });
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
  edgex_connection_ratio: "연결된 센서 디바이스 수 / 전체 등록 센서 수입니다.",
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
  if (device.connection_state === "disconnected") messages.push(`수집 서비스 ${text(device.device_service_name, "unknown")}와 센서 연결을 확인합니다.`);
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

function renderTelemetryChart(points = [], context = {}) {
  const title = text(context.title, "Core Data readings");
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
    return `<div class="telemetry-chart empty">Core Data readings가 없습니다.</div>`;
  }

  if (!numericPoints.length) {
    const recent = points.slice(-8).reverse();
    return `
      <div class="telemetry-chart">
        <div class="chart-head"><strong>${escapeHtml(title)}</strong><span>non-numeric values</span></div>
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
      <div class="chart-head"><strong>${escapeHtml(title)}</strong><span>${numericPoints.length} numeric readings · ${escapeHtml(formatChartTime(numericPoints[0].timestamp))}</span></div>
      <div class="telemetry-summary-strip">${summaryCards}</div>
      <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(title)} chart">
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

function telemetryWindowLabel(windowValue) {
  return DEVICE_TELEMETRY_WINDOWS.find((item) => item.value === windowValue)?.label
    || text(windowValue, "30분");
}

function formatHistoryTimestamp(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return date.toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function renderDeviceTelemetryHistory(
  history = createDeviceTelemetryHistoryState(),
) {
  const controls = DEVICE_TELEMETRY_WINDOWS
    .map(({value, label}) => `<button type="button" data-telemetry-window="${value}" aria-pressed="${value === history.window ? "true" : "false"}">${label}</button>`)
    .join("");
  let body;

  if (history.loading) {
    body = `<div class="telemetry-history-state loading" role="status">Core Data 이력을 조회 중입니다.</div>`;
  } else if (history.error) {
    body = `<div class="telemetry-history-state error" role="status"><strong>이력 조회 실패</strong><span>${escapeHtml(history.error)}</span></div>`;
  } else if (!history.points.length) {
    body = `<div class="telemetry-history-state empty" role="status">선택한 범위에 저장된 이력이 없습니다.</div>`;
  } else {
    const timestamps = history.points
      .map((point) => new Date(point.timestamp).getTime())
      .filter(Number.isFinite)
      .sort((left, right) => left - right);
    const actualCoverage = timestamps.length
      ? `${formatHistoryTimestamp(timestamps[0])} ~ ${formatHistoryTimestamp(timestamps.at(-1))}`
      : "timestamp 없음";
    body = `
      <div class="telemetry-history-meta">
        <span>요청 범위 ${escapeHtml(telemetryWindowLabel(history.window))}</span>
        <span>${history.points.length} readings</span>
        <span>실제 구간 ${escapeHtml(actualCoverage)}</span>
        <span>최신 ${DEVICE_TELEMETRY_LIMIT} events 제한</span>
      </div>
      ${renderTelemetryChart(history.points, {title: "Core Data history"})}
    `;
  }

  return `
    <section class="telemetry-history-shell" aria-label="센서 이벤트 저장 이력" aria-busy="${history.loading ? "true" : "false"}">
      <div class="telemetry-history-toolbar">
        <div class="telemetry-history-ranges" aria-label="이력 조회 범위">${controls}</div>
        <button type="button" class="telemetry-history-refresh" data-telemetry-refresh>새로고침</button>
      </div>
      <p class="telemetry-history-source">저장 이력 · Core Data</p>
      ${body}
    </section>
  `;
}

function showDeviceExplanation(
  device,
  history = state.deviceTelemetryHistory,
) {
  const panel = $("explainPanel");
  if (!panel || !device) return;
  state.selectedDeviceName = device.name;
  panel.innerHTML = `
    <div class="explain-header">
      <span class="explain-badge">센서 디바이스</span>
      <strong>${escapeHtml(sensorResourceDisplayName(device))}</strong>
    </div>
    <div class="explain-status-strip">
      <div>
        <span>상태</span>
        <strong>${escapeHtml(sensorDeviceStatusLabel(device))}</strong>
      </div>
      <div>
        <span>연결</span>
        <strong>${escapeHtml(text(device.connection_state, "unknown"))}</strong>
      </div>
      <div>
        <span>최신 이벤트</span>
        <strong>${escapeHtml(text(device.telemetry_freshness, "no_events"))}</strong>
      </div>
    </div>
    ${renderDeviceFactList([
      ["EdgeX 등록 ID", device.name],
      ["수집 서비스", device.device_service_name],
      ["센서 프로필", device.profile_name],
      ["프로토콜", Array.isArray(device.protocol_names) ? device.protocol_names.join(", ") : null],
      ["관리 / 동작 상태", `${text(device.admin_state, "UNKNOWN")} / ${text(device.operating_state, "UNKNOWN")}`],
      ["데이터 항목", [...new Set((device.latest_readings || []).map((reading) => reading.source_name).filter(Boolean))].join(", ") || "이벤트 없음"],
      ["최신 이벤트 시각", device.latest_event_timestamp || "이벤트 없음"],
      ["이벤트 경과", timestampAge(device.latest_event_timestamp)],
      ["배치 노드", deviceNodeLabel(device)],
    ])}
    <div id="telemetryChart">${renderDeviceTelemetryHistory(history)}</div>
    ${renderDeviceReasonList(explainDeviceRules(device))}
  `;
}

function showResourceExplanation(item) {
  const panel = $("explainPanel");
  if (!panel || !item) return;
  if (item.kind === "sensor") {
    state.selectedResourceId = null;
    showDeviceExplanation(item.raw);
    return;
  }

  state.selectedDeviceName = null;
  state.selectedResourceId = item.id;
  const view = resourceCategoryView(item.kind);
  const raw = item.raw || {};
  const metrics = raw.raw_metrics || {};
  const statusStrip = [
    ["상태", item.statusLabel],
    ["분류", view.label],
    ["최신 관측", timestampAge(item.observedAt)],
  ];
  const facts = [
    ["호스트 이름", raw.hostname || item.name],
    ["노드 분류", view.label],
    ["CPU 사용률", pct(metrics.cpu_utilization)],
    ["메모리 사용률", pct(metrics.memory_usage_ratio)],
    ["GPU 사용률", metrics.gpu_utilization === null || metrics.gpu_utilization === undefined ? "N/A" : pct(metrics.gpu_utilization)],
    ["Compute / Memory / Network 압력", `${text(raw.compute_pressure, "unknown")} / ${text(raw.memory_pressure, "unknown")} / ${text(raw.network_pressure, "unknown")}`],
    ["최신 관측 시각", item.observedAt || "관측 없음"],
  ];
  const reason = `Prometheus와 Kubernetes 노드 관측 결과가 ${text(raw.node_health, "unknown")}입니다.`;

  panel.innerHTML = `
    <div class="explain-header">
      <span class="explain-badge">${escapeHtml(view.label)}</span>
      <strong>${escapeHtml(item.name)}</strong>
    </div>
    <div class="explain-status-strip">
      ${statusStrip.map(([label, value]) => `
        <div>
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(displayValue(value))}</strong>
        </div>
      `).join("")}
    </div>
    ${renderDeviceFactList(facts)}
    ${renderDeviceReasonList([{
      title: "상태 근거",
      text: reason,
    }])}
  `;
}

function cancelDeviceTelemetryHistorySelection() {
  const current = state.deviceTelemetryHistory;
  state.selectedDeviceName = null;
  state.deviceTelemetryHistory = createDeviceTelemetryHistoryState({
    window: current.window,
    requestId: current.requestId + 1,
  });
}

function selectResourceCategory(category, {render = true} = {}) {
  if (!RESOURCE_CATEGORY_VIEWS[category]) return false;
  if (isContextDetailPanelOpen()) {
    closeContextDetailPanel({restoreFocus: false});
  }
  state.selectedResourceCategory = category;
  state.selectedResourceId = null;
  cancelDeviceTelemetryHistorySelection();
  if (render) renderDevices(state.data?.devices || [], state.data);
  return true;
}

function scrollResourceCategoryIntoView(category) {
  if (!RESOURCE_CATEGORY_VIEWS[category] || typeof document === "undefined") {
    return false;
  }
  const section = document.getElementById(`resourceInventory-${category}`);
  if (!section) return false;
  section.scrollIntoView({block: "start"});
  return true;
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
  cancelDeviceTelemetryHistorySelection();
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
  cancelDeviceTelemetryHistorySelection();
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

function deviceTelemetryHistoryUrl(
  deviceName,
  windowValue,
  limit = DEVICE_TELEMETRY_LIMIT,
) {
  return `/state/devices/${encodeURIComponent(deviceName)}/telemetry?window=${encodeURIComponent(windowValue)}&limit=${limit}`;
}

async function fetchDeviceTelemetryHistory(
  deviceName,
  windowValue,
  fetchFn = fetch,
) {
  const response = await fetchFn(
    deviceTelemetryHistoryUrl(deviceName, windowValue),
    {cache: "no-store"},
  );
  if (!response.ok) {
    throw new Error(`telemetry history request failed: ${response.status}`);
  }
  const payload = await response.json();
  if (!Array.isArray(payload)) {
    throw new Error("telemetry history response must be an array");
  }
  return payload;
}

async function loadDeviceTelemetryHistory(
  device,
  windowValue = "-30m",
  fetchFn = fetch,
  renderFn = showDeviceExplanation,
) {
  const requestId = state.deviceTelemetryHistory.requestId + 1;
  state.selectedDeviceName = device.name;
  state.deviceTelemetryHistory = createDeviceTelemetryHistoryState({
    deviceName: device.name,
    window: windowValue,
    loading: true,
    requestId,
  });
  renderFn(device, state.deviceTelemetryHistory);

  try {
    const points = await fetchDeviceTelemetryHistory(
      device.name,
      windowValue,
      fetchFn,
    );
    if (
      state.deviceTelemetryHistory.requestId !== requestId
      || state.selectedDeviceName !== device.name
    ) {
      return false;
    }
    state.deviceTelemetryHistory = {
      ...state.deviceTelemetryHistory,
      points,
      loading: false,
      error: null,
    };
  } catch (error) {
    if (
      state.deviceTelemetryHistory.requestId !== requestId
      || state.selectedDeviceName !== device.name
    ) {
      return false;
    }
    state.deviceTelemetryHistory = {
      ...state.deviceTelemetryHistory,
      points: [],
      loading: false,
      error: error instanceof Error
        ? error.message
        : "telemetry history request failed",
    };
  }

  renderFn(device, state.deviceTelemetryHistory);
  return true;
}

async function loadDashboard() {
  const response = await fetch("/state/dashboard", { cache: "no-store" });
  if (!response.ok) throw new Error(`dashboard api failed: ${response.status}`);
  state.data = await response.json();
  globalThis.edgeDashboardData = state.data;
  if (typeof globalThis.updateServiceDesignerInventory === "function") {
    globalThis.updateServiceDesignerInventory(state.data);
  }
  render();
}

function setAsyncButtonState(button, {
  busy = false,
  label = "",
  success = false,
} = {}) {
  if (!button) return;
  if (!button.dataset.defaultLabel) button.dataset.defaultLabel = button.textContent.trim();
  button.disabled = busy;
  button.setAttribute("aria-busy", String(busy));
  button.dataset.state = success ? "success" : busy ? "busy" : "ready";
  button.textContent = label || button.dataset.defaultLabel;
}

async function refreshDashboardNow() {
  const button = $("refreshButton");
  setAsyncButtonState(button, {busy: true, label: "새로고침 중…"});
  try {
    const requests = [loadDashboard()];
    if (typeof globalThis.refreshServiceDemo === "function") {
      requests.push(globalThis.refreshServiceDemo());
    }
    if (
      typeof document !== "undefined"
      && document.body?.dataset.dashboardPage === "designer"
      && typeof globalThis.refreshServiceDesignerProfiles === "function"
    ) {
      requests.push(globalThis.refreshServiceDesignerProfiles());
    }
    await Promise.all(requests);
    setAsyncButtonState(button, {label: "새로고침 완료", success: true});
    globalThis.setTimeout?.(
      () => setAsyncButtonState(button),
      1200,
    );
  } catch (error) {
    setAsyncButtonState(button, {label: "새로고침 실패"});
    if ($("alertList")) {
      $("alertList").innerHTML = `<article class="item alert high"><strong>${escapeHtml(error.message)}</strong></article>`;
    }
    globalThis.setTimeout?.(
      () => setAsyncButtonState(button),
      2000,
    );
  }
}

function renderGlobalSearch(query = $("globalResourceSearch")?.value || "") {
  const input = $("globalResourceSearch");
  const status = $("globalSearchStatus");
  const container = $("globalSearchResults");
  if (!input || !status || !container) return [];
  const normalized = String(query || "").trim();
  const results = buildGlobalSearchResults(normalized, state.data || {});
  input.setAttribute("aria-expanded", String(Boolean(normalized)));
  container.hidden = !normalized;
  if (!normalized) {
    status.textContent = "";
    container.replaceChildren();
    return [];
  }
  status.textContent = results.length ? `${results.length}건` : "검색 결과 없음";
  container.innerHTML = results.length
    ? results.map((result, index) => `
        <button
          type="button"
          role="option"
          class="global-search-result"
          data-global-result-kind="${escapeHtml(result.kind)}"
          data-global-result-id="${escapeHtml(result.id)}"
          data-global-result-index="${escapeHtml(result.index ?? "")}"
          data-global-result-category="${escapeHtml(result.category ?? "")}"
          ${index === 0 ? 'data-global-first-result="true"' : ""}
        >
          <span>${escapeHtml({node: "NODE", device: "DEVICE", service: "SERVICE"}[result.kind] || result.kind)}</span>
          <strong>${escapeHtml(result.label)}</strong>
          <small>${escapeHtml(result.detail)}</small>
        </button>
      `).join("")
    : `<p class="global-search-empty">일치하는 노드·디바이스·서비스가 없습니다.</p>`;
  return results;
}

function openGlobalSearchResult(target) {
  const button = target?.closest?.("[data-global-result-kind]");
  if (!button) return false;
  const kind = button.dataset.globalResultKind;
  const id = button.dataset.globalResultId;
  if (typeof globalThis.showDashboardPage === "function") {
    globalThis.showDashboardPage("inventory");
  }
  if (globalThis.location && globalThis.location.hash !== "#inventory") {
    globalThis.location.hash = "inventory";
  }
  if (kind === "node" || kind === "device") {
    const category = kind === "node"
      ? button.dataset.globalResultCategory || "physical"
      : "sensor";
    selectResourceCategory(category, {render: false});
    state.selectedNodeName = null;
    state.selectedNodeFilterValues = [];
    const item = resourceCategoryItems(state.data || {}, category)
      .find((resource) => resource.id === id);
    if (item) {
      if (item.kind === "sensor") {
        void loadDeviceTelemetryHistory(item.raw);
      } else {
        showResourceExplanation(item);
      }
      renderDevices(state.data?.devices || []);
      scrollResourceCategoryIntoView(category);
      const trigger = Array.from(
        document.querySelectorAll('[data-resource-id]'),
      ).find((candidate) => (
        candidate.dataset.resourceKind === category
        && candidate.dataset.resourceId === id
      ));
      markSelectedExplain(trigger);
      openContextDetailPanel(trigger);
    }
  } else if (kind === "service") {
    state.selectedTopologyService = id;
    renderTopology(state.data?.resource_profiles || {}, state.data?.kpis || {});
  }
  const input = $("globalResourceSearch");
  const container = $("globalSearchResults");
  if (input) input.value = "";
  if (container) container.hidden = true;
  if (input) input.setAttribute("aria-expanded", "false");
  setText("globalSearchStatus", `${id} 열기 완료`);
  return true;
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
  const serverItems = resourceCategoryItems(data, "server");
  const physicalItems = resourceCategoryItems(data, "physical");
  const sensorItems = resourceCategoryItems(data, "sensor");
  const resourceState = data.resource_profiles || {};
  const deviceObservationFailed = deviceObservationUnavailable(data);
  const deviceObservationError = text(
    data.device_observation_error,
    "EdgeX 등록 디바이스 관측 불가",
  );
  const unavailableDevices = devices.filter((device) => deviceStatus(device) === "unavailable").length;
  const degradedDevices = devices.filter((device) => deviceStatus(device) === "degraded").length;
  const boundDevices = Number(kpis.device_service_available_count) || 0;
  const registeredDevices = Number(kpis.registered_device_count) || devices.length;
  const profiledContainers = Number(kpis.service_resource_profile_container_count) || 0;
  const sampledContainers = Math.round(profiledContainers * ratio(kpis.service_resource_usage_coverage_ratio));
  const availableCount = (items) => items.filter((item) => item.status === "available").length;
  setText("updatedAt", `갱신 ${new Date(data.generated_at).toLocaleString()}`);
  setText("edgeAiServerCount", serverItems.length);
  setText("edgeAiServerHealth", `${availableCount(serverItems)}/${serverItems.length}개 Available`);
  setText("physicalDeviceCount", physicalItems.length);
  setText("physicalDeviceHealth", `${availableCount(physicalItems)}/${physicalItems.length}개 Available`);
  setText("sensorDeviceCount", deviceObservationFailed ? "관측 불가" : sensorItems.length);
  setText(
    "sensorDeviceHealth",
    deviceObservationFailed
      ? deviceObservationError
      : `${availableCount(sensorItems)}/${sensorItems.length}개 Available`,
  );
  setText("resourceProfileCount", text(kpis.service_resource_profile_count, 0));
  setText("placementFitCaption", `${text(kpis.service_resource_profile_pod_count, 0)}개 pod · ${text(kpis.service_resource_partially_declared_profile_count, 0)}개 spec 누락`);
  setText("serviceCpuUsage", threeDecimal(kpis.service_resource_current_cpu_usage_cores));
  setText("serviceCpuUsageCaption", `${threeDecimal(kpis.service_resource_request_cpu_cores)} core request`);
  setText("serviceMemoryUsage", `${oneDecimal(kpis.service_resource_current_memory_working_set_mib)} MiB`);
  setText("serviceMemoryUsageCaption", `${oneDecimal(kpis.service_resource_request_memory_mib)} MiB request`);
  setText("usageCoverageRatio", pct(kpis.service_resource_usage_coverage_ratio));
  setText("usageCoverageCaption", `${sampledContainers}/${profiledContainers}개 컨테이너 수집`);
  setText("serviceBindingRatio", deviceObservationFailed ? "관측 불가" : pct(kpis.device_service_availability_ratio));
  setText("serviceBindingCaption", deviceObservationFailed ? "EdgeX 등록 디바이스 관측 불가" : `${boundDevices}/${registeredDevices}개 디바이스 연결`);
  setText("riskCount", deviceObservationFailed ? "EdgeX 관측 불가" : `${unavailableDevices}개 unavailable · ${degradedDevices}개 degraded`);
  renderOverviewVisuals(data, kpis, devices);
  renderServerOverview(data);
  renderPhysicalDeviceOverview(data);
  renderKpiCatalog(kpis, deviceObservationFailed);
  renderNodeMetricMatrix(nodes);
  if ($("globalResourceSearch")?.value.trim()) renderGlobalSearch();
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
  const resourceItems = Object.keys(RESOURCE_CATEGORY_VIEWS)
    .flatMap((category) => resourceCategoryItems(data, category));
  const total = resourceItems.length || 0;
  const available = resourceItems.filter((item) => item.status === "available").length;
  const degraded = resourceItems.filter((item) => item.status === "degraded").length;
  const unavailable = resourceItems.filter((item) => item.status === "unavailable").length;
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
  setText("overviewMetricScope", `${nodeScope} · 서버 · 엣지 노드 · EdgeX 등록 디바이스`);
  setText(
    "overviewHealthCaption",
    deviceObservationFailed
      ? "센서 상태를 가져오지 못했습니다."
      : `${available}/${total}개 Available`,
  );
  const fleetStatus = $("overviewFleetStatus");
  if (fleetStatus) {
    const stateView = deviceObservationFailed
      ? {label: "관측 불가", status: "unknown"}
      : unavailable > 0
        ? {label: "장애 확인", status: "unavailable"}
        : degraded + unknown > 0
          ? {label: "확인 필요", status: "degraded"}
          : {label: "정상 운영", status: "available"};
    fleetStatus.textContent = stateView.label;
    fleetStatus.dataset.status = stateView.status;
  }
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
  if (key.includes("device_service") || key.includes("edgex")) return "센서 디바이스";
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

function observedNodeMetric(node = {}, key) {
  const metrics = node.raw_metrics || {};
  if (!Object.prototype.hasOwnProperty.call(metrics, key)) return null;
  const value = Number(metrics[key]);
  return Number.isFinite(value) ? ratio(value) : null;
}

function serverPressureNeedsAttention(node = {}) {
  return [
    node.compute_pressure,
    node.memory_pressure,
    node.network_pressure,
  ].some((value) => ["medium", "high"].includes(text(value, "").toLowerCase()));
}

function nodeOverviewModel(data = {}, category = "server") {
  const items = resourceCategoryItems(data, category);
  const average = (key) => {
    const values = items
      .map((item) => observedNodeMetric(item.raw, key))
      .filter((value) => value !== null);
    return values.length
      ? values.reduce((sum, value) => sum + value, 0) / values.length
      : null;
  };
  const observedTimes = items
    .map((item) => new Date(item.observedAt).getTime())
    .filter(Number.isFinite);
  return {
    items,
    total: items.length,
    available: items.filter((item) => item.status === "available").length,
    averageCpu: average("cpu_utilization"),
    averageMemory: average("memory_usage_ratio"),
    gpuObserved: items.filter(
      (item) => observedNodeMetric(item.raw, "gpu_utilization") !== null,
    ).length,
    pressureAttention: items.filter(
      (item) => serverPressureNeedsAttention(item.raw),
    ).length,
    latestObservedAt: observedTimes.length
      ? new Date(Math.max(...observedTimes)).toISOString()
      : null,
  };
}

function serverOverviewModel(data = {}) {
  return nodeOverviewModel(data, "server");
}

function physicalDeviceOverviewModel(data = {}) {
  return nodeOverviewModel(data, "physical");
}

function renderServerMetric(label, value, serverName) {
  const percentage = value === null ? null : Math.round(value * 100);
  const ariaValue = percentage === null
    ? 'aria-valuetext="관측 불가"'
    : `aria-valuenow="${percentage}"`;
  return `
    <div class="server-status-metric">
      <span>${escapeHtml(label)}</span>
      <strong>${percentage === null ? "N/A" : `${percentage}%`}</strong>
      <div
        class="server-status-meter ${percentage === null ? "unobserved" : ""}"
        role="progressbar"
        aria-label="${escapeHtml(serverName)} ${escapeHtml(label)} 사용률"
        aria-valuemin="0"
        aria-valuemax="100"
        ${ariaValue}
      ><i style="width:${percentage === null ? 0 : percentage}%"></i></div>
    </div>
  `;
}

function physicalNodeTypeLabel(node = {}) {
  return {
    edge_ai_device: "AI 엣지 노드",
    edge_light_device: "경량 엣지 노드",
    edge_device: "엣지 노드",
  }[text(node.node_type, "").toLowerCase()] || "물리 노드";
}

function renderNodeStatusRows(items = [], options = {}) {
  const {
    emptyLabel = "관측된 노드가 없습니다.",
    showNodeType = false,
  } = options;
  if (!items.length) {
    return `<div class="server-status-empty">${escapeHtml(emptyLabel)}</div>`;
  }
  return items.map((item) => {
    const raw = item.raw || {};
    const cpu = observedNodeMetric(raw, "cpu_utilization");
    const memory = observedNodeMetric(raw, "memory_usage_ratio");
    const gpu = observedNodeMetric(raw, "gpu_utilization");
    const pressure = [
      text(raw.compute_pressure, "unknown"),
      text(raw.memory_pressure, "unknown"),
      text(raw.network_pressure, "unknown"),
    ].join(" / ");
    const observedAge = timestampAge(item.observedAt).replace("이벤트 없음", "관측 없음");
    const observationLabel = showNodeType
      ? `${physicalNodeTypeLabel(raw)} · ${observedAge}`
      : observedAge;
    return `
      <article class="server-status-row ${item.kind === "physical" ? "physical-device-status-row" : ""}" data-status="${escapeHtml(item.status)}">
        <div class="server-status-identity">
          <span class="server-status-label">
            <i aria-hidden="true"></i>${escapeHtml(item.statusLabel)}
          </span>
          <strong title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</strong>
          <small>${escapeHtml(observationLabel)}</small>
        </div>
        ${renderServerMetric("CPU", cpu, item.name)}
        ${renderServerMetric("메모리", memory, item.name)}
        ${renderServerMetric("GPU", gpu, item.name)}
        <div class="server-status-pressure">
          <span>C / M / N 압력</span>
          <strong aria-label="Compute, Memory, Network 압력 ${escapeHtml(pressure)}">${escapeHtml(pressure)}</strong>
        </div>
      </article>
    `;
  }).join("");
}

function renderServerStatusRows(items = []) {
  return renderNodeStatusRows(items, {
    emptyLabel: "관측된 엣지 AI 서버가 없습니다.",
  });
}

function renderPhysicalDeviceStatusRows(items = []) {
  return renderNodeStatusRows(items, {
    emptyLabel: "관측된 현장 엣지 노드가 없습니다.",
    showNodeType: true,
  });
}

function renderServerOverview(data = {}) {
  const model = serverOverviewModel(data);
  setText(
    "serverOverviewAvailability",
    model.total
      ? `${model.available}/${model.total}대 Available`
      : "서버 관측 없음",
  );
  setText(
    "serverOverviewCpu",
    model.averageCpu === null ? "N/A" : pct(model.averageCpu),
  );
  setText(
    "serverOverviewMemory",
    model.averageMemory === null ? "N/A" : pct(model.averageMemory),
  );
  setText("serverOverviewGpu", `${model.gpuObserved}/${model.total}대`);
  setText("serverOverviewPressure", `${model.pressureAttention}대`);
  setText(
    "serverOverviewObservedAt",
    model.latestObservedAt
      ? `현재 관측값 · ${timestampAge(model.latestObservedAt)} · Prometheus / Kubernetes`
      : "관측 없음 · Prometheus / Kubernetes",
  );
  const list = $("serverStatusList");
  if (list) list.innerHTML = renderServerStatusRows(model.items);
  return model;
}

function renderPhysicalDeviceOverview(data = {}) {
  const model = physicalDeviceOverviewModel(data);
  setText(
    "physicalDeviceOverviewAvailability",
    model.total
      ? `${model.available}/${model.total}대 Available`
      : "현장 엣지 노드 관측 없음",
  );
  setText(
    "physicalDeviceOverviewCpu",
    model.averageCpu === null ? "N/A" : pct(model.averageCpu),
  );
  setText(
    "physicalDeviceOverviewMemory",
    model.averageMemory === null ? "N/A" : pct(model.averageMemory),
  );
  setText("physicalDeviceOverviewGpu", `${model.gpuObserved}/${model.total}대`);
  setText("physicalDeviceOverviewPressure", `${model.pressureAttention}대`);
  setText(
    "physicalDeviceOverviewObservedAt",
    model.latestObservedAt
      ? `현재 관측값 · ${timestampAge(model.latestObservedAt)} · Prometheus / Kubernetes`
      : "관측 없음 · Prometheus / Kubernetes",
  );
  const list = $("physicalDeviceStatusList");
  if (list) list.innerHTML = renderPhysicalDeviceStatusRows(model.items);
  return model;
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
                <span>load ${escapeHtml(threeDecimal(metrics.load_average))}${Number(metrics.cpu_logical_cores) > 0 ? ` / ${escapeHtml(Math.round(Number(metrics.cpu_logical_cores)))} CPU` : ""}</span>
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
  const select = $("nodeFilterSelect");
  if (!select) return;
  const options = nodes.map((node, index) => {
    const displayName = nodeDisplayName(node, index);
    const status = text(node.node_health, "unknown");
    return `<option value="${escapeHtml(displayName)}" data-node-index="${index}">${escapeHtml(displayName)} · ${escapeHtml(status)}</option>`;
  }).join("");
  select.innerHTML = `<option value="">모든 노드</option>${options}`;
  select.value = state.selectedNodeName || "";
}

function deviceObservationUnavailable(data = state.data) {
  return Boolean(data?.device_observation_error);
}

function resourceCategoryObservationError(
  data = state.data,
  category = state.selectedResourceCategory,
) {
  if (category === "sensor") return data?.device_observation_error || "";
  return "";
}

function deviceFilterEmptyText(
  data = state.data,
  category = state.selectedResourceCategory,
) {
  const error = resourceCategoryObservationError(data, category);
  if (error) return `${resourceCategoryView(category).label} 관측 불가`;
  if (state.selectedNodeName) {
    return `${state.selectedNodeName}에 해당하는 ${resourceCategoryView(category).label}가 없습니다.`;
  }
  return resourceCategoryView(category).emptyLabel;
}

function resourceItemMatchesNodeFilter(item) {
  if (!state.selectedNodeName) return true;
  const labels = [
    text(item?.nodeName, "").trim(),
    cleanNodeLabel(item?.nodeName, ""),
  ].filter(Boolean);
  return labels.some((label) => state.selectedNodeFilterValues.includes(label));
}

function renderResourceInventoryRows(
  items = [],
  {
    category = state.selectedResourceCategory,
    selectedResourceId = null,
    contextPanelOpen = false,
  } = {},
) {
  const latestLabel = resourceCategoryView(category).latestLabel;
  return items.map((item) => {
    const isSelected = selectedResourceId === item.id;
    const observedAt = text(item.observedAt, "");
    const isSensor = item.kind === "sensor";
    return `
      <tr class="sensor-device-row resource-inventory-row ${isSelected ? "selected" : ""}" data-resource-row="${escapeHtml(item.id)}">
        <td class="sensor-device-name-cell" data-label="이름">
          <strong class="sensor-device-name" title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</strong>
        </td>
        <td data-label="상태">
          <span class="sensor-status sensor-status-${escapeHtml(item.status)}" aria-label="상태 ${escapeHtml(item.statusLabel)}">
            <span class="sensor-status-dot" aria-hidden="true"></span>
            <span class="sensor-status-label">${escapeHtml(item.statusLabel)}</span>
          </span>
        </td>
        <td class="sensor-event-cell" data-label="${escapeHtml(latestLabel)}">
          <time datetime="${escapeHtml(observedAt)}">${escapeHtml(timestampAge(item.observedAt))}</time>
        </td>
        <td class="sensor-device-action-cell">
          <button
            type="button"
            class="sensor-detail-button explainable"
            data-explain-type="${isSensor ? "device" : "resource"}"
            ${isSensor ? `data-device-name="${escapeHtml(item.id)}"` : ""}
            data-resource-kind="${escapeHtml(item.kind)}"
            data-resource-id="${escapeHtml(item.id)}"
            aria-label="${escapeHtml(item.name)} 상세정보 보기"
            aria-controls="contextDetailPanel"
            aria-expanded="${isSelected && contextPanelOpen ? "true" : "false"}"
          >상세보기</button>
        </td>
      </tr>
    `;
  }).join("");
}

function renderResourceInventorySection({
  category,
  items = [],
  visibleItems = items,
  selectedResourceId = null,
  contextPanelOpen = false,
  observationError = "",
  filtered = false,
} = {}) {
  const view = resourceCategoryView(category);
  const available = visibleItems.filter(
    (item) => item.status === "available",
  ).length;
  const summary = observationError
    ? "관측 불가"
    : filtered
      ? `${visibleItems.length}/${items.length}개 · Available ${available}개`
      : `${items.length}개 · Available ${available}개`;
  const emptyText = observationError
    ? `${view.label} 관측 불가`
    : filtered && state.selectedNodeName
      ? `${state.selectedNodeName}에 해당하는 ${view.label}가 없습니다.`
      : view.emptyLabel;
  const rows = visibleItems.length
    ? renderResourceInventoryRows(
        visibleItems,
        {
          category,
          selectedResourceId,
          contextPanelOpen,
        },
      )
    : `<tr class="sensor-device-empty"><td colspan="4">${escapeHtml(emptyText)}</td></tr>`;
  return `
    <section
      id="resourceInventory-${escapeHtml(category)}"
      class="resource-inventory-section"
      data-resource-category-section="${escapeHtml(category)}"
      aria-labelledby="resourceInventoryTitle-${escapeHtml(category)}"
    >
      <div class="resource-inventory-section-head">
        <div>
          <span>${escapeHtml(category === "sensor" ? "EdgeX inventory" : "운영 자원")}</span>
          <h3 id="resourceInventoryTitle-${escapeHtml(category)}">${escapeHtml(view.label)}</h3>
        </div>
        <strong>${escapeHtml(summary)}</strong>
      </div>
      <div class="sensor-table-shell" role="region" aria-label="${escapeHtml(view.label)} 목록" tabindex="0">
        <table class="sensor-device-table">
          <thead>
            <tr>
              <th scope="col">이름</th>
              <th scope="col">상태</th>
              <th scope="col">${escapeHtml(view.latestLabel)}</th>
              <th scope="col"><span class="sr-only">상세정보</span></th>
            </tr>
          </thead>
          <tbody class="resource-inventory-body" data-resource-category-list="${escapeHtml(category)}">${rows}</tbody>
        </table>
      </div>
    </section>
  `;
}

function renderSensorDeviceRows(
  devices = [],
  selectedDeviceName = null,
  contextPanelOpen = false,
) {
  return renderResourceInventoryRows(
    devices.map(normalizeSensorResourceItem),
    {
      category: "sensor",
      selectedResourceId: selectedDeviceName,
      contextPanelOpen,
    },
  );
}

function renderDevices(devices, data = state.data) {
  const dashboardData = data || {devices: devices || []};
  const inventories = RESOURCE_CATEGORY_ORDER.map((category) => {
    const items = resourceCategoryItems(dashboardData, category);
    return {
      category,
      items,
      visibleItems: items.filter(resourceItemMatchesNodeFilter),
    };
  });
  const total = inventories.reduce((sum, inventory) => sum + inventory.items.length, 0);
  const visibleTotal = inventories.reduce(
    (sum, inventory) => sum + inventory.visibleItems.length,
    0,
  );
  const available = inventories.reduce(
    (sum, inventory) => sum + inventory.visibleItems.filter(
      (item) => item.status === "available",
    ).length,
    0,
  );
  const list = $("resourceInventorySections");
  renderDeviceFilterSummary(total, visibleTotal);
  setText("inventoryTitle", "전체 디바이스");
  setText(
    "assetCount",
    `${visibleTotal}개 · Available ${available}개`,
  );
  const topology = $("sensorTopologyPanel");
  if (topology) topology.hidden = false;
  if (!list) return;
  list.innerHTML = inventories.map((inventory) => renderResourceInventorySection({
    ...inventory,
    selectedResourceId: inventory.category === "sensor"
      ? state.selectedDeviceName
      : state.selectedResourceCategory === inventory.category
        ? state.selectedResourceId
        : null,
    contextPanelOpen: isContextDetailPanelOpen(),
    observationError: resourceCategoryObservationError(
      dashboardData,
      inventory.category,
    ),
    filtered: Boolean(state.selectedNodeName),
  })).join("");
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
      title: "EdgeX 등록 디바이스 관측 불가",
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
  const attentionCount = state.alerts.length;
  setText("attentionCount", attentionCount);
  setText(
    "attentionCaption",
    attentionCount ? `${attentionCount}개 항목 확인` : "정상 운영",
  );
  const attentionMetric = $("attentionCount")?.closest?.(".metric");
  if (attentionMetric) {
    attentionMetric.dataset.status = attentionCount ? "attention" : "available";
  }

  const overviewList = $("overviewAlertList");
  if (overviewList) {
    overviewList.innerHTML = attentionCount
      ? state.alerts.slice(0, 6).map((alert, index) => `
          <button
            type="button"
            class="overview-alert-row overview-alert-${escapeHtml(alert.level)} explainable"
            data-explain-type="issue"
            data-alert-index="${index}"
            aria-label="${escapeHtml(alert.title)} 상세정보 보기"
          >
            <span class="overview-alert-indicator" aria-hidden="true"></span>
            <span class="overview-alert-copy">
              <strong>${escapeHtml(alert.title)}</strong>
              <small>${escapeHtml(alert.text)}</small>
            </span>
            <span class="overview-alert-action">상세보기</span>
          </button>
        `).join("")
      : `
        <div class="overview-all-clear">
          <span class="overview-all-clear-mark" aria-hidden="true"></span>
          <div>
            <strong>모든 센서가 정상입니다.</strong>
            <span>연결 상태와 최신 이벤트가 기준을 충족합니다.</span>
          </div>
        </div>
      `;
  }

  const hiddenList = $("alertList");
  if (!hiddenList) return;
  hiddenList.innerHTML = state.alerts.length
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
              <span>수집 서비스: ${escapeHtml(text(device.device_service_name, "unknown"))}</span>
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



function markSelectedExplain(target, documentRef = document) {
  if (!documentRef?.querySelectorAll) return;
  documentRef.querySelectorAll(".explainable").forEach((item) => {
    item.classList.remove("selected");
    item.setAttribute("aria-expanded", "false");
  });
  if (!target) return;
  target.classList.add("selected");
  target.setAttribute("aria-expanded", "true");
}

let contextDetailTrigger = null;

function isContextDetailPanelOpen(documentRef = document) {
  const panel = documentRef?.getElementById?.("contextDetailPanel");
  return Boolean(panel && !panel.hidden);
}

function resolveContextDetailTrigger(documentRef = document) {
  if (contextDetailTrigger?.isConnected) return contextDetailTrigger;
  const type = contextDetailTrigger?.dataset?.explainType;
  const deviceName = contextDetailTrigger?.dataset?.deviceName;
  const resourceId = contextDetailTrigger?.dataset?.resourceId;
  return Array.from(documentRef.querySelectorAll?.("[data-explain-type]") || [])
    .find((item) => (
      item.dataset.explainType === type
      && (!deviceName || item.dataset.deviceName === deviceName)
      && (!resourceId || item.dataset.resourceId === resourceId)
    )) || null;
}

function openContextDetailPanel(trigger = null, documentRef = document) {
  const panel = documentRef.getElementById("contextDetailPanel");
  const backdrop = documentRef.getElementById("contextDetailBackdrop");
  if (!panel) return false;
  contextDetailTrigger = trigger;
  panel.hidden = false;
  panel.setAttribute("aria-hidden", "false");
  if (backdrop) backdrop.hidden = false;
  documentRef.body?.classList.add("context-detail-open");
  documentRef.getElementById("contextDetailClose")?.focus?.({preventScroll: true});
  return true;
}

function closeContextDetailPanel(
  {restoreFocus = true, documentRef = document} = {},
) {
  const panel = documentRef.getElementById("contextDetailPanel");
  const backdrop = documentRef.getElementById("contextDetailBackdrop");
  if (!panel || panel.hidden) return false;
  const restoreTarget = resolveContextDetailTrigger(documentRef);
  panel.hidden = true;
  panel.setAttribute("aria-hidden", "true");
  if (backdrop) backdrop.hidden = true;
  documentRef.body?.classList.remove("context-detail-open");
  if (state.selectedDeviceName) {
    cancelDeviceTelemetryHistorySelection();
  }
  state.selectedResourceId = null;
  renderDevices(state.data?.devices || [], state.data);
  markSelectedExplain(null, documentRef);
  if (restoreFocus && restoreTarget?.isConnected) {
    restoreTarget.focus?.({preventScroll: true});
  }
  contextDetailTrigger = null;
  return true;
}

function handleNodeFilterSelection(target) {
  const nodeTarget = target.closest?.("[data-node-filter]");
  if (!nodeTarget) return false;
  applyNodeDeviceFilter(nodeTarget.dataset.nodeFilter, nodeTarget.dataset.nodeIndex);
  return true;
}

function handleTelemetryHistoryAction(
  target,
  loadFn = loadDeviceTelemetryHistory,
) {
  const rangeTarget = target?.closest?.("[data-telemetry-window]");
  const refreshTarget = target?.closest?.("[data-telemetry-refresh]");
  if (!rangeTarget && !refreshTarget) return false;

  const device = (state.data?.devices || [])
    .find((item) => item.name === state.selectedDeviceName);
  if (!device) return true;
  const windowValue = rangeTarget?.dataset.telemetryWindow
    || state.deviceTelemetryHistory.window;
  void loadFn(device, windowValue);
  return true;
}


function handleExplainSelection(target) {
  const explainTarget = target.closest?.("[data-explain-type]");
  if (!explainTarget) return;
  const type = explainTarget.dataset.explainType;
  if (type === "device") {
    state.selectedResourceCategory = "sensor";
    const deviceName = explainTarget.dataset.deviceName;
    const device = (state.data?.devices || []).find((item) => item.name === deviceName);
    void loadDeviceTelemetryHistory(device);
    renderDevices(state.data?.devices || []);
    const selectedRow = Array.from(document.querySelectorAll('[data-explain-type="device"]')).find((item) => item.dataset.deviceName === deviceName);
    markSelectedExplain(selectedRow);
  }
  if (type === "resource") {
    const category = explainTarget.dataset.resourceKind;
    state.selectedResourceCategory = category;
    const resourceId = explainTarget.dataset.resourceId;
    const item = resourceCategoryItems(state.data || {}, category)
      .find((resource) => resource.id === resourceId);
    if (!item) return;
    showResourceExplanation(item);
    renderDevices(state.data?.devices || [], state.data);
    const selectedRow = Array.from(document.querySelectorAll('[data-explain-type="resource"]'))
      .find((row) => (
        row.dataset.resourceKind === category
        && row.dataset.resourceId === resourceId
      ));
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
  openContextDetailPanel(
    document.querySelector(".explainable.selected") || explainTarget,
  );
}

if (typeof document !== "undefined") {
  document.addEventListener("click", (event) => {
    const categoryTarget = event.target.closest?.("[data-resource-category]");
    if (categoryTarget) {
      selectResourceCategory(categoryTarget.dataset.resourceCategory);
      return;
    }
    const categoryLink = event.target.closest?.("[data-resource-category-link]");
    if (categoryLink) {
      const category = categoryLink.dataset.resourceCategoryLink;
      selectResourceCategory(category);
      if (typeof globalThis.showDashboardPage === "function") {
        globalThis.showDashboardPage("inventory");
      }
      if (globalThis.location && globalThis.location.hash !== "#inventory") {
        globalThis.location.hash = "inventory";
      }
      globalThis.requestAnimationFrame?.(() => {
        scrollResourceCategoryIntoView(category);
      });
      return;
    }
    if (handleTelemetryHistoryAction(event.target)) return;
    if (handleNodeFilterSelection(event.target)) return;
    handleExplainSelection(event.target);
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && closeContextDetailPanel()) {
      event.preventDefault();
      return;
    }
    if (event.key !== "Enter" && event.key !== " ") return;
    const target = event.target?.closest?.("[data-explain-type], [data-node-filter]");
    if (!target) return;
    event.preventDefault();
    if (handleNodeFilterSelection(target)) return;
    handleExplainSelection(target);
  });
  $("contextDetailClose")?.addEventListener("click", () => {
    closeContextDetailPanel();
  });
  $("contextDetailBackdrop")?.addEventListener("click", () => {
    closeContextDetailPanel();
  });
}

if (typeof document !== "undefined" && $("nodeFilterSelect")) {
  $("nodeFilterSelect").addEventListener("change", (event) => {
    const option = event.currentTarget.selectedOptions?.[0];
    const nodeName = event.currentTarget.value || null;
    const nodeIndex = nodeName ? option?.dataset?.nodeIndex : null;
    applyNodeDeviceFilter(nodeName, nodeIndex);
  });
}

if (typeof document !== "undefined" && $("refreshButton")) {
  $("refreshButton").addEventListener("click", refreshDashboardNow);
}

if (typeof document !== "undefined" && $("globalResourceSearch")) {
  $("globalResourceSearch").addEventListener("input", (event) => {
    renderGlobalSearch(event.target.value);
  });
  $("globalResourceSearch").addEventListener("focus", (event) => {
    if (event.target.value.trim()) renderGlobalSearch(event.target.value);
  });
  $("globalResourceSearch").addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      event.currentTarget.value = "";
      renderGlobalSearch("");
      return;
    }
    if (event.key === "Enter") {
      const first = $("globalSearchResults")?.querySelector("[data-global-first-result]");
      if (first) {
        event.preventDefault();
        openGlobalSearchResult(first);
      }
    }
  });
  $("globalSearchResults")?.addEventListener("click", (event) => {
    openGlobalSearchResult(event.target);
  });
  document.addEventListener("click", (event) => {
    if (event.target.closest?.(".global-search")) return;
    const results = $("globalSearchResults");
    if (results) results.hidden = true;
    $("globalResourceSearch")?.setAttribute("aria-expanded", "false");
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
    cancelDeviceTelemetryHistorySelection,
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
    buildGlobalSearchResults,
    createDeviceTelemetryHistoryState,
    deviceTelemetryHistoryUrl,
    fetchDeviceTelemetryHistory,
    handleTelemetryHistoryAction,
    loadDeviceTelemetryHistory,
    openContextDetailPanel,
    closeContextDetailPanel,
    renderDeviceTelemetryHistory,
    renderResourceInventoryRows,
    renderResourceInventorySection,
    renderPhysicalDeviceOverview,
    renderPhysicalDeviceStatusRows,
    renderServerOverview,
    renderServerStatusRows,
    renderSensorDeviceRows,
    renderGlobalSearch,
    refreshDashboardNow,
    sensorDeviceStatusLabel,
    sensorResourceDisplayName,
    resourceCategoryItems,
    resourceCategoryView,
    resourceAvailabilityStatus,
    physicalDeviceOverviewModel,
    serverOverviewModel,
    selectResourceCategory,
    scrollResourceCategoryIntoView,
    submitOperatorChat,
    renderTopology,
    state,
  };
}
