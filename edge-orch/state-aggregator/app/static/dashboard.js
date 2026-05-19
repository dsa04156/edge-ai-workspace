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

  if (status === "healthy" && device.telemetry_fresh === true) {
    rules.push({
      id: "Rule A",
      title: "healthy + telemetry fresh",
      text: "이 device는 InfluxDB latest telemetry가 freshness 기준을 만족하므로 healthy로 판단됩니다. DeviceStatus freshness는 status-plane 보조 신호이며, telemetry가 fresh하면 DeviceStatus가 stale이어도 healthy일 수 있습니다.",
    });
  }

  if (device.severity === "critical") {
    rules.push({
      id: "Rule B",
      title: "severity critical",
      text: "최근 telemetry는 들어오지만 severity가 critical이므로 degraded로 표시됩니다.",
    });
  }

  if (device.telemetry_enabled === true && device.telemetry_fresh === false) {
    rules.push({
      id: "Rule C",
      title: "telemetry missing/stale",
      text: "이 device는 telemetry 대상이지만 InfluxDB latest sample이 없거나 freshness 기준을 만족하지 않습니다. publisher 실행 위치, local mosquitto, mapper log, InfluxDB 적재 상태를 확인해야 합니다.",
    });
  }

  if (device.mapper_running === false) {
    rules.push({
      id: "Rule D",
      title: "mapper not running",
      text: "이 device는 mqttvirtual mapper가 필요한 device지만, 할당 node에서 mapper pod가 Running 상태가 아닙니다.",
    });
  }

  if (device.node_ready === false) {
    rules.push({
      id: "Rule E",
      title: "node unavailable",
      text: "이 device가 할당된 node가 dashboard 기준 unavailable입니다. Kubernetes Ready와 dashboard node_ready는 다르며, dashboard node_ready는 Prometheus/node-exporter 기반 node_health 판단입니다.",
    });
  }

  if (device.telemetry_fresh === true && device.device_status_fresh === false) {
    rules.push({
      id: "Rule F",
      title: "DeviceStatus stale but telemetry fresh",
      text: "data-plane은 살아 있지만 status-plane snapshot은 오래됐습니다. DeviceStatus stale은 healthy 판단을 반드시 막지는 않지만, mapper allowlist/report 경로 점검 대상입니다.",
    });
  }

  if (device.service_connected === false) {
    rules.push({
      id: "Rule G",
      title: "service binding missing",
      text: "이 device는 현재 service demo group에 연결되어 있지 않습니다. service binding rule 또는 device naming rule을 확인해야 합니다.",
    });
  }

  if (!rules.length) {
    rules.push({
      id: "기본 설명",
      title: "추가 rule 없음",
      text: "현재 API payload 기준으로 우선 점검 rule에 해당하지 않습니다. 상세 원인은 reason 필드와 telemetry/status-plane 필드를 함께 확인합니다.",
    });
  }

  return rules;
}

const KPI_EXPLANATIONS = {
  active_node_count: "dashboard 기준 healthy node 수입니다. node_online_ratio와 함께 전체 node 관측 상태를 봅니다.",
  registered_device_count: "KubeEdge에 등록된 전체 Device CR 수입니다.",
  live_device_count: "state-aggregator 최종 status가 healthy인 device 수입니다.",
  telemetry_device_count: "telemetry_enabled device 수입니다.",
  device_telemetry_ratio: "telemetry configured ratio입니다. telemetry_enabled device 수 / 전체 registered device 수이며 freshness 비율이 아닙니다.",
  fresh_telemetry_device_count: "telemetry_fresh == true인 device 수입니다.",
  telemetry_freshness_ratio: "fresh telemetry device 수 / telemetry_enabled device 수입니다.",
  fresh_device_status_count: "device_status_fresh == true인 device 수입니다.",
  device_status_freshness_ratio: "fresh DeviceStatus device 수 / 전체 device 수입니다. DeviceStatus는 status-plane 보조 신호입니다.",
  operator_focus_count: "degraded/unavailable device 수 + non-healthy node 수입니다. workflow/offloading/placement risk는 포함하지 않습니다.",
  service_bound_device_count: "service demo group에 연결된 device 수입니다.",
  device_service_binding_ratio: "service-bound device 수 / 전체 registered device 수입니다.",
};

function explainKpi(key, kpis = {}) {
  const value = Object.prototype.hasOwnProperty.call(kpis, key) ? kpis[key] : "현재 API payload에 없음";
  return {
    key,
    value,
    text: KPI_EXPLANATIONS[key] || "현재 dashboard에 정의된 KPI 설명이 없습니다.",
  };
}

