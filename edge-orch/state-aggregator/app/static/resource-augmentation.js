function resetRuntimeAugmentationState() {
  augmentationState.candidateResources = [];
  augmentationState.decision = null;
  augmentationState.workflowDemo = null;
  augmentationState.runtimeSummary = { candidate_resource_total: 0, available: 0, bound: 0, blocked: 0 };
  augmentationState.aiService = "";
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

async function loadRuntimeAugmentationDecision() {
  const response = await fetch(runtimeAugmentationUrl(), { cache: "no-store", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`runtime augmentation API unavailable: HTTP ${response.status}`);
  const payload = await response.json();
  augmentationState.runtimeSummary = payload.summary || { candidate_resource_total: 0, available: 0, bound: 0, blocked: 0 };
  augmentationState.aiService = payload.ai_service || "";
  augmentationState.candidateResources = (payload.candidate_resources || []).map(normalizeCandidateResource);
  augmentationState.decision = normalizeAugmentationDecision(payload.decision);
  augmentationState.workflowDemo = normalizeWorkflowDemo(payload.workflow_demo);
  alignSelectedCandidateResource();
}

async function loadVirtualResources() {
  const response = await fetch("/state/virtual-resources", { cache: "no-store", headers: { Accept: "application/json" } });
  if (!response.ok) {
    augmentationState.loadError = `virtual resource API unavailable: HTTP ${response.status}`;
    augmentationState.resources = [];
    return;
  }
  const payload = await response.json();
  augmentationState.loadError = payload.observation_error || "";
  augmentationState.resources = (payload.resources || []).map(normalizeAugmentationResource);
}

async function loadAugmentation() {
  try {
    await window.loadAugmentationCrd?.();
    await loadRuntimeAugmentationDecision();
    await loadVirtualResources();
  } catch (error) {
    augmentationState.loadError = `resource augmentation API unavailable: ${error?.name || "network error"}`;
    augmentationState.resources = [];
    resetRuntimeAugmentationState();
  }
  alignSelectedAugmentationResource();
  renderAugmentation();
}

function bindAugmentationEvents() {
  augEl("augmentationRefresh")?.addEventListener("click", () => loadAugmentation().catch(console.error));
  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Element)) return;
    const modeTarget = event.target.closest("[data-augmentation-mode]");
    const target = event.target.closest("[data-augmentation-id]");
    const candidateTarget = event.target.closest("[data-candidate-resource-id]");
    if (!modeTarget && !target && !candidateTarget) return;
    if (modeTarget) {
      setAugmentationMode(modeTarget.dataset.augmentationMode || "observed");
      stopAugmentationWorkflowPlayback();
      loadAugmentation().catch(console.error);
      return;
    }
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
