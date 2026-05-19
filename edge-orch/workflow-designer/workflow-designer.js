/* Mixed-Device AI Service Workflow Designer
 * Read-only + dry-run only. No Kubernetes/MQTT/Device mutation is performed here.
 */

const COMPUTE_NODES = [
  { id: "factoryName-ser0001-CG0MS0", name: "factoryName-ser0001-CG0MS0", label: "Edge AI Server", kind: "compute", role: "Edge AI Server", arch: "x86_64", type: "server", accelerator: "GPU", availableFor: ["ai-inference", "event-publish", "storage", "sink", "threshold-check", "dashboard-update"] },
  { id: "etri-dev0001-jetorn", name: "etri-dev0001-jetorn", label: "Jetson", kind: "compute", role: "Edge Device", arch: "aarch64", type: "Jetson", accelerator: "GPU-lite", availableFor: ["input", "collect", "processing", "preprocess", "ai-inference", "state-read"] },
  { id: "etri-dev0002-raspi5", name: "etri-dev0002-raspi5", label: "Raspberry Pi 5", kind: "compute", role: "Edge Device", arch: "aarch64", type: "Raspberry Pi 5", accelerator: "none", availableFor: ["input", "collect", "processing", "preprocess", "state-read"] },
];

const NODE_POOL = COMPUTE_NODES;

const PLATFORM_ENDPOINTS = [
  { id: "mqtt-broker", name: "MQTT Broker", kind: "endpoint", endpointType: "message-broker", transportTypes: ["mqtt"] },
  { id: "influxdb", name: "InfluxDB", kind: "endpoint", endpointType: "time-series-db", transportTypes: ["influx-line", "http"] },
  { id: "state-aggregator", name: "State Aggregator", kind: "endpoint", endpointType: "api-service", transportTypes: ["http", "internal-api"] },
  { id: "dashboard", name: "Dashboard", kind: "endpoint", endpointType: "operator-ui", transportTypes: ["http", "websocket"] },
];

const INPUT_DEVICES = [
  { name: "vib-device-01", group: "factory-anomaly-detection", node: "etri-dev0001-jetorn", type: "vibration" },
  { name: "rpi-vib-device-01", group: "factory-anomaly-detection", node: "etri-dev0002-raspi5", type: "vibration" },
  { name: "env-device-01", group: "environment-monitoring", node: "etri-dev0001-jetorn", type: "environment" },
  { name: "rpi-env-device-01", group: "environment-monitoring", node: "etri-dev0002-raspi5", type: "environment" },
  { name: "act-device-01", group: "actuator-command-monitoring", node: "etri-dev0001-jetorn", type: "actuator-state" },
  { name: "rpi-act-device-01", group: "actuator-command-monitoring", node: "etri-dev0002-raspi5", type: "actuator-state" },
];