function issueExplanation(alert) {
  if (!alert) return ["선택한 Issue 항목 데이터가 없습니다."];
  if (alert.kind === "node") {
    return ["이 node는 dashboard 기준 non-healthy 상태이므로 우선 점검 대상입니다. node 상태, node-exporter/Prometheus 관측, edgecore/cloudcore 연결 상태를 확인합니다."];
  }
  const device = alert.device || {};
  const messages = [];
  if (device.telemetry_enabled === true && device.telemetry_fresh === false) {
    messages.push("telemetry_fresh=false이므로 publisher 실행 위치, local mosquitto, mapper log, InfluxDB 적재 상태를 확인합니다.");
  }
  if (device.mapper_running === false) {
    messages.push("mapper_running=false이므로 할당 node의 mqttvirtual mapper pod와 node 배치를 확인합니다.");
  }
  if (device.node_ready === false) {
    messages.push("node_ready=false이므로 node 상태와 edgecore/cloudcore 연결 상태를 확인합니다.");
  }
  if (device.device_status_fresh === false && device.telemetry_fresh === true) {
    messages.push("DeviceStatus는 stale이지만 telemetry는 fresh입니다. data-plane은 살아 있고 DeviceStatus report path를 별도로 확인합니다.");
  }
  if (!messages.length) {
    messages.push("이 항목은 degraded/unavailable 상태 또는 reason 때문에 우선 점검 대상으로 표시됐습니다. device reason과 상세 필드를 확인합니다.");
  }
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
      <span class="explain-badge">Device Explain</span>
      <strong>${escapeHtml(displayValue(device.name))}</strong>
    </div>
    ${renderExplainFields([
      ["device name", device.name],
      ["node_name", device.node_name],
      ["device_type", device.device_type],
      ["overall_status", deviceStatus(device)],
      ["reason", deviceReason(device)],
      ["telemetry_enabled", device.telemetry_enabled],
      ["telemetry_fresh", device.telemetry_fresh],
      ["telemetry_last_seen_at", device.telemetry_last_seen_at || device.telemetry_last_seen],
      ["telemetry_property", device.telemetry_property],
      ["telemetry_value", device.telemetry_value],
      ["device_status_fresh", device.device_status_fresh],
      ["device_status_last_reported_at", device.device_status_last_reported_at || device.last_reported_at],
      ["mapper_running", device.mapper_running],
      ["node_ready", device.node_ready],
      ["service_demo_group", device.service_demo_group],
      ["service_connected", device.service_connected],
    ])}
    <h3>적용된 설명 rule</h3>
    ${renderRuleList(explainDeviceRules(device))}
  `;
}

function kpiKeysForCard(key) {
  const groups = {
    registered_device_count: ["registered_device_count", "live_device_count"],
    device_telemetry_ratio: ["telemetry_device_count", "device_telemetry_ratio"],
    telemetry_freshness_ratio: ["fresh_telemetry_device_count", "telemetry_freshness_ratio"],
    device_status_freshness_ratio: ["fresh_device_status_count", "device_status_freshness_ratio"],
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
  const freshDeviceStatus = kpis.fresh_device_status_count ?? devices.filter((device) => device.device_status_fresh).length;
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
  setText("deviceStatusFreshnessRatio", pct(kpis.device_status_freshness_ratio));
  setText("deviceStatusFreshnessCaption", `${freshDeviceStatus} fresh status snapshots`);
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
              <span>type: ${escapeHtml(device.device_type)}</span>
              <span>node: ${escapeHtml(text(device.node_name, "unassigned"))}</span>
              <span>telemetry_enabled: ${boolText(device.telemetry_enabled)}</span>
              <span>telemetry_fresh: ${boolText(device.telemetry_fresh)}</span>
              <span>last_seen: ${escapeHtml(text(device.telemetry_last_seen_at || device.telemetry_last_seen, "DB timestamp 없음"))}</span>
              <span>age: ${escapeHtml(age(device.telemetry_age_seconds))}</span>
              <span>property: ${escapeHtml(text(device.telemetry_property, "DB property 없음"))}</span>
              <span>DeviceStatus: ${device.device_status_fresh ? "fresh" : "stale"}</span>
              <span>mapper_running: ${boolText(device.mapper_running)}</span>
              <span>node_ready: ${boolText(device.node_ready)}</span>
              <span>service: ${escapeHtml(text(device.service_demo_group, "service pending"))}</span>
              <span>service_connected: ${boolText(device.service_connected)}</span>
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
          <span>Telemetry / Status</span>
          <strong>${escapeHtml(telemetry)}</strong>
          <small>${escapeHtml(text(device.telemetry_property, "property pending"))} · telemetry_fresh=${boolText(device.telemetry_fresh)} · DeviceStatus=${device.device_status_fresh ? "fresh" : "stale"}</small>
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
              <span>DeviceStatus: ${device.device_status_fresh ? "fresh" : "stale"}</span>
              <span>Telemetry: ${device.telemetry_fresh ? "fresh" : "stale"}</span>
              <span>${escapeHtml(text(device.telemetry_property, "DB property 없음"))}: ${escapeHtml(text(device.telemetry_value, "DB value 없음"))}</span>
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
