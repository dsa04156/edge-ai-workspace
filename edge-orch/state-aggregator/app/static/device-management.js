const MANAGEMENT_ADAPTERS_URL = "/management/adapters";
const MANAGEMENT_VALIDATE_URL = "/management/devices/validate";
const MANAGEMENT_DEVICES_URL = "/management/devices";

let sessionAdminToken = "";

const managementState = {
  adapters: [],
  devices: [],
  selectedAdapterId: "",
  validation: null,
  operation: null,
};


function adapterCanApply(adapter) {
  return Boolean(
    adapter
    && adapter.status === "installed"
    && adapter.mutationEnabled === true,
  );
}


async function managementPayload(response) {
  let payload;
  try {
    payload = await response.json();
  } catch (_error) {
    throw new Error(`management API returned invalid JSON (${response.status})`);
  }
  if (response.ok) return payload;
  const detail = payload?.detail;
  const message = typeof detail === "string"
    ? detail
    : detail?.message || detail?.error || `management request failed (${response.status})`;
  const error = new Error(message);
  error.status = response.status;
  error.detail = detail;
  throw error;
}


async function fetchManagementAdapters(fetchFn = fetch) {
  const response = await fetchFn(MANAGEMENT_ADAPTERS_URL, {cache: "no-store"});
  const payload = await managementPayload(response);
  if (!Array.isArray(payload)) throw new Error("adapter catalog response must be an array");
  return payload;
}


async function fetchManagedDevices(fetchFn = fetch) {
  const response = await fetchFn("/state/devices", {cache: "no-store"});
  const payload = await managementPayload(response);
  if (!Array.isArray(payload)) throw new Error("device inventory response must be an array");
  return payload;
}