const EXAMPLE_WORKFLOWS = {
  "factory-anomaly-detection": {
    serviceName: "factory-anomaly-detection",
    mode: "dry-run",
    description: "진동 입력을 수집/전처리/추론하고 이벤트와 운영 화면으로 전달하는 서비스 설계 예시",
    inputDevices: ["vib-device-01", "rpi-vib-device-01"],
    stages: [
      { name: "collect", type: "collect", input: "vib-device-01", output: "raw-signal", connectedDevice: "vib-device-01", requiredResource: "edge mqtt + sensor adapter" },
      { name: "preprocess", type: "preprocess", input: "raw-signal", output: "feature-vector", connectedDevice: "vib-device-01", requiredResource: "aarch64 cpu" },
      { name: "inference", type: "ai-inference", input: "feature-vector", output: "anomaly-score", connectedDevice: "vib-device-01", requiredResource: "gpu or jetson" },
      { name: "event-publish", type: "output", input: "anomaly-score", output: "mqtt-event", connectedDevice: "vib-device-01", requiredResource: "mqtt publisher" },
      { name: "dashboard-sink", type: "sink", input: "mqtt-event", output: "operator-view", connectedDevice: "", requiredResource: "dashboard/state view" },
      { name: "state-aggregator-sink", type: "sink", input: "mqtt-event", output: "aggregated-state", connectedDevice: "", requiredResource: "state-aggregator api" },
      { name: "influxdb-sink", type: "sink", input: "anomaly-score", output: "time-series-record", connectedDevice: "", requiredResource: "InfluxDB write path" },
    ],
    edges: [
      { from: "device:vib-device-01", to: "collect", data: "vib-device-01", transport: "mqtt" },
      { from: "collect", to: "preprocess", data: "raw-signal", transport: "mqtt" },
      { from: "preprocess", to: "inference", data: "feature-vector", transport: "http" },
      { from: "inference", to: "event-publish", data: "anomaly-score", transport: "internal" },
      { from: "event-publish", to: "dashboard-sink", data: "mqtt-event", transport: "mqtt" },
      { from: "event-publish", to: "state-aggregator-sink", data: "mqtt-event", transport: "mqtt" },
      { from: "inference", to: "influxdb-sink", data: "anomaly-score", transport: "influx-line" },
    ],
    placements: [
      { stage: "collect", targetNode: "etri-dev0001-jetorn" },
      { stage: "preprocess", targetNode: "etri-dev0001-jetorn" },
      { stage: "inference", targetNode: "factoryName-ser0001-CG0MS0" },
      { stage: "event-publish", targetNode: "factoryName-ser0001-CG0MS0" },
      { stage: "dashboard-sink", targetNode: "factoryName-ser0001-CG0MS0" },
      { stage: "state-aggregator-sink", targetNode: "factoryName-ser0001-CG0MS0" },
      { stage: "influxdb-sink", targetNode: "factoryName-ser0001-CG0MS0" },
    ],
    endpoints: ["MQTT Broker", "InfluxDB", "State Aggregator", "Dashboard"],
    transports: [
      { data: "raw-signal", producer: "collect", consumer: "preprocess", transport: "mqtt" },
      { data: "feature-vector", producer: "preprocess", consumer: "inference", transport: "http" },
      { data: "anomaly-score", producer: "inference", consumer: "event-publish", transport: "internal" },
      { data: "mqtt-event", producer: "event-publish", consumer: "MQTT Broker", endpoint: "MQTT Broker", transport: "mqtt" },
      { data: "mqtt-event", producer: "event-publish", consumer: "State Aggregator", endpoint: "State Aggregator", transport: "mqtt" },
      { data: "mqtt-event", producer: "event-publish", consumer: "Dashboard", endpoint: "Dashboard", transport: "http" },
      { data: "anomaly-score", producer: "inference", consumer: "InfluxDB", endpoint: "InfluxDB", transport: "influx-line" },
    ],
  },
  "environment-monitoring": {
    serviceName: "environment-monitoring",
    mode: "dry-run",
    description: "환경 센서를 수집/정규화/임계치 판단 후 저장 및 대시보드 sink로 전달하는 설계 예시",
    inputDevices: ["env-device-01", "rpi-env-device-01"],
    stages: [
      { name: "collect", type: "collect", input: "env-device-01", output: "env-raw", connectedDevice: "env-device-01", requiredResource: "sensor mqtt" },
      { name: "normalize", type: "preprocess", input: "env-raw", output: "normalized-env", connectedDevice: "env-device-01", requiredResource: "lightweight preprocessing" },
      { name: "threshold-check", type: "processing", input: "normalized-env", output: "environment-state", connectedDevice: "env-device-01", requiredResource: "server cpu" },
      { name: "storage-sink", type: "sink", input: "environment-state", output: "state-record", connectedDevice: "", requiredResource: "InfluxDB/state store" },
      { name: "dashboard-sink", type: "sink", input: "environment-state", output: "operator-view", connectedDevice: "", requiredResource: "dashboard" },
    ],
    edges: [
      { from: "device:env-device-01", to: "collect", data: "env-device-01", transport: "mqtt" },
      { from: "collect", to: "normalize", data: "env-raw", transport: "mqtt" },
      { from: "normalize", to: "threshold-check", data: "normalized-env", transport: "http" },
      { from: "threshold-check", to: "storage-sink", data: "environment-state", transport: "influx-line" },
      { from: "threshold-check", to: "dashboard-sink", data: "environment-state", transport: "http" },
    ],
    placements: [
      { stage: "collect", targetNode: "etri-dev0001-jetorn" },
      { stage: "normalize", targetNode: "etri-dev0001-jetorn" },
      { stage: "threshold-check", targetNode: "factoryName-ser0001-CG0MS0" },
      { stage: "storage-sink", targetNode: "factoryName-ser0001-CG0MS0" },
      { stage: "dashboard-sink", targetNode: "factoryName-ser0001-CG0MS0" },
    ],
    endpoints: ["InfluxDB", "State Aggregator", "Dashboard"],
    transports: [
      { data: "env-raw", producer: "collect", consumer: "normalize", transport: "mqtt" },
      { data: "normalized-env", producer: "normalize", consumer: "threshold-check", transport: "http" },
      { data: "environment-state", producer: "threshold-check", consumer: "InfluxDB", endpoint: "InfluxDB", transport: "influx-line" },
      { data: "environment-state", producer: "threshold-check", consumer: "State Aggregator", endpoint: "State Aggregator", transport: "http" },
      { data: "environment-state", producer: "threshold-check", consumer: "Dashboard", endpoint: "Dashboard", transport: "http" },
    ],
  },
  "actuator-command-monitoring": {
    serviceName: "actuator-command-monitoring",
    mode: "dry-run",
    description: "actuator command 실행 없이 command_state/health 상태만 읽어 이벤트와 dashboard에 반영하는 설계 예시",
    inputDevices: ["act-device-01", "rpi-act-device-01"],
    stages: [
      { name: "command-state-read", type: "input", input: "act-device-01", output: "command-state", connectedDevice: "act-device-01", requiredResource: "read-only DeviceStatus/telemetry" },
      { name: "state-validate", type: "processing", input: "command-state", output: "command-health-event", connectedDevice: "act-device-01", requiredResource: "server cpu" },
      { name: "event-publish", type: "output", input: "command-health-event", output: "mqtt-event", connectedDevice: "act-device-01", requiredResource: "event bus" },
      { name: "dashboard-sink", type: "sink", input: "mqtt-event", output: "operator-view", connectedDevice: "", requiredResource: "dashboard" },
    ],
    edges: [
      { from: "device:act-device-01", to: "command-state-read", data: "act-device-01", transport: "read-only" },
      { from: "command-state-read", to: "state-validate", data: "command-state", transport: "http" },
      { from: "state-validate", to: "event-publish", data: "command-health-event", transport: "internal" },
      { from: "event-publish", to: "dashboard-sink", data: "mqtt-event", transport: "mqtt" },
    ],
    placements: [
      { stage: "command-state-read", targetNode: "etri-dev0001-jetorn" },
      { stage: "state-validate", targetNode: "factoryName-ser0001-CG0MS0" },
      { stage: "event-publish", targetNode: "factoryName-ser0001-CG0MS0" },
      { stage: "dashboard-sink", targetNode: "factoryName-ser0001-CG0MS0" },
    ],
    endpoints: ["MQTT Broker", "State Aggregator", "Dashboard"],
    transports: [
      { data: "command-state", producer: "command-state-read", consumer: "state-validate", transport: "http" },
      { data: "command-health-event", producer: "state-validate", consumer: "event-publish", transport: "internal" },
      { data: "mqtt-event", producer: "event-publish", consumer: "MQTT Broker", endpoint: "MQTT Broker", transport: "mqtt" },
      { data: "mqtt-event", producer: "event-publish", consumer: "State Aggregator", endpoint: "State Aggregator", transport: "mqtt" },
      { data: "mqtt-event", producer: "event-publish", consumer: "Dashboard", endpoint: "Dashboard", transport: "http" },
    ],
  },
};

