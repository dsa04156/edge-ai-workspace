function roundedPolyline(points, radius = 16) {
  if (points.length < 2) return "";
  let path = `M ${points[0].x} ${points[0].y}`;
  for (let index = 1; index < points.length; index += 1) {
    const current = points[index];
    const next = points[index + 1];
    if (!next) {
      path += ` L ${current.x} ${current.y}`;
      continue;
    }
    const previous = points[index - 1];
    const inDx = current.x - previous.x;
    const inDy = current.y - previous.y;
    const outDx = next.x - current.x;
    const outDy = next.y - current.y;
    const inLength = Math.hypot(inDx, inDy);
    const outLength = Math.hypot(outDx, outDy);
    const corner = Math.min(radius, inLength / 2, outLength / 2);
    if (!corner || (inDx && outDx) || (inDy && outDy)) {
      path += ` L ${current.x} ${current.y}`;
      continue;
    }
    const before = { x: current.x - (inDx / inLength) * corner, y: current.y - (inDy / inLength) * corner };
    const after = { x: current.x + (outDx / outLength) * corner, y: current.y + (outDy / outLength) * corner };
    path += ` L ${before.x} ${before.y} Q ${current.x} ${current.y} ${after.x} ${after.y}`;
  }
  return path;
}

function edgeLabelPoint(points) {
  if (points.length < 2) return { x: 0, y: 0 };
  const segments = [];
  let total = 0;
  for (let index = 1; index < points.length; index += 1) {
    const from = points[index - 1];
    const to = points[index];
    const length = Math.hypot(to.x - from.x, to.y - from.y);
    segments.push({ from, to, length });
    total += length;
  }
  let cursor = total / 2;
  for (const segment of segments) {
    if (cursor > segment.length) {
      cursor -= segment.length;
      continue;
    }
    const ratio = segment.length ? cursor / segment.length : 0;
    return {
      x: segment.from.x + (segment.to.x - segment.from.x) * ratio,
      y: segment.from.y + (segment.to.y - segment.from.y) * ratio,
    };
  }
  return segments.at(-1).to;
}

function routeWorkflowEdge(from, to, vertical) {
  if (vertical) {
    const start = { x: from.x + from.w / 2, y: from.y + from.h };
    const end = { x: to.x + to.w / 2, y: to.y };
    if (start.x === end.x) return { points: [start, end], className: "route-vertical" };
    const midY = start.y + Math.max(42, (end.y - start.y) / 2);
    const points = [start, { x: start.x, y: midY }, { x: end.x, y: midY }, end];
    return { points, className: "route-vertical" };
  }
  const fromCenter = { x: from.x + from.w / 2, y: from.y + from.h / 2 };
  const toCenter = { x: to.x + to.w / 2, y: to.y + to.h / 2 };
  const rowGap = Math.abs(toCenter.y - fromCenter.y);
  const targetRight = to.x >= from.x + from.w + 24;
  if (targetRight && rowGap < Math.max(from.h, to.h) * 0.85) {
    const start = { x: from.x + from.w, y: fromCenter.y };
    const end = { x: to.x, y: toCenter.y };
    if (start.y === end.y) return { points: [start, end], className: "route-forward" };
    const midX = start.x + Math.max(38, (end.x - start.x) / 2);
    return { points: [start, { x: midX, y: start.y }, { x: midX, y: end.y }, end], className: "route-forward" };
  }
  if (toCenter.y >= fromCenter.y) {
    const start = { x: fromCenter.x, y: from.y + from.h };
    const end = { x: toCenter.x, y: to.y };
    const midY = start.y + Math.max(36, (end.y - start.y) / 2);
    return { points: [start, { x: start.x, y: midY }, { x: end.x, y: midY }, end], className: "route-down" };
  }
  const start = { x: fromCenter.x, y: from.y };
  const end = { x: toCenter.x, y: to.y + to.h };
  const midY = end.y + Math.max(36, (start.y - end.y) / 2);
  return { points: [start, { x: start.x, y: midY }, { x: end.x, y: midY }, end], className: "route-up" };
}

