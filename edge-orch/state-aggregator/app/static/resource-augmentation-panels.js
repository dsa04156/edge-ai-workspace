function renderAugmentationModeControls() {
  document.querySelectorAll("[data-augmentation-mode]").forEach((button) => {
    const active = button.dataset.augmentationMode === augmentationState.runtimeMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function augmentationStatusClass(value) {
  const safe = String(value || "unknown").toLowerCase();
  return [
    "idle",
    "allocated",
    "partially_available",
    "configured_not_running",
    "degraded",
    "unavailable",
  ].includes(safe) ? safe : "unknown";
}

function renderAugmentationKpis(resources) {
  const observed = resources.reduce((sum, item) => sum + item.observed, 0);
  const allocated = resources.reduce((sum, item) => sum + item.allocated, 0);
  const available = resources.filter((item) => item.free > 0 || item.status === "idle").length;
  const notRunning = resources.filter((item) => item.status === "configured_not_running").length;
  const risk = resources.filter((item) => ["degraded", "unavailable"].includes(item.status)).length;
  const modeLabel = augmentationModeLabel(augmentationState.runtimeMode);
  renderAugmentationModeControls();
  augEl("augmentationProfileCount").textContent = resources.length;
  augEl("augmentationObservedCount").textContent = observed;
  augEl("augmentationAvailableCount").textContent = available;
  augEl("augmentationAllocatedCount").textContent = allocated;
  augEl("augmentationNotRunningCount").textContent = notRunning;
  augEl("augmentationRiskCount").textContent = risk;
  augEl("augmentationRecommendationTotal").textContent = augmentationState.runtimeSummary.candidate_resource_total || 0;
  augEl("augmentationRecommendationSelected").textContent = augmentationState.decision?.selectedResources?.length || 0;
  augEl("augmentationRecommendationBlocked").textContent = augRecommendationLabel(augmentationState.decision?.state);
  augEl("augmentationRuntimeScope").textContent = augmentationState.loadError || `${modeLabel} · ${observed} observed runtime instances`;
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
      <td><span class="augmentation-status ${augmentationStatusClass(resource.status)}">${augEscape(augStatusLabel(resource.status))}</span></td>
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
    <button class="augmentation-instance-chip ${augmentationStatusClass(resource.status)} ${resource.id === augmentationState.selectedId ? "selected" : ""}" type="button" data-augmentation-id="${augEscape(resource.id)}">
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
    runtime_mode: augmentationState.runtimeMode,
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

function renderAugmentationDecision() {
  const candidateResources = augmentationState.candidateResources;
  const selected = selectedCandidateResource();
  const decision = augmentationState.decision;
  const summary = augmentationState.runtimeSummary;
  const modeLabel = augmentationModeLabel(augmentationState.runtimeMode);
  augEl("augmentationRecommendationService").textContent = augmentationState.aiService || decision?.aiService || "-";
  augEl("augmentationRecommendationScope").textContent = `${modeLabel} · ${summary.candidate_resource_total || 0} candidate resources · ${summary.available || 0} available · trigger=${augEscape(decision?.trigger || "none")}`;
  augEl("augmentationCandidateResourceRows").innerHTML = candidateResources.map((item) => `
    <button class="augmentation-recommendation-row ${augEscape(item.phase.toLowerCase())} ${item.id === augmentationState.selectedCandidateResourceId ? "selected" : ""}" type="button" data-candidate-resource-id="${augEscape(item.id)}">
      <span><strong>${augEscape(item.id)}</strong><em>${augEscape(item.capability)}</em></span>
      <b>${augEscape(item.kind)}</b>
      <small>${augEscape(item.phase)}</small>
    </button>
  `).join("") || '<div class="workflow-empty">Candidate resource API response pending.</div>';
  if (!decision) {
    augEl("augmentationDecisionDetail").innerHTML = "<h4>Read-only Decision</h4><div>Augmented Device Plan is pending.</div>";
    return;
  }
  const augmentedDevice = decision.resultingAugmentedDevice || {};
  augEl("augmentationDecisionDetail").innerHTML = `
    <h4>Read-only Decision</h4>
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