const state = { workflow: clone(EXAMPLE_WORKFLOWS["factory-anomaly-detection"]), nodes: COMPUTE_NODES, endpoints: PLATFORM_ENDPOINTS, devices: INPUT_DEVICES, planFormat: "json", apiMode: "example mode", selectedStage: "" };

function clone(value) { return JSON.parse(JSON.stringify(value)); }
function $(id) { return document.getElementById(id); }
function stageByName(workflow) { return new Map((workflow.stages || []).map((stage) => [stage.name, stage])); }
function placementByStage(workflow) { return new Map((workflow.placements || []).map((item) => [item.stage, item])); }
function endpointByName(endpoints = PLATFORM_ENDPOINTS) { return new Map(endpoints.map((item) => [item.name, item])); }
function computeNodeByName(nodes = COMPUTE_NODES) { return new Map(nodes.map((item) => [item.name || item.id, item])); }
function stageTypeClass(type) { return String(type || "stage").replace(/[^a-z0-9-]/gi, "-").toLowerCase(); }

function getStagePlacement(workflow, stageName) { return (workflow.placements || []).find((item) => item.stage === stageName); }
function getStageNode(workflow, stageName) { return (getStagePlacement(workflow, stageName) || {}).targetNode || ""; }
function isEndpointName(name, endpoints = PLATFORM_ENDPOINTS) { return endpointByName(endpoints).has(name); }
function nodeLabel(nodeName, nodes = COMPUTE_NODES) { const node = computeNodeByName(nodes).get(nodeName); return node ? `${node.label || node.name} (${node.name})` : nodeName || "미지정"; }

function applyStagePlacement(workflow, stageName, targetNode) {
  const placements = workflow.placements || [];
  const exists = placements.some((item) => item.stage === stageName);
  return { ...workflow, placements: exists ? placements.map((item) => item.stage === stageName ? { ...item, targetNode } : { ...item }) : [...placements, { stage: stageName, targetNode }] };
}

function selectStageForPlacement(targetState, stageName) {
  targetState.selectedStage = stageName || "";
  return targetState;
}

function assignSelectedStageToNode(workflow, targetState, targetNode) {
  if (!targetState.selectedStage || !targetNode) return workflow;
  const next = applyStagePlacement(workflow, targetState.selectedStage, targetNode);
  targetState.selectedStage = "";
  return next;
}