function measureWorkflowNode(nodeRoot, canvas, scale, node) {
  const element = [...nodeRoot.querySelectorAll("[data-node-id]")].find((item) => item.dataset.nodeId === node.id);
  if (!element) return { ...node, w: NODE_W, h: NODE_H };
  const canvasRect = canvas.getBoundingClientRect();
  const rect = element.getBoundingClientRect();
  return {
    ...node,
    x: (rect.left - canvasRect.left + canvas.scrollLeft) / scale,
    y: (rect.top - canvasRect.top + canvas.scrollTop) / scale,
    w: rect.width / scale,
    h: rect.height / scale,
  };
}

function renderGraph() {
  const workflow = currentWorkflow();
  const edgeRoot = workflowEl("workflowGraphEdges");
  const nodeRoot = workflowEl("workflowGraphNodes");
  const canvas = workflowEl("workflowGraphCanvas");
  const compact = canvas && canvas.clientWidth < 980;
  const vertical = canvas && canvas.clientWidth < 430;
  const stacked = window.innerWidth <= 600;
  const scale = compact ? Math.min(workflowState.canvasScale, 0.96) : workflowState.canvasScale;
  workflowState.renderedCanvasScale = scale;
  canvas.classList.toggle("workflow-vertical", Boolean(vertical));
  const compactColumns = vertical
    ? 1
    : Math.max(2, Math.min(3, Math.floor((canvas.clientWidth - 64) / 200)));
  const visualNodes = workflow.nodes.map((node, index) => {
    if (!compact) return node;
    if (vertical) return { ...node, x: 40, y: 56 + index * 190 };
    return {
      ...node,
      x: 32 + (index % compactColumns) * 196,
      y: 52 + Math.floor(index / compactColumns) * 170,
    };
  });
  const compactWidth = compactColumns === 2 ? 470 : 660;
  const maxX = Math.max(vertical ? 260 : compact ? compactWidth : 720, ...visualNodes.map((node) => node.x + NODE_W + 72));
  const visualMaxY = stacked ? 0 : Math.max(...visualNodes.map((node) => node.y + NODE_H + 96));
  const maxY = Math.max(stacked ? 460 : vertical ? 1320 : compact ? 460 : 460, visualMaxY);
  canvas.style.setProperty("--workflow-scale", String(scale));
  edgeRoot.setAttribute("viewBox", `0 0 ${maxX} ${maxY}`);
  edgeRoot.style.width = `${maxX * scale}px`;
  edgeRoot.style.height = `${maxY * scale}px`;
  nodeRoot.style.width = `${maxX * scale}px`;
  nodeRoot.style.height = `${maxY * scale}px`;
  nodeRoot.innerHTML = visualNodes.map((node) => {
    const selected = workflowState.selectedNodeId === node.id ? "selected" : "";
    const linkSource = workflowState.linkFromNodeId === node.id ? "link-source" : "";
    const target = targetById(node.targetId);
    const template = nodeTemplate(node.type);
    const bound = target ? "bound" : "unbound";
    return `<button class="workflow-node ${selected} ${linkSource} ${bound} type-${workflowEscape(node.type)}" type="button" data-node-id="${workflowEscape(node.id)}" style="left:${node.x * scale}px;top:${node.y * scale}px;transform:scale(${scale})"><i class="workflow-port workflow-port-in"></i><i class="workflow-port workflow-port-out"></i><span>${workflowEscape(template.label)}</span><strong>${workflowEscape(node.label)}</strong><small>${workflowEscape(target?.displayName || template.caption)}</small><em>in ${incomingEdges(workflow, node.id).length} · out ${outgoingEdges(workflow, node.id).length}</em></button>`;
  }).join("");
  const measuredNodes = visualNodes.map((node) => measureWorkflowNode(nodeRoot, canvas, scale, node));
  const nodeMap = new Map(measuredNodes.map((node) => [node.id, node]));
  const measuredMaxX = Math.max(maxX, ...measuredNodes.map((node) => node.x + node.w + 88));
  const measuredMaxY = Math.max(maxY, ...measuredNodes.map((node) => node.y + node.h + 110));
  edgeRoot.setAttribute("viewBox", `0 0 ${measuredMaxX} ${measuredMaxY}`);
  edgeRoot.style.width = `${measuredMaxX * scale}px`;
  edgeRoot.style.height = `${measuredMaxY * scale}px`;
  nodeRoot.style.width = `${measuredMaxX * scale}px`;
  nodeRoot.style.height = `${measuredMaxY * scale}px`;
  edgeRoot.innerHTML = `<defs><marker id="workflow-arrow" markerWidth="10" markerHeight="10" refX="9" refY="5" orient="auto"><path d="M 0 0 L 10 5 L 0 10 z"></path></marker></defs>${workflow.edges.map((edge) => {
    const from = nodeMap.get(edge.from);
    const to = nodeMap.get(edge.to);
    if (!from || !to) return "";
    const route = routeWorkflowEdge(from, to, vertical);
    const path = roundedPolyline(route.points);
    const label = edgeLabelPoint(route.points);
    const start = route.points[0];
    const end = route.points.at(-1);
    return `<path class="workflow-edge-path ${route.className}" d="${path}" marker-end="url(#workflow-arrow)"></path><circle class="workflow-edge-dot" cx="${start.x}" cy="${start.y}" r="4"></circle><circle class="workflow-edge-dot endpoint" cx="${end.x}" cy="${end.y}" r="4"></circle><text class="workflow-edge-label" x="${label.x}" y="${label.y - 8}">${workflowEscape(edge.label || "data")}</text>`;
  }).join("")}`;
  const zoomReset = workflowEl("workflowZoomReset");
  if (zoomReset) zoomReset.textContent = `${Math.round(scale * 100)}%`;
}

