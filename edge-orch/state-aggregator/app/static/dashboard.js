const state = {
  data: null,
  refreshMs: 5000,
  selectedDeviceName: null,
  selectedNodeName: null,
  selectedNodeFilterValues: [],
  telemetryHistory: {},
  alerts: [],
  chat: {
    loading: false,
    messages: [],
  },
};

const $ = (id) => document.getElementById(id);

function pct(value) {
  return `${Math.round((value || 0) * 100)}%`;
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

function age(value) {
  if (value === null || value === undefined) return "DB timestamp 없음";

  const minutes = Math.floor(value / 60);
  const seconds = Math.floor(value % 60);

  if (minutes === 0) return `${seconds}s ago`;
  return `${minutes}m ${seconds}s ago`;
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
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
  return device?.overall_status || device?.status || "unknown";
}

function deviceReason(device) {
  return device?.reason || device?.status_reason || "데이터 없음";
}

function isOperationalDevice(device) {
  const status = deviceStatus(device);
  return status === "available" || status === "healthy";
}

function sortDevicesStatusFirst(devices = []) {
  return [...devices].sort((left, right) => {
    const statusDelta = Number(isOperationalDevice(right)) - Number(isOperationalDevice(left));
    if (statusDelta !== 0) return statusDelta;
    return text(left?.name, "").localeCompare(text(right?.name, ""));
  });
}

function deviceNodeLabel(device) {
  return cleanNodeLabel(device?.node_name || device?.nodeName, "unassigned");
}

function filteredDevices(devices = []) {
  if (!state.selectedNodeName) return sortDevicesStatusFirst(devices);
  return sortDevicesStatusFirst(devices.filter((device) => {
    const labels = [text(device?.node_name, "").trim(), text(device?.nodeName, "").trim(), deviceNodeLabel(device)].filter(Boolean);
    return labels.some((label) => state.selectedNodeFilterValues.includes(label));
  }));
}

function renderDeviceFilterSummary(totalCount, visibleCount) {
  const label = $("deviceFilterLabel");
  const clear = $("clearNodeFilter");
  if (label) {
    label.textContent = state.selectedNodeName
      ? `${visibleCount}/${totalCount} on ${state.selectedNodeName}`
      : "registered assets";
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
  const rules = [];
  const status = deviceStatus(device);
  if (status === "available" || status === "healthy") {
    rules.push({ id: "Sensor OK", title: "latest telemetry sample is fresh", text: "node와 mapper 선행 조건이 정상이고 InfluxDB latest telemetry가 freshness 기준을 만족해 available로 판단됩니다." });
  }
  if (device.telemetry_enabled === true && device.telemetry_fresh === false) {
    rules.push({ id: "Sensor Stale", title: "sensor data missing/stale", text: "InfluxDB latest telemetry가 없거나 오래되어 degraded로 판단됩니다. publisher/MQTT/mapper/DB 적재 경로를 확인합니다." });
  }
  if (device.mapper_running === false) {
    rules.push({ id: "Mapper", title: "mapper not running", text: "이 device가 할당된 node에서 mqttvirtual mapper가 Running 상태가 아닙니다." });
  }
  if (device.node_ready === false) {
    rules.push({ id: "Node", title: "assigned node unavailable", text: "할당 node가 dashboard 기준 unavailable입니다. node 상태와 edgecore/cloudcore 연결을 확인합니다." });
  }
  if (device.severity === "critical") {
    rules.push({ id: "Severity", title: "critical severity", text: "최근 센서 데이터는 있지만 severity가 critical이므로 degraded로 표시됩니다." });
  }
  if (device.service_connected === false) {
    rules.push({ id: "Service", title: "service binding missing", text: "서비스 데모 그룹에 아직 연결되지 않았습니다. device naming 또는 binding rule을 확인합니다." });
  }
  if (!rules.length) {
    rules.push({ id: "Status", title: "current state", text: deviceReason(device) });
  }
  return rules;
}

const KPI_EXPLANATIONS = {
  active_node_count: "현재 사용 가능한 node 수입니다.",
  registered_device_count: "KubeEdge에 등록된 Device CR 수와 available device 수를 함께 봅니다.",
  live_device_count: "control/status 기준 available인 device 수입니다. 센서 데이터 freshness와 분리됩니다.",
  telemetry_device_count: "센서 데이터 적재/수집 대상 device 수입니다.",
  device_telemetry_ratio: "센서 데이터 적재가 설정된 device 비율입니다. freshness 비율은 아닙니다.",
  fresh_telemetry_device_count: "fresh sensor data device 수입니다.",
  telemetry_freshness_ratio: "fresh sensor data device 수 / telemetry-enabled device 수입니다.",
  fresh_sensor_data_device_count: "최근 센서 데이터 sample이 들어온 실제 sensor stream 수입니다.",
  sensor_data_freshness_ratio: "센서 데이터 freshness KPI입니다. availability 판단과 분리해서 봅니다.",
  operator_focus_count: "운영자가 먼저 볼 degraded/unavailable device와 non-healthy node 수입니다.",
  service_bound_device_count: "서비스 데모 그룹에 연결된 device 수입니다.",
  device_service_binding_ratio: "service-bound device 수 / 전체 registered device 수입니다.",
  service_resource_profile_count: "현재 Running Pod를 서비스 단위로 묶어 만든 자원 요구량 프로파일 수입니다.",
  service_resource_profile_pod_count: "프로파일링 대상 Running Pod 수입니다.",
  service_resource_request_cpu_cores: "실행 서비스들이 Kubernetes requests.cpu로 선언한 CPU core 합계입니다.",
  service_resource_request_memory_mib: "실행 서비스들이 Kubernetes requests.memory로 선언한 memory MiB 합계입니다.",
  service_resource_current_cpu_usage_cores: "Prometheus/cAdvisor에서 가져온 현재 컨테이너 CPU 사용량(core) 합계입니다.",
  service_resource_current_memory_working_set_mib: "Prometheus/cAdvisor에서 가져온 현재 컨테이너 memory working set(MiB) 합계입니다.",
  service_resource_usage_coverage_ratio: "현재 사용량 샘플이 붙은 컨테이너 비율입니다.",
  service_resource_limit_gpu_units: "실행 서비스들이 limits의 GPU 리소스로 선언한 GPU 단위 합계입니다.",
  service_resource_partially_declared_profile_count: "requests/limits가 일부 또는 전체 누락된 서비스 프로파일 수입니다.",
};

function explainKpi(key, kpis = {}) {
  const aliases = {
    sensor_data_freshness_ratio: "telemetry_freshness_ratio",
    fresh_sensor_data_device_count: "fresh_telemetry_device_count",
    sensor_data_device_count: "telemetry_device_count",
  };
  const alias = aliases[key];
  const value = Object.prototype.hasOwnProperty.call(kpis, key)
    ? kpis[key]
    : alias && Object.prototype.hasOwnProperty.call(kpis, alias)
      ? kpis[alias]
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
  if (device.node_ready === false) messages.push("할당 node가 unavailable입니다. node 상태와 edgecore/cloudcore 연결을 먼저 확인합니다.");
  if (device.mapper_running === false) messages.push("mqttvirtual mapper가 Running인지, 해당 device가 올바른 node에 배치됐는지 확인합니다.");
  if (device.telemetry_enabled === true && device.telemetry_fresh === false) messages.push("센서 데이터가 stale입니다. availability 판단과 분리해서 EdgeX/collector/MQTT/DB 적재 경로를 확인합니다.");
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
      property: point.property || "value",
    }))
    .filter((point) => Number.isFinite(point.at) && point.numeric !== null)
    .sort((a, b) => a.at - b.at);

  if (!points.length) {
    return `<div class="telemetry-chart empty">InfluxDB history 데이터가 없습니다.</div>`;
  }

  if (!numericPoints.length) {
    const recent = points.slice(-8).reverse();
    return `
      <div class="telemetry-chart">
        <div class="chart-head"><strong>Recent telemetry</strong><span>non-numeric values</span></div>
        <ul class="telemetry-values">${recent
          .map((point) => `<li><span>${escapeHtml(formatChartTime(point.timestamp))}</span><strong>${escapeHtml(text(point.property, "value"))}=${escapeHtml(text(point.value))}</strong></li>`)
          .join("")}</ul>
      </div>
    `;
  }

  const width = 420;
  const height = 190;
  const pad = { left: 42, right: 14, top: 18, bottom: 30 };
  const minTime = Math.min(...numericPoints.map((point) => point.at));
  const maxTime = Math.max(...numericPoints.map((point) => point.at));
  const minValue = Math.min(...numericPoints.map((point) => point.numeric));
  const maxValue = Math.max(...numericPoints.map((point) => point.numeric));
  const timeSpan = Math.max(1, maxTime - minTime);
  const valueSpan = Math.max(1, maxValue - minValue);
  const x = (time) => pad.left + ((time - minTime) / timeSpan) * (width - pad.left - pad.right);
  const y = (value) => height - pad.bottom - ((value - minValue) / valueSpan) * (height - pad.top - pad.bottom);
  const colors = ["#2dd477", "#7c83ff", "#f6b84b", "#ff6b6b", "#55d6ff"];
  const grouped = numericPoints.reduce((acc, point) => {
    acc[point.property] = acc[point.property] || [];
    acc[point.property].push(point);
    return acc;
  }, {});
  const series = Object.entries(grouped).slice(0, 5);
  const polylines = series
    .map(([property, values], index) => {
      const coordinates = values.map((point) => `${x(point.at).toFixed(1)},${y(point.numeric).toFixed(1)}`).join(" ");
      return `<polyline points="${coordinates}" fill="none" stroke="${colors[index]}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round" />`;
    })
    .join("");
  const dots = series
    .flatMap(([property, values], index) => values.slice(-24).map((point) => `<circle cx="${x(point.at).toFixed(1)}" cy="${y(point.numeric).toFixed(1)}" r="2.4" fill="${colors[index]}" />`))
    .join("");
  const legend = series
    .map(([property], index) => `<span><i style="background:${colors[index]}"></i>${escapeHtml(property)}</span>`)
    .join("");

  return `
    <div class="telemetry-chart">
      <div class="chart-head"><strong>InfluxDB telemetry history</strong><span>${numericPoints.length} points · ${escapeHtml(formatChartTime(numericPoints[0].timestamp))} - ${escapeHtml(formatChartTime(numericPoints.at(-1).timestamp))}</span></div>
      <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="Telemetry history chart">
        <line x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}" />
        <line x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${height - pad.bottom}" />
        <text x="8" y="${y(maxValue).toFixed(1)}">${escapeHtml(maxValue.toFixed(2))}</text>
        <text x="8" y="${y(minValue).toFixed(1)}">${escapeHtml(minValue.toFixed(2))}</text>
        ${polylines}
        ${dots}
      </svg>
      <div class="chart-legend">${legend}</div>
    </div>
  `;
}

