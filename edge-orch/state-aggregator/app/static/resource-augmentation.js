const augmentationState = {
  resources: [],
  selectedId: "vd-x86-gpu-inference",
  recommendations: [],
  recommendationSummary: { total: 0, selected: 0, candidate: 0, blocked: 0, none: 0 },
  selectedRecommendationId: "",
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

function normalizeAugmentationRecommendation(item) {
  return {
    id: item.virtual_device,
    scenario: item.scenario,
    targetDevice: item.target_device,
    workload: item.workload,
    recommendation: item.recommendation || "none",
    pressureScore: Number(item.pressure_score) || 0,
    pressureReason: item.pressure_reason || [],
    selectedResources: item.selected_resources || [],
    applyState: item.apply_state || "observed-only",
    explanation: item.explanation || "",
  };
}

function selectedAugmentationResource() {
  return augmentationState.resources.find((resource) => resource.id === augmentationState.selectedId) || augmentationState.resources[0];
}

function selectedAugmentationRecommendation() {
  return augmentationState.recommendations.find((item) => item.id === augmentationState.selectedRecommendationId)
    || augmentationState.recommendations[0];
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
  augEl("augmentationRecommendationTotal").textContent = augmentationState.recommendationSummary.total || 0;
  augEl("augmentationRecommendationSelected").textContent = augmentationState.recommendationSummary.selected || 0;
  augEl("augmentationRecommendationBlocked").textContent = augmentationState.recommendationSummary.blocked || 0;
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

function alignSelectedAugmentationRecommendation() {
  if (augmentationState.recommendations.some((item) => item.id === augmentationState.selectedRecommendationId)) return;
  augmentationState.selectedRecommendationId = augmentationState.recommendations[0]?.id || "";
}

function renderAugmentationRecommendations() {
  const recommendations = augmentationState.recommendations;
  const selected = selectedAugmentationRecommendation();
  const summary = augmentationState.recommendationSummary;
  augEl("augmentationRecommendationScope").textContent = `${summary.total || 0} demo AI services · ${summary.selected || 0} selected · ${summary.blocked || 0} blocked`;
  augEl("augmentationRecommendationRows").innerHTML = recommendations.map((item) => `
    <button class="augmentation-recommendation-row ${augEscape(item.recommendation)} ${item.id === augmentationState.selectedRecommendationId ? "selected" : ""}" type="button" data-augmentation-recommendation-id="${augEscape(item.id)}">
      <span><strong>${augEscape(item.id)}</strong><em>${augEscape(item.workload)}</em></span>
      <b>${augEscape(augRecommendationLabel(item.recommendation))}</b>
      <small>${item.pressureScore}%</small>
    </button>
  `).join("") || '<div class="workflow-empty">runtime recommendation API 응답 대기 중입니다.</div>';
  if (!selected) {
    augEl("augmentationRecommendationDetail").textContent = "runtime recommendation 대기 중입니다.";
    return;
  }
  augEl("augmentationRecommendationDetail").innerHTML = `
    <dl class="augmentation-fields">
      <div><dt>service</dt><dd>${augEscape(selected.id)}</dd></div>
      <div><dt>target</dt><dd>${augEscape(selected.targetDevice)}</dd></div>
      <div><dt>state</dt><dd>${augEscape(augRecommendationLabel(selected.recommendation))} · ${selected.pressureScore}%</dd></div>
      <div><dt>apply</dt><dd>${augEscape(selected.applyState)}</dd></div>
      <div><dt>reason</dt><dd>${augEscape(selected.pressureReason.join(", ") || "no pressure")}</dd></div>
      <div><dt>explain</dt><dd>${augEscape(selected.explanation)}</dd></div>
    </dl>
    <ul class="augmentation-instance-list">
      ${selected.selectedResources.length ? selected.selectedResources.map((resource) => `<li><strong>${augEscape(resource.role)} · ${augEscape(resource.name)}</strong><span>${augEscape(resource.reason || "-")}</span></li>`).join("") : "<li><strong>no resource selected</strong><span>현재는 보강 자원이 선택되지 않았습니다.</span></li>"}
    </ul>
  `;
}

function renderAugmentation() {
  const resources = augmentationState.resources;
  const selected = selectedAugmentationResource();
  renderAugmentationKpis(resources);
  renderAugmentationRows(resources);
  renderAugmentationInspector(selected);
  renderAugmentationRecommendations();
  renderAugmentationFlow(resources, selected);
  renderAugmentationPlan(selected);
  window.renderAugmentationCrd?.(DEVICE_AUGMENTATION_ID);
}

async function loadAugmentationRecommendations() {
  const response = await fetch("/state/runtime-resource-augmentation", { cache: "no-store", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`runtime augmentation API unavailable: HTTP ${response.status}`);
  const payload = await response.json();
  augmentationState.recommendationSummary = payload.summary || { total: 0, selected: 0, candidate: 0, blocked: 0, none: 0 };
  augmentationState.recommendations = (payload.recommendations || []).map(normalizeAugmentationRecommendation);
  alignSelectedAugmentationRecommendation();
}

async function loadAugmentation() {
  try {
    await window.loadAugmentationCrd?.();
    await loadAugmentationRecommendations();
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
    augmentationState.recommendations = [];
    augmentationState.recommendationSummary = { total: 0, selected: 0, candidate: 0, blocked: 0, none: 0 };
  }
  alignSelectedAugmentationResource();
  renderAugmentation();
}

function bindAugmentationEvents() {
  augEl("augmentationRefresh")?.addEventListener("click", () => loadAugmentation().catch(console.error));
  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    const target = event.target.closest("[data-augmentation-id]");
    const recommendationTarget = event.target.closest("[data-augmentation-recommendation-id]");
    if (!target && !recommendationTarget) return;
    if (target) augmentationState.selectedId = target.dataset.augmentationId || augmentationState.selectedId;
    if (recommendationTarget) {
      augmentationState.selectedRecommendationId = recommendationTarget.dataset.augmentationRecommendationId || augmentationState.selectedRecommendationId;
    }
    renderAugmentation();
  });
}

if (typeof document !== "undefined") {
  bindAugmentationEvents();
  loadAugmentation().catch(console.error);
}