function rectanglesOverlap(a, b, gap = 0) {
  const aw = a.width || 0;
  const ah = a.height || 0;
  const bw = b.width || 0;
  const bh = b.height || 0;
  return !(
    a.x + aw + gap <= b.x ||
    b.x + bw + gap <= a.x ||
    a.y + ah + gap <= b.y ||
    b.y + bh + gap <= a.y
  );
}

function buildExecutionPlan(workflow) {
  return {
    serviceName: workflow.serviceName,
    mode: "dry-run",
    inputDevices: [...(workflow.inputDevices || [])],
    stages: (workflow.stages || []).map((stage) => ({ stage: stage.name, ...stage })),
    edges: (workflow.edges || []).map((edge) => ({ ...edge })),
    placements: (workflow.placements || []).map((placement) => ({ ...placement })),
    endpoints: [...(workflow.endpoints || [])],
    transports: (workflow.transports || []).map((transport) => ({ ...transport })),
  };
}

function toYaml(value, indent = 0) {
  const pad = " ".repeat(indent);
  if (Array.isArray(value)) return value.map((item) => typeof item === "object" && item !== null ? `${pad}- ${toYaml(item, indent + 2).trimStart()}` : `${pad}- ${item}`).join("\n");
  if (typeof value === "object" && value !== null) return Object.entries(value).map(([key, item]) => Array.isArray(item) || (typeof item === "object" && item !== null) ? `${pad}${key}:\n${toYaml(item, indent + 2)}` : `${pad}${key}: ${item}`).join("\n");
  return `${pad}${value}`;
}

function normalizeEdgeNodeId(id) { return String(id || "").startsWith("device:") || String(id || "").startsWith("endpoint:") || String(id || "").startsWith("stage:") ? id : `stage:${id}`; }

function buildWorkflowDagModel(workflow) {
  const stages = workflow.stages || [];
  const nodes = [];
  const edges = [];
  const nodeWidth = 210;
  const nodeHeight = 96;
  const columnGap = 92;
  const startX = 44;
  const deviceY = 48;
  const stageY = 210;
  const sinkY = 372;
  const endpointY = 534;
  const mainStages = stages.filter((stage) => stage.type !== "sink");
  const sinkStages = stages.filter((stage) => stage.type === "sink");
  const stageColumns = new Map();

  (workflow.inputDevices || []).forEach((device, index) => {
    nodes.push({ id: `device:${device}`, label: device, kind: "device", type: "input-device", x: startX, y: deviceY + index * 118, width: nodeWidth, height: nodeHeight });
  });

  mainStages.forEach((stage, index) => {
    const x = startX + (index + 1) * (nodeWidth + columnGap);
    stageColumns.set(stage.name, x);
    nodes.push({ id: `stage:${stage.name}`, label: stage.name, kind: "stage", type: stage.type, input: stage.input, output: stage.output, connectedDevice: stage.connectedDevice, x, y: stageY, width: nodeWidth, height: nodeHeight });
  });

  const sinkStartX = startX + Math.max(1, mainStages.length - 2) * (nodeWidth + columnGap);
  sinkStages.forEach((stage, index) => {
    const x = sinkStartX + index * (nodeWidth + 42);
    stageColumns.set(stage.name, x);
    nodes.push({ id: `stage:${stage.name}`, label: stage.name, kind: "stage", type: stage.type, input: stage.input, output: stage.output, connectedDevice: stage.connectedDevice, x, y: sinkY, width: nodeWidth, height: nodeHeight });
  });

  const endpointStartX = startX + Math.max(1, mainStages.length - 2) * (nodeWidth + columnGap);
  (workflow.endpoints || []).forEach((endpoint, index) => {
    nodes.push({ id: `endpoint:${endpoint}`, label: endpoint, kind: "endpoint", type: "platform-endpoint", x: endpointStartX + index * (nodeWidth + 42), y: endpointY, width: nodeWidth, height: nodeHeight });
  });

  (workflow.edges || []).forEach((edge) => {
    const from = String(edge.from || "").startsWith("device:") ? edge.from : normalizeEdgeNodeId(edge.from);
    const to = isEndpointName(edge.to, PLATFORM_ENDPOINTS) ? `endpoint:${edge.to}` : normalizeEdgeNodeId(edge.to);
    edges.push({ from, to, data: edge.data, transport: edge.transport });
  });
  for (const transport of workflow.transports || []) {
    if (transport.endpoint && isEndpointName(transport.consumer)) {
      edges.push({ from: normalizeEdgeNodeId(transport.producer), to: `endpoint:${transport.consumer}`, data: transport.data, transport: transport.transport, endpoint: transport.endpoint });
    }
  }
  const uniqEdges = Array.from(new Map(edges.map((edge) => [`${edge.from}|${edge.to}|${edge.data}|${edge.transport}`, edge])).values());
  const maxX = Math.max(...nodes.map((node) => node.x + node.width), 1120);
  const maxY = Math.max(...nodes.map((node) => node.y + node.height), 650);
  return { nodes, edges: uniqEdges, width: maxX + 56, height: maxY + 44 };
}

