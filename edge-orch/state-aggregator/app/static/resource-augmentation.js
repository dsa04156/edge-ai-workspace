const augmentationState = {
  resources: [],
  selectedId: "vd-x86-gpu-inference",
  candidateResources: [],
  decision: null,
  workflowDemo: null,
  runtimeSummary: { candidate_resource_total: 0, available: 0, bound: 0, blocked: 0 },
  selectedCandidateResourceId: "",
  aiService: "",
  workflowPlaybackIndex: 0,
  workflowPlaybackTimer: null,
  workflowPlaybackSignature: "",
};
const DEVICE_AUGMENTATION_ID = "jetson-gpu-storage-augmentation";

function augEl(id) {
  return document.getElementById(id);
}

function augText(value, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function augEscape(value) {
  return augText(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function augStatusLabel(value) {
  return {
    configured_not_running: "not running",
    partially_available: "partially available",
    unavailable: "unavailable",
    allocated: "allocated",
    degraded: "degraded",
    idle: "idle",
  }[value] || augText(value, "unknown");
}

function augReasonLabel(value) {
  const reason = augText(value, "-");
  if (reason === "registry exists but no runtime instance is observed") return "registry exists · 0 runtime instances observed";
  return reason;
}

function augRecommendationLabel(value) {
  return {
    none: "normal",
    candidate: "candidate",
    selected: "selected",
    blocked: "blocked",
  }[value] || augText(value, "unknown");
}

function normalizeAugmentationResource(resource) {
  const twin = resource.twin || {};
  return {
    id: resource.id,
    name: resource.display_name,
    node: resource.node,
    type: resource.resource_type,
    desired: Number(resource.desired_instances) || 0,
    observed: Number(resource.observed_instances) || 0,
    free: Number(resource.free_instances) || 0,
    allocated: Number(resource.allocated_instances) || 0,
    status: resource.status || "unknown",
    stage: (resource.supported_stage_types || []).join(", ") || "-",
    capabilities: resource.capabilities || [],
    instances: resource.instances || [],
    nodeReady: Boolean(twin.node_ready),
    podReady: Boolean(twin.pod_ready),
    endpointReady: Boolean(twin.endpoint_ready),
    bindingState: twin.binding_state || "unknown",
    statusReason: augReasonLabel(twin.status_reason),
  };
}

function normalizeCandidateResource(item) {
  return {
    id: item.name,
    kind: item.kind || "-",
    phase: item.phase || "Unknown",
    capability: item.capability || "-",
    node: item.node || "-",
  };
}

function selectedAugmentationResource() {
  return augmentationState.resources.find((resource) => resource.id === augmentationState.selectedId) || augmentationState.resources[0];
}

function selectedCandidateResource() {
  return augmentationState.candidateResources.find((item) => item.id === augmentationState.selectedCandidateResourceId)
    || augmentationState.candidateResources[0];
}

function resourceMatches(resource, text) {
  const haystack = `${resource?.id || ""} ${resource?.name || ""} ${resource?.type || ""} ${(resource?.capabilities || []).join(" ")}`.toLowerCase();
  return haystack.includes(text);
}

function augmentationWorkflowBindings(selected) {
  const resources = augmentationState.resources;
  const inference = selected && !resourceMatches(selected, "storage")
    ? selected
    : resources.find((resource) => resourceMatches(resource, "inference") || resourceMatches(resource, "gpu") || resourceMatches(resource, "ai"));
  const storage = selected && resourceMatches(selected, "storage")
    ? selected
    : resources.find((resource) => resourceMatches(resource, "storage") || resourceMatches(resource, "cache"));
  return { inference, storage };
}

function alignSelectedAugmentationResource() {
  if (augmentationState.resources.some((resource) => resource.id === augmentationState.selectedId)) return;
  augmentationState.selectedId = augmentationState.resources[0]?.id || "";
}

function renderAugmentationKpis(resources) {
  const observed = resources.reduce((sum, item) => sum + item.observed, 0);
  const allocated = resources.reduce((sum, item) => sum + item.allocated, 0);
  const available = resources.filter((item) => item.free > 0 || item.status === "idle").length;
  const notRunning = resources.filter((item) => item.status === "configured_not_running").length;
  const risk = resources.filter((item) => ["degraded", "unavailable"].includes(item.status)).length;
  augEl("augmentationProfileCount").textContent = resources.length;
  augEl("augmentationObservedCount").textContent = observed;
  augEl("augmentationAvailableCount").textContent = available;
  augEl("augmentationAllocatedCount").textContent = allocated;
  augEl("augmentationNotRunningCount").textContent = notRunning;
  augEl("augmentationRiskCount").textContent = risk;
  augEl("augmentationRecommendationTotal").textContent = augmentationState.runtimeSummary.candidate_resource_total || 0;
  augEl("augmentationRecommendationSelected").textContent = augmentationState.decision?.selectedResources?.length || 0;
  augEl("augmentationRecommendationBlocked").textContent = augRecommendationLabel(augmentationState.decision?.state);
  augEl("augmentationRuntimeScope").textContent = augmentationState.loadError || `${observed} observed runtime instances`;
}

function renderAugmentationRows(resources) {
  augEl("augmentationResourceRows").innerHTML = resources.map((resource) => `
    <tr class="${resource.id === augmentationState.selectedId ? "selected" : ""}" data-augmentation-id="${augEscape(resource.id)}">
      <td><strong>${augEscape(resource.name)}</strong><span>${augEscape(resource.stage)}</span></td>
      <td>${augEscape(resource.node)}</td>
      <td>${augEscape(resource.type)}</td>
      <td>${resource.desired}</td>
      <td>${resource.observed}</td>
      <td>${resource.free}</td>
      <td>${resource.allocated}</td>
      <td><span class="augmentation-status ${augEscape(resource.status)}">${augEscape(augStatusLabel(resource.status))}</span></td>
    </tr>
  `).join("");
}

function renderAugmentationInspector(resource) {
  augEl("augmentationInspectorTitle").textContent = resource?.name || "Selected Resource";
  augEl("augmentationInspectorStatus").textContent = resource ? augStatusLabel(resource.status) : "unknown";
  if (!resource) {
    augEl("augmentationInspectorBody").innerHTML = '<div class="workflow-empty">Virtual resource API response pending.</div>';
    return;
  }
  augEl("augmentationInspectorBody").innerHTML = `
    <dl class="augmentation-fields">
      <div><dt>profile</dt><dd>${augEscape(resource.id)}</dd></div>
      <div><dt>desired / observed</dt><dd>${resource.desired} / ${resource.observed}</dd></div>
      <div><dt>free / allocated</dt><dd>${resource.free} / ${resource.allocated}</dd></div>
      <div><dt>node ready</dt><dd>${resource.nodeReady ? "true" : "false"}</dd></div>
      <div><dt>pod ready</dt><dd>${resource.podReady ? "true" : "false"}</dd></div>
      <div><dt>endpoint ready</dt><dd>${resource.endpointReady ? "true" : "false"}</dd></div>
      <div><dt>binding state</dt><dd>${augEscape(resource.bindingState)}</dd></div>
      <div><dt>reason</dt><dd>${augEscape(resource.statusReason)}</dd></div>
    </dl>
    <ul class="augmentation-instance-list">
      ${resource.instances.length ? resource.instances.map((instance) => `<li><strong>${augEscape(instance.id)}</strong><span>${augEscape(instance.node)} · ${augEscape(instance.pod)} · ${augEscape(instance.binding_state || "free")}</span></li>`).join("") : "<li><strong>0 runtime</strong><span>registry exists, but no runtime instance is observed.</span></li>"}
    </ul>
  `;
}

function renderAugmentationFlow(resources, selected) {
  const bindings = augmentationWorkflowBindings(selected);
  augEl("augmentationBoundResource").textContent = bindings.inference ? bindings.inference.name : "inference resource pending";
  augEl("augmentationStorageResource").textContent = bindings.storage ? bindings.storage.name : "storage resource pending";
  augEl("augmentationInstanceLane").innerHTML = resources.map((resource) => `
    <button class="augmentation-instance-chip ${resource.status} ${resource.id === augmentationState.selectedId ? "selected" : ""}" type="button" data-augmentation-id="${augEscape(resource.id)}">
      <span>${augEscape(resource.name)}</span>
      <strong>${resource.observed} running · ${augEscape(augStatusLabel(resource.status))}</strong>
    </button>
  `).join("");
}

function renderAugmentationPlan(resource) {
  const bindings = augmentationWorkflowBindings(resource);
  const checks = [
    ["target edge device mapped", true],
    ["inference resource selected", Boolean(bindings.inference)],
    ["inference endpoint ready", bindings.inference?.endpointReady],
    ["storage resource selected", Boolean(bindings.storage)],
    ["storage endpoint ready", bindings.storage?.endpointReady],
    ["binding conflict", !bindings.inference?.allocated || bindings.inference.free > 0],
  ];
  augEl("augmentationValidationList").innerHTML = checks.map(([label, pass]) => `<li class="${pass ? "pass" : "warn"}"><strong>${pass ? "PASS" : "WAIT"}</strong><span>${augEscape(label)}</span></li>`).join("");
  augEl("augmentationPlanPreview").textContent = JSON.stringify({
    mode: "dry-run",
    device_augmentation: DEVICE_AUGMENTATION_ID,
    target_edge_device: {
      kind: "EdgeNode",
      name: "etri-dev0001-jetorn",
      baseline_capability: "local preprocess + limited gpu-lite inference",
    },
    resource_gap: {
      gpu_inference: "external resource required for heavier model",
      result_cache: "external storage cache required for result windows",
    },
    kubernetes_apply: false,
    bindings: {
      inference_virtual_device: bindings.inference?.id || null,
      storage_virtual_device: bindings.storage?.id || null,
    },
    stages: [
      "edge_device_workload_request",
      "resource_gap_detection",
      "augmentation_resource_binding",
      "remote_inference_execution",
      "result_cache_binding",
      "augmented_device_status",
    ],
    status: bindings.inference?.status || "resource_pending",
    next_action: bindings.inference?.observed ? "bind preview only" : "runtime deployment required before binding",
  }, null, 2);
}

function alignSelectedCandidateResource() {
  if (augmentationState.candidateResources.some((item) => item.id === augmentationState.selectedCandidateResourceId)) return;
  augmentationState.selectedCandidateResourceId = augmentationState.candidateResources[0]?.id || "";
}

function renderAugmentationDecision() {
  const candidateResources = augmentationState.candidateResources;
  const selected = selectedCandidateResource();
  const decision = augmentationState.decision;
  const summary = augmentationState.runtimeSummary;
  augEl("augmentationRecommendationService").textContent = augmentationState.aiService || decision?.aiService || "-";
  augEl("augmentationRecommendationScope").textContent = `${summary.candidate_resource_total || 0} candidate resources · ${summary.available || 0} available · trigger=${augEscape(decision?.trigger || "none")}`;
  augEl("augmentationCandidateResourceRows").innerHTML = candidateResources.map((item) => `
    <button class="augmentation-recommendation-row ${augEscape(item.phase.toLowerCase())} ${item.id === augmentationState.selectedCandidateResourceId ? "selected" : ""}" type="button" data-candidate-resource-id="${augEscape(item.id)}">
      <span><strong>${augEscape(item.id)}</strong><em>${augEscape(item.capability)}</em></span>
      <b>${augEscape(item.kind)}</b>
      <small>${augEscape(item.phase)}</small>
    </button>
  `).join("") || '<div class="workflow-empty">Candidate resource API response pending.</div>';
  if (!decision) {
    augEl("augmentationDecisionDetail").innerHTML = "<h4>Scheduler Decision</h4><div>Augmented Device Plan is pending.</div>";
    return;
  }
  const augmentedDevice = decision.resultingAugmentedDevice || {};
  augEl("augmentationDecisionDetail").innerHTML = `
    <h4>Scheduler Decision</h4>
    <dl class="augmentation-fields">
      <div><dt>candidate</dt><dd>${augEscape(selected?.id || "-")}</dd></div>
      <div><dt>AI Workload</dt><dd>${augEscape(decision.aiService)}</dd></div>
      <div><dt>target</dt><dd>${augEscape(decision.targetDevice)}</dd></div>
      <div><dt>state</dt><dd>${augEscape(augRecommendationLabel(decision.state))} · ${decision.pressureScore}%</dd></div>
      <div><dt>apply</dt><dd>${augEscape(decision.applyState)}</dd></div>
      <div><dt>reason</dt><dd>${augEscape(decision.pressureReason.join(", ") || "no request")}</dd></div>
      <div><dt>selected candidates</dt><dd>${augEscape(decision.candidateResourceNames.join(", ") || "-")}</dd></div>
      <div><dt>Augmented Device Plan</dt><dd>${augEscape(augmentedDevice.name || "-")} · ${augEscape(augmentedDevice.phase || "-")}</dd></div>
      <div><dt>explain</dt><dd>${augEscape(decision.explanation)}</dd></div>
    </dl>
    <ul class="augmentation-instance-list">
      ${decision.selectedResources.length ? decision.selectedResources.map((resource) => `<li><strong>${augEscape(resource.role)} · ${augEscape(resource.name)}</strong><span>${augEscape(resource.reason || "-")}</span></li>`).join("") : "<li><strong>no resource selected</strong><span>No augmentation resource is selected.</span></li>"}
    </ul>
  `;
}

function normalizeWorkflowDemo(workflowDemo) {
  if (!workflowDemo || typeof workflowDemo !== "object") return null;
  const offloadPath = workflowDemo.offload_path || {};
  const progressPercent = Math.max(0, Math.min(100, Number(workflowDemo.progress_percent) || 0));
  return {
    name: workflowDemo.name || "-",
    status: workflowDemo.status || "unknown",
    automationTrigger: workflowDemo.automation_trigger || "runtime_metrics_observed",
    progressPercent,
    currentStepId: workflowDemo.current_step_id || "",
    operatorSummary: workflowDemo.operator_summary || "",
    autoPlay: workflowDemo.auto_play !== false,
    playbackIntervalMs: Math.max(500, Number(workflowDemo.playback_interval_ms) || 1600),
    scenarioTimeline: Array.isArray(workflowDemo.scenario_timeline)
      ? workflowDemo.scenario_timeline.map((phase) => ({
        id: phase.id || "",
        label: phase.label || phase.id || "",
        activeStepId: phase.active_step_id || "",
        progressPercent: Math.max(0, Math.min(100, Number(phase.progress_percent) || 0)),
        summary: phase.summary || "",
      }))
      : [],
    steps: Array.isArray(workflowDemo.steps) ? workflowDemo.steps : [],
    offloadPath: {
      source: offloadPath.source || "-",
      inference: offloadPath.inference || "-",
      cache: offloadPath.cache || "-",
      result: offloadPath.result || "-",
    },
  };
}

function workflowStepLabel(state) {
  return {
    completed: "done",
    active: "running",
    planned: "planned",
  }[state] || augText(state, "unknown");
}

function workflowAutomationLabel(value) {
  return {
    runtime_metrics_observed: "runtime metrics observed",
  }[value] || augText(value, "automatic decision");
}

function workflowRuntimeStatusLabel(state) {
  return {
    completed: "completed",
    current: "running",
    planned: "waiting",
  }[state] || augText(state, "waiting");
}

function workflowNodeStates(model, activeStepId) {
  const activeNodes = model.nodes.filter((node) => node.stepId === activeStepId);
  const activeOrderMin = activeNodes.length ? Math.min(...activeNodes.map((node) => node.order)) : -1;
  return Object.fromEntries(model.nodes.map((node) => {
    const state = node.stepId === activeStepId ? "current" : node.order < activeOrderMin ? "completed" : "planned";
    return [node.id, state];
  }));
}

function augmentationNodePayload(model, activeStepId, frame) {
  const states = workflowNodeStates(model, activeStepId);
  const activeNode = model.nodes.find((node) => node.stepId === activeStepId) || model.nodes[0];
  return {
    states,
    activeNode,
    phase: frame?.label || activeNode?.title || "workflow playback",
    summary: frame?.summary || activeNode?.meta || "runtime observation pending",
  };
}

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

function augmentationNodeCanvasModel(workflow) {
  const decision = augmentationState.decision || {};
  const selectedResources = decision.selectedResources || [];
  const inference = selectedResources.find((resource) => resource.role === "inference")?.name || "inference pending";
  const storage = selectedResources.find((resource) => resource.role === "storage")?.name || "cache pending";
  const result = decision.resultingAugmentedDevice?.name || "augmented device pending";
  const candidateCount = augmentationState.runtimeSummary.candidate_resource_total || augmentationState.candidateResources.length || 0;
  const pressure = decision.pressureReason?.join(" + ") || "pressure pending";
  return {
    nodes: [
      { id: "edge-device", stepId: "service-request", kind: "device", title: "Observe Edge Device", value: decision.targetDevice || "-", meta: "physical resource target", x: 14, y: 22, order: 0 },
      { id: "pressure", stepId: "pressure-detected", kind: "pressure", title: "Detect Resource Pressure", value: `${decision.pressureScore || 0}% pressure`, meta: pressure, x: 35, y: 22, order: 1 },
      { id: "candidates", stepId: "candidate-scan", kind: "pool", title: "Evaluate Candidate Pool", value: `${candidateCount} resources`, meta: "12 available · 3 blocked", x: 56, y: 22, order: 2 },
      { id: "gpu-offload", stepId: "offload-plan", kind: "resource", title: "Select GPU Resource", value: inference, meta: "remote inference", x: 45, y: 70, order: 3 },
      { id: "cache-offload", stepId: "offload-plan", kind: "resource", title: "Select Cache Resource", value: storage, meta: "result window", x: 67, y: 70, order: 4 },
      { id: "augmented-device", stepId: "augmented-device-bind", kind: "result", title: "Plan Augmented Device Binding", value: result, meta: workflow?.status || "planned binding", x: 88, y: 46, order: 5 },
    ],
    edges: [
      ["edge-device", "pressure", "runtime metrics"],
      ["pressure", "candidates", "pressure signal"],
      ["candidates", "gpu-offload", "candidate scan"],
      ["candidates", "cache-offload", "candidate scan"],
      ["gpu-offload", "augmented-device", "select inference"],
      ["cache-offload", "augmented-device", "select cache"],
    ],
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
      const x1 = from.x * 10;
      const y1 = from.y * 3.9;
      const x2 = to.x * 10;
      const y2 = to.y * 3.9;
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
    augEl("augmentationOffloadPath").innerHTML = '<div class="workflow-empty">Planned offload path pending.</div>';
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

function renderAugmentation() {
  const resources = augmentationState.resources;
  const selected = selectedAugmentationResource();
  renderAugmentationKpis(resources);
  renderAugmentationRows(resources);
  renderAugmentationInspector(selected);
  renderAugmentationDecision();
  renderAugmentationWorkflowDemo();
  renderAugmentationFlow(resources, selected);
  renderAugmentationPlan(selected);
  window.renderAugmentationCrd?.(DEVICE_AUGMENTATION_ID);
}

function normalizeAugmentationDecision(decision) {
  if (!decision || typeof decision !== "object") return null;
  return {
    state: decision.state || "none",
    trigger: decision.trigger || "none",
    aiService: decision.ai_service || "",
    scenario: decision.scenario || "",
    targetDevice: decision.target_device || "",
    pressureScore: Number(decision.pressure_score) || 0,
    pressureReason: decision.pressure_reason || [],
    candidateResourceNames: decision.candidate_resource_names || [],
    selectedResources: decision.selected_resources || [],
    resultingAugmentedDevice: decision.resulting_augmented_device || null,
    applyState: decision.apply_state || "observed-only",
    explanation: decision.explanation || "",
  };
}

async function loadRuntimeAugmentationDecision() {
  const response = await fetch("/state/runtime-resource-augmentation", { cache: "no-store", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`runtime augmentation API unavailable: HTTP ${response.status}`);
  const payload = await response.json();
  augmentationState.runtimeSummary = payload.summary || { candidate_resource_total: 0, available: 0, bound: 0, blocked: 0 };
  augmentationState.aiService = payload.ai_service || "";
  augmentationState.candidateResources = (payload.candidate_resources || []).map(normalizeCandidateResource);
  augmentationState.decision = normalizeAugmentationDecision(payload.decision);
  augmentationState.workflowDemo = normalizeWorkflowDemo(payload.workflow_demo);
  alignSelectedCandidateResource();
}

async function loadAugmentation() {
  try {
    await window.loadAugmentationCrd?.();
    await loadRuntimeAugmentationDecision();
    const response = await fetch("/state/virtual-resources", { cache: "no-store", headers: { Accept: "application/json" } });
    if (!response.ok) {
      augmentationState.loadError = `virtual resource API unavailable: HTTP ${response.status}`;
      augmentationState.resources = [];
      alignSelectedAugmentationResource();
      renderAugmentation();
      return;
    }
    const payload = await response.json();
    augmentationState.loadError = payload.observation_error || "";
    augmentationState.resources = (payload.resources || []).map(normalizeAugmentationResource);
  } catch (error) {
    augmentationState.loadError = `virtual resource API unavailable: ${error?.name || "network error"}`;
    augmentationState.resources = [];
    augmentationState.candidateResources = [];
    augmentationState.decision = null;
    augmentationState.workflowDemo = null;
    augmentationState.runtimeSummary = { candidate_resource_total: 0, available: 0, bound: 0, blocked: 0 };
    augmentationState.aiService = "";
  }
  alignSelectedAugmentationResource();
  renderAugmentation();
}

function bindAugmentationEvents() {
  augEl("augmentationRefresh")?.addEventListener("click", () => loadAugmentation().catch(console.error));
  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    const target = event.target.closest("[data-augmentation-id]");
    const candidateTarget = event.target.closest("[data-candidate-resource-id]");
    if (!target && !candidateTarget) return;
    if (target) augmentationState.selectedId = target.dataset.augmentationId || augmentationState.selectedId;
    if (candidateTarget) {
      augmentationState.selectedCandidateResourceId = candidateTarget.dataset.candidateResourceId || augmentationState.selectedCandidateResourceId;
    }
    renderAugmentation();
  });
}

if (typeof document !== "undefined") {
  bindAugmentationEvents();
  loadAugmentation().catch(console.error);
}
