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
    configured_not_running: "미실행",
    partially_available: "부분 가능",
    unavailable: "장애",
    allocated: "할당됨",
    degraded: "주의",
    idle: "대기",
  }[value] || augText(value, "unknown");
}

function augReasonLabel(value) {
  const reason = augText(value, "-");
  if (reason === "registry exists but no runtime instance is observed") return "registry 등록됨 · 실행 인스턴스 0";
  return reason;
}

function augRecommendationLabel(value) {
  return {
    none: "정상",
    candidate: "후보",
    selected: "선택",
    blocked: "차단",
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
  augEl("augmentationInspectorTitle").textContent = resource?.name || "선택 자원";
  augEl("augmentationInspectorStatus").textContent = resource ? augStatusLabel(resource.status) : "unknown";
  if (!resource) {
    augEl("augmentationInspectorBody").innerHTML = '<div class="workflow-empty">Virtual resource API 응답 대기 중입니다.</div>';
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
      ${resource.instances.length ? resource.instances.map((instance) => `<li><strong>${augEscape(instance.id)}</strong><span>${augEscape(instance.node)} · ${augEscape(instance.pod)} · ${augEscape(instance.binding_state || "free")}</span></li>`).join("") : "<li><strong>0 runtime</strong><span>registry에는 있으나 실행 인스턴스가 관측되지 않습니다.</span></li>"}
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
  `).join("") || '<div class="workflow-empty">증강 자원 후보 API 응답 대기 중입니다.</div>';
  if (!decision) {
    augEl("augmentationDecisionDetail").innerHTML = "<h4>스케줄링 결정</h4><div>결과 가상디바이스 계획 대기 중입니다.</div>";
    return;
  }
  const augmentedDevice = decision.resultingAugmentedDevice || {};
  augEl("augmentationDecisionDetail").innerHTML = `
    <h4>스케줄링 결정</h4>
    <dl class="augmentation-fields">
      <div><dt>candidate</dt><dd>${augEscape(selected?.id || "-")}</dd></div>
      <div><dt>AI service</dt><dd>${augEscape(decision.aiService)}</dd></div>
      <div><dt>target</dt><dd>${augEscape(decision.targetDevice)}</dd></div>
      <div><dt>state</dt><dd>${augEscape(augRecommendationLabel(decision.state))} · ${decision.pressureScore}%</dd></div>
      <div><dt>apply</dt><dd>${augEscape(decision.applyState)}</dd></div>
      <div><dt>reason</dt><dd>${augEscape(decision.pressureReason.join(", ") || "no request")}</dd></div>
      <div><dt>selected candidates</dt><dd>${augEscape(decision.candidateResourceNames.join(", ") || "-")}</dd></div>
      <div><dt>결과 가상디바이스</dt><dd>${augEscape(augmentedDevice.name || "-")} · ${augEscape(augmentedDevice.phase || "-")}</dd></div>
      <div><dt>explain</dt><dd>${augEscape(decision.explanation)}</dd></div>
    </dl>
    <ul class="augmentation-instance-list">
      ${decision.selectedResources.length ? decision.selectedResources.map((resource) => `<li><strong>${augEscape(resource.role)} · ${augEscape(resource.name)}</strong><span>${augEscape(resource.reason || "-")}</span></li>`).join("") : "<li><strong>no resource selected</strong><span>현재는 보강 자원이 선택되지 않았습니다.</span></li>"}
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
    completed: "완료",
    active: "진행",
    planned: "계획",
  }[state] || augText(state, "unknown");
}

function workflowAutomationLabel(value) {
  return {
    runtime_metrics_observed: "런타임 관측 기반 자동 판단",
  }[value] || augText(value, "자동 판단");
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
    augEl("augmentationWorkflowSummary").textContent = "observed runtime 판단 대기";
    augEl("augmentationWorkflowProgress").style.width = "0%";
    augEl("augmentationWorkflowProgressText").textContent = "0%";
    augEl("augmentationWorkflowSteps").innerHTML = "";
    augEl("augmentationOffloadPath").innerHTML = '<div class="workflow-empty">오프로딩 경로 대기 중입니다.</div>';
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
