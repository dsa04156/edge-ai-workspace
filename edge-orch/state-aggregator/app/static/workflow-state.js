const NODE_W = 160;
const NODE_H = 118;
const AI_HAT_NODE = "etri-dev0002-raspi5";

const NODE_TEMPLATES = [
  { type: "device_source", label: "Collect", caption: "Device Service recent data or Core Data history", data: "typed readings" },
  { type: "transform", label: "Preprocess", caption: "normalize, window, feature extraction", data: "feature tensor" },
  { type: "ai_inference", label: "Inference", caption: "edge model execution", data: "prediction" },
  { type: "postprocess", label: "Postprocess", caption: "threshold, score, event shaping", data: "inspection event" },
  { type: "store_observe", label: "Store & Observe", caption: "result cache and event persistence", data: "stored result" },
  { type: "dashboard_event", label: "Dashboard", caption: "operator signal and review", data: "operator signal" },
  { type: "condition", label: "Quality Gate", caption: "optional freshness/threshold branch", data: "branch decision" },
];

const DEVICE_SOURCE_MODE_LABELS = {
  local_latest: "로컬 최신값",
  local_window: "로컬 최근 구간",
  history: "중앙 저장 이력",
};

const workflowState = {
  targets: [],
  nodes: [],
  workflows: [
    {
      id: "factory-vision-inspection-pipeline",
      name: "factory-vision-inspection-pipeline",
      nodes: [
        { id: "collect-1", label: "Collect Device Data", type: "device_source", x: 40, y: 72, targetId: "", config: { readMode: "local_window", window: "-10s", property: "auto" } },
        { id: "preprocess-1", label: "Normalize Feature Window", type: "transform", x: 236, y: 72, targetId: "", config: { method: "normalize-window" } },
        { id: "inference-1", label: "Run Defect Inference", type: "ai_inference", x: 432, y: 72, targetId: `resource:${AI_HAT_NODE}:ai-hat`, config: { model: "factory-vision-inspection-lite", accelerator: "ai-hat" } },
        { id: "postprocess-1", label: "Format Inspection Event", type: "postprocess", x: 40, y: 242, targetId: "", config: { threshold: "0.82", output: "defect-score" } },
        { id: "store-1", label: "Persist Result Cache", type: "store_observe", x: 236, y: 242, targetId: "", config: { sink: "result cache" } },
        { id: "dashboard-1", label: "Publish Dashboard Signal", type: "dashboard_event", x: 432, y: 242, targetId: "", config: { severity: "warning" } },
      ],
      edges: [
        { from: "collect-1", to: "preprocess-1", label: "typed readings" },
        { from: "preprocess-1", to: "inference-1", label: "feature tensor" },
        { from: "inference-1", to: "postprocess-1", label: "prediction" },
        { from: "postprocess-1", to: "store-1", label: "inspection event" },
        { from: "store-1", to: "dashboard-1", label: "operator signal" },
      ],
    },
  ],
  selectedWorkflowId: "factory-vision-inspection-pipeline",
  selectedNodeId: "collect-1",
  selectedTargetId: "",
  selectedFilter: "all",
  linkFromNodeId: "",
  canvasScale: 1,
  renderedCanvasScale: 1,
  drag: null,
};

function workflowEl(id) {
  return document.getElementById(id);
}