function buildPlacementModel(workflow, nodes = COMPUTE_NODES) {
  const placementMap = placementByStage(workflow);
  return { nodes: nodes.map((node) => ({ ...node, kind: "compute" })), rows: (workflow.stages || []).map((stage) => ({ stage: stage.name, type: stage.type, targetNode: (placementMap.get(stage.name) || {}).targetNode || "", input: stage.input || "", output: stage.output || "", requiredResource: stage.requiredResource || "", connectedDevice: stage.connectedDevice || "" })) };
}

function buildTransportModel(workflow, nodes = COMPUTE_NODES, endpoints = PLATFORM_ENDPOINTS) {
  const stages = stageByName(workflow);
  const nodeMap = computeNodeByName(nodes);
  const rows = [];
  for (const transport of workflow.transports || []) {
    const producerStage = stages.has(transport.producer) ? transport.producer : "";
    const consumerStage = stages.has(transport.consumer) ? transport.consumer : "";
    const consumerEndpoint = transport.endpoint || (isEndpointName(transport.consumer, endpoints) ? transport.consumer : "");
    const producerNodeName = producerStage ? getStageNode(workflow, producerStage) : "";
    const consumerNodeName = consumerStage ? getStageNode(workflow, consumerStage) : "";
    rows.push({ data: transport.data, producerStage, producerNode: producerNodeName, producerNodeLabel: nodeLabel(producerNodeName, nodes), transport: transport.transport, consumerStage, consumerEndpoint, consumerNode: consumerNodeName, consumerNodeLabel: consumerStage ? nodeLabel(consumerNodeName, nodes) : consumerEndpoint, platformService: consumerEndpoint, producerNodeType: (nodeMap.get(producerNodeName) || {}).type || "" });
  }
  return { rows };
}

function validateWorkflowPlan(workflow, nodes = COMPUTE_NODES, endpoints = PLATFORM_ENDPOINTS, devices = INPUT_DEVICES) {
  const results = [];
  const stages = workflow.stages || [];
  const stageNames = new Set(stages.map((stage) => stage.name));
  const nodeNames = new Set(nodes.map((node) => node.name || node.id));
  const endpointNames = new Set(endpoints.map((endpoint) => endpoint.name));
  const deviceNames = new Set((devices || []).map((device) => device.name || device.device_name).filter(Boolean));
  const placements = placementByStage(workflow);
  const outputNames = new Set(stages.map((stage) => stage.output).filter(Boolean));

  if (!(workflow.inputDevices || []).length) results.push({ level: "WARN", rule: "input-device", message: "service input device가 비어 있습니다." });
  else results.push({ level: "PASS", rule: "input-device", message: `service input device ${(workflow.inputDevices || []).length}개가 정의되어 있습니다.` });
  for (const device of workflow.inputDevices || []) if (deviceNames.size && !deviceNames.has(device)) results.push({ level: "WARN", rule: "device-exists", message: `${device}는 device model에서 확인되지 않았습니다.` });

  for (const stage of stages) {
    const placement = placements.get(stage.name);
    if (!placement || !placement.targetNode) { results.push({ level: "FAIL", rule: "placement", message: `${stage.name} stage target node가 지정되지 않았습니다.` }); continue; }
    if (!nodeNames.has(placement.targetNode)) { results.push({ level: "FAIL", rule: "placement", message: `${stage.name} stage target node '${placement.targetNode}' is unknown node.` }); continue; }
    const node = nodes.find((item) => (item.name || item.id) === placement.targetNode);
    const type = `${stage.type} ${stage.name}`.toLowerCase();
    if (type.includes("inference") && node && node.type === "Raspberry Pi 5") results.push({ level: "WARN", rule: "inference-placement", message: `${stage.name} inference stage가 Raspberry Pi 5에 배치되었습니다. GPU/Edge AI Server 또는 Jetson 권장.` });
  }

  for (const stage of stages) {
    if (stage.input && !outputNames.has(stage.input) && !(workflow.inputDevices || []).includes(stage.input) && !deviceNames.has(stage.input)) {
      results.push({ level: "FAIL", rule: "chain", message: `${stage.name} stage input/output chain이 끊겼습니다: '${stage.input}' 생산자를 찾을 수 없습니다.` });
    }
  }

  for (const edge of workflow.edges || []) {
    const fromOk = String(edge.from || "").startsWith("device:") ? (workflow.inputDevices || []).includes(String(edge.from).replace("device:", "")) : stageNames.has(edge.from);
    const toOk = stageNames.has(edge.to) || endpointNames.has(edge.to);
    if (!fromOk || !toOk) results.push({ level: "FAIL", rule: "edge", message: `${edge.from} -> ${edge.to} producer/consumer edge가 유효하지 않습니다.` });
    if (edge.data && !outputNames.has(edge.data) && !(workflow.inputDevices || []).includes(edge.data) && !String(edge.from || "").startsWith("device:")) results.push({ level: "FAIL", rule: "edge-data", message: `${edge.data} data producer를 찾을 수 없습니다.` });
  }

  for (const endpoint of workflow.endpoints || []) if (!endpointNames.has(endpoint)) results.push({ level: "FAIL", rule: "endpoint", message: `${endpoint} endpoint model이 없습니다.` });
  const transportConsumers = new Set((workflow.transports || []).map((item) => item.consumer));
  const transportEndpoints = new Set((workflow.transports || []).map((item) => item.endpoint).filter(Boolean));
  const eventPublish = stages.find((stage) => stage.name === "event-publish" || stage.type === "output");
  if (eventPublish && !transportEndpoints.has("MQTT Broker") && !transportConsumers.has("MQTT Broker")) results.push({ level: "FAIL", rule: "mqtt-transport", message: "event-publish stage에서 MQTT Broker transport 연결이 없습니다." });
  if (!transportEndpoints.has("Dashboard") && !transportConsumers.has("Dashboard")) results.push({ level: "WARN", rule: "dashboard-sink", message: "dashboard sink 연결이 없습니다." });
  for (const endpoint of workflow.endpoints || []) if (!transportEndpoints.has(endpoint) && !transportConsumers.has(endpoint)) results.push({ level: "WARN", rule: "endpoint-transport", message: `${endpoint} endpoint 연결 transport가 없습니다.` });

  for (const transport of workflow.transports || []) {
    if (!stageNames.has(transport.producer)) results.push({ level: "FAIL", rule: "transport", message: `${transport.data} transport producer ${transport.producer} stage가 없습니다.` });
    if (!stageNames.has(transport.consumer) && !endpointNames.has(transport.consumer)) results.push({ level: "FAIL", rule: "transport", message: `${transport.data} transport consumer ${transport.consumer}가 stage/endpoint에 없습니다.` });
  }
  if (!results.some((item) => item.level === "FAIL")) results.push({ level: "PASS", rule: "dry-run", message: "dry-run plan generation 가능. 실제 배포/명령 실행은 수행하지 않습니다." });
  return { status: results.some((item) => item.level === "FAIL") ? "FAIL" : results.some((item) => item.level === "WARN") ? "WARN" : "PASS", results };
}