async function validateManagementDevice(payload, fetchFn = fetch) {
  const response = await fetchFn(MANAGEMENT_VALIDATE_URL, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return managementPayload(response);
}


function guardedHeaders(token, idempotencyKey) {
  return {
    "Content-Type": "application/json",
    Authorization: `Bearer ${token}`,
    "Idempotency-Key": idempotencyKey,
  };
}


async function createManagementDevice(payload, {
  token,
  idempotencyKey,
  fetchFn = fetch,
}) {
  const response = await fetchFn(MANAGEMENT_DEVICES_URL, {
    method: "POST",
    headers: guardedHeaders(token, idempotencyKey),
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return managementPayload(response);
}


async function patchManagementDevice(name, payload, {
  token,
  idempotencyKey,
  fetchFn = fetch,
}) {
  const response = await fetchFn(
    `${MANAGEMENT_DEVICES_URL}/${encodeURIComponent(name)}`,
    {
      method: "PATCH",
      headers: guardedHeaders(token, idempotencyKey),
      body: JSON.stringify(payload),
      cache: "no-store",
    },
  );
  return managementPayload(response);
}


async function fetchManagementOperation(requestId, fetchFn = fetch) {
  const response = await fetchFn(
    `/management/operations/${encodeURIComponent(requestId)}`,
    {cache: "no-store"},
  );
  return managementPayload(response);
}


function operationStatusView(operation = {}) {
  if (operation.status === "verified") {
    return {
      label: "VERIFIED",
      tone: "verified",
      detail: "EdgeX Metadata 적용 · 첫 Core Data Event 검증 완료",
      terminal: true,
    };
  }
  if (operation.status === "failed") {
    return {
      label: "FAILED",
      tone: "failed",
      detail: operation.error || "EdgeX Metadata 적용 또는 readback 실패",
      terminal: true,
    };
  }
  if (operation.status === "metadata_applied") {
    return {
      label: "METADATA APPLIED",
      tone: "applied",
      detail: "EdgeX Profile/Device readback 완료",
      terminal: false,
    };
  }
  return {
    label: "WAITING FOR EVENT",
    tone: "waiting",
    detail: operation.error || "EdgeX Metadata 적용 완료 · 첫 Core Data Event 대기",
    terminal: false,
  };
}


function delay(milliseconds) {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}


async function pollManagementOperation(requestId, {
  fetchFn = fetch,
  sleepFn = delay,
  intervalMs = 2000,
  maxAttempts = 10,
} = {}) {
  let latest = null;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    latest = await fetchManagementOperation(requestId, fetchFn);
    if (operationStatusView(latest).terminal) return latest;
    if (attempt + 1 < maxAttempts) await sleepFn(intervalMs);
  }
  return latest;
}


function byId(id, documentRef = document) {
  return documentRef.getElementById(id);
}


function clearElement(element) {
  if (element) element.replaceChildren();
}


function appendTextElement(parent, tagName, className, text) {
  const element = parent.ownerDocument.createElement(tagName);
  if (className) element.className = className;
  element.textContent = text;
  parent.appendChild(element);
  return element;
}


function renderAdapterCatalog(documentRef = document) {
  const container = byId("managementAdapterList", documentRef);
  clearElement(container);
  managementState.adapters.forEach((adapter) => {
    const card = documentRef.createElement("article");
    card.className = "management-adapter-card";
    card.dataset.status = adapter.status;
    appendTextElement(card, "strong", "", adapter.displayName || adapter.adapterId);
    appendTextElement(
      card,
      "span",
      "management-status",
      String(adapter.status || "unknown").toUpperCase(),
    );
    appendTextElement(
      card,
      "small",
      "",
      adapter.serviceName
        ? `${adapter.serviceName} · ${adapter.protocolName}`
        : adapter.reason || "Device Service 미검증",
    );
    container?.appendChild(card);
  });
}


function renderManagedDevices(documentRef = document) {
  const container = byId("managedDeviceList", documentRef);
  clearElement(container);
  if (!managementState.devices.length) {
    if (container) appendTextElement(container, "p", "management-empty", "등록된 EdgeX Device가 없습니다.");
    return;
  }
  managementState.devices.forEach((device) => {
    const row = documentRef.createElement("article");
    row.className = "managed-device-row";
    const identity = documentRef.createElement("div");
    appendTextElement(identity, "strong", "", device.name || "unknown-device");
    appendTextElement(
      identity,
      "small",
      "",
      `${device.profile_name || "profile unknown"} · ${device.device_service_name || "service unknown"}`,
    );
    appendTextElement(
      identity,
      "small",
      "",
      `${device.admin_state || "UNKNOWN"} / ${device.operating_state || "UNKNOWN"} · event ${device.telemetry_freshness || "unknown"}`,
    );
    const button = documentRef.createElement("button");
    button.type = "button";
    button.dataset.managementEditDevice = device.name;
    button.textContent = "Select for update";
    row.append(identity, button);
    container?.appendChild(row);
  });
}


function selectedAdapter() {
  return managementState.adapters.find(
    (item) => item.adapterId === managementState.selectedAdapterId,
  ) || null;
}


function renderMutationMode(documentRef = document) {
  const enabled = managementState.adapters.some(
    (adapter) => adapter.mutationEnabled === true,
  );
  const mode = byId("managementMutationMode", documentRef);
  if (mode) {
    mode.textContent = enabled ? "MUTATION ENABLED" : "DRY-RUN ONLY · MUTATION DISABLED";
    mode.dataset.status = enabled ? "enabled" : "disabled";
  }
  const tokenInput = byId("managementAdminToken", documentRef);
  if (tokenInput) tokenInput.disabled = !enabled;
  const patchButton = byId("managementPatchApply", documentRef);
  if (patchButton) patchButton.disabled = !enabled;
}


function renderProtocolFields(documentRef = document) {
  const container = byId("managementProtocolFields", documentRef);
  clearElement(container);
  const adapter = selectedAdapter();
  if (!adapter) return;
  (adapter.fields || []).forEach((field) => {
    const label = documentRef.createElement("label");
    const caption = documentRef.createElement("span");
    caption.textContent = field.label || field.name;
    let input;
    if (field.type === "enum") {
      input = documentRef.createElement("select");
      (field.options || []).forEach((value) => {
        const option = documentRef.createElement("option");
        option.value = String(value);
        option.textContent = String(value);
        input.appendChild(option);
      });
    } else {
      input = documentRef.createElement("input");
      input.type = field.type === "integer" ? "number" : "text";
    }
    input.dataset.protocolField = field.name;
    input.dataset.protocolType = field.type;
    input.required = Boolean(field.required);
    const defaultValue = field.const ?? field.default;
    if (defaultValue !== null && defaultValue !== undefined) input.value = String(defaultValue);
    if (field.const !== null && field.const !== undefined) input.readOnly = true;
    label.append(caption, input);
    container?.appendChild(label);
  });
  const applyButton = byId("managementApply", documentRef);
  if (applyButton) applyButton.disabled = true;
  const adapterNote = byId("managementAdapterNote", documentRef);
  if (adapterNote) {
    adapterNote.textContent = adapterCanApply(adapter)
      ? `${adapter.serviceName}에 Profile/Device를 등록합니다.`
      : adapter.status === "installed" && adapter.mutationEnabled !== true
        ? `${adapter.serviceName} dry-run만 가능합니다. 관리 mutation은 비활성화되어 있습니다.`
      : adapter.reason || "현재 apply할 수 없는 adapter입니다.";
    adapterNote.dataset.status = adapter.status || "unknown";
  }
}


function collectProtocolProperties(documentRef = document) {
  const properties = {};
  documentRef.querySelectorAll("[data-protocol-field]").forEach((input) => {
    const name = input.dataset.protocolField;
    const value = input.dataset.protocolType === "integer"
      ? Number.parseInt(input.value, 10)
      : input.value.trim();
    properties[name] = value;
  });
  return properties;
}


function commaList(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}


function collectOnboardingPayload(documentRef = document) {
  const adapter = selectedAdapter();
  if (!adapter) throw new Error("Adapter를 선택하세요.");
  const protocolProperties = collectProtocolProperties(documentRef);
  const deviceId = protocolProperties.DeviceID || "";
  const profileMode = byId("managementProfileMode", documentRef).value;
  const profile = {
    mode: profileMode,
    name: byId("managementProfileName", documentRef).value.trim(),
  };
  if (profileMode === "create") {
    profile.description = byId("managementProfileDescription", documentRef).value.trim();
    profile.manufacturer = byId("managementProfileManufacturer", documentRef).value.trim();
    profile.model = byId("managementProfileModel", documentRef).value.trim();
    profile.labels = commaList(byId("managementProfileLabels", documentRef).value);
  }
  const tags = {};
  if (deviceId) tags.physicalDeviceId = deviceId;
  if (adapter.nodeName) tags.nodeName = adapter.nodeName;
  return {
    adapterId: adapter.adapterId,
    device: {
      name: byId("managementDeviceName", documentRef).value.trim(),
      description: byId("managementDeviceDescription", documentRef).value.trim(),
      labels: commaList(byId("managementDeviceLabels", documentRef).value),
      tags,
      protocolProperties,
      adminState: "UNLOCKED",
    },
    profile,
  };
}


function renderManagementValidation(result, documentRef = document) {
  const container = byId("managementValidation", documentRef);
  clearElement(container);
  if (!container) return;
  container.dataset.status = result?.valid ? "valid" : "invalid";
  appendTextElement(
    container,
    "strong",
    "",
    result?.valid ? "VALID · mutation plan ready" : "VALIDATION FAILED",
  );
  (result?.issues || []).forEach((issue) => {
    appendTextElement(
      container,
      "p",
      "management-issue",
      `${issue.field || "request"}: ${issue.message}`,
    );
  });
  if (result?.valid) {
    const mutations = result.plan?.mutations || [];
    appendTextElement(
      container,
      "p",
      "management-plan",
      `Plan: ${mutations.join(" → ")} → Metadata readback → first Event`,
    );
  }
  const applyButton = byId("managementApply", documentRef);
  if (applyButton) applyButton.disabled = !(result?.valid && adapterCanApply(selectedAdapter()));
}


function renderOperation(operation, documentRef = document) {
  const container = byId("managementOperation", documentRef);
  clearElement(container);
  if (!container || !operation) return;
  const view = operationStatusView(operation);
  container.dataset.status = view.tone;
  appendTextElement(container, "strong", "", view.label);
  appendTextElement(container, "p", "", view.detail);
  appendTextElement(
    container,
    "small",
    "",
    `${operation.action || "create"} · ${operation.deviceName || "device"} · request ${operation.requestId || "pending"}`,
  );
}


function renderManagementError(error, documentRef = document) {
  const container = byId("managementOperation", documentRef);
  clearElement(container);
  if (!container) return;
  container.dataset.status = error?.status === 404 ? "disabled" : "failed";
  appendTextElement(
    container,
    "strong",
    "",
    error?.status === 404 ? "MUTATION DISABLED" : "REQUEST FAILED",
  );
  appendTextElement(container, "p", "", error?.message || "관리 요청에 실패했습니다.");
}


function updateProfileMode(documentRef = document) {
  const createFields = byId("managementCreateProfileFields", documentRef);
  const createMode = byId("managementProfileMode", documentRef)?.value === "create";
  if (createFields) createFields.hidden = !createMode;
}


function setSelectedPatchDevice(name, documentRef = document) {
  const device = managementState.devices.find((item) => item.name === name);
  byId("patchDeviceName", documentRef).value = name || "";
  byId("patchDeviceDescription", documentRef).value = device?.description || "";
  byId("patchDeviceAdminState", documentRef).value = device?.admin_state || "UNLOCKED";
  byId("patchDeviceLabels", documentRef).value = (device?.labels || []).join(", ");
}


function collectPatchPayload(documentRef = document) {
  const payload = {};
  const description = byId("patchDeviceDescription", documentRef).value.trim();
  const labels = commaList(byId("patchDeviceLabels", documentRef).value);
  const tagsText = byId("patchDeviceTags", documentRef).value.trim();
  const protocolText = byId("patchDeviceProtocol", documentRef).value.trim();
  payload.description = description;
  payload.labels = labels;
  payload.adminState = byId("patchDeviceAdminState", documentRef).value;
  if (tagsText) payload.tags = JSON.parse(tagsText);
  if (protocolText) payload.protocolProperties = JSON.parse(protocolText);
  return payload;
}


function ensureIdempotencyInput(input) {
  if (input.value.trim()) return input.value.trim();
  const value = globalThis.crypto?.randomUUID?.()
    || `management-${Date.now()}-${Math.random().toString(16).slice(2)}`;
  input.value = value;
  return value;
}


async function loadDeviceManagement(documentRef = document, fetchFn = fetch) {
  const [adapters, devices] = await Promise.all([
    fetchManagementAdapters(fetchFn),
    fetchManagedDevices(fetchFn),
  ]);
  managementState.adapters = adapters;
  managementState.devices = devices;
  const firstInstalled = adapters.find((adapter) => adapter.status === "installed") || adapters[0];
  managementState.selectedAdapterId = firstInstalled?.adapterId || "";
  const select = byId("managementAdapter", documentRef);
  clearElement(select);
  adapters.forEach((adapter) => {
    const option = documentRef.createElement("option");
    option.value = adapter.adapterId;
    option.textContent = `${adapter.displayName} · ${adapter.status}`;
    option.disabled = adapter.status === "unsupported";
    option.selected = adapter.adapterId === managementState.selectedAdapterId;
    select?.appendChild(option);
  });
  renderAdapterCatalog(documentRef);
  renderManagedDevices(documentRef);
  renderMutationMode(documentRef);
  renderProtocolFields(documentRef);
  ensureIdempotencyInput(byId("managementIdempotencyKey", documentRef));
  ensureIdempotencyInput(byId("patchIdempotencyKey", documentRef));
}


function initializeDeviceManagement(documentRef = document, fetchFn = fetch) {
  const adapterSelect = byId("managementAdapter", documentRef);
  if (!adapterSelect) return;
  adapterSelect.addEventListener("change", () => {
    managementState.selectedAdapterId = adapterSelect.value;
    managementState.validation = null;
    renderProtocolFields(documentRef);
    clearElement(byId("managementValidation", documentRef));
  });
  byId("managementProfileMode", documentRef)?.addEventListener("change", () => {
    updateProfileMode(documentRef);
    managementState.validation = null;
    const applyButton = byId("managementApply", documentRef);
    if (applyButton) applyButton.disabled = true;
  });
  byId("managementAdminToken", documentRef)?.addEventListener("input", (event) => {
    sessionAdminToken = event.target.value;
  });
  byId("managementValidate", documentRef)?.addEventListener("click", async () => {
    try {
      const payload = collectOnboardingPayload(documentRef);
      managementState.validation = await validateManagementDevice(payload, fetchFn);
      renderManagementValidation(managementState.validation, documentRef);
    } catch (error) {
      renderManagementError(error, documentRef);
    }
  });
  byId("managementApply", documentRef)?.addEventListener("click", async () => {
    try {
      const payload = collectOnboardingPayload(documentRef);
      const validation = await validateManagementDevice(payload, fetchFn);
      managementState.validation = validation;
      renderManagementValidation(validation, documentRef);
      if (!validation.valid) return;
      const operation = await createManagementDevice(payload, {
        token: sessionAdminToken,
        idempotencyKey: ensureIdempotencyInput(
          byId("managementIdempotencyKey", documentRef),
        ),
        fetchFn,
      });
      managementState.operation = operation;
      renderOperation(operation, documentRef);
      if (!operationStatusView(operation).terminal) {
        managementState.operation = await pollManagementOperation(operation.requestId, {fetchFn});
        renderOperation(managementState.operation, documentRef);
      }
    } catch (error) {
      renderManagementError(error, documentRef);
    }
  });
  byId("managementRefresh", documentRef)?.addEventListener("click", () => {
    loadDeviceManagement(documentRef, fetchFn).catch((error) => {
      renderManagementError(error, documentRef);
    });
  });
  byId("managedDeviceList", documentRef)?.addEventListener("click", (event) => {
    const button = event.target.closest?.("[data-management-edit-device]");
    if (button) setSelectedPatchDevice(button.dataset.managementEditDevice, documentRef);
  });
  byId("devicePatchForm", documentRef)?.addEventListener("submit", async (event) => {
    event.preventDefault();
    try {
      const name = byId("patchDeviceName", documentRef).value.trim();
      const result = await patchManagementDevice(name, collectPatchPayload(documentRef), {
        token: sessionAdminToken,
        idempotencyKey: ensureIdempotencyInput(
          byId("patchIdempotencyKey", documentRef),
        ),
        fetchFn,
      });
      renderOperation(result, documentRef);
    } catch (error) {
      renderManagementError(error, documentRef);
    }
  });
  updateProfileMode(documentRef);
  loadDeviceManagement(documentRef, fetchFn).catch((error) => {
    renderManagementError(error, documentRef);
  });
}


if (typeof document !== "undefined") {
  initializeDeviceManagement();
}


if (typeof module !== "undefined") {
  module.exports = {
    adapterCanApply,
    createManagementDevice,
    fetchManagementAdapters,
    fetchManagementOperation,
    operationStatusView,
    patchManagementDevice,
    pollManagementOperation,
    validateManagementDevice,
  };
}