function workflowText(value, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function workflowEscape(value) {
  return workflowText(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function workflowSlug(value) {
  return workflowText(value, "").trim().toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-|-$/g, "");
}

function nodeTemplate(type) {
  return NODE_TEMPLATES.find((template) => template.type === type) || NODE_TEMPLATES[0];
}

function currentWorkflow() {
  return workflowState.workflows.find((workflow) => workflow.id === workflowState.selectedWorkflowId) || workflowState.workflows[0];
}

function selectedWorkflowNode() {
  const workflow = currentWorkflow();
  return workflow?.nodes.find((node) => node.id === workflowState.selectedNodeId) || workflow?.nodes[0] || null;
}

function targetById(id) {
  return workflowState.targets.find((target) => target.id === id) || null;
}

function selectedWorkflowTarget() {
  return targetById(workflowState.selectedTargetId);
}

function sourceReadModesForTarget(target) {
  const modes = Array.isArray(target?.sourceReadModes) ? target.sourceReadModes : ["history"];
  return [...new Set(modes.filter((mode) => DEVICE_SOURCE_MODE_LABELS[mode]))];
}

function preferredSourceReadMode(target) {
  const modes = sourceReadModesForTarget(target);
  if (modes.includes("local_window")) return "local_window";
  if (modes.includes("local_latest")) return "local_latest";
  return "history";
}

function resolvedWorkflowResource(node, target) {
  if (!node || !target || target.kind !== "device") return "";
  if (node.config.property && node.config.property !== "auto") return node.config.property;
  return target.properties[0] || "";
}


function targetFromDevice(device) {
  const nodeName = device.node_name || "";
  const readings = Array.isArray(device.latest_readings) ? device.latest_readings : [];
  const properties = [...new Set(readings.map((reading) => reading.resource_name || reading.source_name).filter(Boolean))];
  return {
    id: `edgex:${device.name}`,
    kind: "device",
    name: device.name,
    namespace: "",
    displayName: device.name,
    nodeName,
    type: "EdgeX device",
    source: device.source || "edgex",
    profileName: device.profile_name,
    serviceName: device.device_service_name,
    protocolNames: Array.isArray(device.protocol_names) ? device.protocol_names : [],
    protocol: Array.isArray(device.protocol_names) ? device.protocol_names.join(", ") : "-",
    properties,
    sourceNames: [...new Set(readings.map((reading) => reading.source_name).filter(Boolean))],
    sourceReadModes: Array.isArray(device.source_read_modes) && device.source_read_modes.length ? device.source_read_modes : ["history"],
    latestReadings: readings,
    eventFresh: device.telemetry_freshness === "fresh",
    eventFreshness: device.telemetry_freshness || "no_events",
    latestEventTimestamp: device.latest_event_timestamp || null,
    connectionState: device.connection_state || "unknown",
    adminState: device.admin_state || "UNKNOWN",
    operatingState: device.operating_state || "UNKNOWN",
    deviceServiceAvailable: Boolean(device.device_service_available),
    telemetryEnabled: true,
    telemetryFresh: device.telemetry_freshness === "fresh",
    telemetryStatus: device.telemetry_freshness || "no_events",
    telemetryLastSeenAt: device.latest_event_timestamp || null,
    overallStatus: device.overall_status || (device.admin_state !== "UNKNOWN" && device.connection_state === "connected" && device.operating_state === "UP" && device.telemetry_freshness === "fresh" ? "available" : device.connection_state === "disconnected" || device.admin_state === "LOCKED" || device.operating_state === "DOWN" ? "unavailable" : "degraded"),
    reason: device.reason || `${device.admin_state || "UNKNOWN"} / ${device.operating_state || "UNKNOWN"} · ${device.connection_state || "unknown"}`,
  };
}

function resourceTargets(devices, nodes) {
  const hostnames = new Set(nodes.map((node) => node.hostname).filter(Boolean));
  devices.forEach((device) => {
    if (device.nodeName) hostnames.add(device.nodeName);
    if (device.node_name) hostnames.add(device.node_name);
  });
  const node = nodes.find((item) => item.hostname === AI_HAT_NODE) || {};
  const nodeKnown = hostnames.has(AI_HAT_NODE);
  return [{
    id: `resource:${AI_HAT_NODE}:ai-hat`,
    kind: "resource",
    name: "ai-hat",
    namespace: "",
    displayName: `${AI_HAT_NODE} AI HAT`,
    nodeName: AI_HAT_NODE,
    type: "edge-ai-resource",
    protocol: "node resource",
    properties: ["ai-hat"],
    telemetryEnabled: false,
    telemetryFresh: false,
    telemetryStatus: "resource",
    telemetryLastSeenAt: null,
    overallStatus: node.node_health || "unknown",
    reason: nodeKnown ? "AI HAT resource is mapped to a registered edge node." : "AI HAT resource is declared for dev0002, but node status is not observed yet.",
  }];
}

function isSenseHatTarget(target) {
  const text = `${target.displayName} ${target.nodeName} ${target.type} ${target.properties.join(" ")}`.toLowerCase();
  return text.includes("sensehat") || text.includes("sense-hat") || target.nodeName === "etri-dev0003-raspi5";
}

function nodeAcceptsTarget(node, target) {
  if (!node || !target) return false;
  if (node.type === "device_source") return target.kind === "device";
  if (node.type === "ai_inference") return target.kind === "resource" || target.nodeName === AI_HAT_NODE;
  return false;
}

function incomingEdges(workflow, nodeId) {
  return workflow.edges.filter((edge) => edge.to === nodeId);
}

function outgoingEdges(workflow, nodeId) {
  return workflow.edges.filter((edge) => edge.from === nodeId);
}

function edgeExists(workflow, from, to) {
  return workflow.edges.some((edge) => edge.from === from && edge.to === to);
}