function normalizeLiveNodes(dashboardPayload) { return COMPUTE_NODES.map((node) => ({ ...node, live: ((dashboardPayload && dashboardPayload.nodes) || []).some((item) => item.name === node.name) })); }
function normalizeLiveDevices(dashboardPayload) { return ((dashboardPayload && dashboardPayload.devices) || []).map((device) => ({ name: device.name, nodeName: device.node_name || device.nodeName, status: device.overall_status || device.status })); }

function render() { if (typeof document === "undefined") return; renderServices(); renderDag(); renderPlacement(); renderTransport(); renderPlan(); renderValidation(); renderApiMode(); renderSummary(); }
function renderSummary() {
  if (typeof document === "undefined") return;
  const validation = validateWorkflowPlan(state.workflow, state.nodes, state.endpoints, state.devices);
  const set = (id, value) => { const el = $(id); if (el) el.textContent = value; };
  set("summaryService", state.workflow.serviceName || "-");
  set("summaryInputs", String((state.workflow.inputDevices || []).length));
  set("summaryInputNames", (state.workflow.inputDevices || []).join(", ") || "-");
  set("summaryStages", String((state.workflow.stages || []).length));
  set("summaryEdges", String((state.workflow.edges || []).length));
  set("summaryEndpoints", String((state.workflow.endpoints || []).length));
  set("summaryValidation", validation.status);
  const validationMetric = $("validationMetric");
  if (validationMetric) validationMetric.className = `metric status-${levelClass(validation.status)}`;
}
function renderServices() {
  const root = $("servicePalette"); if (!root) return;
  root.innerHTML = Object.values(EXAMPLE_WORKFLOWS).map((workflow) => `<button class="service-option ${workflow.serviceName === state.workflow.serviceName ? "selected" : ""}" data-service="${workflow.serviceName}" type="button"><strong>${workflow.serviceName}</strong><span>${workflow.description}</span><small>${(workflow.inputDevices || []).join(", ")}</small></button>`).join("");
}
function edgePath(from, to) {
  const fromW = from.width || 210;
  const fromH = from.height || 96;
  const toH = to.height || 96;
  const x1 = from.x + fromW;
  const y1 = from.y + fromH / 2;
  const x2 = to.x;
  const y2 = to.y + toH / 2;
  const dx = Math.max(70, Math.abs(x2 - x1) / 2);
  return { d: `M ${x1} ${y1} C ${x1 + dx} ${y1}, ${x2 - dx} ${y2}, ${x2} ${y2}`, labelX: (x1 + x2) / 2, labelY: (y1 + y2) / 2 - 10 };
}
function renderDag() {
  const root = $("workflowDag"); if (!root) return;
  const title = $("serviceName"); if (title) title.textContent = state.workflow.serviceName;
  const desc = $("serviceDescription"); if (desc) desc.textContent = state.workflow.description;
  const inputs = $("inputDevices"); if (inputs) inputs.textContent = (state.workflow.inputDevices || []).join(", ") || "입력 device 없음";
  const dag = buildWorkflowDagModel(state.workflow); const nodeMap = new Map(dag.nodes.map((node) => [node.id, node]));
  const edges = dag.edges.map((edge) => { const from = nodeMap.get(edge.from); const to = nodeMap.get(edge.to); if (!from || !to) return ""; const p = edgePath(from, to); return `<path class="dag-edge" d="${p.d}" marker-end="url(#arrowHead)"></path><text class="edge-label" x="${p.labelX}" y="${p.labelY}">${edge.data} · ${edge.transport}</text>`; }).join("");
  const nodes = dag.nodes.map((node) => `<article class="dag-node ${node.kind} type-${stageTypeClass(node.type)}" style="left:${node.x}px; top:${node.y}px; width:${node.width}px; min-height:${node.height}px"><span>${node.kind}</span><strong>${node.label}</strong>${node.kind === "stage" ? `<small>${node.type} · in:${node.input || "-"} · out:${node.output || "-"}</small>` : `<small>${node.type || ""}</small>`}</article>`).join("");
  root.innerHTML = `<div class="dag-surface" style="width:${dag.width}px;height:${dag.height}px"><svg class="dag-svg" width="${dag.width}" height="${dag.height}" viewBox="0 0 ${dag.width} ${dag.height}"><defs><marker id="arrowHead" markerWidth="10" markerHeight="10" refX="8" refY="3" orient="auto" markerUnits="strokeWidth"><path d="M0,0 L0,6 L9,3 z"></path></marker></defs>${edges}</svg>${nodes}</div>`;
}
function renderPlacement() {
  const root = $("placementInspector"); if (!root) return;
  const model = buildPlacementModel(state.workflow, state.nodes);
  root.innerHTML = model.rows.map((row) => `<article class="placement-row type-${stageTypeClass(row.type)} ${state.selectedStage === row.stage ? "selected" : ""}" draggable="true" data-stage="${row.stage}" title="클릭 후 오른쪽 compute node를 누르거나, 이 카드를 node로 드래그하세요."><div><strong>${row.stage}</strong><span class="type-badge">${row.type}</span><small>in ${row.input || "-"} → out ${row.output || "-"}</small><small>${row.requiredResource || "-"}</small></div><label>target node<select data-placement-stage="${row.stage}">${model.nodes.map((node) => `<option value="${node.name}" ${node.name === row.targetNode ? "selected" : ""}>${node.label} · ${node.name}</option>`).join("")}</select></label></article>`).join("");
  const nodeRoot = $("nodeDropTargets"); if (nodeRoot) nodeRoot.innerHTML = model.nodes.map((node) => `<article class="node-drop ${state.selectedStage ? "click-target" : ""}" data-node="${node.name}" title="선택된 stage를 이 node에 배치"><strong>${node.label}</strong><small>${node.name}</small><span>${node.arch} · ${node.type} · ${node.accelerator}</span><em>${state.selectedStage ? `${state.selectedStage} 배치` : "drag/drop 또는 stage 선택 후 클릭"}</em></article>`).join("");
}
function renderTransport() {
  const root = $("transportView"); if (!root) return;
  const model = buildTransportModel(state.workflow, state.nodes, state.endpoints);
  root.innerHTML = `<table><thead><tr><th>data</th><th>producer</th><th>producer node</th><th>transport</th><th>consumer / endpoint</th><th>consumer node / platform</th></tr></thead><tbody>${model.rows.map((row) => `<tr><td><strong>${row.data}</strong></td><td>${row.producerStage}</td><td>${row.producerNodeLabel}</td><td><span class="transport-badge">${row.transport}</span></td><td>${row.consumerStage || row.consumerEndpoint}</td><td>${row.consumerStage ? row.consumerNodeLabel : row.platformService}</td></tr>`).join("")}</tbody></table>`;
}
function renderPlan() { const root = $("planPreview"); if (!root) return; const plan = buildExecutionPlan(state.workflow); root.textContent = state.planFormat === "yaml" ? toYaml(plan) : JSON.stringify(plan, null, 2); }
function levelClass(level) { return String(level || "PASS").toLowerCase(); }
function renderValidation() { const root = $("validationResult"); if (!root) return; const validation = validateWorkflowPlan(state.workflow, state.nodes, state.endpoints, state.devices); const status = $("validationStatus"); if (status) { status.textContent = validation.status; status.className = `status-pill ${levelClass(validation.status)}`; } root.innerHTML = validation.results.map((item) => `<li class="validation-item ${levelClass(item.level)}"><strong>${item.level}</strong><span>${item.message}</span></li>`).join(""); }
function renderApiMode() { const root = $("apiMode"); if (root) root.textContent = state.apiMode; }

