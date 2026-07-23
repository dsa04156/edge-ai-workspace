const MANAGEMENT_ADAPTERS_URL = "/management/adapters";
const MANAGEMENT_VALIDATE_URL = "/management/devices/validate";
const MANAGEMENT_DEVICES_URL = "/management/devices";
const MANAGEMENT_RUNTIMES_URL = "/management/adapter-runtimes";
const MANAGEMENT_CONNECTIONS_URL = "/management/connections";
const MANAGEMENT_NODES_URL = "/state/nodes";
const UNASSIGNED_NODE = "미할당 노드";

let sessionAdminToken = "";

const managementState = {
  adapters: [],
  nodes: [],
  runtimes: [],
  devices: [],
  selectedNodeName: "",
  selectedAdapterId: "",
  selectedPatchDeviceName: "",
  activeView: "overview",
  registrationStep: 1,
  nodeLoadError: null,
  runtimePlan: null,
  runtimeLoadError: null,
  runtimeActionKeys: new Map(),
  validation: null,
  operation: null,
};


const MANAGEMENT_LABELS = {
  adapterStatus: {
    installed: "설치됨",
    installable: "설치 가능",
    unavailable: "사용 불가",
    unsupported: "미지원",
    unknown: "알 수 없음",
  },
  presence: {
    detected: "장비 관측됨",
    not_detected: "장비 미관측",
    unknown: "관측 근거 없음",
  },
  communication: {
    connected: "통신 연결",
    disconnected: "통신 끊김",
    unknown: "통신 미확인",
  },
  telemetry: {
    fresh: "데이터 최신",
    stale: "데이터 지연",
    missing: "데이터 없음",
    unknown: "데이터 미확인",
  },
  runtimeState: {
    ready: "Device Service 준비",
    not_ready: "Device Service 준비 중",
    not_installed: "Device Service 미설치",
  },
  runtimePhase: {
    PLANNED: "배치 계획",
    DEPLOYING: "배포 중",
    WORKLOAD_READY: "워크로드 준비 완료",
    SERVICE_READY: "서비스 준비 완료",
    RESTARTING: "재시작 중",
    FAILED: "실패",
    RETIRING: "퇴역 중",
    RETIRED: "퇴역 완료",
    UNKNOWN: "상태 미확인",
  },
  verification: {
    "hardware-verified": "실기기 검증 완료",
    "template-verified": "템플릿 검증 완료",
    unverified: "미검증",
  },
  nodeHealth: {
    available: "정상",
    healthy: "정상",
    degraded: "주의",
    unavailable: "연결 안 됨",
    unknown: "상태 미확인",
  },
  protocolField: {
    Port: "디바이스 경로",
    BaudRate: "통신 속도",
    DeviceID: "물리 소스 ID",
    ResourceName: "시리얼 리소스",
    Bus: "I2C 버스",
    ResourceGroup: "센서 리소스 그룹",
    Broker: "브로커 주소",
    Password: "비밀번호",
  },
  protocol: {
    serial: "Serial / USB",
    i2c: "I²C",
    modbus: "Modbus",
    opcua: "OPC-UA",
    mqtt: "MQTT",
    rtsp: "RTSP",
  },
  issue: {
    reserved_tag: "시스템 관리 태그는 직접 지정할 수 없습니다.",
    system_tag_mismatch: "선택한 노드 또는 물리 소스 정보가 승인된 연결과 다릅니다.",
    adapter_unavailable: "선택한 어댑터를 현재 사용할 수 없습니다.",
    device_exists: "같은 이름의 디바이스가 이미 등록되어 있습니다.",
    protocol_binding_exists: "같은 물리 연결과 리소스가 이미 다른 디바이스에 연결되어 있습니다.",
    profile_template_unavailable: "선택한 리소스에 사용할 프로필 템플릿이 없습니다.",
    profile_missing: "선택한 기존 프로필을 찾을 수 없습니다.",
    profile_incompatible: "선택한 프로필이 어댑터 리소스와 호환되지 않습니다.",
    profile_exists: "같은 이름의 프로필이 이미 등록되어 있습니다.",
    device_missing: "수정할 디바이스를 찾을 수 없습니다.",
    unknown_adapter: "승인 카탈로그에 없는 어댑터입니다.",
    template_unverified: "런타임 템플릿이 검증되지 않았습니다.",
    hardware_binding_not_allowed: "승인되지 않은 하드웨어 연결입니다.",
    hardware_binding_mismatch: "선택한 연결과 프로토콜 값이 일치하지 않습니다.",
    hardware_binding_immutable: "기존 디바이스의 물리 연결은 수정할 수 없습니다.",
    node_not_allowed: "해당 노드에 허용되지 않은 어댑터입니다.",
    node_not_ready: "대상 노드가 준비되지 않았습니다.",
    runtime_not_ready: "기존 런타임이 아직 준비되지 않았습니다.",
    hardware_binding_in_use: "하드웨어 연결을 다른 런타임이 사용 중입니다.",
    runtime_not_found: "재사용할 런타임을 찾을 수 없습니다.",
    template_not_deployable: "현재 배포할 수 없는 런타임 템플릿입니다.",
  },
  mutation: {
    create_profile: "프로필 생성",
    create_device: "디바이스 생성",
    profile_readback: "프로필 재조회",
    device_readback: "디바이스 재조회",
    first_event: "첫 이벤트 확인",
  },
};


function managementDeviceNode(device = {}) {
  return device.node_name
    || device.nodeName
    || device.tags?.nodeName
    || UNASSIGNED_NODE;
}


function managementDevicePhysicalId(device = {}) {
  return device.physical_device_id
    || device.physicalDeviceId
    || device.tags?.physicalDeviceId
    || "";
}


function managementDeviceBindingId(device = {}) {
  return device.hardware_binding_id
    || device.hardwareBindingId
    || device.tags?.hardwareBindingId
    || "";
}


function runtimeOwnsBinding(runtime = {}, bindingId = "") {
  const bindingIds = runtime.hardwareBindingIds
    || runtime.hardware_binding_ids
    || [];
  const primary = runtime.hardwareBindingId || runtime.hardware_binding_id;
  return Boolean(
    bindingId
    && (
      bindingIds.includes(bindingId)
      || primary === bindingId
    )
  );
}


function protocolPackageStatus(adapter, nodeName, _runtimes = []) {
  if (!adapter || adapter.status === "unsupported"
    || adapter.runtime?.verificationState === "unverified") {
    return {
      state: "verification_required",
      action: "none",
      label: "검증 필요",
      reason: adapter?.reason || "Device Service와 실장비 검증이 필요합니다.",
    };
  }
  const bindings = (adapter.runtime?.hardwareBindings || []).filter(
    (binding) => binding.nodeName === nodeName,
  );
  if (!bindings.length) {
    return {
      state: "connection_required",
      action: "none",
      label: "연결 등록 필요",
      reason: "이 노드에 등록된 물리 연결이 없습니다.",
    };
  }
  if (
    adapter.status === "installable"
    && adapter.runtime?.deploymentEnabled === true
  ) {
    return {
      state: "install_ready",
      action: "install",
      label: "설치 가능",
      reason: "검증된 Device Service 패키지를 이 노드에 설치할 수 있습니다.",
    };
  }
  if (adapter.status === "installed") {
    return {
      state: "reuse_ready",
      action: "reuse",
      label: "재사용 가능",
      reason: "등록된 Device Service와 물리 연결을 재사용합니다.",
    };
  }
  return {
    state: "unavailable",
    action: "none",
    label: "사용 불가",
    reason: adapter.reason || "Device Service 상태를 확인해야 합니다.",
  };
}