function renderTargetPool() {
  const node = selectedWorkflowNode();
  const targets = sortedWorkflowTargets();
  const pool = workflowEl("deviceSourcePool");
  if (!targets.length) {
    pool.innerHTML = '<div class="workflow-empty">No Device/source matches the selected filter.</div>';
    return;
  }
  pool.innerHTML = targets.map((target) => {
    const selected = workflowState.selectedTargetId === target.id ? "selected" : "";
    const recommended = nodeAcceptsTarget(node, target) ? "recommended" : "";
    const status = target.kind === "resource" ? target.overallStatus : target.telemetryStatus;
    const detail = target.kind === "resource" ? "AI HAT resource" : `${target.protocol} · ${target.properties.slice(0, 3).join(", ") || "no properties"}`;
    return `<button class="device-card ${selected} ${recommended} status-${workflowEscape(status)}" type="button" data-target-id="${workflowEscape(target.id)}"><span>${workflowEscape(status)}</span><strong>${workflowEscape(target.displayName)}</strong><small>${workflowEscape(target.nodeName || "unassigned")} · ${workflowEscape(target.type)}</small><em>${workflowEscape(detail)}</em></button>`;
  }).join("");
}

function renderInspector(latestPayload = null) {
  const node = selectedWorkflowNode();
  const target = node ? targetById(node.targetId) : null;
  if (!node) {
    workflowEl("workflowBindingInspector").innerHTML = '<div class="workflow-empty"><span class="workflow-message-text">Select a node on the canvas.</span></div>';
    return;
  }
  workflowEl("workflowBindingInspector").innerHTML = `${renderNodeConfig(node)}${renderTargetInspector(node, target, latestPayload)}`;
}