function bindDomEvents() {
  if (typeof document === "undefined") return;
  document.addEventListener("click", (event) => {
    const serviceButton = event.target.closest("[data-service]");
    if (serviceButton) { state.workflow = clone(EXAMPLE_WORKFLOWS[serviceButton.dataset.service]); state.selectedStage = ""; render(); return; }
    const placementRow = event.target.closest("[data-stage]");
    if (placementRow && !event.target.closest("select")) { selectStageForPlacement(state, placementRow.dataset.stage); renderPlacement(); return; }
    const nodeTarget = event.target.closest("[data-node]");
    if (nodeTarget && state.selectedStage) { state.workflow = assignSelectedStageToNode(state.workflow, state, nodeTarget.dataset.node); render(); return; }
    const formatButton = event.target.closest("[data-format]");
    if (formatButton) { state.planFormat = formatButton.dataset.format; document.querySelectorAll("[data-format]").forEach((btn) => btn.classList.toggle("selected", btn.dataset.format === state.planFormat)); renderPlan(); }
  });
  document.addEventListener("change", (event) => { const select = event.target.closest("[data-placement-stage]"); if (!select) return; state.workflow = applyStagePlacement(state.workflow, select.dataset.placementStage, select.value); render(); });
  document.addEventListener("dragstart", (event) => { const row = event.target.closest("[data-stage]"); if (!row || event.target.closest("select")) return; selectStageForPlacement(state, row.dataset.stage); row.classList.add("selected"); document.querySelectorAll("[data-node]").forEach((item) => item.classList.add("click-target")); if (event.dataTransfer) { event.dataTransfer.setData("text/plain", row.dataset.stage); event.dataTransfer.effectAllowed = "move"; } });
  document.addEventListener("dragend", () => { document.querySelectorAll(".drop-target").forEach((item) => item.classList.remove("drop-target")); });
  document.addEventListener("dragover", (event) => { const target = event.target.closest("[data-node]"); if (!target) return; event.preventDefault(); target.classList.add("drop-target"); });
  document.addEventListener("dragleave", (event) => { const target = event.target.closest("[data-node]"); if (target && !target.contains(event.relatedTarget)) target.classList.remove("drop-target"); });
  document.addEventListener("drop", (event) => { const target = event.target.closest("[data-node]"); if (!target) return; event.preventDefault(); const stage = event.dataTransfer ? event.dataTransfer.getData("text/plain") : state.selectedStage; state.workflow = applyStagePlacement(state.workflow, stage || state.selectedStage, target.dataset.node); state.selectedStage = ""; document.querySelectorAll(".drop-target").forEach((item) => item.classList.remove("drop-target")); render(); });
}