function buildPhysicalConnectionObservations({
  adapters = [],
  runtimes = [],
  devices = [],
  nodeName = "",
} = {}) {
  const observations = [];
  adapters.forEach((adapter) => {
    const bindings = (adapter.runtime?.hardwareBindings || []).filter(
      (binding) => binding.nodeName === nodeName,
    );
    bindings.forEach((binding) => {
      const runtime = runtimes.find((candidate) => (
        (candidate.targetNode || candidate.target_node) === nodeName
        && (
          candidate.adapterId === adapter.adapterId
          || candidate.adapter_id === adapter.adapterId
        )
        && runtimeOwnsBinding(candidate, binding.bindingId)
      )) || null;
      const serviceNames = new Set(
        [adapter.serviceName, runtime?.serviceName, runtime?.service_name]
          .filter(Boolean),
      );
      const expectedPhysicalId = binding.protocolProperties?.DeviceID || "";
      const adapterBindingCount = bindings.length;
      const matchingDevices = devices.filter((device) => {
        if (managementDeviceNode(device) !== nodeName) return false;
        const serviceName = device.device_service_name || device.deviceServiceName;
        if (serviceNames.size && !serviceNames.has(serviceName)) return false;
        const protocols = device.protocol_names || device.protocolNames || [];
        if (
          adapter.protocolName
          && !protocols.some(
            (protocol) => String(protocol).toLowerCase()
              === String(adapter.protocolName).toLowerCase(),
          )
        ) return false;
        const exactBindingId = managementDeviceBindingId(device);
        if (exactBindingId) return exactBindingId === binding.bindingId;
        const physicalId = managementDevicePhysicalId(device);
        if (expectedPhysicalId) return physicalId === expectedPhysicalId;
        return adapterBindingCount === 1;
      });
      const connectedDevices = matchingDevices.filter((device) => (
        String(device.admin_state || device.adminState || "").toUpperCase() !== "LOCKED"
        && String(
          device.operating_state || device.operatingState || "",
        ).toUpperCase() === "UP"
      ));
      const disconnectedDevices = matchingDevices.filter((device) => (
        String(device.admin_state || device.adminState || "").toUpperCase() === "LOCKED"
        || String(
          device.operating_state || device.operatingState || "",
        ).toUpperCase() === "DOWN"
      ));
      const freshDevices = matchingDevices.filter(
        (device) => (device.telemetry_freshness || device.telemetryFreshness) === "fresh",
      );
      const staleDevices = matchingDevices.filter(
        (device) => (device.telemetry_freshness || device.telemetryFreshness) === "stale",
      );
      const runtimeState = runtime?.phase === "SERVICE_READY"
        && runtime.edgeXServiceObserved !== false
        ? "ready"
        : runtime
          ? "not_ready"
          : "not_installed";
      const communicationState = connectedDevices.length
        ? "connected"
        : matchingDevices.length && disconnectedDevices.length === matchingDevices.length
          ? "disconnected"
          : "unknown";
      const telemetryState = freshDevices.length
        ? "fresh"
        : staleDevices.length
          ? "stale"
          : matchingDevices.length
            ? "missing"
            : "unknown";
      const presenceState = freshDevices.length
        || (runtimeState === "ready" && connectedDevices.length)
        ? "detected"
        : matchingDevices.length
          && disconnectedDevices.length === matchingDevices.length
          ? "not_detected"
          : "unknown";
      const timestamps = matchingDevices
        .map((device) => (
          device.latest_event_timestamp || device.latestEventTimestamp || ""
        ))
        .filter(Boolean)
        .sort();
      let reason = "등록되어 있지만 실제 장비 관측 증거가 없습니다.";
      if (
        presenceState === "detected"
        && communicationState === "connected"
        && telemetryState === "fresh"
      ) {
        reason = "Device Service 연결과 최신 Event가 모두 확인됐습니다.";
      } else if (presenceState === "detected" && telemetryState !== "fresh") {
        reason = "Device Service 통신은 확인됐지만 최신 Event를 확인해야 합니다.";
      } else if (presenceState === "not_detected") {
        reason = "EdgeX Device가 DOWN 또는 LOCKED 상태여서 물리 연결을 관측하지 못했습니다.";
      } else if (runtimeState === "not_ready") {
        reason = "Device Service가 준비되지 않아 장비 관측을 완료할 수 없습니다.";
      }
      observations.push({
        adapterId: adapter.adapterId,
        adapterName: adapter.displayName || adapter.adapterId,
        protocolName: adapter.protocolName,
        serviceName: runtime?.serviceName || runtime?.service_name || adapter.serviceName || "",
        bindingId: binding.bindingId,
        bindingName: binding.displayName,
        nodeName: binding.nodeName,
        devicePath: binding.devicePath || "",
        physicalDeviceId: expectedPhysicalId,
        registrationState: "registered",
        runtimeState,
        runtimeName: runtime?.runtimeName || runtime?.runtime_name || "",
        presenceState,
        communicationState,
        telemetryState,
        deviceCount: matchingDevices.length,
        deviceNames: matchingDevices.map((device) => device.name).sort(),
        latestEventTimestamp: timestamps.at(-1) || null,
        reason,
      });
    });
  });
  return observations.sort((left, right) => (
    left.protocolName.localeCompare(right.protocolName)
    || left.bindingName.localeCompare(right.bindingName)
  ));
}


function adapterSupportsNode(adapter, nodeName) {
  if (
    !adapter
    || !["installed", "installable"].includes(adapter.status)
    || !nodeName
  ) return false;
  const bindings = adapter.runtime?.hardwareBindings || [];
  if (bindings.some((binding) => binding.nodeName === nodeName)) return true;
  return bindings.length === 0 && adapter.nodeName === nodeName;
}


function adapterSelectionOptions(adapters = [], nodeName = "") {
  return adapters
    .map((adapter, index) => {
      const enabled = adapterSupportsNode(adapter, nodeName);
      let availability = adapter?.status === "installable"
        ? "검증된 Device Service 설치"
        : "기존 Device Service 재사용";
      if (!enabled && adapter?.status === "unsupported") {
        availability = "지원 준비 필요";
      } else if (!enabled && adapter?.status === "unavailable") {
        availability = "Device Service 확인 필요";
      } else if (!enabled) {
        availability = "다른 노드에만 연결 등록됨";
      }
      return {
        adapter,
        enabled,
        availability,
        reason: enabled
          ? ""
          : adapter?.reason || (
            availability === "다른 노드에만 연결 등록됨"
              ? `${nodeName || "선택 노드"}에 등록된 물리 연결이 없습니다.`
              : availability
          ),
        index,
      };
    })
    .sort((left, right) => {
      if (left.enabled !== right.enabled) return left.enabled ? -1 : 1;
      return left.index - right.index;
    });
}


function bindingProtocolValue(field = {}, binding = {}) {
  const bindingProperties = binding?.protocolProperties || {};
  if (Object.prototype.hasOwnProperty.call(bindingProperties, field.name)) {
    return {value: bindingProperties[field.name], locked: true};
  }
  return {
    value: field.const ?? field.default,
    locked: field.const !== null && field.const !== undefined,
  };
}


