function renderAugmentationAtGlance(workflow, frame) {
  const decision = augmentationState.decision || {};
  const augmentedDevice = decision.resultingAugmentedDevice || {};
  const selectedResources = (decision.selectedResources || []).map((resource) => resource.name).filter(Boolean);
  augEl("augmentationAtGlancePhase").textContent = frame?.label || workflow?.status || "-";
  augEl("augmentationAtGlanceService").textContent = augmentationState.aiService || decision.aiService || "-";
  augEl("augmentationAtGlanceTarget").textContent = decision.targetDevice || "-";
  augEl("augmentationAtGlanceResources").textContent = selectedResources.length ? selectedResources.join(" + ") : "-";
  augEl("augmentationAtGlanceResult").textContent = augmentedDevice.name || "-";
}

const AUGMENTATION_GRAPH_NODE_HALF_WIDTH = 86;
const AUGMENTATION_GRAPH_NODE_HALF_HEIGHT = 52;

function augmentationEdgeBoundaryPoint(origin, target) {
  const dx = target.x - origin.x;
  const dy = target.y - origin.y;
  if (!dx && !dy) return origin;
  const xRatio = dx ? AUGMENTATION_GRAPH_NODE_HALF_WIDTH / Math.abs(dx) : Number.POSITIVE_INFINITY;
  const yRatio = dy ? AUGMENTATION_GRAPH_NODE_HALF_HEIGHT / Math.abs(dy) : Number.POSITIVE_INFINITY;
  const ratio = Math.min(1, xRatio, yRatio);
  return {
    x: origin.x + dx * ratio,
    y: origin.y + dy * ratio,
  };
}

function renderAugmentationNodeCanvas(workflow, frame) {
  const nodesEl = augEl("augmentationGraphNodes");
  const edgesEl = augEl("augmentationGraphEdges");
  if (!nodesEl || !edgesEl) return;
  if (!workflow) {
    nodesEl.innerHTML = "";
    edgesEl.innerHTML = "";
    return;
  }
  const activeStepId = frame?.activeStepId || workflow.currentStepId;
  const model = augmentationNodeCanvasModel(workflow);
  const nodesById = Object.fromEntries(model.nodes.map((node) => [node.id, node]));
  const payload = augmentationNodePayload(model, activeStepId, frame);
  const nodeStates = payload.states;
  edgesEl.innerHTML = `
    <defs>
      <marker id="augmentationArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
        <path d="M 0 0 L 10 5 L 0 10 z"></path>
      </marker>
    </defs>
    ${model.edges.map(([fromId, toId, label]) => {
      const from = nodesById[fromId];
      const to = nodesById[toId];
      if (!from || !to) return "";
      const fromCenter = { x: from.x * 10, y: from.y * 3.9 };
      const toCenter = { x: to.x * 10, y: to.y * 3.9 };
      const start = augmentationEdgeBoundaryPoint(fromCenter, toCenter);
      const end = augmentationEdgeBoundaryPoint(toCenter, fromCenter);
      const x1 = start.x;
      const y1 = start.y;
      const x2 = end.x;
      const y2 = end.y;
      const bend = Math.max(56, Math.abs(x2 - x1) * 0.34);
      const fromState = nodeStates[from.id] || "planned";
      const toState = nodeStates[to.id] || "planned";
      const edgeState = toState === "completed" ? "completed" : ["current", "completed"].includes(fromState) && toState !== "completed" ? "flowing" : "planned";
      const midX = (x1 + x2) / 2;
      const midY = (y1 + y2) / 2 - 8;
      return `
        <path class="${augEscape(edgeState)} ${edgeState === "flowing" ? "active" : ""}" d="M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}" marker-end="url(#augmentationArrow)"></path>
        ${edgeState === "flowing" ? `<circle class="augmentation-flow-packet" r="5"><animateMotion dur="1.8s" repeatCount="indefinite" path="M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}"></animateMotion></circle>` : ""}
        <text class="augmentation-edge-label ${edgeState === "planned" ? "" : "active"}" x="${midX}" y="${midY}">${augEscape(label || "")}</text>
      `;
    }).join("")}
  `;
  nodesEl.innerHTML = model.nodes.map((node) => {
    const state = nodeStates[node.id] || "planned";
    const badge = workflowRuntimeStatusLabel(state);
    return `
      <article class="augmentation-graph-node ${augEscape(node.kind)} ${augEscape(state)}" data-workflow-node-id="${augEscape(node.id)}" style="--x: ${node.x}%; --y: ${node.y}%">
        <b class="augmentation-node-badge">${augEscape(badge)}</b>
        <span>${augEscape(node.title)}</span>
        <strong>${augEscape(node.value)}</strong>
        <em>${augEscape(node.meta)}</em>
      </article>
    `;
  }).join("");
}

