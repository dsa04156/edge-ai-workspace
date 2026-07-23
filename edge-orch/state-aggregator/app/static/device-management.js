const MANAGEMENT_ADAPTERS_URL = "/management/adapters";
const MANAGEMENT_VALIDATE_URL = "/management/devices/validate";
const MANAGEMENT_DEVICES_URL = "/management/devices";
const MANAGEMENT_RUNTIMES_URL = "/management/adapter-runtimes";
const MANAGEMENT_CONNECTIONS_URL = "/management/connections";

let sessionAdminToken = "";

const managementState = {
  adapters: [],
  runtimes: [],
  devices: [],
  selectedAdapterId: "",
  runtimePlan: null,
  runtimeLoadError: null,
  runtimeActionKeys: new Map(),
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


function runtimeCanMutate(runtime) {
  return Boolean(
    runtime
    && runtime.managementMode === "controller"
    && runtime.mutable === true
    && runtime.mutationEnabled === true,
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


async function fetchAdapterRuntimes(fetchFn = fetch) {
  const response = await fetchFn(MANAGEMENT_RUNTIMES_URL, {cache: "no-store"});
  const payload = await managementPayload(response);
  if (!Array.isArray(payload)) throw new Error("runtime inventory response must be an array");
  return payload;
}


async function planAdapterRuntime(payload, fetchFn = fetch) {
  const response = await fetchFn(`${MANAGEMENT_RUNTIMES_URL}/plan`, {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return managementPayload(response);
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


async function validateManagementConnection(payload, fetchFn = fetch) {
  const response = await fetchFn(`${MANAGEMENT_CONNECTIONS_URL}/validate`, {
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


async function createManagementConnection(payload, {
  token,
  idempotencyKey,
  fetchFn = fetch,
}) {
  const response = await fetchFn(MANAGEMENT_CONNECTIONS_URL, {
    method: "POST",
    headers: guardedHeaders(token, idempotencyKey),
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return managementPayload(response);
}


async function restartAdapterRuntime(name, {
  token,
  idempotencyKey,
  fetchFn = fetch,
}) {
  const response = await fetchFn(
    `${MANAGEMENT_RUNTIMES_URL}/${encodeURIComponent(name)}/restart`,
    {
      method: "POST",
      headers: guardedHeaders(token, idempotencyKey),
      cache: "no-store",
    },
  );
  return managementPayload(response);
}


async function retireAdapterRuntime(name, {
  token,
  idempotencyKey,
  fetchFn = fetch,
}) {
  const response = await fetchFn(
    `${MANAGEMENT_RUNTIMES_URL}/${encodeURIComponent(name)}`,
    {
      method: "DELETE",
      headers: {
        ...guardedHeaders(token, idempotencyKey),
        "X-Confirm-Runtime": name,
      },
      cache: "no-store",
    },
  );
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


async function fetchConnectionOperation(requestId, fetchFn = fetch) {
  const response = await fetchFn(
    `${MANAGEMENT_CONNECTIONS_URL}/operations/${encodeURIComponent(requestId)}`,
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


function connectionStatusView(operation = {}) {
  const status = String(operation.status || "PLANNED");
  const views = {
    PLANNED: {
      label: "PLANNED",
      tone: "applied",
      detail: "검증된 실행 plan 준비",
      terminal: false,
    },
    RUNTIME_REQUESTED: {
      label: "RUNTIME REQUESTED",
      tone: "waiting",
      detail: "Adapter Runtime 배포와 EdgeX Device Service 등록 대기",
      terminal: false,
    },
    RUNTIME_READY: {
      label: "RUNTIME READY",
      tone: "applied",
      detail: "Adapter Runtime과 EdgeX Device Service readback 완료",
      terminal: false,
    },
    PROFILE_APPLIED: {
      label: "PROFILE APPLIED",
      tone: "applied",
      detail: "EdgeX Device Profile 적용 완료",
      terminal: false,
    },
    DEVICE_APPLIED: {
      label: "DEVICE APPLIED",
      tone: "applied",
      detail: "EdgeX Device binding readback 완료",
      terminal: false,
    },
    WAITING_EVENT: {
      label: "WAITING FOR EVENT",
      tone: "waiting",
      detail: "Metadata 적용 완료 · 첫 Core Data Event 대기",
      terminal: false,
    },
    ACTIVE: {
      label: "ACTIVE",
      tone: "verified",
      detail: "Runtime · Metadata · 첫 Event 검증 완료",
      terminal: true,
    },
    COMPENSATING: {
      label: "COMPENSATING",
      tone: "waiting",
      detail: "실패한 신규 Runtime을 안전하게 퇴역하는 중",
      terminal: false,
    },
    COMPENSATED: {
      label: "COMPENSATED",
      tone: "failed",
      detail: operation.compensationStatus || "실패 보상 완료",
      terminal: true,
    },
    FAILED: {
      label: "FAILED",
      tone: "failed",
      detail: operation.error || "연결 작업 실패",
      terminal: true,
    },
  };
  return views[status] || views.PLANNED;
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


async function pollConnectionOperation(requestId, {
  fetchFn = fetch,
  sleepFn = delay,
  intervalMs = 2000,
  maxAttempts = 30,
} = {}) {
  let latest = null;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    latest = await fetchConnectionOperation(requestId, fetchFn);
    if (connectionStatusView(latest).terminal) return latest;
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


function renderRuntimeInventory(documentRef = document) {
  const container = byId("managementRuntimeList", documentRef);
  clearElement(container);
  if (!container) return;
  if (managementState.runtimeLoadError) {
    appendTextElement(
      container,
      "p",
      "management-empty",
      `Adapter Runtime 상태를 읽지 못했습니다: ${managementState.runtimeLoadError.message}`,
    );
    return;
  }
  if (!managementState.runtimes.length) {
    appendTextElement(
      container,
      "p",
      "management-empty",
      "관측된 Adapter Runtime이 없습니다.",
    );
    return;
  }
  managementState.runtimes.forEach((runtime) => {
    const card = documentRef.createElement("article");
    card.className = "management-runtime-card";
    card.dataset.phase = runtime.phase || "UNKNOWN";

    const header = documentRef.createElement("div");
    header.className = "management-runtime-card-header";
    appendTextElement(
      header,
      "strong",
      "",
      runtime.runtimeName || runtime.serviceName || "unknown-runtime",
    );
    appendTextElement(
      header,
      "span",
      "management-status",
      String(runtime.phase || "UNKNOWN").replaceAll("_", " "),
    );

    const service = runtime.edgeXServiceObserved === false
      ? `${runtime.serviceName} · EdgeX 미관측`
      : `${runtime.serviceName} · EdgeX 관측`;
    appendTextElement(card, "small", "", service);

    const facts = documentRef.createElement("div");
    facts.className = "management-runtime-facts";
    [
      `${runtime.targetNode || "node unknown"}`,
      `${runtime.managementOwner || "owner unknown"} 소유`,
      `${runtime.verificationState || "unverified"}`,
      `소비 Device ${Number(runtime.consumers || 0)}개`,
    ].forEach((fact) => appendTextElement(facts, "span", "", fact));

    const actions = documentRef.createElement("div");
    actions.className = "management-runtime-actions";
    const mutable = runtimeCanMutate(runtime);
    const restart = documentRef.createElement("button");
    restart.type = "button";
    restart.textContent = "Restart";
    restart.dataset.runtimeAction = "restart";
    restart.dataset.runtimeName = runtime.runtimeName;
    restart.disabled = !mutable;
    restart.title = mutable
      ? "컨트롤러 소유 Runtime을 재시작합니다."
      : "외부/Argo CD 소유 Runtime은 대시보드에서 변경할 수 없습니다.";
    const retire = documentRef.createElement("button");
    retire.type = "button";
    retire.textContent = "Retire";
    retire.dataset.runtimeAction = "retire";
    retire.dataset.runtimeName = runtime.runtimeName;
    retire.disabled = !mutable || Number(runtime.consumers || 0) > 0;
    retire.title = Number(runtime.consumers || 0) > 0
      ? "연결된 EdgeX Device가 있어 퇴역할 수 없습니다."
      : restart.title;
    actions.append(restart, retire);

    card.prepend(header);
    card.append(facts, actions);
    container.appendChild(card);
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
  ) || managementState.runtimes.some(
    (runtime) => runtime.mutationEnabled === true,
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


function renderRuntimeSelection(documentRef = document) {
  const adapter = selectedAdapter();
  const bindings = adapter?.runtime?.hardwareBindings || [];
  const bindingSelect = byId("managementHardwareBinding", documentRef);
  const nodeSelect = byId("managementTargetNode", documentRef);
  clearElement(bindingSelect);
  clearElement(nodeSelect);

  bindings.forEach((binding) => {
    const option = documentRef.createElement("option");
    option.value = binding.bindingId;
    option.textContent = binding.devicePath
      ? `${binding.displayName} · ${binding.devicePath}`
      : binding.displayName;
    option.dataset.nodeName = binding.nodeName;
    bindingSelect?.appendChild(option);
  });
  [...new Set(bindings.map((binding) => binding.nodeName))].forEach((nodeName) => {
    const option = documentRef.createElement("option");
    option.value = nodeName;
    option.textContent = nodeName;
    nodeSelect?.appendChild(option);
  });

  const hasBindings = bindings.length > 0;
  if (bindingSelect) bindingSelect.disabled = !hasBindings;
  if (nodeSelect) nodeSelect.disabled = !hasBindings;

  const modeSelect = byId("managementRuntimeMode", documentRef);
  const deployOption = modeSelect?.querySelector('option[value="deploy"]');
  if (deployOption) {
    deployOption.disabled = adapter?.runtime?.deploymentEnabled !== true;
    deployOption.textContent = deployOption.disabled
      ? "Deploy approved template · unavailable"
      : "Deploy approved template";
  }
  if (modeSelect?.value === "deploy" && deployOption?.disabled) {
    modeSelect.value = "auto";
  }
}


function syncRuntimeNodeFromBinding(documentRef = document) {
  const bindingSelect = byId("managementHardwareBinding", documentRef);
  const selected = bindingSelect?.selectedOptions?.[0];
  const nodeName = selected?.dataset?.nodeName;
  const nodeSelect = byId("managementTargetNode", documentRef);
  if (nodeName && nodeSelect) nodeSelect.value = nodeName;
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
  const selectedNode = byId("managementTargetNode", documentRef)?.value || adapter.nodeName;
  if (selectedNode) tags.nodeName = selectedNode;
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


function collectConnectionPayload(documentRef = document) {
  const payload = collectOnboardingPayload(documentRef);
  return {
    ...payload,
    runtime: {
      mode: byId("managementRuntimeMode", documentRef).value,
      targetNode: byId("managementTargetNode", documentRef).value,
      hardwareBindingId: byId("managementHardwareBinding", documentRef).value,
    },
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
  const runtimePlan = result?.runtimePlan;
  if (runtimePlan) {
    const reasons = runtimePlan.reasons || [];
    appendTextElement(
      container,
      "p",
      "management-plan",
      `Runtime: ${runtimePlan.action} · ${runtimePlan.runtimeName || "not assigned"} · `
        + `${runtimePlan.serviceName || "service unavailable"} · `
        + `${runtimePlan.verificationState || "unverified"}`,
    );
    reasons.forEach((reason) => {
      appendTextElement(
        container,
        "p",
        "management-issue",
        `${reason.code || "runtime"}: ${reason.message}`,
      );
    });
  }
  if (result?.valid) {
    const plan = result.edgeXPlan || result.plan || {};
    const mutations = plan.mutations || [];
    appendTextElement(
      container,
      "p",
      "management-plan",
      `EdgeX: ${mutations.join(" → ") || "readback"} → first Event`,
    );
  }
  (result?.warnings || []).forEach((warning) => {
    appendTextElement(
      container,
      "p",
      "management-warning",
      `${warning.field || "warning"}: ${warning.message}`,
    );
  });
  const applyButton = byId("managementApply", documentRef);
  if (applyButton) applyButton.disabled = !(result?.valid && adapterCanApply(selectedAdapter()));
}


function renderOperation(operation, documentRef = document) {
  const container = byId("managementOperation", documentRef);
  clearElement(container);
  if (!container || !operation) return;
  const isConnection = /^[A-Z_]+$/.test(String(operation.status || ""));
  const view = isConnection
    ? connectionStatusView(operation)
    : operationStatusView(operation);
  container.dataset.status = view.tone;
  appendTextElement(container, "strong", "", view.label);
  appendTextElement(container, "p", "", view.detail);
  appendTextElement(
    container,
    "small",
    "",
    isConnection
      ? `${operation.runtimeAction || "runtime"} · ${operation.runtimeName || "runtime"} · `
        + `${operation.deviceName || "device"} · request ${operation.requestId || "pending"}`
      : `${operation.action || "create"} · ${operation.deviceName || "device"} · `
        + `request ${operation.requestId || "pending"}`,
  );
}


function renderRuntimeActionResult(runtime, action, documentRef = document) {
  const container = byId("managementOperation", documentRef);
  clearElement(container);
  if (!container) return;
  container.dataset.status = runtime.phase === "FAILED" ? "failed" : "applied";
  appendTextElement(
    container,
    "strong",
    "",
    `${action.toUpperCase()} · ${runtime.phase || "REQUESTED"}`,
  );
  appendTextElement(
    container,
    "p",
    "",
    `${runtime.runtimeName} · ${runtime.serviceName} · ${runtime.targetNode}`,
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
  const runtimeRequest = fetchAdapterRuntimes(fetchFn)
    .then((runtimes) => {
      managementState.runtimeLoadError = null;
      return runtimes;
    })
    .catch((error) => {
      managementState.runtimeLoadError = error;
      return [];
    });
  const [adapters, devices, runtimes] = await Promise.all([
    fetchManagementAdapters(fetchFn),
    fetchManagedDevices(fetchFn),
    runtimeRequest,
  ]);
  managementState.adapters = adapters;
  managementState.devices = devices;
  managementState.runtimes = runtimes;
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
  renderRuntimeInventory(documentRef);
  renderManagedDevices(documentRef);
  renderMutationMode(documentRef);
  renderRuntimeSelection(documentRef);
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
    renderRuntimeSelection(documentRef);
    clearElement(byId("managementValidation", documentRef));
  });
  byId("managementHardwareBinding", documentRef)?.addEventListener("change", () => {
    syncRuntimeNodeFromBinding(documentRef);
    managementState.validation = null;
    const applyButton = byId("managementApply", documentRef);
    if (applyButton) applyButton.disabled = true;
  });
  byId("managementRuntimeMode", documentRef)?.addEventListener("change", () => {
    managementState.validation = null;
    const applyButton = byId("managementApply", documentRef);
    if (applyButton) applyButton.disabled = true;
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
      const payload = collectConnectionPayload(documentRef);
      managementState.validation = await validateManagementConnection(payload, fetchFn);
      managementState.runtimePlan = managementState.validation.runtimePlan || null;
      renderManagementValidation(managementState.validation, documentRef);
    } catch (error) {
      renderManagementError(error, documentRef);
    }
  });
  byId("managementApply", documentRef)?.addEventListener("click", async () => {
    try {
      const payload = collectConnectionPayload(documentRef);
      const validation = await validateManagementConnection(payload, fetchFn);
      managementState.validation = validation;
      managementState.runtimePlan = validation.runtimePlan || null;
      renderManagementValidation(validation, documentRef);
      if (!validation.valid) return;
      const operation = await createManagementConnection(payload, {
        token: sessionAdminToken,
        idempotencyKey: ensureIdempotencyInput(
          byId("managementIdempotencyKey", documentRef),
        ),
        fetchFn,
      });
      managementState.operation = operation;
      renderOperation(operation, documentRef);
      if (!connectionStatusView(operation).terminal) {
        managementState.operation = await pollConnectionOperation(operation.requestId, {fetchFn});
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
  byId("managementRuntimeList", documentRef)?.addEventListener("click", async (event) => {
    const button = event.target.closest?.("[data-runtime-action]");
    if (!button || button.disabled) return;
    const action = button.dataset.runtimeAction;
    const name = button.dataset.runtimeName;
    if (
      action === "retire"
      && typeof globalThis.confirm === "function"
      && !globalThis.confirm(`${name} Runtime을 퇴역하시겠습니까? 이 작업은 정확한 이름 확인 후 실행됩니다.`)
    ) {
      return;
    }
    const actionKey = `${action}:${name}`;
    if (!managementState.runtimeActionKeys.has(actionKey)) {
      managementState.runtimeActionKeys.set(
        actionKey,
        `runtime-${action}-${name}-${Date.now()}`,
      );
    }
    button.disabled = true;
    try {
      const options = {
        token: sessionAdminToken,
        idempotencyKey: managementState.runtimeActionKeys.get(actionKey),
        fetchFn,
      };
      const runtime = action === "restart"
        ? await restartAdapterRuntime(name, options)
        : await retireAdapterRuntime(name, options);
      renderRuntimeActionResult(runtime, action, documentRef);
      await loadDeviceManagement(documentRef, fetchFn);
    } catch (error) {
      renderManagementError(error, documentRef);
      button.disabled = false;
    }
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
    connectionStatusView,
    createManagementConnection,
    createManagementDevice,
    fetchAdapterRuntimes,
    fetchConnectionOperation,
    fetchManagementAdapters,
    fetchManagementOperation,
    operationStatusView,
    patchManagementDevice,
    planAdapterRuntime,
    pollConnectionOperation,
    pollManagementOperation,
    restartAdapterRuntime,
    retireAdapterRuntime,
    runtimeCanMutate,
    validateManagementConnection,
    validateManagementDevice,
  };
}
