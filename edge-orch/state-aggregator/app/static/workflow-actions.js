function setWorkflowStatus(message, status = "ready") {
  const element = workflowEl("workflowStatus");
  if (!element) return;
  element.textContent = message;
  element.dataset.status = status;
}

function setWorkflowButtonBusy(button, busy, busyLabel = "처리 중…") {
  if (!button) return;
  if (!button.dataset.defaultLabel) button.dataset.defaultLabel = button.textContent.trim();
  button.disabled = busy;
  button.setAttribute("aria-busy", String(busy));
  button.textContent = busy ? busyLabel : button.dataset.defaultLabel;
}

function createWorkflow() {
  const input = workflowEl("workflowNameInput");
  const name = workflowText(input.value, "").trim();
  const id = workflowSlug(name);
  if (!id || workflowState.workflows.some((workflow) => workflow.id === id)) {
    setWorkflowStatus("이름이 비었거나 이미 사용 중입니다.", "error");
    input.focus();
    return;
  }
  workflowState.workflows.push({ id, name, nodes: [], edges: [] });
  workflowState.selectedWorkflowId = id;
  workflowState.selectedNodeId = "";
  input.value = "";
  renderWorkflow();
  setWorkflowStatus(`${name} 초안을 만들었습니다. 브라우저 안에서만 유지됩니다.`, "success");
}

function addWorkflowNode(type) {
  const workflow = currentWorkflow();
  const template = nodeTemplate(type);
  const count = workflow.nodes.filter((node) => node.type === type).length + 1;
  const id = `${workflowSlug(type)}-${Date.now().toString(36)}`;
  workflow.nodes.push({ id, label: `${template.label} ${count}`, type, x: 40 + (workflow.nodes.length % 3) * 196, y: 72 + Math.floor(workflow.nodes.length / 3) * 170, targetId: "", config: defaultNodeConfig(type) });
  workflowState.selectedNodeId = id;
  autoBindDefaults();
  renderWorkflow();
  setWorkflowStatus(`${template.label} 단계를 추가했습니다. 아직 실행되거나 배포되지 않습니다.`, "success");
}

function setWorkflowScale(value) {
  workflowState.canvasScale = Math.min(1.35, Math.max(0.72, Math.round(value * 10) / 10));
  renderGraph();
  setWorkflowStatus(`캔버스 배율 ${Math.round(workflowState.canvasScale * 100)}%`, "success");
}

function autoLayoutWorkflow() {
  const workflow = currentWorkflow();
  const laneByType = { device_source: 0, transform: 1, ai_inference: 2, postprocess: 0, store_observe: 1, dashboard_event: 2, condition: 1 };
  const laneCounts = new Map();
  workflow.nodes.forEach((node) => {
    const lane = laneByType[node.type] ?? 1;
    const offset = laneCounts.get(lane) || 0;
    node.x = 40 + lane * 196;
    node.y = 72 + offset * 170;
    laneCounts.set(lane, offset + 1);
  });
  workflowState.linkFromNodeId = "";
  renderWorkflow();
  setWorkflowStatus("단계를 자동 정렬했습니다. 브라우저 초안만 변경되었습니다.", "success");
}

function defaultNodeConfig(type) {
  if (type === "device_source") return { window: "-30m", property: "auto" };
  if (type === "condition") return { metric: "event_fresh", operator: "equals", value: "true" };
  if (type === "ai_inference") return { model: "anomaly-lite", accelerator: "ai-hat" };
  if (type === "postprocess") return { threshold: "0.82", output: "defect-score" };
  if (type === "store_observe") return { sink: "EdgeX downstream storage + result cache" };
  if (type === "dashboard_event") return { severity: "warning" };
  return { method: "rolling-vector" };
}

function removeSelectedNode() {
  const workflow = currentWorkflow();
  const node = selectedWorkflowNode();
  if (!node) {
    setWorkflowStatus("삭제할 단계를 먼저 선택하세요.", "warning");
    return;
  }
  const label = node.label;
  workflow.nodes = workflow.nodes.filter((item) => item.id !== node.id);
  workflow.edges = workflow.edges.filter((edge) => edge.from !== node.id && edge.to !== node.id);
  workflowState.selectedNodeId = workflow.nodes[0]?.id || "";
  workflowState.linkFromNodeId = "";
  renderWorkflow();
  setWorkflowStatus(`${label} 단계를 삭제했습니다.`, "success");
}