async function loadDeviceTelemetry(deviceName) {
  const chart = $("telemetryChart");
  if (!chart || !deviceName) return;
  chart.innerHTML = `<div class="telemetry-chart empty">InfluxDB history 조회 중...</div>`;
  try {
    const response = await fetch(`/state/devices/${encodeURIComponent(deviceName)}/telemetry?window=-30m&limit=300`, { cache: "no-store" });
    if (!response.ok) throw new Error(`telemetry history api failed: ${response.status}`);
    const points = await response.json();
    state.telemetryHistory[deviceName] = points;
    if (state.selectedDeviceName === deviceName) {
      chart.innerHTML = renderTelemetryChart(points);
    }
  } catch (error) {
    if (state.selectedDeviceName === deviceName) {
      chart.innerHTML = `<div class="telemetry-chart empty">${escapeHtml(error.message)}</div>`;
    }
  }
}

function showDeviceExplanation(device) {
  const panel = $("explainPanel");
  if (!panel || !device) return;
  state.selectedDeviceName = device.name;
  panel.innerHTML = `
    <div class="explain-header">
      <span class="explain-badge">Device</span>
      <strong>${escapeHtml(displayValue(device.name))}</strong>
    </div>
    ${renderExplainFields([
      ["status", deviceStatus(device)],
      ["reason", deviceReason(device)],
      ["node", deviceNodeLabel(device)],
      ["sensor", `${text(device.telemetry_property, "property 없음")}=${text(device.telemetry_value, "value 없음")}`],
      ["last seen", age(device.telemetry_age_seconds)],
      ["mapper", device.mapper_running ? "running" : "not running"],
      ["service", device.service_demo_group || "service pending"],
    ])}
    <div id="telemetryChart">${renderTelemetryChart(state.telemetryHistory[device.name] || [])}</div>
    ${renderRuleList(explainDeviceRules(device))}
  `;
  loadDeviceTelemetry(device.name);
}

