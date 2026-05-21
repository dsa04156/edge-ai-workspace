const state = {
  data: null,
  refreshMs: 5000,
  selectedDeviceName: null,
  alerts: [],
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

function deviceStatus(device) {
  return device?.overall_status || device?.status || "unknown";
}

function deviceReason(device) {
  return device?.reason || device?.status_reason || "데이터 없음";
}

function explainDeviceRules(device) {
  const rules = [];
  const status = deviceStatus(device);
  if (status === "healthy") {
    rules.push({ id: "Control OK", title: "control/status path available", text: "node와 mapper 경로가 살아 있어 healthy로 판단됩니다. 센서 데이터 freshness는 별도 KPI로 봅니다." });
  }
  if (device.telemetry_enabled === true && device.telemetry_fresh === false) {
    rules.push({ id: "Sensor Stale", title: "sensor data missing/stale", text: "센서 데이터 freshness가 낮습니다. healthy 판단과는 분리해서 EdgeX/collector/MQTT/DB 적재 경로를 확인합니다." });
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
  registered_device_count: "KubeEdge에 등록된 Device CR 수와 healthy device 수를 함께 봅니다.",
  live_device_count: "control/status 기준 healthy인 device 수입니다. 센서 데이터 freshness와 분리됩니다.",
  telemetry_device_count: "센서 데이터 적재/수집 대상 device 수입니다.",
  device_telemetry_ratio: "센서 데이터 적재가 설정된 device 비율입니다. freshness 비율은 아닙니다.",
  fresh_telemetry_device_count: "fresh sensor data device 수입니다.",
  telemetry_freshness_ratio: "fresh sensor data device 수 / telemetry-enabled device 수입니다.",
  fresh_sensor_data_device_count: "최근 센서 데이터 sample이 들어온 실제 sensor stream 수입니다.",
  sensor_data_freshness_ratio: "센서 데이터 freshness KPI입니다. healthy 판단과 분리해서 봅니다.",
  operator_focus_count: "운영자가 먼저 볼 degraded/unavailable device와 non-healthy node 수입니다.",
  service_bound_device_count: "서비스 데모 그룹에 연결된 device 수입니다.",
  device_service_binding_ratio: "service-bound device 수 / 전체 registered device 수입니다.",
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
  if (device.telemetry_enabled === true && device.telemetry_fresh === false) messages.push("센서 데이터 freshness가 낮습니다. healthy 판단과 분리해서 EdgeX/collector/MQTT/DB 적재 경로를 확인합니다.");
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
      ["node", device.node_name],
      ["sensor", `${text(device.telemetry_property, "property 없음")}=${text(device.telemetry_value, "value 없음")}`],
      ["last seen", age(device.telemetry_age_seconds)],
      ["mapper", device.mapper_running ? "running" : "not running"],
      ["service", device.service_demo_group || "service pending"],
    ])}
    ${renderRuleList(explainDeviceRules(device))}
  `;
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
  setText("assetCount", `${(data.nodes || []).length + devices.length} assets`);
  setText("riskCount", `${unavailableDevices} unavailable · ${degradedDevices} degraded`);

  renderNodes(data.nodes || []);
  renderDevices(devices);
  renderRelations(devices, kpis);
  renderAlerts(data);
  renderScenario(devices, kpis);
}

function renderNodes(nodes) {
  $("nodeList").innerHTML = nodes.length
    ? nodes
        .map((node) => {
          const cpu = Math.round((node.raw_metrics?.cpu_utilization || 0) * 100);
          const mem = Math.round((node.raw_metrics?.memory_usage_ratio || 0) * 100);
          return `
            <article class="item">
              <div class="item-title">
                <strong>${escapeHtml(node.hostname)}</strong>
                ${statusPill(node.node_health)}
              </div>
              <div class="meta">
                <span>${escapeHtml(text(node.node_type, "node"))}</span>
                <span>cpu ${cpu}%</span>
                <span>mem ${mem}%</span>
              </div>
            </article>
          `;
        })
        .join("")
    : `<div class="empty">No node state yet</div>`;
}

function renderDevices(devices) {
  $("deviceList").innerHTML = devices.length
    ? devices
        .map((device) => `
          <article class="item device-row explainable ${state.selectedDeviceName === device.name ? "selected" : ""}" data-explain-type="device" data-device-name="${escapeHtml(device.name)}" tabindex="0" role="button" aria-label="${escapeHtml(device.name)} 설명 보기">
            <div class="item-title">
              <strong>${escapeHtml(device.name)}</strong>
              ${statusPill(device.overall_status || device.status)}
            </div>
            <div class="meta">
              <span>node: ${escapeHtml(text(device.node_name, "unassigned"))}</span>
              <span>sensor: ${escapeHtml(text(device.telemetry_property, "sensor property 없음"))}=${escapeHtml(text(device.telemetry_value, "sensor value 없음"))}</span>
              <span>age: ${escapeHtml(age(device.telemetry_age_seconds))}</span>
              <span>mapper: ${device.mapper_running ? "running" : "not running"}</span>
              <span>service: ${escapeHtml(text(device.service_demo_group, "service pending"))}</span>
              <span>reason: ${escapeHtml(text(device.reason || device.status_reason))}</span>
            </div>
          </article>
        `)
        .join("")
    : `<div class="empty">No KubeEdge devices found</div>`;
}

function serviceGroup(device) {
  return text(device.service_demo_group, device.service_connected ? "서비스 데모 연결" : "service pending");
}

function serviceBindingReason(device) {
  return text(device.service_binding_reason, device.service_connected ? "binding detail pending" : "not bound");
}

function renderRelations(devices, kpis) {
  const rows = devices.map((device) => {
    const telemetry = device.telemetry_last_seen_at || device.telemetry_last_seen ? `last seen ${age(device.telemetry_age_seconds)}` : "DB timestamp pending";
    return `
      <article class="relation">
        <div class="relation-node">
          <span>Device</span>
          <strong>${escapeHtml(device.name)}</strong>
          <small>${escapeHtml(text(device.device_type))}</small>
        </div>
        <div class="arrow">-&gt;</div>
        <div class="relation-node">
          <span>Node</span>
          <strong>${escapeHtml(text(device.node_name, "unassigned"))}</strong>
          <small>node_ready=${boolText(device.node_ready)}</small>
        </div>
        <div class="arrow">-&gt;</div>
        <div class="relation-node">
          <span>Sensor Data</span>
          <strong>${escapeHtml(telemetry)}</strong>
          <small>${escapeHtml(text(device.telemetry_property, "property pending"))}=${escapeHtml(text(device.telemetry_value, "sensor value 없음"))} · sensor_data_fresh=${boolText(device.telemetry_fresh)}</small>
        </div>
        <div class="arrow">-&gt;</div>
        <div class="relation-node">
          <span>Service Demo</span>
          <strong>${escapeHtml(serviceGroup(device))}</strong>
          <small>${escapeHtml(serviceBindingReason(device))}</small>
        </div>
      </article>
    `;
  });
  const summary = `<div class="relation-summary">service_bound_device_count=${text(kpis.service_bound_device_count, 0)} · device_service_binding_ratio=${pct(kpis.device_service_binding_ratio)}</div>`;
  $("relationList").innerHTML = rows.length ? summary + rows.join("") : `<div class="empty">No device relationships yet</div>`;
}

function renderAlerts(data) {
  const alerts = [];
  for (const node of data.nodes || []) {
    if (node.node_health !== "healthy") {
      alerts.push({
        kind: "node",
        level: node.node_health === "unavailable" ? "high" : "medium",
        title: `${node.hostname}: non-healthy node`,
        text: `${node.hostname}: non-healthy node (${node.node_health})`,
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
    const key = device.node_name || "unassigned";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const busiestNode = Object.entries(byNode).sort((a, b) => b[1] - a[1])[0];
  setText("responseKpi", busiestNode ? `${busiestNode[0]} (${busiestNode[1]})` : "no devices");
  setText("interventionKpi", `${kpis.operator_focus_count || 0} focus`);
  setText("handlingKpi", unavailable ? `${unavailable} risk` : degraded ? `${degraded} watch` : "normal");
  $("deviceStatusList").innerHTML = devices.length
    ? devices
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


function markSelectedExplain(target) {
  if (typeof document === "undefined" || !target) return;
  document.querySelectorAll(".explainable.selected").forEach((item) => item.classList.remove("selected"));
  target.classList.add("selected");
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
  document.addEventListener("click", (event) => handleExplainSelection(event.target));
  document.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const target = event.target?.closest?.("[data-explain-type]");
    if (!target) return;
    event.preventDefault();
    handleExplainSelection(target);
  });
}

if (typeof document !== "undefined" && $("refreshButton")) {
  $("refreshButton").addEventListener("click", () => {
    loadDashboard().catch((error) => {
      $("alertList").innerHTML = `<article class="item alert high"><strong>${escapeHtml(error.message)}</strong></article>`;
    });
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
    explainKpi,
    issueExplanation,
    deviceStatus,
    deviceReason,
  };
}
