const state = {
  data: null,
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
  const deviceRisks = (data.devices || []).filter((device) => device.status !== "healthy").length;
  setText("updatedAt", `Updated ${new Date(data.generated_at).toLocaleString()}`);
  setText("activeNodeCount", text(kpis.active_node_count, 0));
  setText("nodeRatio", `${pct(kpis.node_online_ratio)} online`);
  setText("deviceCount", text(kpis.registered_device_count, 0));
  setText("deviceHealthRatio", `${pct(kpis.device_healthy_ratio)} healthy`);
  setText("telemetryRatio", pct(kpis.device_telemetry_ratio));
  setText("telemetryCaption", `${telemetry} devices`);
  setText("focusCount", text(kpis.operator_focus_count, 0));
  setText("assetCount", `${(data.nodes || []).length + (data.devices || []).length} assets`);
  setText("riskCount", `${deviceRisks} device risks`);

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
              <span>${text(device.node_name, "unassigned")}</span>
              <span>${device.telemetry_enabled ? "telemetry" : "no telemetry"}</span>
              <span>${device.properties.length} properties</span>
            </div>
          </article>
        `)
        .join("")
    : `<div class="empty">No KubeEdge devices found</div>`;
}

function renderRelations(devices) {
  const rows = devices.slice(0, 12).map((device) => {
    const twin = device.twin && Object.keys(device.twin).length ? "twin reported" : "twin pending";
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
          <span>Twin / Telemetry</span>
          <strong>${device.telemetry_enabled ? "telemetry enabled" : twin}</strong>
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
  const risky = devices.filter((device) => device.status !== "healthy").length;
  const byNode = devices.reduce((acc, device) => {
    const key = device.node_name || "unassigned";
    acc[key] = (acc[key] || 0) + 1;
    return acc;
  }, {});
  const busiestNode = Object.entries(byNode).sort((a, b) => b[1] - a[1])[0];
  setText("responseKpi", busiestNode ? `${busiestNode[0]} (${busiestNode[1]})` : "no devices");
  setText("interventionKpi", `${kpis.operator_focus_count || 0} focus`);
  setText("handlingKpi", risky ? `${risky} risk` : "normal");
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

loadDashboard().catch((error) => {
  $("alertList").innerHTML = `<article class="item alert high"><strong>${error.message}</strong></article>`;
});
setInterval(loadDashboard, 15000);