function adapterConnectionGuidance(adapter, bindingCount = 0) {
  if (!adapter) {
    return {
      title: "프로토콜을 먼저 선택하세요",
      text: "선택한 노드에서 검증된 Device Service와 등록된 물리 연결만 사용할 수 있습니다.",
      status: "unavailable",
    };
  }
  if (adapter.status === "installable") {
    return {
      title: `${koreanLabel("protocol", adapter.protocolName, adapter.protocolName)} Device Service 설치`,
      text: `검증된 패키지를 대상 노드에 배포한 뒤 등록된 물리 연결 ${bindingCount}개 중 하나를 `
        + "EdgeX Device로 연결합니다. 설치 전에 임의 이미지나 장치 경로를 입력할 수 없습니다.",
      status: "installable",
    };
  }
  if (adapter.status !== "installed") {
    return {
      title: `${koreanLabel("protocol", adapter.protocolName, adapter.protocolName)} 연결 준비 필요`,
      text: adapter.reason || "Device Service와 실장비 연결을 검증한 뒤 활성화할 수 있습니다.",
      status: adapter.status || "unavailable",
    };
  }
  const policy = adapter.runtime?.reusePolicy || {};
  if (adapter.protocolName === "serial" && policy.multiDevice === true) {
    return {
      title: "Serial 다중 연결 방식",
      text: `현재 등록 연결 ${bindingCount}개. 같은 USB 포트의 다른 리소스는 기존 reader와 `
        + "Device Service를 공유합니다. 두 번째 USB Serial이 같은 데이터 포맷과 리소스 계약이면 "
        + "고정 장치 경로를 Git 카탈로그와 Pod 장치 마운트에 추가해 같은 Device Service에서 "
        + "별도 reader로 처리합니다. 포맷이 다르면 parser와 Adapter 검증이 먼저 필요합니다.",
      status: "installed",
    };
  }
  if (policy.multiDevice === true) {
    return {
      title: "한 Device Service에서 여러 디바이스 처리",
      text: `현재 등록 연결 ${bindingCount}개. 등록된 물리 연결과 리소스를 선택하면 `
        + `${adapter.serviceName}가 여러 EdgeX Device를 함께 관리합니다.`,
      status: "installed",
    };
  }
  return {
    title: "Device Service 연결 방식",
    text: "선택한 물리 연결 전용 Device Service를 사용합니다.",
    status: "installed",
  };
}


function buildManagementNodeScopes({
  nodes = [],
  runtimes = [],
  devices = [],
  adapters = [],
} = {}) {
  const scopes = new Map();
  const eligibleNodes = new Set();
  const ensure = (name) => {
    const safeName = name || UNASSIGNED_NODE;
    if (!scopes.has(safeName)) {
      scopes.set(safeName, {
        name: safeName,
        health: "unknown",
        observed: false,
        runtimeCount: 0,
        deviceCount: 0,
        adapterCount: 0,
      });
    }
    return scopes.get(safeName);
  };

  nodes.forEach((node) => {
    const name = node.hostname || node.name || node.node_name;
    if (!name) return;
    const scope = ensure(name);
    scope.observed = true;
    scope.health = node.node_health || node.nodeHealth || "unknown";
    const nodeType = node.node_type || node.nodeType;
    if (!nodeType || String(nodeType).startsWith("edge_")) {
      eligibleNodes.add(name);
    }
  });
  runtimes.forEach((runtime) => {
    const nodeName = runtime.targetNode || runtime.target_node;
    ensure(nodeName).runtimeCount += 1;
    eligibleNodes.add(nodeName || UNASSIGNED_NODE);
  });
  devices.forEach((device) => {
    const nodeName = managementDeviceNode(device);
    ensure(nodeName).deviceCount += 1;
    eligibleNodes.add(nodeName);
  });
  adapters.forEach((adapter) => {
    const bindingNodes = new Set(
      (adapter.runtime?.hardwareBindings || [])
        .map((binding) => binding.nodeName)
        .filter(Boolean),
    );
    if (!bindingNodes.size && adapter.nodeName) bindingNodes.add(adapter.nodeName);
    bindingNodes.forEach((nodeName) => {
      ensure(nodeName).adapterCount += 1;
      eligibleNodes.add(nodeName);
    });
  });

  return [...scopes.values()]
    .filter((scope) => eligibleNodes.has(scope.name))
    .sort((left, right) => {
    if (left.name === UNASSIGNED_NODE) return 1;
    if (right.name === UNASSIGNED_NODE) return -1;
    return left.name.localeCompare(right.name);
    });
}


function koreanLabel(group, value, fallback = "알 수 없음") {
  return MANAGEMENT_LABELS[group]?.[value] || fallback;
}


function managementIssueText(issue = {}) {
  const translated = MANAGEMENT_LABELS.issue[issue.code];
  return translated || issue.message || "요청 내용을 확인하세요.";
}


function adapterCanApply(adapter) {
  return Boolean(
    adapter
    && ["installed", "installable"].includes(adapter.status)
    && adapter.mutationEnabled === true,
  );
}


function canPatchSelectedDevice(mutationEnabled, selectedDeviceName) {
  return Boolean(mutationEnabled && selectedDeviceName);
}


function normalizeManagementView(view) {
  return ["overview", "register", "edit"].includes(view) ? view : "overview";
}


function normalizeRegistrationStep(step) {
  const parsed = Number(step);
  return Number.isInteger(parsed) && parsed >= 1 && parsed <= 4 ? parsed : 1;
}


function managementTabIndexForKey(key, currentIndex, tabCount) {
  if (
    !Number.isInteger(currentIndex)
    || currentIndex < 0
    || !Number.isInteger(tabCount)
    || tabCount < 1
    || currentIndex >= tabCount
  ) return null;
  if (key === "Home") return 0;
  if (key === "End") return tabCount - 1;
  if (key === "ArrowRight" || key === "ArrowDown") {
    return (currentIndex + 1) % tabCount;
  }
  if (key === "ArrowLeft" || key === "ArrowUp") {
    return (currentIndex - 1 + tabCount) % tabCount;
  }
  return null;
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


async function fetchManagementNodes(fetchFn = fetch) {
  const response = await fetchFn(MANAGEMENT_NODES_URL, {cache: "no-store"});
  const payload = await managementPayload(response);
  if (!Array.isArray(payload)) throw new Error("node inventory response must be an array");
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
      label: "검증 완료",
      tone: "verified",
      detail: "EdgeX 메타데이터 적용 · 첫 Core Data 이벤트 검증 완료",
      terminal: true,
    };
  }
  if (operation.status === "failed") {
    return {
      label: "실패",
      tone: "failed",
      detail: operation.error || "EdgeX 메타데이터 적용 또는 재조회 실패",
      terminal: true,
    };
  }
  if (operation.status === "metadata_applied") {
    return {
      label: "메타데이터 적용 완료",
      tone: "applied",
      detail: "EdgeX 프로필과 디바이스 재조회 완료",
      terminal: false,
    };
  }
  return {
    label: "첫 이벤트 대기",
    tone: "waiting",
    detail: operation.error || "EdgeX 메타데이터 적용 완료 · 첫 Core Data 이벤트 대기",
    terminal: false,
  };
}