function kpiKeysForCard(key) {
  const groups = {
    registered_device_count: ["registered_device_count", "live_device_count"],
    device_telemetry_ratio: ["telemetry_device_count", "device_telemetry_ratio"],
    telemetry_freshness_ratio: ["fresh_telemetry_device_count", "telemetry_freshness_ratio"],
    sensor_data_freshness_ratio: ["fresh_sensor_data_device_count", "sensor_data_freshness_ratio"],
    service_bound_device_count: ["service_bound_device_count", "device_service_binding_ratio"],
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
  setText("chatStatus", loading ? "Qwen 응답 대기 중" : "read-only mode");
}

function chatResponseMeta(payload) {
  const meta = [text(payload.assistant_name, "qwen operator"), `mode=${text(payload.mode, "read_only")}`, `model=${text(payload.model, "unknown")}`, `upstream=${text(payload.upstream_status, "unknown")}`];
  if (Array.isArray(payload.source_endpoints) && payload.source_endpoints.length) meta.push(`${payload.source_endpoints.length} source endpoints`);
  if (Array.isArray(payload.guardrails) && payload.guardrails.length) meta.push(`${payload.guardrails.length} guardrails`);
  return meta;
}

async function submitOperatorChat(message) {
  state.chat.messages.push({ role: "user", label: "Operator", text: message });
  const loadingMessage = { role: "assistant", label: "Qwen read-only", text: "현재 dashboard 상태를 기준으로 답변을 생성 중입니다.", loading: true };
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
      label: "Qwen read-only",
      text: text(payload.answer, "응답이 비어 있습니다."),
      loading: false,
      meta: chatResponseMeta(payload),
    });
  } catch (error) {
    Object.assign(loadingMessage, {
      role: "error",
      label: "Chat error",
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
  const telemetryEnabled = kpis.telemetry_device_count ?? devices.filter((device) => device.telemetry_enabled).length;
  const freshTelemetry = kpis.fresh_telemetry_device_count ?? devices.filter((device) => device.telemetry_fresh).length;
  const freshSensorData = kpis.fresh_sensor_data_device_count ?? freshTelemetry;
  const sensorDataTotal = kpis.sensor_data_device_count ?? telemetryEnabled;
  const unavailableDevices = devices.filter((device) => device.status === "unavailable").length;
  const degradedDevices = devices.filter((device) => device.status === "degraded").length;
  setText("updatedAt", `Updated ${new Date(data.generated_at).toLocaleString()}`);
  setText("activeNodeCount", text(kpis.active_node_count, 0));
  setText("nodeRatio", `${pct(kpis.node_online_ratio)} online`);
  setText("deviceCount", text(kpis.registered_device_count, 0));
  setText("deviceHealthRatio", `${pct(kpis.device_operational_ratio)} available · ${text(kpis.live_device_count, 0)} live`);
  setText("telemetryRatio", pct(kpis.device_telemetry_ratio));
  setText("telemetryCaption", `${telemetryEnabled} telemetry-enabled devices`);
  setText("telemetryFreshnessRatio", pct(kpis.telemetry_freshness_ratio));
  setText("telemetryFreshnessCaption", `${freshTelemetry} fresh telemetry devices`);
  setText("sensorDataFreshnessRatio", pct(kpis.sensor_data_freshness_ratio ?? kpis.telemetry_freshness_ratio));
  setText("sensorDataFreshnessCaption", `${freshSensorData}/${sensorDataTotal} live sensor streams`);
  setText("serviceBindingCount", text(kpis.service_bound_device_count, 0));
  setText("serviceBindingRatio", `${pct(kpis.device_service_binding_ratio)} bound`);
  setText("focusCount", text(kpis.operator_focus_count, 0));
  setText("resourceProfileCount", text(kpis.service_resource_profile_count, 0));
  setText("placementFitCaption", `${text(kpis.service_resource_profile_pod_count, 0)} pods · ${text(kpis.service_resource_partially_declared_profile_count, 0)} missing spec`);
  setText("assetCount", `${(data.nodes || []).length + devices.length} assets`);
  setText("riskCount", `${unavailableDevices} unavailable · ${degradedDevices} degraded`);

  renderNodes(data.nodes || []);
  renderDevices(devices);
  renderPodPlacement(data.resource_profiles || {}, kpis);
  renderAlerts(data);
  renderResourceProfiles(data.resource_profiles || {}, kpis);
  renderScenario(devices, kpis);
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
          const mappingMeta = isRawInstance(node.hostname) ? `<span>hostname mapping pending</span>` : "";
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
    : `<div class="empty">No node state yet</div>`;
}

function renderDevices(devices) {
  const visibleDevices = filteredDevices(devices);
  renderDeviceFilterSummary(devices.length, visibleDevices.length);
  $("deviceList").innerHTML = visibleDevices.length
    ? visibleDevices
        .map((device) => `
          <article class="item device-row explainable ${state.selectedDeviceName === device.name ? "selected" : ""}" data-explain-type="device" data-device-name="${escapeHtml(device.name)}" tabindex="0" role="button" aria-label="${escapeHtml(device.name)} 설명 보기">
            <div class="item-title">
              <strong>${escapeHtml(device.name)}</strong>
              ${statusPill(device.overall_status || device.status)}
            </div>
            <div class="meta">
              <span>node: ${escapeHtml(deviceNodeLabel(device))}</span>
              <span>sensor: ${escapeHtml(text(device.telemetry_property, "sensor property 없음"))}=${escapeHtml(text(device.telemetry_value, "sensor value 없음"))}</span>
              <span>age: ${escapeHtml(age(device.telemetry_age_seconds))}</span>
              <span>mapper: ${device.mapper_running ? "running" : "not running"}</span>
              <span>service: ${escapeHtml(text(device.service_demo_group, "service pending"))}</span>
              <span>reason: ${escapeHtml(text(device.reason || device.status_reason))}</span>
            </div>
          </article>
        `)
        .join("")
    : state.selectedNodeName
      ? `<div class="empty">${escapeHtml(state.selectedNodeName)}에 연결된 device가 없습니다.</div>`
      : `<div class="empty">No KubeEdge devices found</div>`;
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
      <div class="relation-summary">recording=${resourceState.recorded_at ? "influxdb ok" : "pending/token 없음"} · scope=current usage + declared requests · total_use=${text(kpis.service_resource_current_cpu_usage_cores, 0)} core / ${text(kpis.service_resource_current_memory_working_set_mib, 0)} MiB · total_req=${text(kpis.service_resource_request_cpu_cores, 0)} core / ${text(kpis.service_resource_request_memory_mib, 0)} MiB</div>
      <ul class="compact-list">${rows.join("")}</ul>
    `
    : `<div class="empty">Running service resource requirement profile pending</div>`;
}

function serviceGroup(device) {
  return text(device.service_demo_group, device.service_connected ? "서비스 데모 연결" : "service pending");
}

function serviceBindingReason(device) {
  return text(device.service_binding_reason, device.service_connected ? "binding detail pending" : "not bound");
}

function formatResourceValue(value, unit) {
  const numeric = numericValue(value);
  if (numeric === null) return "missing";
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

function renderAlerts(data) {
  const alerts = [];
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
    if (device.mapper_running === false) reasons.push("mapper_running=false");
    if (device.telemetry_enabled && device.telemetry_fresh === false) reasons.push("telemetry_fresh=false");
    if (device.node_ready === false) reasons.push("node_ready=false");
    if (reasons.length) {
      const level = status === "unavailable" || device.node_ready === false ? "high" : "medium";
      alerts.push({
        kind: "device",
        level,
        title: `${device.name}: ${reasons.join(", ")}`,
        text: `${device.name}: ${reasons.join(", ")} · ${deviceReason(device)}`,
        device,
      });
    }
  }
  state.alerts = alerts.slice(0, 12);
  $("alertList").innerHTML = state.alerts.length
    ? state.alerts
        .map((alert, index) => `<article class="item alert ${escapeHtml(alert.level)} explainable" data-explain-type="issue" data-alert-index="${index}" tabindex="0" role="button" aria-label="Issue 설명 보기"><strong>${escapeHtml(alert.text)}</strong></article>`)
        .join("")
    : `<div class="empty">No active alerts</div>`;
}

function renderScenario(devices, kpis) {
  const unavailable = devices.filter((device) => device.status === "unavailable").length;
  const degraded = devices.filter((device) => device.status === "degraded").length;
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
              ${statusPill(device.status)}
            </div>
            <div class="meta">
              <span>${escapeHtml(text(device.model, "model unknown"))}</span>
              <span>${escapeHtml(text(device.protocol, "protocol unknown"))}</span>
              <span>Sensor Data: ${device.telemetry_fresh ? "fresh" : "stale"}</span>
              <span>${escapeHtml(text(device.telemetry_property, "sensor property 없음"))}: ${escapeHtml(text(device.telemetry_value, "sensor value 없음"))}</span>
              <span>${escapeHtml(text(device.status_reason))}</span>
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
    state,
  };
}