function renderAugmentationPlaybackInspector(workflow, frame) {
  const el = augEl("augmentationPlaybackInspector");
  if (!el) return;
  if (!workflow) {
    el.innerHTML = '<div class="workflow-empty">Runtime playback pending</div>';
    return;
  }
  const model = augmentationNodeCanvasModel(workflow);
  const payload = augmentationNodePayload(model, frame?.activeStepId || workflow.currentStepId, frame);
  const currentIndex = Math.max(0, workflow.scenarioTimeline.findIndex((phase) => phase.id === frame?.id));
  const elapsedSeconds = currentIndex * Math.round(workflow.playbackIntervalMs / 1000);
  el.innerHTML = `
    <div>
      <span>Now running</span>
      <strong>${augEscape(payload.activeNode?.title || "-")}</strong>
      <em>${augEscape(payload.summary)}</em>
    </div>
    <dl>
      <div><dt>phase</dt><dd>${augEscape(payload.phase)}</dd></div>
      <div><dt>elapsed</dt><dd>${elapsedSeconds}s</dd></div>
      <div><dt>mode</dt><dd>read-only playback</dd></div>
    </dl>
  `;
}

function renderAugmentationExecutionTimeline(workflow, frame) {
  const el = augEl("augmentationExecutionTimeline");
  if (!el) return;
  if (!workflow) {
    el.innerHTML = "";
    return;
  }
  const activeIndex = Math.max(0, workflow.scenarioTimeline.findIndex((phase) => phase.id === frame?.id));
  el.innerHTML = workflow.scenarioTimeline.map((phase, index) => {
    const state = index === activeIndex ? "current" : index < activeIndex ? "completed" : "planned";
    const seconds = index * Math.round(workflow.playbackIntervalMs / 1000);
    return `
      <li class="${augEscape(state)}">
        <b>00:${String(seconds).padStart(2, "0")}</b>
        <span><strong>${augEscape(phase.label || phase.id || "-")}</strong><em>${augEscape(phase.summary || "-")}</em></span>
      </li>
    `;
  }).join("");
}

function workflowPlaybackSignature(workflow) {
  return [
    workflow.name,
    workflow.playbackIntervalMs,
    workflow.scenarioTimeline.map((phase) => `${phase.id}:${phase.progressPercent}:${phase.activeStepId}`).join("|"),
  ].join("::");
}

function stopAugmentationWorkflowPlayback() {
  if (augmentationState.workflowPlaybackTimer) {
    window.clearInterval(augmentationState.workflowPlaybackTimer);
  }
  augmentationState.workflowPlaybackTimer = null;
  augmentationState.workflowPlaybackSignature = "";
  augmentationState.workflowPlaybackIndex = 0;
}

function workflowStepStateForFrame(workflow, step, activeStepId) {
  const stepIds = workflow.steps.map((item) => item.id);
  const activeIndex = stepIds.indexOf(activeStepId);
  const stepIndex = stepIds.indexOf(step.id);
  if (activeIndex < 0 || stepIndex < 0) return step.state || "planned";
  if (stepIndex < activeIndex) return "completed";
  if (stepIndex === activeIndex) return "active";
  return "planned";
}