function renderNodeConfig(node) {
  const targetOptions = workflowState.targets.filter((target) => nodeAcceptsTarget(node, target)).map((target) => `<option value="${workflowEscape(target.id)}" ${target.id === node.targetId ? "selected" : ""}>${workflowEscape(target.displayName)}</option>`).join("");
  const propertyOptions = (targetById(node.targetId)?.properties || []).map((property) => `<option value="${workflowEscape(property)}" ${node.config.property === property ? "selected" : ""}>${workflowEscape(property)}</option>`).join("");
  return `<div class="inspector-title"><span>Node Settings</span><strong>${workflowEscape(node.label)}</strong></div><dl class="workflow-fields"><div><dt>type</dt><dd>${workflowEscape(nodeTemplate(node.type).label)}</dd></div><div><dt>label</dt><dd><input class="workflow-config-input" data-config-field="label" value="${workflowEscape(node.label)}" /></dd></div>${targetOptions ? `<div><dt>target</dt><dd><select class="workflow-config-input" data-config-field="targetId"><option value="">none</option>${targetOptions}</select></dd></div>` : ""}${node.type === "device_source" ? `<div><dt>window</dt><dd><input class="workflow-config-input" data-config-field="window" value="${workflowEscape(node.config.window || "-30m")}" /></dd></div><div><dt>property</dt><dd><select class="workflow-config-input" data-config-field="property"><option value="auto">auto</option>${propertyOptions}</select></dd></div>` : ""}${node.type === "condition" ? `<div><dt>rule</dt><dd><input class="workflow-config-input" data-config-field="value" value="${workflowEscape(node.config.value || "true")}" /></dd></div>` : ""}${node.type === "ai_inference" ? `<div><dt>model</dt><dd><input class="workflow-config-input" data-config-field="model" value="${workflowEscape(node.config.model || "anomaly-lite")}" /></dd></div>` : ""}${node.type === "postprocess" ? `<div><dt>threshold</dt><dd><input class="workflow-config-input" data-config-field="threshold" value="${workflowEscape(node.config.threshold || "0.82")}" /></dd></div>` : ""}${node.type === "store_observe" ? `<div><dt>sink</dt><dd><input class="workflow-config-input" data-config-field="sink" value="${workflowEscape(node.config.sink || "InfluxDB + result cache")}" /></dd></div>` : ""}</dl>`;
}

function renderTargetInspector(node, target, latestPayload) {
  if (!target) return '<div class="workflow-source-list"><span>Binding</span><p class="workflow-message-text">Select a Device or resource for this node.</p></div>';
  const latestRows = Array.isArray(latestPayload) ? latestPayload.slice(0, 6).map((item) => `<li>${workflowEscape(item.property)} = ${workflowEscape(item.value)} · ${workflowEscape(item.timestamp)}</li>`).join("") : "";
  return `<div class="workflow-source-list"><span>Binding Target</span><dl class="workflow-fields compact"><div><dt>target</dt><dd>${workflowEscape(target.displayName)}</dd></div><div><dt>node</dt><dd>${workflowEscape(target.nodeName || "unassigned")}</dd></div><div><dt>telemetry</dt><dd>${workflowEscape(target.telemetryStatus)} · ${workflowEscape(target.telemetryLastSeenAt || "no sample")}</dd></div><div><dt>status</dt><dd>${workflowEscape(target.overallStatus)} · ${workflowEscape(target.reason)}</dd></div></dl><ul>${target.properties.length ? target.properties.slice(0, 8).map((item) => `<li>${workflowEscape(item)}</li>`).join("") : "<li>not a telemetry source</li>"}</ul></div>${latestRows ? `<div class="workflow-source-list"><span>Latest Telemetry</span><ul>${latestRows}</ul></div>` : ""}`;
}

function renderValidation() {
  const validation = buildValidation();
  const badge = workflowEl("workflowValidationBadge");
  badge.textContent = validation.status;
  badge.className = `validation-${validation.status.toLowerCase()}`;
  workflowEl("workflowValidationList").innerHTML = validation.results.map((item) => `<li class="validation-item ${item.level.toLowerCase()}"><strong>${workflowEscape(item.level)}</strong><span>${workflowEscape(item.rule)}</span><em>${workflowEscape(item.message)}</em></li>`).join("");
}

function renderWorkflow() {
  renderWorkflowSelector();
  renderWorkflowSummary();
  renderNodePalette();
  renderGraph();
  renderTargetPool();
  renderInspector();
  renderValidation();
  workflowEl("workflowExecutionPlan").textContent = JSON.stringify(buildExecutionPlan(), null, 2);
}