async function fetchJson(url) { const response = await fetch(url, { cache: "no-store" }); if (!response.ok) throw new Error(`${url} ${response.status}`); return response.json(); }
async function tryLoadStateAggregator() {
  if (typeof window === "undefined" || typeof fetch === "undefined") return;
  const bases = []; if (window.location.protocol.startsWith("http")) bases.push(window.location.origin); bases.push("http://localhost:8000", "http://aggregator.192.168.0.56.sslip.io");
  for (const base of [...new Set(bases)]) {
    try { const dashboard = await fetchJson(`${base}/state/dashboard`); state.nodes = normalizeLiveNodes(dashboard); state.devices = normalizeLiveDevices(dashboard); state.apiMode = `read-only API connected: ${base}/state/dashboard`; render(); return; } catch (error) { /* fallback */ }
  }
  state.apiMode = "example mode: state-aggregator API fetch failed or blocked by browser/CORS"; renderApiMode();
}
function init() { bindDomEvents(); render(); tryLoadStateAggregator(); }
if (typeof document !== "undefined") document.addEventListener("DOMContentLoaded", init);
if (typeof module !== "undefined") module.exports = { COMPUTE_NODES, NODE_POOL, PLATFORM_ENDPOINTS, INPUT_DEVICES, EXAMPLE_WORKFLOWS, buildExecutionPlan, toYaml, applyStagePlacement, selectStageForPlacement, assignSelectedStageToNode, rectanglesOverlap, buildWorkflowDagModel, buildPlacementModel, buildTransportModel, validateWorkflowPlan, normalizeLiveNodes, normalizeLiveDevices };
