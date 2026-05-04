const state = {
  data: null,
  refreshMs: 5000,
};

const $ = (id) => document.getElementById(id);

function pct(value) {
  return `${Math.round((value || 0) * 100)}%`;
}

function statusPill(value) {
  const safe = value || "unknown";
  return `<span class="pill ${safe}">${safe}</span>`;
}

function text(value, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function age(value) {
  if (value === null || value === undefined) return "no telemetry";

  const minutes = Math.floor(value / 60);
  const seconds = Math.floor(value % 60);

  if (minutes === 0) return `${seconds}s ago`;
  return `${minutes}m ${seconds}s ago`;
}

function setText(id, value) {
  const el = $(id);
  if (el) el.textContent = value;
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
  const telemetry = (data.devices || []).filter((device) => device.telemetry_enabled).length;
  const unavailableDevices = (data.devices || []).filter((device) => device.status === "unavailable").length;
  const degradedDevices = (data.devices || []).filter((device) => device.status === "degraded").length;
  setText("updatedAt", `Updated ${new Date(data.generated_at).toLocaleString()}`);
  setText("activeNodeCount", text(kpis.active_node_count, 0));
  setText("nodeRatio", `${pct(kpis.node_online_ratio)} online`);
  setText("deviceCount", text(kpis.registered_device_count, 0));
  setText("deviceHealthRatio", `${pct(kpis.device_operational_ratio)} available · ${text(kpis.live_device_count, 0)} live`);
  setText("telemetryRatio", pct(kpis.device_telemetry_ratio));
  setText("telemetryCaption", `${telemetry} devices`);
  setText("serviceBindingCount", text(kpis.service_bound_device_count, 0));
  setText("serviceBindingRatio", `${pct(kpis.device_service_binding_ratio)} bound`);
  setText("focusCount", text(kpis.operator_focus_count, 0));
  setText("assetCount", `${(data.nodes || []).length + (data.devices || []).length} assets`);
  setText("riskCount", `${unavailableDevices} unavailable · ${degradedDevices} watch`);

  renderNodes(data.nodes || []);
  renderDevices(data.devices || []);
  renderRelations(data.devices || []);
  renderAlerts(data);
  renderScenario(data.devices || [], kpis);
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
                <strong>${text(node.hostname)}</strong>
                ${statusPill(node.node_health)}
              </div>
              <div class="meta">
                <span>${text(node.node_type, "node")}</span>
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
          <article class="item">
            <div class="item-title">
              <strong>${text(device.name)}</strong>
              ${statusPill(device.status)}
            </div>
            <div class="meta">
              <span>${text(device.device_type)}</span>
              <span>${text(device.service_demo_group, "service pending")}</span>
              <span>${text(device.node_name, "unassigned")}</span>
              <span>${age(device.telemetry_age_seconds)}</span>
              <span>${device.properties.length} properties</span>
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

function renderRelations(devices) {
  const rows = devices.slice(0, 12).map((device) => {
    const telemetry = device.telemetry_last_seen ? `last seen ${age(device.telemetry_age_seconds)}` : "telemetry pending";
    return `
      <article class="relation">
        <div class="relation-node">
          <span>Device</span>
          <strong>${text(device.name)}</strong>
        </div>
        <div class="arrow">-&gt;</div>
        <div class="relation-node">
          <span>Node</span>
          <strong>${text(device.node_name, "unassigned")}</strong>
        </div>
        <div class="arrow">-&gt;</div>
        <div class="relation-node">
          <span>Telemetry / Status</span>
          <strong>${telemetry}</strong>
        </div>
        <div class="arrow">-&gt;</div>
        <div class="relation-node">
          <span>Service Demo</span>
          <strong>${serviceGroup(device)}</strong>
          <small>${serviceBindingReason(device)}</small>
        </div>
      </article>
    `;
  });
  $("relationList").innerHTML = rows.length ? rows.join("") : `<div class="empty">No device relationships yet</div>`;
}

function renderAlerts(data) {
  const alerts = [];
  for (const node of data.nodes || []) {
    if (node.node_health !== "healthy") {
      alerts.push({ level: node.node_health === "unavailable" ? "high" : "medium", text: `${node.hostname}: ${node.node_health}` });
    }
  }
  for (const device of data.devices || []) {
    if (device.status !== "healthy") {
      alerts.push({ level: device.status === "unavailable" ? "high" : "medium", text: `${device.name}: ${device.status_reason}` });
    }
  }
  $("alertList").innerHTML = alerts.length
    ? alerts
        .slice(0, 8)
        .map((alert) => `<article class="item alert ${alert.level}"><strong>${alert.text}</strong></article>`)
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
        .slice(0, 6)
        .map((device) => `
          <article class="item">
            <div class="item-title">
              <strong>${text(device.name)}</strong>
              ${statusPill(device.status)}
            </div>
            <div class="meta">
              <span>${text(device.model, "model unknown")}</span>
              <span>${text(device.protocol, "protocol unknown")}</span>
              <span>DeviceStatus: ${device.device_status_fresh ? "fresh" : "stale"}</span>
              <span>Telemetry: ${device.telemetry_fresh ? "fresh" : "stale"}</span>
              <span>${text(device.telemetry_property, "no property")}: ${text(device.telemetry_value, "no value")}</span>
              <span>${text(device.status_reason)}</span>
            </div>
          </article>
        `)
        .join("")
    : `<div class="empty">No device status received</div>`;
}

$("refreshButton").addEventListener("click", () => {
  loadDashboard().catch((error) => {
    $("alertList").innerHTML = `<article class="item alert high"><strong>${error.message}</strong></article>`;
  });
});

function scheduleDashboardRefresh() {
  loadDashboard()
    .catch((error) => {
      $("alertList").innerHTML = `<article class="item alert high"><strong>${error.message}</strong></article>`;
    })
    .finally(() => {
      window.setTimeout(scheduleDashboardRefresh, state.refreshMs);
    });
}

scheduleDashboardRefresh();
