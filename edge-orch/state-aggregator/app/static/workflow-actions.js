function createWorkflow() {
  const input = workflowEl("workflowNameInput");
  const name = workflowText(input.value, "").trim();
  const id = workflowSlug(name);
  if (!id || workflowState.workflows.some((workflow) => workflow.id === id)) {
    workflowEl("workflowStatus").textContent = "workflow name 중복 또는 입력 오류";
    return;
  }
  workflowState.workflows.push({ id, name, nodes: [], edges: [] });
  workflowState.selectedWorkflowId = id;
  workflowState.selectedNodeId = "";
  input.value = "";
  renderWorkflow();
}

function addWorkflowNode(type) {
  const workflow = currentWorkflow();
  const template = nodeTemplate(type);
  const count = workflow.nodes.filter((node) => node.type === type).length + 1;
  const id = `${workflowSlug(type)}-${Date.now().toString(36)}`;
  workflow.nodes.push({ id, label: `${template.label} ${count}`, type, x: 56 + (workflow.nodes.length % 4) * 248, y: 104 + Math.floor(workflow.nodes.length / 4) * 196, targetId: "", config: defaultNodeConfig(type) });
  workflowState.selectedNodeId = id;
  autoBindDefaults();
  renderWorkflow();
}

function setWorkflowScale(value) {
  workflowState.canvasScale = Math.min(1.35, Math.max(0.72, Math.round(value * 10) / 10));
  renderGraph();
}

function autoLayoutWorkflow() {
  const workflow = currentWorkflow();
  const laneByType = { device_source: 0, transform: 1, condition: 2, ai_inference: 1, dashboard_event: 2 };
  const laneCounts = new Map();
  workflow.nodes.forEach((node) => {
    const lane = laneByType[node.type] ?? 1;
    const offset = laneCounts.get(lane) || 0;
    node.x = 56 + lane * 248;
    node.y = 104 + offset * 196;
    laneCounts.set(lane, offset + 1);
  });
  workflowState.linkFromNodeId = "";
  renderWorkflow();
}

function defaultNodeConfig(type) {
  if (type === "device_source") return { window: "-30m", property: "auto" };
  if (type === "condition") return { metric: "telemetry_fresh", operator: "equals", value: "true" };
  if (type === "ai_inference") return { model: "anomaly-lite", accelerator: "ai-hat" };
  if (type === "dashboard_event") return { severity: "warning" };
  return { method: "rolling-vector" };
}

function removeSelectedNode() {
  const workflow = currentWorkflow();
  const node = selectedWorkflowNode();
  if (!node) return;
  workflow.nodes = workflow.nodes.filter((item) => item.id !== node.id);
  workflow.edges = workflow.edges.filter((edge) => edge.from !== node.id && edge.to !== node.id);
  workflowState.selectedNodeId = workflow.nodes[0]?.id || "";
  workflowState.linkFromNodeId = "";
  renderWorkflow();
}

function removeSelectedLink() {
  const workflow = currentWorkflow();
  const node = selectedWorkflowNode();
  if (!node) return;
  const previousCount = workflow.edges.length;
  workflow.edges = workflow.edges.filter((edge) => edge.from !== node.id && edge.to !== node.id);
  workflowEl("workflowStatus").textContent = `${previousCount - workflow.edges.length} link removed`;
  renderWorkflow();
}

function handleNodeClick(nodeId) {
  const workflow = currentWorkflow();
  if (workflowState.linkFromNodeId && workflowState.linkFromNodeId !== nodeId) {
    if (!edgeExists(workflow, workflowState.linkFromNodeId, nodeId)) {
      const from = workflow.nodes.find((node) => node.id === workflowState.linkFromNodeId);
      const to = workflow.nodes.find((node) => node.id === nodeId);
      workflow.edges.push({ from: workflowState.linkFromNodeId, to: nodeId, label: `${nodeTemplate(from?.type).data} → ${nodeTemplate(to?.type).data}` });
    }
    workflowState.linkFromNodeId = "";
  }
  workflowState.selectedNodeId = nodeId;
  workflowState.selectedTargetId = selectedWorkflowNode()?.targetId || workflowState.selectedTargetId;
  renderWorkflow();
}

function bindSelectedTargetToNode() {
  const node = selectedWorkflowNode();
  const target = selectedWorkflowTarget();
  if (!node || !target || !nodeAcceptsTarget(node, target)) return;
  node.targetId = target.id;
  if (node.type === "device_source" && target.properties.length && node.config.property === "auto") node.config.property = target.properties[0];
  renderWorkflow();
}

function releaseSelectedTargetFromNode() {
  const node = selectedWorkflowNode();
  if (!node) return;
  node.targetId = "";
  renderWorkflow();
}

function updateSelectedNodeConfig(field, value) {
  const node = selectedWorkflowNode();
  if (!node) return;
  if (field === "label") node.label = value;
  else if (field === "targetId") node.targetId = value;
  else node.config[field] = value;
  renderWorkflow();
}

function autoBindDefaults() {
  const sourceTarget = workflowState.targets.find((target) => target.kind === "device" && target.telemetryEnabled && isSenseHatTarget(target)) || workflowState.targets.find((target) => target.kind === "device" && target.telemetryEnabled);
  const aiTarget = targetById(`resource:${AI_HAT_NODE}:ai-hat`);
  for (const workflow of workflowState.workflows) {
    for (const node of workflow.nodes) {
      if (node.type === "device_source" && !node.targetId && sourceTarget) node.targetId = sourceTarget.id;
      if (node.type === "ai_inference" && !node.targetId && aiTarget) node.targetId = aiTarget.id;
    }
  }
  workflowState.selectedTargetId = selectedWorkflowNode()?.targetId || sourceTarget?.id || workflowState.targets[0]?.id || "";
}

async function fetchJson(path) {
  const response = await fetch(path, { headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`${path} HTTP ${response.status}`);
  return response.json();
}

async function loadWorkflowDevices() {
  workflowEl("workflowStatus").textContent = "registered devices loading";
  const devicePayload = await fetchJson("/state/devices");
  const nodeResult = await fetchJson("/state/nodes").catch(() => []);
  const devices = Array.isArray(devicePayload) ? devicePayload : [];
  const nodes = Array.isArray(nodeResult) ? nodeResult : [];
  workflowState.nodes = nodes;
  workflowState.targets = devices.map(targetFromDevice).concat(resourceTargets(devices, nodes));
  autoBindDefaults();
  workflowEl("workflowStatus").textContent = `${devices.length} devices loaded`;
  renderWorkflow();
}

async function readLatestWorkflowDevice() {
  const target = targetById(selectedWorkflowNode()?.targetId || workflowState.selectedTargetId);
  if (!target || target.kind !== "device") {
    workflowEl("workflowStatus").textContent = "선택 node는 telemetry device가 아닙니다";
    return;
  }
  const node = selectedWorkflowNode();
  const windowValue = node?.config.window || "-30m";
  workflowEl("workflowStatus").textContent = "telemetry reading";
  const payload = await fetchJson(`/state/devices/${encodeURIComponent(target.name)}/telemetry?window=${encodeURIComponent(windowValue)}&limit=10`);
  workflowEl("workflowStatus").textContent = `${Array.isArray(payload) ? payload.length : 0} samples · ${target.name}`;
  renderInspector(Array.isArray(payload) ? payload : []);
}