function connectionStatusView(operation = {}) {
  const status = String(operation.status || "PLANNED");
  const views = {
    PLANNED: {
      label: "실행 계획 준비",
      tone: "applied",
      detail: "검증된 실행 계획을 준비했습니다.",
      terminal: false,
    },
    RUNTIME_REQUESTED: {
      label: "런타임 요청 완료",
      tone: "waiting",
      detail: "어댑터 런타임 배포와 EdgeX Device Service 등록 대기",
      terminal: false,
    },
    RUNTIME_READY: {
      label: "런타임 준비 완료",
      tone: "applied",
      detail: "어댑터 런타임과 EdgeX Device Service 재조회 완료",
      terminal: false,
    },
    PROFILE_APPLIED: {
      label: "프로필 적용 완료",
      tone: "applied",
      detail: "EdgeX 디바이스 프로필 적용 완료",
      terminal: false,
    },
    DEVICE_APPLIED: {
      label: "디바이스 적용 완료",
      tone: "applied",
      detail: "EdgeX 디바이스 연결 재조회 완료",
      terminal: false,
    },
    WAITING_EVENT: {
      label: "첫 이벤트 대기",
      tone: "waiting",
      detail: "메타데이터 적용 완료 · 첫 Core Data 이벤트 대기",
      terminal: false,
    },
    ACTIVE: {
      label: "연결 활성화",
      tone: "verified",
      detail: "런타임 · 메타데이터 · 첫 이벤트 검증 완료",
      terminal: true,
    },
    COMPENSATING: {
      label: "실패 보상 중",
      tone: "waiting",
      detail: "실패한 신규 런타임을 안전하게 퇴역하는 중",
      terminal: false,
    },
    COMPENSATED: {
      label: "실패 보상 완료",
      tone: "failed",
      detail: operation.compensationStatus || "실패 보상 완료",
      terminal: true,
    },
    FAILED: {
      label: "연결 실패",
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


function renderManagementView(documentRef = document) {
  const activeView = normalizeManagementView(managementState.activeView);
  managementState.activeView = activeView;
  documentRef.querySelectorAll?.("[data-management-view]").forEach((button) => {
    const selected = button.dataset.managementView === activeView;
    button.setAttribute("aria-selected", String(selected));
    button.tabIndex = selected ? 0 : -1;
  });
  documentRef.querySelectorAll?.("[data-management-view-panel]").forEach((panel) => {
    const selected = panel.dataset.managementViewPanel === activeView;
    panel.hidden = !selected;
    panel.setAttribute("aria-hidden", String(!selected));
  });
}


function setManagementView(view, documentRef = document) {
  managementState.activeView = normalizeManagementView(view);
  renderManagementView(documentRef);
}


function renderRegistrationReview(documentRef = document) {
  const adapter = selectedAdapter();
  const binding = byId("managementHardwareBinding", documentRef)?.selectedOptions?.[0];
  const deviceName = byId("managementDeviceName", documentRef)?.value.trim() || "이름 입력 전";
  const profileName = byId("managementProfileName", documentRef)?.value.trim() || "프로필 선택 전";
  const values = {
    managementReviewNode: managementState.selectedNodeName || "노드 선택 전",
    managementReviewAdapter: adapter?.displayName || "어댑터 선택 전",
    managementReviewBinding: binding?.textContent || "물리 연결 선택 전",
    managementReviewDevice: `${deviceName} / ${profileName}`,
  };
  Object.entries(values).forEach(([id, value]) => {
    const element = byId(id, documentRef);
    if (element) element.textContent = value;
  });
}


function renderRegistrationStep(documentRef = document) {
  const activeStep = normalizeRegistrationStep(managementState.registrationStep);
  managementState.registrationStep = activeStep;
  documentRef.querySelectorAll?.("[data-management-step]").forEach((button) => {
    const step = normalizeRegistrationStep(button.dataset.managementStep);
    const selected = step === activeStep;
    button.dataset.state = step < activeStep ? "complete" : selected ? "current" : "upcoming";
    if (selected) button.setAttribute("aria-current", "step");
    else button.removeAttribute("aria-current");
  });
  documentRef.querySelectorAll?.("[data-management-step-panel]").forEach((panel) => {
    const selected = Number(panel.dataset.managementStepPanel) === activeStep;
    panel.hidden = !selected;
    panel.setAttribute("aria-hidden", String(!selected));
  });
  if (activeStep === 4) renderRegistrationReview(documentRef);
}


function setRegistrationStep(step, documentRef = document) {
  managementState.registrationStep = normalizeRegistrationStep(step);
  renderRegistrationStep(documentRef);
}


function appendTextElement(parent, tagName, className, text) {
  const element = parent.ownerDocument.createElement(tagName);
  if (className) element.className = className;
  element.textContent = text;
  parent.appendChild(element);
  return element;
}


function managementNodeScopes() {
  return buildManagementNodeScopes(managementState);
}


function ensureSelectedAdapterForNode() {
  const compatible = adapterSelectionOptions(
    managementState.adapters,
    managementState.selectedNodeName,
  )
    .filter((option) => option.enabled)
    .map((option) => option.adapter);
  if (!compatible.some((adapter) => adapter.adapterId === managementState.selectedAdapterId)) {
    managementState.selectedAdapterId = compatible[0]?.adapterId || "";
  }
  return compatible;
}


function renderManagementNodes(documentRef = document) {
  const container = byId("managementNodeList", documentRef);
  const selected = byId("managementSelectedNode", documentRef);
  clearElement(container);
  const scopes = managementNodeScopes();
  if (!managementState.selectedNodeName && scopes.length) {
    managementState.selectedNodeName = (
      scopes.find((scope) => scope.runtimeCount > 0)
      || scopes.find((scope) => scope.adapterCount > 0)
      || scopes[0]
    ).name;
  }
  if (selected) {
    selected.textContent = managementState.selectedNodeName
      ? `선택 노드: ${managementState.selectedNodeName}`
        + (managementState.nodeLoadError ? " · Kubernetes 상태 조회 실패" : "")
      : "선택된 노드 없음";
  }
  if (!container) return;
  if (!scopes.length) {
    appendTextElement(container, "p", "management-empty", "관리 가능한 노드가 없습니다.");
    return;
  }

  scopes.forEach((scope) => {
    const button = documentRef.createElement("button");
    button.type = "button";
    button.className = "management-node-card";
    button.dataset.managementNode = scope.name;
    button.dataset.health = scope.health;
    const isSelected = scope.name === managementState.selectedNodeName;
    button.dataset.selected = String(isSelected);
    button.setAttribute("aria-pressed", String(isSelected));

    const heading = documentRef.createElement("span");
    heading.className = "management-node-card-head";
    appendTextElement(heading, "strong", "", scope.name);
    appendTextElement(
      heading,
      "small",
      "management-node-health",
      scope.observed
        ? koreanLabel("nodeHealth", scope.health)
        : "Kubernetes 상태 미관측",
    );
    const facts = documentRef.createElement("span");
    facts.className = "management-node-card-facts";
    appendTextElement(facts, "span", "", `런타임 ${scope.runtimeCount}개`);
    appendTextElement(facts, "span", "", `디바이스 ${scope.deviceCount}개`);
    appendTextElement(facts, "span", "", `프로토콜 ${scope.adapterCount}개`);
    button.append(heading, facts);
    container.appendChild(button);
  });
}


function renderAdapterOptions(documentRef = document) {
  const select = byId("managementAdapter", documentRef);
  clearElement(select);
  const compatible = ensureSelectedAdapterForNode();
  const options = adapterSelectionOptions(
    managementState.adapters,
    managementState.selectedNodeName,
  );
  if (!compatible.length) {
    const option = documentRef.createElement("option");
    option.value = "";
    option.textContent = "현재 연결 가능한 프로토콜이 없습니다";
    select?.appendChild(option);
  }
  if (select) select.disabled = options.length === 0;
  const enabledGroup = documentRef.createElement("optgroup");
  enabledGroup.label = "현재 연결 가능";
  const pendingGroup = documentRef.createElement("optgroup");
  pendingGroup.label = "준비 필요 · 선택 불가";
  options.forEach(({adapter, enabled, availability, reason}) => {
    const option = documentRef.createElement("option");
    option.value = adapter.adapterId;
    option.textContent = `${koreanLabel(
      "protocol",
      adapter.protocolName,
      adapter.protocolName,
    )} · ${adapter.displayName} · ${availability}`;
    option.selected = enabled && adapter.adapterId === managementState.selectedAdapterId;
    option.disabled = !enabled;
    if (reason) option.title = reason;
    (enabled ? enabledGroup : pendingGroup).appendChild(option);
  });
  if (enabledGroup.children.length) select?.appendChild(enabledGroup);
  if (pendingGroup.children.length) select?.appendChild(pendingGroup);
}


function selectedHardwareBinding(documentRef = document) {
  const adapter = selectedAdapter();
  const bindingId = byId("managementHardwareBinding", documentRef)?.value;
  return (adapter?.runtime?.hardwareBindings || []).find(
    (binding) => binding.bindingId === bindingId,
  ) || null;
}


function renderConnectionGuidance(documentRef = document) {
  const container = byId("managementConnectionGuidance", documentRef);
  clearElement(container);
  if (!container) return;
  const adapter = selectedAdapter();
  const bindingCount = (adapter?.runtime?.hardwareBindings || []).filter(
    (binding) => binding.nodeName === managementState.selectedNodeName,
  ).length;
  const guidance = adapterConnectionGuidance(adapter, bindingCount);
  container.dataset.status = guidance.status;
  appendTextElement(container, "strong", "", guidance.title);
  appendTextElement(container, "p", "", guidance.text);
}


function formatManagementTimestamp(value) {
  if (!value) return "확인되지 않음";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("ko-KR", {
    timeZone: "Asia/Seoul",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  });
}


function renderPhysicalConnections(documentRef = document) {
  const container = byId("managementPhysicalConnectionList", documentRef);
  clearElement(container);
  if (!container) return;
  const observations = buildPhysicalConnectionObservations({
    adapters: managementState.adapters,
    runtimes: managementState.runtimes,
    devices: managementState.devices,
    nodeName: managementState.selectedNodeName,
  });
  if (!observations.length) {
    appendTextElement(
      container,
      "p",
      "management-empty",
      "이 노드의 Git 카탈로그에 등록된 물리 연결이 없습니다. 장비 자동 검색 결과가 아니라 등록 현황입니다.",
    );
    return;
  }
  observations.forEach((observation) => {
    const card = documentRef.createElement("article");
    card.className = "management-physical-card";
    card.dataset.presence = observation.presenceState;
    card.dataset.communication = observation.communicationState;
    card.dataset.telemetry = observation.telemetryState;

    const header = documentRef.createElement("div");
    header.className = "management-physical-head";
    const identity = documentRef.createElement("div");
    appendTextElement(
      identity,
      "strong",
      "",
      observation.bindingName || observation.bindingId,
    );
    appendTextElement(
      identity,
      "small",
      "",
      `${observation.adapterName} · ${observation.serviceName || "Device Service 미확인"}`,
    );
    appendTextElement(
      header,
      "span",
      "management-protocol-pill",
      koreanLabel("protocol", observation.protocolName, observation.protocolName),
    );
    header.prepend(identity);

    const evidence = documentRef.createElement("div");
    evidence.className = "management-evidence-grid";
    [
      {
        label: "연결 등록",
        state: observation.registrationState,
        value: "등록됨",
      },
      {
        label: "장비 관측",
        state: observation.presenceState,
        value: koreanLabel("presence", observation.presenceState),
      },
      {
        label: "통신 상태",
        state: observation.communicationState,
        value: koreanLabel("communication", observation.communicationState),
      },
      {
        label: "데이터 상태",
        state: observation.telemetryState,
        value: koreanLabel("telemetry", observation.telemetryState),
      },
    ].forEach((item) => {
      const cell = documentRef.createElement("div");
      cell.className = "management-evidence-cell";
      cell.dataset.state = item.state;
      appendTextElement(cell, "span", "", item.label);
      appendTextElement(cell, "strong", "", item.value);
      evidence.appendChild(cell);
    });

    const facts = documentRef.createElement("div");
    facts.className = "management-physical-facts";
    [
      `연결 ID ${observation.bindingId}`,
      observation.devicePath ? `장치 경로 ${observation.devicePath}` : "",
      observation.physicalDeviceId ? `물리 소스 ${observation.physicalDeviceId}` : "",
      `${koreanLabel("runtimeState", observation.runtimeState)}`
        + (observation.runtimeName ? ` · ${observation.runtimeName}` : ""),
      `EdgeX Device ${observation.deviceCount}개`,
    ].filter(Boolean).forEach((fact) => appendTextElement(facts, "span", "", fact));

    appendTextElement(card, "p", "management-physical-reason", observation.reason);
    appendTextElement(
      card,
      "small",
      "management-physical-latest",
      observation.deviceNames.length
        ? `연결 디바이스 ${observation.deviceNames.join(", ")} · 최신 Event `
          + formatManagementTimestamp(observation.latestEventTimestamp)
        : "연결된 EdgeX Device와 Event가 아직 없습니다.",
    );
    card.prepend(header, evidence, facts);
    container.appendChild(card);
  });
}


function renderAdapterCatalog(documentRef = document) {
  const container = byId("managementAdapterList", documentRef);
  const unsupportedContainer = byId("managementUnsupportedAdapterList", documentRef);
  clearElement(container);
  clearElement(unsupportedContainer);
  let primaryCount = 0;
  let secondaryCount = 0;
  managementState.adapters.forEach((adapter) => {
    const packageStatus = protocolPackageStatus(
      adapter,
      managementState.selectedNodeName,
      managementState.runtimes,
    );
    const card = documentRef.createElement("article");
    card.className = "management-adapter-card";
    card.dataset.status = packageStatus.state;
    const header = documentRef.createElement("div");
    header.className = "management-adapter-card-head";
    appendTextElement(header, "strong", "", adapter.displayName || adapter.adapterId);
    appendTextElement(
      header,
      "span",
      "management-status",
      packageStatus.label,
    );
    appendTextElement(
      card,
      "small",
      "",
      adapter.serviceName
        ? `${koreanLabel("protocol", adapter.protocolName, adapter.protocolName)} · ${adapter.serviceName}`
        : koreanLabel("protocol", adapter.protocolName, adapter.protocolName),
    );
    appendTextElement(card, "p", "management-adapter-reason", packageStatus.reason);
    const verification = adapter.runtime?.verificationState || "unverified";
    appendTextElement(
      card,
      "small",
      "management-adapter-verification",
      `${koreanLabel("verification", verification)} · `
        + `${(adapter.runtime?.hardwareBindings || []).filter(
          (binding) => binding.nodeName === managementState.selectedNodeName,
        ).length}개 물리 연결 등록`,
    );
    if (packageStatus.action !== "none") {
      const action = documentRef.createElement("button");
      action.type = "button";
      action.className = "management-adapter-action";
      action.dataset.managementSelectAdapter = adapter.adapterId;
      action.textContent = packageStatus.action === "install"
        ? "설치하고 디바이스 등록"
        : "이 프로토콜로 디바이스 등록";
      card.appendChild(action);
    }
    card.prepend(header);
    if (packageStatus.action === "none") {
      secondaryCount += 1;
      unsupportedContainer?.appendChild(card);
    } else {
      primaryCount += 1;
      container?.appendChild(card);
    }
  });
  if (!primaryCount && container) {
    appendTextElement(
      container,
      "p",
      "management-empty",
      "선택한 노드에서 즉시 설치하거나 재사용할 수 있는 검증 패키지가 없습니다.",
    );
  }
  if (!secondaryCount && unsupportedContainer) {
    appendTextElement(
      unsupportedContainer,
      "p",
      "management-empty",
      "추가 확인이 필요한 프로토콜이 없습니다.",
    );
  }
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
      `어댑터 런타임 상태를 읽지 못했습니다: ${managementState.runtimeLoadError.message}`,
    );
    return;
  }
  const runtimes = managementState.runtimes.filter(
    (runtime) => (runtime.targetNode || runtime.target_node) === managementState.selectedNodeName,
  );
  if (!runtimes.length) {
    appendTextElement(
      container,
      "p",
      "management-empty",
      "선택한 노드에서 관측된 어댑터 런타임이 없습니다.",
    );
    return;
  }
  runtimes.forEach((runtime) => {
    const card = documentRef.createElement("article");
    card.className = "management-runtime-card";
    card.dataset.phase = runtime.phase || "UNKNOWN";

    const header = documentRef.createElement("div");
    header.className = "management-runtime-card-header";
    appendTextElement(
      header,
      "strong",
      "",
      runtime.runtimeName || runtime.serviceName || "이름 미확인 런타임",
    );
    appendTextElement(
      header,
      "span",
      "management-status",
      koreanLabel("runtimePhase", runtime.phase || "UNKNOWN"),
    );

    const service = runtime.edgeXServiceObserved === false
      ? `${runtime.serviceName} · EdgeX 등록 미확인`
      : `${runtime.serviceName} · EdgeX 등록 확인`;
    appendTextElement(card, "small", "", service);

    const facts = documentRef.createElement("div");
    facts.className = "management-runtime-facts";
    [
      `노드 ${runtime.targetNode || "미확인"}`,
      `${runtime.managementOwner === "argocd" ? "Argo CD" : "컨트롤러"} 소유`,
      koreanLabel("verification", runtime.verificationState || "unverified"),
      `등록 물리 연결 ${Number(
        runtime.hardwareBindingIds?.length
          || runtime.hardware_binding_ids?.length
          || (runtime.hardwareBindingId || runtime.hardware_binding_id ? 1 : 0),
      )}개`,
      `연결 디바이스 ${Number(runtime.consumers || 0)}개`,
    ].forEach((fact) => appendTextElement(facts, "span", "", fact));

    const actions = documentRef.createElement("div");
    actions.className = "management-runtime-actions";
    const mutable = runtimeCanMutate(runtime);
    const restart = documentRef.createElement("button");
    restart.type = "button";
    restart.textContent = "재시작";
    restart.dataset.runtimeAction = "restart";
    restart.dataset.runtimeName = runtime.runtimeName;
    restart.disabled = !mutable;
    restart.title = mutable
      ? "컨트롤러 소유 런타임을 재시작합니다."
      : "외부/Argo CD 소유 런타임은 대시보드에서 변경할 수 없습니다.";
    const retire = documentRef.createElement("button");
    retire.type = "button";
    retire.textContent = "퇴역";
    retire.dataset.runtimeAction = "retire";
    retire.dataset.runtimeName = runtime.runtimeName;
    retire.disabled = !mutable || Number(runtime.consumers || 0) > 0;
    retire.title = Number(runtime.consumers || 0) > 0
      ? "연결된 EdgeX 디바이스가 있어 퇴역할 수 없습니다."
      : restart.title;
    actions.append(restart, retire);

    card.prepend(header);
    card.append(facts, actions);
    container.appendChild(card);
  });
}


function renderManagedDevices(documentRef = document) {
  const container = byId("managedDeviceList", documentRef);
  const selector = byId("managementPatchDeviceSelect", documentRef);
  clearElement(container);
  clearElement(selector);
  if (selector) {
    const placeholder = documentRef.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "디바이스를 선택하세요";
    selector.appendChild(placeholder);
  }
  const devices = managementState.devices.filter(
    (device) => managementDeviceNode(device) === managementState.selectedNodeName,
  );
  if (!devices.length) {
    if (container) {
      appendTextElement(
        container,
        "p",
        "management-empty",
        "선택한 노드에 등록된 EdgeX 디바이스가 없습니다.",
      );
    }
    return;
  }
  devices.forEach((device) => {
    if (selector) {
      const option = documentRef.createElement("option");
      option.value = device.name;
      option.textContent = device.name;
      option.selected = device.name === managementState.selectedPatchDeviceName;
      selector.appendChild(option);
    }
    const row = documentRef.createElement("article");
    row.className = "managed-device-row";
    const identity = documentRef.createElement("div");
    appendTextElement(identity, "strong", "", device.name || "이름 미확인 디바이스");
    appendTextElement(
      identity,
      "small",
      "",
      `${device.profile_name || "프로필 미확인"} · ${device.device_service_name || "서비스 미확인"}`,
    );
    appendTextElement(
      identity,
      "small",
      "",
      `관리 상태 ${device.admin_state === "LOCKED" ? "잠김" : "잠금 해제"}`
        + ` · 동작 상태 ${device.operating_state === "UP" ? "정상" : device.operating_state || "미확인"}`
        + ` · 이벤트 ${{
          fresh: "최신",
          stale: "지연",
          no_events: "없음",
        }[device.telemetry_freshness] || "미확인"}`,
    );
    const button = documentRef.createElement("button");
    button.type = "button";
    button.dataset.managementEditDevice = device.name;
    button.textContent = "수정";
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
    (adapter) => adapter.mutationEnabled === true
      && adapterSupportsNode(adapter, managementState.selectedNodeName),
  ) || managementState.runtimes.some(
    (runtime) => runtime.mutationEnabled === true
      && (runtime.targetNode || runtime.target_node) === managementState.selectedNodeName,
  );
  const mode = byId("managementMutationMode", documentRef);
  if (mode) {
    mode.textContent = enabled ? "변경 기능 활성화" : "검증 전용 · 변경 기능 비활성화";
    mode.dataset.status = enabled ? "enabled" : "disabled";
  }
  const tokenInput = byId("managementAdminToken", documentRef);
  if (tokenInput) tokenInput.disabled = !enabled;
  const patchButton = byId("managementPatchApply", documentRef);
  if (patchButton) {
    patchButton.disabled = !canPatchSelectedDevice(
      enabled,
      managementState.selectedPatchDeviceName,
    );
  }
}


function renderRuntimeSelection(documentRef = document) {
  const adapter = selectedAdapter();
  const bindings = (adapter?.runtime?.hardwareBindings || []).filter(
    (binding) => binding.nodeName === managementState.selectedNodeName,
  );
  const bindingSelect = byId("managementHardwareBinding", documentRef);
  const nodeSelect = byId("managementTargetNode", documentRef);
  clearElement(bindingSelect);
  clearElement(nodeSelect);
  const observations = buildPhysicalConnectionObservations({
    adapters: managementState.adapters,
    runtimes: managementState.runtimes,
    devices: managementState.devices,
    nodeName: managementState.selectedNodeName,
  });

  bindings.forEach((binding) => {
    const option = documentRef.createElement("option");
    option.value = binding.bindingId;
    const baseLabel = binding.devicePath
      ? `${binding.displayName} · ${binding.devicePath}`
      : binding.displayName;
    const observation = observations.find(
      (item) => item.bindingId === binding.bindingId,
    );
    option.textContent = observation
      ? `${baseLabel} · ${koreanLabel("presence", observation.presenceState)}`
      : `${baseLabel} · 관측 근거 없음`;
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
  if (nodeSelect) nodeSelect.disabled = true;
  const nextButton = byId(
    "managementRegistrationStep1",
    documentRef,
  )?.querySelector("[data-management-next-step]");
  if (nextButton) nextButton.disabled = !adapter || !hasBindings;

  const modeSelect = byId("managementRuntimeMode", documentRef);
  const autoOption = modeSelect?.querySelector('option[value="auto"]');
  const reuseOption = modeSelect?.querySelector('option[value="reuse"]');
  if (autoOption) autoOption.textContent = "자동 · 가능하면 기존 Device Service 재사용";
  if (reuseOption) reuseOption.textContent = "기존 Device Service만 사용";
  const deployOption = modeSelect?.querySelector('option[value="deploy"]');
  if (deployOption) {
    deployOption.disabled = adapter?.runtime?.deploymentEnabled !== true;
    deployOption.textContent = deployOption.disabled
      ? "새 Device Service 인스턴스 배포 · 현재 사용 불가"
      : "새 Device Service 인스턴스 배포";
  }
  if (modeSelect?.value === "deploy" && deployOption?.disabled) {
    modeSelect.value = "auto";
  }
  renderConnectionGuidance(documentRef);
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
  const binding = selectedHardwareBinding(documentRef);
  if (!adapter) {
    const applyButton = byId("managementApply", documentRef);
    if (applyButton) applyButton.disabled = true;
    const adapterNote = byId("managementAdapterNote", documentRef);
    if (adapterNote) {
      adapterNote.textContent = "선택한 노드에 사용할 수 있는 검증 패키지가 없습니다.";
      adapterNote.dataset.status = "unavailable";
    }
    return;
  }
  (adapter.fields || []).forEach((field) => {
    const label = documentRef.createElement("label");
    const caption = documentRef.createElement("span");
    caption.textContent = MANAGEMENT_LABELS.protocolField[field.name]
      || field.label
      || field.name;
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
    const bindingValue = bindingProtocolValue(field, binding);
    if (bindingValue.value !== null && bindingValue.value !== undefined) {
      input.value = String(bindingValue.value);
    }
    if (bindingValue.locked) {
      input.readOnly = true;
      input.setAttribute("aria-readonly", "true");
    }
    label.append(caption, input);
    container?.appendChild(label);
  });
  const applyButton = byId("managementApply", documentRef);
  if (applyButton) applyButton.disabled = true;
  const adapterNote = byId("managementAdapterNote", documentRef);
  if (adapterNote) {
    adapterNote.textContent = adapterCanApply(adapter)
      ? adapter.status === "installable"
        ? `검증된 ${adapter.serviceName} 패키지를 설치한 뒤 프로필과 디바이스를 등록합니다.`
        : `${adapter.serviceName}에 프로필과 디바이스를 등록합니다.`
      : adapter.status === "installed" && adapter.mutationEnabled !== true
        ? `${adapter.serviceName}는 검증만 가능합니다. 관리 변경 기능이 비활성화되어 있습니다.`
      : adapter.reason || "현재 적용할 수 없는 어댑터입니다.";
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
  if (!adapter) throw new Error("프로토콜 어댑터를 선택하세요.");
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
    result?.valid ? "검증 통과 · 변경 계획 준비" : "검증 실패",
  );
  (result?.issues || []).forEach((issue) => {
    appendTextElement(
      container,
      "p",
      "management-issue",
      `${issue.field || "요청"}: ${managementIssueText(issue)}`,
    );
  });
  const runtimePlan = result?.runtimePlan;
  if (runtimePlan) {
    const reasons = runtimePlan.reasons || [];
    appendTextElement(
      container,
      "p",
      "management-plan",
      `런타임: ${{
        REUSE: "기존 런타임 재사용",
        DEPLOY: "검증된 런타임 배포",
        BLOCKED: "실행 차단",
      }[runtimePlan.action] || runtimePlan.action} · ${runtimePlan.runtimeName || "미할당"} · `
        + `${runtimePlan.serviceName || "서비스 없음"} · `
        + `${koreanLabel("verification", runtimePlan.verificationState || "unverified")}`,
    );
    reasons.forEach((reason) => {
      appendTextElement(
        container,
        "p",
        "management-issue",
        `${reason.code || "런타임"}: ${managementIssueText(reason)}`,
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
      `EdgeX: ${mutations.map(
        (mutation) => MANAGEMENT_LABELS.mutation[mutation] || mutation,
      ).join(" → ") || "재조회"} → 첫 이벤트 확인`,
    );
  }
  (result?.warnings || []).forEach((warning) => {
    appendTextElement(
      container,
      "p",
      "management-warning",
      `${warning.field || "주의"}: ${managementIssueText(warning)}`,
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
      ? `${operation.runtimeAction || "런타임"} · ${operation.runtimeName || "런타임"} · `
        + `${operation.deviceName || "디바이스"} · 요청 ${operation.requestId || "대기 중"}`
      : `${operation.action || "생성"} · ${operation.deviceName || "디바이스"} · `
        + `요청 ${operation.requestId || "대기 중"}`,
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
    `${action === "restart" ? "재시작" : "퇴역"} · `
      + `${koreanLabel("runtimePhase", runtime.phase || "UNKNOWN")}`,
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
    error?.status === 404 ? "변경 기능 비활성화" : "관리 요청 실패",
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
  managementState.selectedPatchDeviceName = device?.name || "";
  byId("patchDeviceName", documentRef).value = device?.name || "";
  byId("patchDeviceDescription", documentRef).value = device?.description || "";
  byId("patchDeviceAdminState", documentRef).value = device?.admin_state || "UNLOCKED";
  byId("patchDeviceLabels", documentRef).value = (device?.labels || []).join(", ");
  byId("patchDeviceTags", documentRef).value = "";
  byId("patchDeviceProtocol", documentRef).value = "";
  const selector = byId("managementPatchDeviceSelect", documentRef);
  if (selector) selector.value = device?.name || "";
  renderMutationMode(documentRef);
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
  const nodeRequest = fetchManagementNodes(fetchFn)
    .then((nodes) => {
      managementState.nodeLoadError = null;
      return nodes;
    })
    .catch((error) => {
      managementState.nodeLoadError = error;
      return [];
    });
  const runtimeRequest = fetchAdapterRuntimes(fetchFn)
    .then((runtimes) => {
      managementState.runtimeLoadError = null;
      return runtimes;
    })
    .catch((error) => {
      managementState.runtimeLoadError = error;
      return [];
    });
  const [adapters, devices, runtimes, nodes] = await Promise.all([
    fetchManagementAdapters(fetchFn),
    fetchManagedDevices(fetchFn),
    runtimeRequest,
    nodeRequest,
  ]);
  managementState.adapters = adapters;
  managementState.nodes = nodes;
  managementState.devices = devices;
  managementState.runtimes = runtimes;
  const scopes = managementNodeScopes();
  if (!scopes.some((scope) => scope.name === managementState.selectedNodeName)) {
    managementState.selectedNodeName = (
      scopes.find((scope) => scope.runtimeCount > 0)
      || scopes.find((scope) => scope.adapterCount > 0)
      || scopes[0]
      || {}
    ).name || "";
  }
  const selectedPatchDevice = devices.find(
    (device) => device.name === managementState.selectedPatchDeviceName
      && managementDeviceNode(device) === managementState.selectedNodeName,
  );
  managementState.selectedPatchDeviceName = selectedPatchDevice?.name || "";
  renderManagementNodes(documentRef);
  renderAdapterOptions(documentRef);
  renderAdapterCatalog(documentRef);
  renderPhysicalConnections(documentRef);
  renderRuntimeInventory(documentRef);
  renderManagedDevices(documentRef);
  renderMutationMode(documentRef);
  renderRuntimeSelection(documentRef);
  renderProtocolFields(documentRef);
  ensureIdempotencyInput(byId("managementIdempotencyKey", documentRef));
  ensureIdempotencyInput(byId("patchIdempotencyKey", documentRef));
  renderRegistrationReview(documentRef);
  renderManagementView(documentRef);
  renderRegistrationStep(documentRef);
}


function initializeDeviceManagement(documentRef = document, fetchFn = fetch) {
  const adapterSelect = byId("managementAdapter", documentRef);
  if (!adapterSelect) return;
  const managementTabs = byId("managementViewTabs", documentRef);
  managementTabs?.addEventListener("click", (event) => {
    const button = event.target.closest?.("[data-management-view]");
    if (button) setManagementView(button.dataset.managementView, documentRef);
  });
  managementTabs?.addEventListener("keydown", (event) => {
    const button = event.target.closest?.("[data-management-view]");
    if (!button) return;
    const tabs = [...managementTabs.querySelectorAll("[data-management-view]")];
    const nextIndex = managementTabIndexForKey(
      event.key,
      tabs.indexOf(button),
      tabs.length,
    );
    if (nextIndex === null) return;
    event.preventDefault();
    const nextTab = tabs[nextIndex];
    setManagementView(nextTab.dataset.managementView, documentRef);
    nextTab.focus();
  });
  documentRef.querySelectorAll?.("[data-management-open-register]").forEach((button) => {
    button.addEventListener("click", () => {
      setManagementView("register", documentRef);
      setRegistrationStep(1, documentRef);
    });
  });
  byId("managementOverviewPanel", documentRef)?.addEventListener("click", (event) => {
    const button = event.target.closest?.("[data-management-select-adapter]");
    if (!button) return;
    const adapter = managementState.adapters.find(
      (item) => item.adapterId === button.dataset.managementSelectAdapter,
    );
    if (!adapter || !adapterSupportsNode(adapter, managementState.selectedNodeName)) return;
    managementState.selectedAdapterId = adapter.adapterId;
    managementState.validation = null;
    renderAdapterOptions(documentRef);
    renderRuntimeSelection(documentRef);
    const modeSelect = byId("managementRuntimeMode", documentRef);
    if (modeSelect) {
      modeSelect.value = adapter.status === "installable" ? "deploy" : "reuse";
    }
    renderProtocolFields(documentRef);
    renderRegistrationReview(documentRef);
    clearElement(byId("managementValidation", documentRef));
    setManagementView("register", documentRef);
    setRegistrationStep(1, documentRef);
  });
  byId("managementRegistrationStepper", documentRef)?.addEventListener("click", (event) => {
    const button = event.target.closest?.("[data-management-step]");
    if (button) setRegistrationStep(button.dataset.managementStep, documentRef);
  });
  byId("deviceOnboardingForm", documentRef)?.addEventListener("click", (event) => {
    if (event.target.closest?.("[data-management-next-step]")) {
      setRegistrationStep(managementState.registrationStep + 1, documentRef);
    }
    if (event.target.closest?.("[data-management-previous-step]")) {
      setRegistrationStep(managementState.registrationStep - 1, documentRef);
    }
  });
  byId("deviceOnboardingForm", documentRef)?.addEventListener("input", () => {
    renderRegistrationReview(documentRef);
  });
  byId("deviceOnboardingForm", documentRef)?.addEventListener("change", () => {
    renderRegistrationReview(documentRef);
  });
  adapterSelect.addEventListener("change", () => {
    managementState.selectedAdapterId = adapterSelect.value;
    managementState.validation = null;
    renderRuntimeSelection(documentRef);
    renderProtocolFields(documentRef);
    renderRegistrationReview(documentRef);
    clearElement(byId("managementValidation", documentRef));
  });
  byId("managementNodeList", documentRef)?.addEventListener("click", (event) => {
    const button = event.target.closest?.("[data-management-node]");
    if (!button) return;
    managementState.selectedNodeName = button.dataset.managementNode;
    managementState.selectedAdapterId = "";
    managementState.validation = null;
    managementState.runtimePlan = null;
    renderManagementNodes(documentRef);
    renderAdapterOptions(documentRef);
    renderAdapterCatalog(documentRef);
    renderPhysicalConnections(documentRef);
    renderRuntimeInventory(documentRef);
    renderManagedDevices(documentRef);
    renderRuntimeSelection(documentRef);
    renderProtocolFields(documentRef);
    clearElement(byId("managementValidation", documentRef));
    setSelectedPatchDevice("", documentRef);
    renderRegistrationReview(documentRef);
  });
  byId("managementHardwareBinding", documentRef)?.addEventListener("change", () => {
    syncRuntimeNodeFromBinding(documentRef);
    managementState.validation = null;
    renderProtocolFields(documentRef);
    renderConnectionGuidance(documentRef);
    renderRegistrationReview(documentRef);
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
      await loadDeviceManagement(documentRef, fetchFn);
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
    if (button) {
      setSelectedPatchDevice(button.dataset.managementEditDevice, documentRef);
      setManagementView("edit", documentRef);
    }
  });
  byId("managementPatchDeviceSelect", documentRef)?.addEventListener("change", (event) => {
    setSelectedPatchDevice(event.target.value, documentRef);
  });
  byId("managementRuntimeList", documentRef)?.addEventListener("click", async (event) => {
    const button = event.target.closest?.("[data-runtime-action]");
    if (!button || button.disabled) return;
    const action = button.dataset.runtimeAction;
    const name = button.dataset.runtimeName;
    if (
      action === "retire"
      && typeof globalThis.confirm === "function"
      && !globalThis.confirm(`${name} 런타임을 퇴역하시겠습니까? 정확한 이름 확인 후 실행됩니다.`)
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
      await loadDeviceManagement(documentRef, fetchFn);
    } catch (error) {
      renderManagementError(error, documentRef);
    }
  });
  updateProfileMode(documentRef);
  renderManagementView(documentRef);
  renderRegistrationStep(documentRef);
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
    adapterConnectionGuidance,
    adapterSelectionOptions,
    adapterSupportsNode,
    bindingProtocolValue,
    buildPhysicalConnectionObservations,
    buildManagementNodeScopes,
    canPatchSelectedDevice,
    connectionStatusView,
    createManagementConnection,
    createManagementDevice,
    fetchAdapterRuntimes,
    fetchConnectionOperation,
    fetchManagementAdapters,
    fetchManagementNodes,
    fetchManagementOperation,
    managementDeviceNode,
    managementTabIndexForKey,
    normalizeManagementView,
    normalizeRegistrationStep,
    operationStatusView,
    patchManagementDevice,
    planAdapterRuntime,
    pollConnectionOperation,
    pollManagementOperation,
    protocolPackageStatus,
    restartAdapterRuntime,
    retireAdapterRuntime,
    runtimeCanMutate,
    validateManagementConnection,
    validateManagementDevice,
  };
}
