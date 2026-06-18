const augmentationCrdState = {
  resources: [],
  deviceAugmentations: [],
  loadError: "",
};

function crdText(value, fallback = "-") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}

function crdEscape(value) {
  return crdText(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function crdEl(id) {
  return document.getElementById(id);
}

function normalizeCondition(condition = {}) {
  return {
    type: crdText(condition.type, "Unknown"),
    status: crdText(condition.status, "Unknown"),
    reason: crdText(condition.reason, "Unknown"),
    message: crdText(condition.message, ""),
  };
}

function normalizeDeviceAugmentation(item = {}) {
  return {
    name: crdText(item.name),
    namespace: crdText(item.namespace, "default"),
    phase: crdText(item.phase, "Unknown"),
    target: crdText(item.target_device_name),
    boundResources: Array.isArray(item.bound_resources) ? item.bound_resources : [],
    selectedResources: Array.isArray(item.selected_resources) ? item.selected_resources : [],
    missingCapabilities: Array.isArray(item.missing_capabilities) ? item.missing_capabilities : [],
    conditions: Array.isArray(item.conditions) ? item.conditions.map(normalizeCondition) : [],
    reason: crdText(item.reason, ""),
  };
}

function selectedDeviceAugmentation(name) {
  return augmentationCrdState.deviceAugmentations.find((item) => item.name === name)
    || augmentationCrdState.deviceAugmentations[0];
}

async function fetchCrdJson(path) {
  const response = await fetch(path, { cache: "no-store", headers: { Accept: "application/json" } });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

async function loadAugmentationCrd() {
  try {
    const [resources, bindings] = await Promise.all([
      fetchCrdJson("/state/augmentation-resources"),
      fetchCrdJson("/state/device-augmentations"),
    ]);
    augmentationCrdState.resources = Array.isArray(resources.resources) ? resources.resources : [];
    augmentationCrdState.deviceAugmentations = Array.isArray(bindings.device_augmentations)
      ? bindings.device_augmentations.map(normalizeDeviceAugmentation)
      : [];
    augmentationCrdState.loadError = resources.observation_error || bindings.observation_error || "";
  } catch (error) {
    augmentationCrdState.resources = [];
    augmentationCrdState.deviceAugmentations = [];
    augmentationCrdState.loadError = `augmentation CRD API unavailable: ${error?.message || "network error"}`;
  }
}

function renderCrdConditions(binding) {
  if (!binding?.conditions?.length) return;
  const items = binding.conditions.map((condition) => {
    const pass = condition.status === "True";
    const label = `${condition.type}: ${condition.reason}`;
    const detail = condition.message ? ` · ${condition.message}` : "";
    return `<li class="${pass ? "pass" : "warn"}"><strong>${pass ? "PASS" : "WAIT"}</strong><span>${crdEscape(label + detail)}</span></li>`;
  });
  crdEl("augmentationValidationList").innerHTML = items.join("");
}

function renderCrdFlow(binding) {
  if (!binding?.selectedResources?.length) return;
  const inference = binding.selectedResources.find((item) => item.role === "inference");
  const storage = binding.selectedResources.find((item) => item.role === "storage");
  if (inference) crdEl("augmentationBoundResource").textContent = inference.name;
  if (storage) crdEl("augmentationStorageResource").textContent = storage.name;
}

function renderCrdPlan(binding) {
  const plan = JSON.parse(crdEl("augmentationPlanPreview").textContent || "{}");
  crdEl("augmentationPlanPreview").textContent = JSON.stringify({
    ...plan,
    kubernetes_crd: true,
    device_augmentation_status: binding ? {
      name: binding.name,
      namespace: binding.namespace,
      phase: binding.phase,
      target_edge_device: binding.target,
      bound_resources: binding.boundResources,
      selected_resources: binding.selectedResources,
      missing_capabilities: binding.missingCapabilities,
      conditions: binding.conditions,
      reason: binding.reason,
    } : null,
    crd_observation_error: augmentationCrdState.loadError || null,
  }, null, 2);
}

function renderAugmentationCrd(deviceAugmentationName) {
  const binding = selectedDeviceAugmentation(deviceAugmentationName);
  const suffix = binding ? ` · CRD ${binding.name}: ${binding.phase}` : " · CRD binding pending";
  crdEl("augmentationRuntimeScope").textContent = `${crdEl("augmentationRuntimeScope").textContent}${suffix}`;
  renderCrdFlow(binding);
  renderCrdConditions(binding);
  renderCrdPlan(binding);
}

window.loadAugmentationCrd = loadAugmentationCrd;
window.renderAugmentationCrd = renderAugmentationCrd;