function renderAugmentationWorkflowFrame(workflow, frame) {
  const activeStepId = frame?.activeStepId || workflow.currentStepId;
  const progressPercent = Number.isFinite(frame?.progressPercent) ? frame.progressPercent : workflow.progressPercent;
  const summary = frame?.summary || workflow.operatorSummary || workflow.status;
  const phaseLabel = frame?.label ? `${frame.label} · ` : "";
  renderAugmentationAtGlance(workflow, frame);
  renderAugmentationNodeCanvas(workflow, frame);
  renderAugmentationPlaybackInspector(workflow, frame);
  renderAugmentationExecutionTimeline(workflow, frame);
  augEl("augmentationWorkflowSummary").textContent = `${workflowAutomationLabel(workflow.automationTrigger)} · ${phaseLabel}${summary}`;
  augEl("augmentationWorkflowProgress").style.width = `${progressPercent}%`;
  augEl("augmentationWorkflowProgressText").textContent = `${progressPercent}%`;
  augEl("augmentationWorkflowSteps").innerHTML = workflow.steps.map((step) => {
    const state = workflowStepStateForFrame(workflow, step, activeStepId);
    return `
      <li class="${augEscape(state)} ${step.id === activeStepId ? "current" : ""}">
        <b>${augEscape(workflowStepLabel(state))}</b>
        <span><strong>${augEscape(step.label || step.id)}</strong><em>${augEscape(step.detail || "-")}</em></span>
      </li>
    `;
  }).join("");
}

function startAugmentationWorkflowPlayback(workflow) {
  const timeline = workflow.scenarioTimeline || [];
  const signature = workflowPlaybackSignature(workflow);
  if (augmentationState.workflowPlaybackSignature !== signature) {
    stopAugmentationWorkflowPlayback();
    augmentationState.workflowPlaybackSignature = signature;
  }
  const frame = timeline[augmentationState.workflowPlaybackIndex] || {
    activeStepId: workflow.currentStepId,
    progressPercent: workflow.progressPercent,
    summary: workflow.operatorSummary,
  };
  renderAugmentationWorkflowFrame(workflow, frame);
  if (!workflow.autoPlay || timeline.length < 2 || augmentationState.workflowPlaybackTimer) return;
  augmentationState.workflowPlaybackTimer = window.setInterval(() => {
    const activeWorkflow = augmentationState.workflowDemo;
    const activeTimeline = activeWorkflow?.scenarioTimeline || [];
    if (!activeWorkflow || activeTimeline.length < 2) return;
    augmentationState.workflowPlaybackIndex = (augmentationState.workflowPlaybackIndex + 1) % activeTimeline.length;
    renderAugmentationWorkflowFrame(activeWorkflow, activeTimeline[augmentationState.workflowPlaybackIndex]);
  }, workflow.playbackIntervalMs);
}

function renderAugmentationWorkflowDemo() {
  const workflow = augmentationState.workflowDemo;
  augEl("augmentationWorkflowStatus").textContent = workflow ? `${workflow.name} · ${workflow.status}` : "workflow pending";
  if (!workflow) {
    stopAugmentationWorkflowPlayback();
    renderAugmentationAtGlance(null, null);
    renderAugmentationNodeCanvas(null, null);
    renderAugmentationPlaybackInspector(null, null);
    renderAugmentationExecutionTimeline(null, null);
    augEl("augmentationWorkflowSummary").textContent = "observed runtime decision pending";
    augEl("augmentationWorkflowProgress").style.width = "0%";
    augEl("augmentationWorkflowProgressText").textContent = "0%";
    augEl("augmentationWorkflowSteps").innerHTML = "";
    augEl("augmentationOffloadPath").innerHTML = '<div class="workflow-empty">Decision path pending.</div>';
    return;
  }
  startAugmentationWorkflowPlayback(workflow);
  const path = workflow.offloadPath;
  augEl("augmentationOffloadPath").innerHTML = `
    <div><span>source</span><strong>${augEscape(path.source)}</strong></div>
    <i></i>
    <div><span>inference</span><strong>${augEscape(path.inference)}</strong></div>
    <i></i>
    <div><span>cache</span><strong>${augEscape(path.cache)}</strong></div>
    <i></i>
    <div><span>result</span><strong>${augEscape(path.result)}</strong></div>
  `;
}