function removeSelectedLink() {
  const workflow = currentWorkflow();
  const node = selectedWorkflowNode();
  if (!node) {
    setWorkflowStatus("연결을 제거할 단계를 먼저 선택하세요.", "warning");
    return;
  }
  const previousCount = workflow.edges.length;
  workflow.edges = workflow.edges.filter((edge) => edge.from !== node.id && edge.to !== node.id);
  const removed = previousCount - workflow.edges.length;
  renderWorkflow();
  setWorkflowStatus(
    removed ? `${removed}개 연결을 제거했습니다.` : "선택한 단계에는 제거할 연결이 없습니다.",
    removed ? "success" : "warning",
  );
}

function handleNodeClick(nodeId) {
  const workflow = currentWorkflow();
  if (workflowState.linkFromNodeId && workflowState.linkFromNodeId !== nodeId) {
    if (!edgeExists(workflow, workflowState.linkFromNodeId, nodeId)) {
      const from = workflow.nodes.find((node) => node.id === workflowState.linkFromNodeId);
      const to = workflow.nodes.find((node) => node.id === nodeId);
      workflow.edges.push({ from: workflowState.linkFromNodeId, to: nodeId, label: `${nodeTemplate(from?.type).data} → ${nodeTemplate(to?.type).data}` });
      setWorkflowStatus(`${from?.label || "시작 단계"} → ${to?.label || "대상 단계"} 연결을 추가했습니다.`, "success");
    } else {
      setWorkflowStatus("이미 존재하는 연결입니다.", "warning");
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
  if (!node) {
    setWorkflowStatus("바인딩할 워크플로우 단계를 먼저 선택하세요.", "warning");
    return;
  }
  if (!target) {
    setWorkflowStatus("왼쪽 목록에서 디바이스 또는 리소스를 선택하세요.", "warning");
    return;
  }
  if (!nodeAcceptsTarget(node, target)) {
    setWorkflowStatus(`${node.label} 단계에는 ${target.displayName} 대상을 연결할 수 없습니다.`, "error");
    return;
  }
  node.targetId = target.id;
  if (node.type === "device_source" && target.properties.length && node.config.property === "auto") node.config.property = target.properties[0];
  renderWorkflow();
  setWorkflowStatus(`${target.displayName}을(를) ${node.label}에 연결했습니다. 브라우저 dry-run입니다.`, "success");
}

function releaseSelectedTargetFromNode() {
  const node = selectedWorkflowNode();
  if (!node) {
    setWorkflowStatus("바인딩을 해제할 단계를 먼저 선택하세요.", "warning");
    return;
  }
  if (!node.targetId) {
    setWorkflowStatus("선택한 단계에는 해제할 바인딩이 없습니다.", "warning");
    return;
  }
  node.targetId = "";
  renderWorkflow();
  setWorkflowStatus(`${node.label}의 바인딩을 해제했습니다.`, "success");
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
  const refreshButton = workflowEl("workflowRefresh");
  setWorkflowButtonBusy(refreshButton, true, "불러오는 중…");
  setWorkflowStatus("EdgeX 등록 디바이스를 불러오는 중입니다.", "waiting");
  try {
    const devicePayload = await fetchJson("/state/devices");
    const nodeResult = await fetchJson("/state/nodes").catch(() => []);
    const devices = Array.isArray(devicePayload) ? devicePayload : [];
    const nodes = Array.isArray(nodeResult) ? nodeResult : [];
    workflowState.nodes = nodes;
    workflowState.targets = devices.map(targetFromDevice).concat(resourceTargets(devices, nodes));
    autoBindDefaults();
    renderWorkflow();
    setWorkflowStatus(`EdgeX 디바이스 ${devices.length}개를 불러왔습니다.`, "success");
  } finally {
    setWorkflowButtonBusy(refreshButton, false);
  }
}

async function readLatestWorkflowDevice() {
  const target = targetById(selectedWorkflowNode()?.targetId || workflowState.selectedTargetId);
  if (!target || target.kind !== "device") {
    setWorkflowStatus("최신 데이터를 읽을 EdgeX 디바이스를 먼저 선택하거나 바인딩하세요.", "warning");
    return;
  }
  const node = selectedWorkflowNode();
  const windowValue = node?.config.window || "-30m";
  const button = workflowEl("readLatestWorkflowDevice");
  setWorkflowButtonBusy(button, true, "읽는 중…");
  setWorkflowStatus(`${target.name} 최신 데이터를 읽는 중입니다.`, "waiting");
  try {
    const payload = await fetchJson(`/state/devices/${encodeURIComponent(target.name)}/telemetry?window=${encodeURIComponent(windowValue)}&limit=10`);
    renderInspector(Array.isArray(payload) ? payload : []);
    setWorkflowStatus(`${target.name} 샘플 ${Array.isArray(payload) ? payload.length : 0}개를 읽었습니다.`, "success");
  } finally {
    setWorkflowButtonBusy(button, false);
  }
}
