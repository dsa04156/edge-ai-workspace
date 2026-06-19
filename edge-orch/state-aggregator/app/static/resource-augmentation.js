const augmentationState = { resources: [], selectedId: "vd-x86-gpu-inference", execution: null, executing: false };
const DEVICE_AUGMENTATION_ID = "jetson-gpu-storage-augmentation";
const AUGMENTATION_EXECUTION_ENDPOINT = "/state/resource-augmentation/execution";

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

function augExecutionStatusLabel(value) {
  return {
    not_run: "실행 전",
    blocked: "차단됨",
    succeeded: "성공",
    failed: "실패",
  }[value] || augText(value, "unknown");
}

function augReasonLabel(value) {
  const reason = augText(value, "-");
  if (reason === "registry exists but no runtime instance is observed") return "registry 등록됨 · 실행 인스턴스 0";
  return reason;
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

function selectedAugmentationResource() {
  return augmentationState.resources.find((resource) => resource.id === augmentationState.selectedId) || augmentationState.resources[0];
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

function renderAugmentationExecution() {
  const button = augEl("augmentationExecute");
  if (button) {
    button.disabled = augmentationState.executing;
    button.textContent = augmentationState.executing ? "실행 중" : "수동 실행";
  }
  const execution = augmentationState.execution?.last_execution || null;
  const status = execution?.status || "not_run";
  augEl("augmentationExecutionStatus").textContent = augExecutionStatusLabel(status);
  augEl("augmentationExecutionTarget").textContent = execution
    ? `${augText(execution.target_device)} · ${augText(execution.target_resources?.inference)}`
    : "-";
  augEl("augmentationExecutionLatency").textContent = execution?.latency_ms === null || execution?.latency_ms === undefined
    ? "-"
    : `${execution.latency_ms} ms`;
  augEl("augmentationExecutionArtifact").textContent = augText(execution?.output_artifact);
  augEl("augmentationExecutionError").textContent = augText(execution?.error);
}

function renderAugmentation() {
  const resources = augmentationState.resources;
  const selected = selectedAugmentationResource();
  renderAugmentationKpis(resources);
  renderAugmentationRows(resources);
  renderAugmentationInspector(selected);
  renderAugmentationFlow(resources, selected);
  renderAugmentationPlan(selected);
  renderAugmentationExecution();
  window.renderAugmentationCrd?.(DEVICE_AUGMENTATION_ID);
}

async function loadAugmentationExecution() {
  const response = await fetch(AUGMENTATION_EXECUTION_ENDPOINT, { cache: "no-store", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  augmentationState.execution = await response.json();
}

async function triggerAugmentationExecution() {
  augmentationState.executing = true;
  renderAugmentationExecution();
  try {
    const response = await fetch(AUGMENTATION_EXECUTION_ENDPOINT, {
      method: "POST",
      cache: "no-store",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: JSON.stringify({
        input_source: "jetson-inspection-camera",
        payload: { triggered_by: "dashboard" },
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    augmentationState.execution = await response.json();
  } catch (error) {
    augmentationState.execution = {
      last_execution: {
        status: "failed",
        target_device: "etri-dev0001-jetorn",
        target_resources: { inference: "vd-x86-gpu-inference", storage: "vd-storage-cache" },
        latency_ms: null,
        output_artifact: null,
        error: `execution API unavailable: ${error?.message || error?.name || "network error"}`,
      },
    };
  } finally {
    augmentationState.executing = false;
    renderAugmentationExecution();
  }
}

async function loadAugmentation() {
  try {
    await window.loadAugmentationCrd?.();
    const response = await fetch("/state/virtual-resources", { cache: "no-store", headers: { Accept: "application/json" } });
    if (!response.ok) {
      augmentationState.loadError = `virtual resource API unavailable: HTTP ${response.status}`;
      augmentationState.resources = [];
    } else {
      const payload = await response.json();
      augmentationState.loadError = payload.observation_error || "";
      augmentationState.resources = (payload.resources || []).map(normalizeAugmentationResource);
    }
  } catch (error) {
    augmentationState.loadError = `virtual resource API unavailable: ${error?.name || "network error"}`;
    augmentationState.resources = [];
  }
  await loadAugmentationExecution().catch((error) => {
    augmentationState.execution = {
      last_execution: {
        status: "failed",
        target_device: "etri-dev0001-jetorn",
        target_resources: {},
        latency_ms: null,
        output_artifact: null,
        error: `execution state unavailable: ${error?.message || error?.name || "network error"}`,
      },
    };
  });
  alignSelectedAugmentationResource();
  renderAugmentation();
}

function bindAugmentationEvents() {
  augEl("augmentationRefresh")?.addEventListener("click", () => loadAugmentation().catch(console.error));
  augEl("augmentationExecute")?.addEventListener("click", () => triggerAugmentationExecution().catch(console.error));
  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    const target = event.target.closest("[data-augmentation-id]");
    if (!target) return;
    augmentationState.selectedId = target.dataset.augmentationId || augmentationState.selectedId;
    renderAugmentation();
  });
}

if (typeof document !== "undefined") {
  bindAugmentationEvents();
  loadAugmentation().catch(console.error);
}
