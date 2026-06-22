const NODE_W = 160;
const NODE_H = 118;
const AI_HAT_NODE = "etri-dev0002-raspi5";

const NODE_TEMPLATES = [
  { type: "device_source", label: "Collect", caption: "camera/sensor telemetry intake", data: "raw telemetry" },
  { type: "transform", label: "Preprocess", caption: "normalize, window, feature extraction", data: "feature tensor" },
  { type: "ai_inference", label: "Inference", caption: "edge model execution", data: "prediction" },
  { type: "postprocess", label: "Postprocess", caption: "threshold, score, event shaping", data: "inspection event" },
  { type: "store_observe", label: "Store & Observe", caption: "InfluxDB/cache/result persistence", data: "stored result" },
  { type: "dashboard_event", label: "Dashboard", caption: "operator signal and review", data: "operator signal" },
  { type: "condition", label: "Quality Gate", caption: "optional freshness/threshold branch", data: "branch decision" },
];

const workflowState = {
  targets: [],
  nodes: [],
  workflows: [
    {
      id: "factory-vision-inspection-pipeline",
      name: "factory-vision-inspection-pipeline",
      nodes: [
        { id: "collect-1", label: "Collect Raw Telemetry", type: "device_source", x: 40, y: 72, targetId: "", config: { window: "-30m", property: "auto" } },
        { id: "preprocess-1", label: "Normalize Feature Window", type: "transform", x: 236, y: 72, targetId: "", config: { method: "normalize-window" } },
        { id: "inference-1", label: "Run Defect Inference", type: "ai_inference", x: 432, y: 72, targetId: `resource:${AI_HAT_NODE}:ai-hat`, config: { model: "factory-vision-inspection-lite", accelerator: "ai-hat" } },
        { id: "postprocess-1", label: "Format Inspection Event", type: "postprocess", x: 40, y: 242, targetId: "", config: { threshold: "0.82", output: "defect-score" } },
        { id: "store-1", label: "Persist Result Cache", type: "store_observe", x: 236, y: 242, targetId: "", config: { sink: "InfluxDB + result cache" } },
        { id: "dashboard-1", label: "Publish Dashboard Signal", type: "dashboard_event", x: 432, y: 242, targetId: "", config: { severity: "warning" } },
      ],
      edges: [
        { from: "collect-1", to: "preprocess-1", label: "raw telemetry" },
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

function displayDeviceType(device) {
  if (device.device_type === "virtual_device") return "registered device";
  return device.device_type || device.model || "device";
}

function targetFromDevice(device) {
  const nodeName = device.node_name || device.nodeName || "";
  return {
    id: `device:${device.namespace || "default"}:${device.name}`,
    kind: "device",
    name: device.name,
    namespace: device.namespace || "default",
    displayName: device.name,
    nodeName,
    type: displayDeviceType(device),
    protocol: device.protocol || "-",
    properties: Array.isArray(device.properties) ? device.properties : [],
    telemetryEnabled: Boolean(device.telemetry_enabled || (device.telemetry_status && device.telemetry_status !== "disabled")),
    telemetryFresh: Boolean(device.telemetry_fresh),
    telemetryStatus: device.telemetry_status || (device.telemetry_fresh ? "fresh" : "stale"),
    telemetryLastSeenAt: device.telemetry_last_seen_at || device.telemetry_last_seen || null,
    deviceStatusFresh: Boolean(device.device_status_fresh),
    deviceStatusLastReportedAt: device.device_status_last_reported_at || null,
    overallStatus: device.overall_status || device.status || "unknown",
    reason: device.reason || device.status_reason || "-",
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
    deviceStatusFresh: node.node_health === "healthy",
    deviceStatusLastReportedAt: null,
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
  if (node.type === "device_source") return target.kind === "device" && target.telemetryEnabled;
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
