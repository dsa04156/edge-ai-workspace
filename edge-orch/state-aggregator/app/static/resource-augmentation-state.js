function initialAugmentationMode() {
  if (typeof window === "undefined") return "observed";
  const mode = new URLSearchParams(window.location.search).get("augmentationMode");
  return mode === "demo" ? "demo" : "observed";
}

const augmentationState = {
  resources: [],
  selectedId: "vd-x86-gpu-inference",
  candidateResources: [],
  decision: null,
  workflowDemo: null,
  runtimeSummary: { candidate_resource_total: 0, available: 0, bound: 0, blocked: 0 },
  selectedCandidateResourceId: "",
  aiService: "",
  runtimeMode: initialAugmentationMode(),
  workflowPlaybackIndex: 0,
  workflowPlaybackTimer: null,
  workflowPlaybackSignature: "",
  loadError: "",
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

function augmentationModeLabel(value) {
  return {
    observed: "observed mode",
    demo: "demo mode",
  }[value] || "observed mode";
}

function setAugmentationMode(value) {
  augmentationState.runtimeMode = value === "demo" ? "demo" : "observed";
}

function runtimeAugmentationUrl() {
  const params = new URLSearchParams();
  if (augmentationState.runtimeMode === "demo") params.set("mode", "demo");
  const query = params.toString();
  return `/state/runtime-resource-augmentation${query ? `?${query}` : ""}`;
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

function alignSelectedCandidateResource() {
  if (augmentationState.candidateResources.some((item) => item.id === augmentationState.selectedCandidateResourceId)) return;
  augmentationState.selectedCandidateResourceId = augmentationState.candidateResources[0]?.id || "";
}
