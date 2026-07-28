function managementApiUrl(path, pathname = globalThis.location?.pathname || "") {
  const ingressPrefix = pathname === "/aggregator"
    || pathname.startsWith("/aggregator/")
    ? "/aggregator"
    : "";
  return `${ingressPrefix}${path}`;
}


const MANAGEMENT_ADAPTERS_URL = managementApiUrl("/management/adapters");
const MANAGEMENT_VALIDATE_URL = managementApiUrl("/management/devices/validate");
const MANAGEMENT_DEVICES_URL = managementApiUrl("/management/devices");
const MANAGEMENT_RUNTIMES_URL = managementApiUrl("/management/adapter-runtimes");
const MANAGEMENT_CONNECTIONS_URL = managementApiUrl("/management/connections");
const MANAGEMENT_DISCOVERY_URL = managementApiUrl("/management/discovery");
const MANAGEMENT_NODES_URL = managementApiUrl("/state/nodes");
const UNASSIGNED_NODE = "미할당 노드";

const managementState = {
  adapters: [],
  nodes: [],
  runtimes: [],
  devices: [],
  discovery: {
    nodes: [],
    candidates: [],
    totalCandidates: 0,
    filteredCandidates: 0,
    staleAfterSeconds: 90,
  },
  selectedNodeName: "",
  selectedAdapterId: "",
  selectedPatchDeviceName: "",
  activeView: "overview",
  registrationStep: 1,
  nodeLoadError: null,
  runtimePlan: null,
  runtimeLoadError: null,
  discoveryLoadError: null,
  runtimeActionKeys: new Map(),
  candidateActionKeys: new Map(),
  manualCandidateCreateKey: "",
  deviceDeleteKey: "",
  validation: null,
  operation: null,
  patchBaseline: null,
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
    onvif: "ONVIF",
    mqtt: "MQTT",
    rtsp: "RTSP",
    rest: "HTTP / REST",
  },
  candidateDecision: {
    pending: "검토 대기",
    accepted: "검토 승인",
    ignored: "무시됨",
  },
  candidatePresence: {
    present: "현재 관측",
    stale: "오래됨",
    declared: "수동 선언",
  },
  candidatePackage: {
    "registration-ready": "EdgeX 등록 가능",
    "binding-required": "연결 승인 필요",
    "verification-required": "패키지 검증 필요",
    unsupported: "패키지 없음",
  },
  candidateState: {
    DETECTED: "발견됨",
    IDENTIFIED: "식별됨",
    PENDING_APPROVAL: "승인 대기",
    APPROVED: "승인됨",
    SERVICE_READY: "서비스 준비",
    METADATA_REGISTERED: "Metadata 등록",
    EVENT_CONFIRMED: "첫 Event 확인",
    BLOCKED: "차단됨",
    REJECTED: "거절됨",
    STALE: "연결 끊김",
    FAILED: "등록 실패",
  },
  candidateAuth: {
    not_checked: "인증 전",
    approved: "인증 승인",
    denied: "인증 거절",
    unavailable: "인증 장애",
    error: "인증 오류",
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


function candidateEndpointSummary(candidate = {}) {
  if (candidate.devicePath) return candidate.devicePath;
  const properties = candidate.properties || {};
  if (candidate.protocol === "mqtt") {
    return [properties.Broker, properties.Topic].filter(Boolean).join(" · ")
      || candidate.transport
      || "MQTT 엔드포인트 미확인";
  }
  if (candidate.protocol === "modbus") {
    const address = properties.Host
      ? `${properties.Host}${properties.Port ? `:${properties.Port}` : ""}`
      : "";
    return [properties.Mode, address, properties.UnitID !== undefined
      ? `Unit ${properties.UnitID}`
      : ""].filter(Boolean).join(" · ")
      || candidate.transport
      || "Modbus 엔드포인트 미확인";
  }
  return properties.Endpoint || candidate.transport || "엔드포인트 미확인";
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

function runtimePurpose(runtime = {}) {
  return (
    runtime.purpose === "development-fixture"
    || runtime.runtimePurpose === "development-fixture"
    || runtime.runtime_purpose === "development-fixture"
  )
    ? "development-fixture"
    : "operational";
}

function devicePurpose(device = {}, runtimes = []) {
  const serviceName = device.device_service_name || device.deviceServiceName || "";
  const runtime = runtimes.find(
    (candidate) => (
      candidate.serviceName || candidate.service_name || ""
    ) === serviceName,
  );
  return runtimePurpose(runtime || {});
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

function buildDeviceServiceObservations({
  adapters = [],
  runtimes = [],
  devices = [],
  nodeName = "",
} = {}) {
  const nodeDevices = devices.filter(
    (device) => managementDeviceNode(device) === nodeName,
  );
  const physicalConnections = buildPhysicalConnectionObservations({
    adapters,
    runtimes,
    devices,
    nodeName,
  });
  const groups = new Map();

  runtimes
    .filter(
      (runtime) => (runtime.targetNode || runtime.target_node) === nodeName,
    )
    .forEach((runtime) => {
      const serviceName = runtime.serviceName
        || runtime.service_name
        || runtime.runtimeName
        || runtime.runtime_name;
      if (!serviceName || groups.has(serviceName)) return;
      groups.set(serviceName, {runtime, serviceName});
    });

  physicalConnections.forEach((connection) => {
    const serviceName = connection.serviceName
      || connection.runtimeName
      || connection.adapterId;
    if (!serviceName) return;
    if (!groups.has(serviceName)) groups.set(serviceName, {serviceName});
  });

  nodeDevices.forEach((device) => {
    const serviceName = device.device_service_name || device.deviceServiceName;
    if (serviceName && !groups.has(serviceName)) {
      groups.set(serviceName, {serviceName});
    }
  });

  return [...groups.values()].map(({runtime = null, serviceName}) => {
    const runtimeName = runtime?.runtimeName || runtime?.runtime_name || "";
    const adapterId = runtime?.adapterId
      || runtime?.adapter_id
      || physicalConnections.find(
        (connection) => connection.serviceName === serviceName,
      )?.adapterId
      || "";
    const adapter = adapters.find(
      (candidate) => candidate.adapterId === adapterId,
    ) || adapters.find(
      (candidate) => candidate.serviceName === serviceName,
    ) || null;
    const bindingIds = new Set([
      ...(runtime?.hardwareBindingIds || runtime?.hardware_binding_ids || []),
      runtime?.hardwareBindingId || runtime?.hardware_binding_id || "",
    ].filter(Boolean));
    const connections = physicalConnections.filter((connection) => (
      connection.serviceName === serviceName
      || (runtimeName && connection.runtimeName === runtimeName)
      || (connection.adapterId === adapterId && bindingIds.has(connection.bindingId))
    ));
    connections.forEach((connection) => bindingIds.add(connection.bindingId));

    const serviceDevices = nodeDevices.filter(
      (device) => (
        device.device_service_name || device.deviceServiceName
      ) === serviceName,
    );
    const connectedDevices = serviceDevices.filter((device) => (
      String(device.admin_state || device.adminState || "").toUpperCase() !== "LOCKED"
      && (
        String(
          device.operating_state || device.operatingState || "",
        ).toUpperCase() === "UP"
        || String(
          device.connection_state || device.connectionState || "",
        ).toLowerCase() === "connected"
      )
    ));
    const disconnectedDevices = serviceDevices.filter((device) => (
      String(device.admin_state || device.adminState || "").toUpperCase() === "LOCKED"
      || String(
        device.operating_state || device.operatingState || "",
      ).toUpperCase() === "DOWN"
      || String(
        device.connection_state || device.connectionState || "",
      ).toLowerCase() === "disconnected"
    ));
    const freshDevices = serviceDevices.filter(
      (device) => (device.telemetry_freshness || device.telemetryFreshness) === "fresh",
    );
    const staleDevices = serviceDevices.filter(
      (device) => (device.telemetry_freshness || device.telemetryFreshness) === "stale",
    );
    const runtimeState = runtime?.phase === "SERVICE_READY"
      && runtime.edgeXServiceObserved !== false
      ? "ready"
      : runtime
        ? "not_ready"
        : "not_installed";
    const registrationState = runtime?.edgeXServiceObserved === true
      || serviceDevices.some(
        (device) => (
          device.device_service_available === true
          || device.deviceServiceAvailable === true
        ),
      )
      ? "registered"
      : "unknown";
    const communicationState = connectedDevices.length
      ? "connected"
      : serviceDevices.length
        && disconnectedDevices.length === serviceDevices.length
        ? "disconnected"
        : "unknown";
    const telemetryState = freshDevices.length
      ? "fresh"
      : staleDevices.length
        ? "stale"
        : serviceDevices.length
          ? "missing"
          : "unknown";
    const presenceState = freshDevices.length || connectedDevices.length
      ? "detected"
      : serviceDevices.length
        && disconnectedDevices.length === serviceDevices.length
        ? "not_detected"
        : "unknown";
    const timestamps = serviceDevices
      .map((device) => (
        device.latest_event_timestamp || device.latestEventTimestamp || ""
      ))
      .filter(Boolean)
      .sort();
    const protocolName = adapter?.protocolName
      || serviceDevices.flatMap(
        (device) => device.protocol_names || device.protocolNames || [],
      )[0]
      || adapterId
      || "unknown";
    const status = physicalObservationStatus({
      registrationState,
      runtimeState,
      presenceState,
      communicationState,
      telemetryState,
    });
    let reason = "Device Service 상태를 확인해야 합니다.";
    if (status.state === "healthy") {
      reason = "Device Service 통신과 최신 Event가 확인됐습니다.";
    } else if (runtimeState !== "ready") {
      reason = "Device Service가 아직 준비되지 않았습니다.";
    } else if (telemetryState === "fresh" && communicationState === "unknown") {
      reason = "최신 Event는 수신 중이며 장비 통신 상태는 확인이 필요합니다.";
    } else if (telemetryState === "stale") {
      reason = "마지막 Event가 freshness 기준을 벗어났습니다.";
    } else if (telemetryState === "missing") {
      reason = "등록된 디바이스에서 Event가 수신되지 않았습니다.";
    } else if (communicationState === "disconnected") {
      reason = "Device Service가 장비 연결 끊김을 보고했습니다.";
    }

    return {
      adapterId,
      adapterName: adapter?.displayName || adapterId || serviceName,
      protocolName,
      serviceName,
      runtimeName,
      nodeName,
      runtimeState,
      runtimePhase: runtime?.phase || "UNKNOWN",
      registrationState,
      presenceState,
      communicationState,
      telemetryState,
      status,
      reason,
      deviceCount: serviceDevices.length,
      deviceNames: serviceDevices.map((device) => device.name).sort(),
      latestEventTimestamp: timestamps.at(-1) || null,
      bindingIds: [...bindingIds].sort(),
      bindingNames: connections.map((connection) => connection.bindingName).filter(Boolean),
      devicePaths: connections.map((connection) => connection.devicePath).filter(Boolean),
      physicalDeviceIds: connections
        .map((connection) => connection.physicalDeviceId)
        .filter(Boolean),
      managementOwner: runtime?.managementOwner || runtime?.management_owner || "",
      purpose: runtimePurpose(runtime || {}),
      verificationState: runtime?.verificationState
        || runtime?.verification_state
        || adapter?.runtime?.verificationState
        || "unverified",
      runtime,
    };
  }).sort((left, right) => (
    left.protocolName.localeCompare(right.protocolName)
    || left.serviceName.localeCompare(right.serviceName)
  ));
}

function physicalObservationStatus(observation = {}) {
  if (observation.registrationState !== "registered") {
    return {state: "warning", label: "등록 확인"};
  }
  if (
    observation.presenceState === "not_detected"
    || observation.communicationState === "disconnected"
  ) {
    return {state: "error", label: "연결 끊김"};
  }
  if (observation.telemetryState === "missing") {
    return {state: "error", label: "데이터 없음"};
  }
  if (observation.telemetryState === "stale") {
    return {state: "warning", label: "데이터 지연"};
  }
  if (
    observation.runtimeState !== "ready"
    || observation.presenceState !== "detected"
    || observation.communicationState !== "connected"
    || observation.telemetryState !== "fresh"
  ) {
    return {state: "warning", label: "확인 필요"};
  }
  return {state: "healthy", label: "정상"};
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
    .filter((adapter) => ["installed", "installable"].includes(adapter?.status))
    .map((adapter, index) => {
      const enabled = adapterSupportsNode(adapter, nodeName);
      let availability = adapter?.status === "installable"
        ? "검증된 Device Service 설치"
        : "기존 Device Service 재사용";
      if (!enabled) {
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
        fixtureRuntimeCount: 0,
        fixtureDeviceCount: 0,
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
  const servicePurposes = new Map(
    runtimes
      .map((runtime) => [
        runtime.serviceName || runtime.service_name || "",
        runtimePurpose(runtime),
      ])
      .filter(([serviceName]) => serviceName),
  );
  runtimes.forEach((runtime) => {
    const nodeName = runtime.targetNode || runtime.target_node;
    const scope = ensure(nodeName);
    if (runtimePurpose(runtime) === "development-fixture") {
      scope.fixtureRuntimeCount += 1;
    } else {
      scope.runtimeCount += 1;
    }
    eligibleNodes.add(nodeName || UNASSIGNED_NODE);
  });
  devices.forEach((device) => {
    const nodeName = managementDeviceNode(device);
    const serviceName = device.device_service_name || device.deviceServiceName || "";
    const scope = ensure(nodeName);
    if (servicePurposes.get(serviceName) === "development-fixture") {
      scope.fixtureDeviceCount += 1;
    } else {
      scope.deviceCount += 1;
    }
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
  return ["discovery", "overview", "register", "edit"].includes(view)
    ? view
    : "overview";
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
  const detailMessage = Array.isArray(detail)
    ? detail.map((item) => {
      const location = Array.isArray(item?.loc)
        ? item.loc.filter((part) => part !== "body").join(".")
        : "";
      return `${location ? `${location}: ` : ""}${item?.msg || item?.message || item?.type || "요청 값 오류"}`;
    }).join(" · ")
    : typeof detail === "string"
      ? detail
      : detail?.message || detail?.error || "";
  const message = detailMessage || `관리 요청에 실패했습니다. (HTTP ${response.status})`;
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


async function fetchDiscoveryInventory(fetchFn = fetch) {
  const response = await fetchFn(
    `${MANAGEMENT_DISCOVERY_URL}?includeIgnored=true&limit=2000`,
    {cache: "no-store"},
  );
  const payload = await managementPayload(response);
  if (!Array.isArray(payload?.candidates) || !Array.isArray(payload?.nodes)) {
    throw new Error("device discovery response contract is invalid");
  }
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


function mutationHeaders(idempotencyKey) {
  return {
    "Content-Type": "application/json",
    "Idempotency-Key": idempotencyKey,
  };
}


async function createManagementDevice(payload, {
  idempotencyKey,
  fetchFn = fetch,
}) {
  const response = await fetchFn(MANAGEMENT_DEVICES_URL, {
    method: "POST",
    headers: mutationHeaders(idempotencyKey),
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return managementPayload(response);
}


async function createManagementConnection(payload, {
  idempotencyKey,
  fetchFn = fetch,
}) {
  const response = await fetchFn(MANAGEMENT_CONNECTIONS_URL, {
    method: "POST",
    headers: mutationHeaders(idempotencyKey),
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return managementPayload(response);
}


async function createManualCandidate(payload, {
  idempotencyKey,
  fetchFn = fetch,
}) {
  const response = await fetchFn(`${MANAGEMENT_DISCOVERY_URL}/manual`, {
    method: "POST",
    headers: mutationHeaders(idempotencyKey),
    body: JSON.stringify(payload),
    cache: "no-store",
  });
  return managementPayload(response);
}


async function updateCandidateDecision(candidateId, payload, {
  idempotencyKey,
  fetchFn = fetch,
}) {
  const response = await fetchFn(
    `${MANAGEMENT_DISCOVERY_URL}/${encodeURIComponent(candidateId)}`,
    {
      method: "PATCH",
      headers: mutationHeaders(idempotencyKey),
      body: JSON.stringify(payload),
      cache: "no-store",
    },
  );
  return managementPayload(response);
}


async function deleteCandidate(candidateId, {
  idempotencyKey,
  fetchFn = fetch,
}) {
  const response = await fetchFn(
    `${MANAGEMENT_DISCOVERY_URL}/${encodeURIComponent(candidateId)}`,
    {
      method: "DELETE",
      headers: mutationHeaders(idempotencyKey),
      cache: "no-store",
    },
  );
  return managementPayload(response);
}

async function decommissionCandidate(candidateId, {
  idempotencyKey,
  reason,
  fetchFn = fetch,
}) {
  const response = await fetchFn(
    `${MANAGEMENT_DISCOVERY_URL}/${encodeURIComponent(candidateId)}/decommission`,
    {
      method: "POST",
      headers: {
        ...mutationHeaders(idempotencyKey),
        "X-Confirm-Candidate": candidateId,
      },
      body: JSON.stringify({reason}),
      cache: "no-store",
    },
  );
  return managementPayload(response);
}


async function restartAdapterRuntime(name, {
  idempotencyKey,
  fetchFn = fetch,
}) {
  const response = await fetchFn(
    `${MANAGEMENT_RUNTIMES_URL}/${encodeURIComponent(name)}/restart`,
    {
      method: "POST",
      headers: mutationHeaders(idempotencyKey),
      cache: "no-store",
    },
  );
  return managementPayload(response);
}


async function retireAdapterRuntime(name, {
  idempotencyKey,
  fetchFn = fetch,
}) {
  const response = await fetchFn(
    `${MANAGEMENT_RUNTIMES_URL}/${encodeURIComponent(name)}`,
    {
      method: "DELETE",
      headers: {
        ...mutationHeaders(idempotencyKey),
        "X-Confirm-Runtime": name,
      },
      cache: "no-store",
    },
  );
  return managementPayload(response);
}


async function patchManagementDevice(name, payload, {
  idempotencyKey,
  fetchFn = fetch,
}) {
  const response = await fetchFn(
    `${MANAGEMENT_DEVICES_URL}/${encodeURIComponent(name)}`,
    {
      method: "PATCH",
      headers: mutationHeaders(idempotencyKey),
      body: JSON.stringify(payload),
      cache: "no-store",
    },
  );
  return managementPayload(response);
}

async function deleteManagementDevice(name, {
  idempotencyKey,
  fetchFn = fetch,
}) {
  const response = await fetchFn(
    `${MANAGEMENT_DEVICES_URL}/${encodeURIComponent(name)}`,
    {
      method: "DELETE",
      headers: {
        ...mutationHeaders(idempotencyKey),
        "X-Confirm-Device": name,
      },
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
    if (operation.action === "delete") {
      return {
        label: "삭제 완료",
        tone: "verified",
        detail: "EdgeX Core Metadata 재조회에서 디바이스 삭제를 확인했습니다.",
        terminal: true,
      };
    }
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


function connectionApplyButtonView(validation = null, operation = null, adapterApplicable = false) {
  if (operation?.status === "ACTIVE") {
    return {
      disabled: true,
      label: "연결 완료",
      title: "EdgeX 등록과 첫 Event 검증이 완료되었습니다. 다른 연결을 등록하려면 입력값을 변경하세요.",
    };
  }
  return {
    disabled: !(validation?.valid && adapterApplicable),
    label: "디바이스 연결",
    title: "",
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


function candidateRegistrationStatusView(candidate = {}) {
  const state = String(candidate.state || "");
  const views = {
    APPROVED: {
      label: "Device Service 설치 시작",
      status: "waiting",
      active: true,
      terminal: false,
    },
    SERVICE_READY: {
      label: "Device Service 준비 완료 · EdgeX 등록 중",
      status: "waiting",
      active: true,
      terminal: false,
    },
    METADATA_REGISTERED: {
      label: "EdgeX 등록 완료 · 첫 Event 확인 중",
      status: "waiting",
      active: true,
      terminal: false,
    },
    EVENT_CONFIRMED: {
      label: "자동 설치·등록 완료",
      status: "success",
      active: false,
      terminal: true,
    },
    FAILED: {
      label: candidate.failureReason || "자동 설치·등록 실패",
      status: "error",
      active: false,
      terminal: true,
    },
    BLOCKED: {
      label: candidate.failureReason || "등록 차단",
      status: "error",
      active: false,
      terminal: true,
    },
    REJECTED: {
      label: "후보 거절",
      status: "warning",
      active: false,
      terminal: true,
    },
    STALE: {
      label: "장비 연결 끊김",
      status: "warning",
      active: false,
      terminal: true,
    },
  };
  return views[state] || {
    label: koreanLabel("candidateState", state, "등록 상태 확인 필요"),
    status: "warning",
    active: false,
    terminal: false,
  };
}


async function pollCandidateRegistration(candidateId, {
  fetchFn = fetch,
  sleepFn = delay,
  intervalMs = 2000,
  maxAttempts = 45,
  onUpdate = () => {},
} = {}) {
  let candidate = null;
  let inventory = null;
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    inventory = await fetchDiscoveryInventory(fetchFn);
    candidate = inventory.candidates.find(
      (item) => item.candidateId === candidateId,
    ) || null;
    if (!candidate) return {candidate, inventory, timedOut: false};
    const view = candidateRegistrationStatusView(candidate);
    onUpdate({candidate, inventory, view});
    if (view.terminal || !view.active) {
      return {candidate, inventory, timedOut: false};
    }
    if (attempt + 1 < maxAttempts) await sleepFn(intervalMs);
  }
  return {candidate, inventory, timedOut: true};
}

function byId(id, documentRef = document) {
  return documentRef.getElementById(id);
}


function clearElement(element) {
  if (element) element.replaceChildren();
}

function renderManagementActionFeedback(message, {
  status = "ready",
  kind = "operation",
  documentRef = document,
} = {}) {
  const element = byId("managementActionFeedback", documentRef);
  if (!element) return;
  element.textContent = message;
  element.dataset.status = status;
  element.dataset.kind = kind;
}


function renderRegistrationFeedback(message, {
  status = "ready",
  documentRef = document,
} = {}) {
  const element = byId("managementRegistrationFeedback", documentRef);
  if (!element) return;
  element.textContent = message;
  element.dataset.status = status;
}


function renderPatchResult(message, {
  status = "ready",
  documentRef = document,
} = {}) {
  const element = byId("managementPatchResult", documentRef);
  if (!element) return;
  element.textContent = message;
  element.dataset.status = status;
}

function renderDeleteDeviceResult(message, {
  status = "warning",
  documentRef = document,
} = {}) {
  const element = byId("managementDeleteDeviceResult", documentRef);
  if (!element) return;
  element.textContent = message;
  element.dataset.status = status;
}


function setManagementButtonBusy(button, busy, busyLabel = "처리 중…") {
  if (!button) return;
  if (!button.dataset.defaultLabel) button.dataset.defaultLabel = button.textContent.trim();
  button.disabled = busy;
  button.setAttribute("aria-busy", String(busy));
  button.textContent = busy ? busyLabel : button.dataset.defaultLabel;
}


function registrationStepIssue(step, documentRef = document) {
  if (step === 1) {
    const fields = [
      ["managementAdapter", "프로토콜과 Device Service를 선택하세요."],
      ["managementHardwareBinding", "등록된 물리 연결을 선택하세요."],
      ["managementTargetNode", "대상 노드를 확인하세요."],
    ];
    for (const [id, message] of fields) {
      const field = byId(id, documentRef);
      if (!field || !String(field.value || "").trim()) return {field, message};
    }
    const requiredProtocolField = [...(documentRef.querySelectorAll?.("[data-protocol-field][required]") || [])]
      .find((field) => !String(field.value || "").trim());
    if (requiredProtocolField) {
      return {field: requiredProtocolField, message: "선택한 물리 연결의 필수 프로토콜 값을 입력하세요."};
    }
  }
  if (step === 2) {
    const field = byId("managementDeviceName", documentRef);
    if (!field?.value.trim()) return {field, message: "고유한 EdgeX 디바이스 이름을 입력하세요."};
  }
  if (step === 3) {
    const field = byId("managementProfileName", documentRef);
    if (!field?.value.trim()) return {field, message: "EdgeX 디바이스 프로필 이름을 입력하세요."};
  }
  return null;
}


function validateRegistrationThrough(targetStep, documentRef = document) {
  const lastStep = Math.min(3, Math.max(0, Number(targetStep) - 1));
  for (let step = 1; step <= lastStep; step += 1) {
    const issue = registrationStepIssue(step, documentRef);
    if (!issue) continue;
    managementState.registrationStep = step;
    renderRegistrationStep(documentRef);
    renderRegistrationFeedback(issue.message, {status: "error", documentRef});
    renderManagementActionFeedback(`등록 ${step}단계를 확인하세요: ${issue.message}`, {
      status: "error",
      documentRef,
    });
    issue.field?.focus?.();
    issue.field?.reportValidity?.();
    return false;
  }
  return true;
}


function setRegistrationStepGuarded(step, documentRef = document) {
  const targetStep = normalizeRegistrationStep(step);
  if (
    targetStep > managementState.registrationStep
    && !validateRegistrationThrough(targetStep, documentRef)
  ) return false;
  setRegistrationStep(targetStep, documentRef);
  renderRegistrationFeedback(
    targetStep === 4
      ? "필수 항목 입력을 확인했습니다. 연결 검증을 실행하세요."
      : `${targetStep}단계로 이동했습니다.`,
    {status: "success", documentRef},
  );
  return true;
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

function preferredManagementNode(scopes = [], discoveryNodes = []) {
  const onlineNodes = new Set(
    discoveryNodes
      .filter((node) => node.presence === "online")
      .map((node) => node.nodeName),
  );
  return (
    scopes.find((scope) => onlineNodes.has(scope.name) && scope.runtimeCount > 0)
    || scopes.find((scope) => onlineNodes.has(scope.name) && scope.adapterCount > 0)
    || scopes.find((scope) => onlineNodes.has(scope.name))
    || scopes.find((scope) => scope.runtimeCount > 0)
    || scopes.find((scope) => scope.adapterCount > 0)
    || scopes[0]
    || null
  );
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
    managementState.selectedNodeName = preferredManagementNode(
      scopes,
      managementState.discovery.nodes,
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
    appendTextElement(facts, "span", "", `현장 서비스 ${scope.runtimeCount}개`);
    appendTextElement(facts, "span", "", `현장 디바이스 ${scope.deviceCount}개`);
    if (scope.fixtureRuntimeCount || scope.fixtureDeviceCount) {
      appendTextElement(
        facts,
        "span",
        "",
        `검증용 ${scope.fixtureRuntimeCount}서비스 · ${scope.fixtureDeviceCount}디바이스`,
      );
    }
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
  pendingGroup.label = "다른 노드에서 사용 가능";
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

function candidateVisibleInDefaultList(candidate = {}, {
  includeIgnored = false,
  showStale = false,
  showRegistered = false,
} = {}) {
  if (!includeIgnored && candidate.state === "REJECTED") return false;
  if (!showRegistered && candidate.state === "EVENT_CONFIRMED") return false;
  if (
    !showStale
    && (candidate.presence === "stale" || candidate.state === "STALE")
  ) return false;
  return true;
}


function normalizeDiscoverySearchTerm(value = "") {
  return String(value)
    .normalize("NFKC")
    .toLocaleLowerCase("ko-KR")
    .replace(/[\s_-]+/g, "");
}


function discoveryFilterStatusView({
  total = 0,
  visible = 0,
  search = "",
  protocol = "",
  stateFilter = "",
  includeIgnored = false,
  showStale = false,
  showRegistered = false,
} = {}) {
  const active = Boolean(
    String(search).trim()
    || protocol
    || stateFilter
    || includeIgnored
    || showStale
    || showRegistered,
  );
  const hidden = Math.max(0, Number(total) - Number(visible));
  return {
    active,
    hidden,
    resetDisabled: !active,
    label: active
      ? `${total}개 중 ${visible}개 표시`
        + (hidden ? ` · 검색 조건으로 ${hidden}개 숨김` : "")
      : `${visible}개 후보 표시`,
  };
}


function discoveryFilterInputs(documentRef = document) {
  return {
    search: byId("managementDiscoverySearch", documentRef)?.value.trim() || "",
    protocol: byId(
      "managementDiscoveryProtocolFilter",
      documentRef,
    )?.value || "",
    stateFilter: byId(
      "managementDiscoveryDecisionFilter",
      documentRef,
    )?.value || "",
    includeIgnored: byId(
      "managementDiscoveryIncludeIgnored",
      documentRef,
    )?.checked === true,
    showStale: byId(
      "managementDiscoveryShowStale",
      documentRef,
    )?.checked === true,
    showRegistered: byId(
      "managementDiscoveryShowRegistered",
      documentRef,
    )?.checked === true,
  };
}


function discoveryCandidatesForSelectedNode(documentRef = document) {
  const {
    search,
    protocol,
    stateFilter,
    includeIgnored,
    showStale,
    showRegistered: requestedRegistered,
  } = discoveryFilterInputs(documentRef);
  const normalizedSearch = normalizeDiscoverySearchTerm(search);
  const showRegistered = requestedRegistered || stateFilter === "EVENT_CONFIRMED";
  return (managementState.discovery.candidates || []).filter((candidate) => {
    if (candidate.nodeName !== managementState.selectedNodeName) return false;
    if (!candidateVisibleInDefaultList(
      candidate,
      {includeIgnored, showStale, showRegistered},
    )) {
      return false;
    }
    if (protocol && candidate.protocol !== protocol) return false;
    if (stateFilter && candidate.state !== stateFilter) return false;
    if (!normalizedSearch) return true;
    const searchable = [
      candidate.candidateId,
      candidate.displayName,
      candidate.nodeName,
      candidate.protocol,
      candidate.transport,
      candidate.devicePath || "",
      candidate.note || "",
      candidate.decisionNote || "",
      candidate.state || "",
      candidate.hardwareId || "",
      candidate.model || "",
      candidate.recommendedProfile || "",
      ...Object.values(candidate.properties || {}).map(String),
    ].join(" ");
    return normalizeDiscoverySearchTerm(searchable).includes(normalizedSearch);
  });
}


function candidateRegisteredDevices(candidate = {}) {
  const bindingId = candidate.matchedHardwareBindingId || "";
  if (!bindingId) return [];
  const observation = buildPhysicalConnectionObservations({
    adapters: managementState.adapters,
    runtimes: managementState.runtimes,
    devices: managementState.devices,
    nodeName: candidate.nodeName,
  }).find(
    (item) => item.bindingId === bindingId
      && (!candidate.matchedAdapterId || item.adapterId === candidate.matchedAdapterId),
  );
  if (observation) {
    const names = new Set(observation.deviceNames);
    return managementState.devices.filter((device) => names.has(device.name));
  }
  return managementState.devices.filter(
    (device) => managementDeviceNode(device) === candidate.nodeName
      && managementDeviceBindingId(device) === bindingId,
  );
}

function registeredCandidateForDevice(deviceName = "") {
  if (!deviceName) return null;
  return (managementState.discovery.candidates || []).find(
    (candidate) => [
      "APPROVED",
      "SERVICE_READY",
      "METADATA_REGISTERED",
      "EVENT_CONFIRMED",
      "FAILED",
    ].includes(candidate.state)
      && candidateRegisteredDevices(candidate).some(
        (device) => device.name === deviceName,
      ),
  ) || null;
}


function deviceDeleteTargetView(deviceName = "") {
  const candidate = registeredCandidateForDevice(deviceName);
  return {
    candidate,
    title: candidate ? "등록 연결 전체 삭제" : "EdgeX 디바이스 삭제",
    summary: candidate
      ? `${deviceName}과 Controller가 만든 Device Service Runtime을 함께 삭제합니다. Device Profile은 다른 장비가 사용하면 유지됩니다.`
      : `${deviceName}을 EdgeX Core Metadata에서 삭제합니다. Device Profile과 Device Service는 유지됩니다.`,
  };
}


function renderDiscoveryNodeHealth(documentRef = document) {
  const container = byId("managementDiscoveryNodeHealth", documentRef);
  clearElement(container);
  (managementState.discovery.nodes || []).forEach((node) => {
    const chip = appendTextElement(
      container,
      "span",
      "",
      `${node.nodeName} · ${node.presence === "online" ? "탐색 중" : "보고 지연"}`
        + ` · 후보 ${node.candidateCount || 0}개`
        + `${(node.scanErrors || []).length ? ` · 오류 ${node.scanErrors.length}` : ""}`,
    );
    chip.dataset.presence = node.presence || "stale";
    if (node.nodeName === managementState.selectedNodeName) {
      chip.setAttribute("aria-current", "true");
    }
  });
  if (!container?.children.length) {
    appendTextElement(
      container,
      "span",
      "",
      managementState.discoveryLoadError
        ? "노드 탐색 상태를 불러오지 못했습니다."
        : "아직 노드 탐색 보고가 없습니다.",
    );
  }
}


function renderDiscoveryStatus(documentRef = document) {
  const status = byId("managementDiscoveryStatus", documentRef);
  if (!status) return;
  if (managementState.discoveryLoadError) {
    status.textContent = "탐색 API 연결 실패";
    status.dataset.status = "error";
    return;
  }
  const node = (managementState.discovery.nodes || []).find(
    (item) => item.nodeName === managementState.selectedNodeName,
  );
  if (!node) {
    status.textContent = "선택 노드 탐색기 미보고";
    status.dataset.status = "degraded";
    return;
  }
  if (node.presence === "online" && !(node.scanErrors || []).length) {
    status.textContent = `탐색 정상 · ${formatManagementTimestamp(node.lastReportAt)}`;
    status.dataset.status = "online";
    return;
  }
  status.textContent = node.presence === "online"
    ? `일부 탐색 오류 · ${(node.scanErrors || []).length}건`
    : `탐색 보고 지연 · ${formatManagementTimestamp(node.lastReportAt)}`;
  status.dataset.status = "degraded";
}


function renderDiscoveryFeedback(message, {
  status = "degraded",
  documentRef = document,
} = {}) {
  const element = byId("managementDiscoveryStatus", documentRef);
  if (!element) return;
  element.textContent = message;
  element.dataset.status = status;
}

function renderDiscoveryStats(documentRef = document) {
  const candidates = (managementState.discovery.candidates || []).filter(
    (candidate) => candidate.nodeName === managementState.selectedNodeName,
  );
  const values = {
    managementDiscoveryPresentCount: candidates.filter(
      (candidate) => candidate.presence === "present",
    ).length,
    managementDiscoveryPendingCount: candidates.filter(
      (candidate) => candidate.state === "PENDING_APPROVAL",
    ).length,
    managementDiscoveryReadyCount: candidates.filter(
      (candidate) => (
        candidate.registrationReady === true
        && candidate.state !== "EVENT_CONFIRMED"
      ),
    ).length,
    managementDiscoveryIgnoredCount: candidates.filter(
      (candidate) => candidate.state === "REJECTED",
    ).length,
  };
  Object.entries(values).forEach(([id, value]) => {
    const element = byId(id, documentRef);
    if (element) element.textContent = String(value);
  });
}


function appendCandidateAction(
  actions,
  label,
  action,
  candidateId,
  {disabled = false, title = ""} = {},
) {
  const button = actions.ownerDocument.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.dataset.candidateAction = action;
  button.dataset.candidateId = candidateId;
  button.disabled = disabled;
  if (title) button.title = title;
  actions.appendChild(button);
  return button;
}

function renderDiscoveryCandidates(documentRef = document) {
  const container = byId("managementDiscoveryList", documentRef);
  clearElement(container);
  const filterInputs = discoveryFilterInputs(documentRef);
  const defaultCandidates = (managementState.discovery.candidates || []).filter(
    (candidate) => candidate.nodeName === managementState.selectedNodeName
      && candidateVisibleInDefaultList(candidate, {
        includeIgnored: filterInputs.includeIgnored,
        showStale: filterInputs.showStale,
        showRegistered: filterInputs.showRegistered
          || filterInputs.stateFilter === "EVENT_CONFIRMED",
      }),
  );
  const candidates = discoveryCandidatesForSelectedNode(documentRef);
  const filterView = discoveryFilterStatusView({
    total: defaultCandidates.length,
    visible: candidates.length,
    search: filterInputs.search,
    protocol: filterInputs.protocol,
    stateFilter: filterInputs.stateFilter,
    includeIgnored: filterInputs.includeIgnored,
    showStale: filterInputs.showStale,
    showRegistered: filterInputs.showRegistered,
  });
  const filterStatus = byId("managementDiscoveryFilterStatus", documentRef);
  const resetFilters = byId("managementDiscoveryResetFilters", documentRef);
  if (filterStatus) filterStatus.textContent = filterView.label;
  if (resetFilters) resetFilters.disabled = filterView.resetDisabled;
  filterStatus?.parentElement?.setAttribute(
    "data-hidden",
    filterView.hidden > 0 ? "true" : "false",
  );
  if (!candidates.length) {
    const staleHidden = byId(
      "managementDiscoveryShowStale",
      documentRef,
    )?.checked !== true && (managementState.discovery.candidates || []).some(
      (candidate) => candidate.nodeName === managementState.selectedNodeName
        && (candidate.presence === "stale" || candidate.state === "STALE"),
    );
    const registeredHidden = byId(
      "managementDiscoveryShowRegistered",
      documentRef,
    )?.checked !== true && (managementState.discovery.candidates || []).some(
      (candidate) => candidate.nodeName === managementState.selectedNodeName
        && candidate.state === "EVENT_CONFIRMED",
    );
    appendTextElement(
      container,
      "p",
      "management-empty",
      managementState.discoveryLoadError
        ? "연결 후보를 불러오지 못했습니다. Controller와 탐색기 상태를 확인하세요."
        : filterView.active && defaultCandidates.length
          ? `${defaultCandidates.length}개 후보가 검색 조건에 가려져 있습니다. ‘검색 조건 초기화’를 누르세요.`
          : staleHidden
          ? "현재 연결된 후보가 없습니다. 이전 관측 기록은 검색·표시 조건에서 ‘오래된 후보 표시’를 켜면 확인할 수 있습니다."
          : registeredHidden
            ? "등록 대기 후보가 없습니다. 등록 완료 장비는 ‘등록 현황’에서 확인할 수 있습니다."
          : "현재 조건에 맞는 연결 후보가 없습니다. 검색 조건을 바꾸거나 엔드포인트를 직접 추가하세요.",
    );
    return;
  }
  candidates.forEach((candidate) => {
    const registeredDevices = candidateRegisteredDevices(candidate);
    const card = documentRef.createElement("article");
    card.className = "management-candidate-card";
    card.dataset.decision = candidate.decision;

    const header = documentRef.createElement("div");
    header.className = "management-candidate-head";
    const identity = documentRef.createElement("div");
    appendTextElement(
      identity,
      "strong",
      "",
      candidate.displayName || "이름 미확인 후보",
    );
    appendTextElement(
      identity,
      "small",
      "",
      `${candidate.nodeName} · ${candidateEndpointSummary(candidate)}`,
    );
    appendTextElement(
      header,
      "span",
      "management-protocol-pill",
      koreanLabel("protocol", candidate.protocol, candidate.protocol),
    );
    header.prepend(identity);

    const badges = documentRef.createElement("div");
    badges.className = "management-candidate-badges";
    const presence = appendTextElement(
      badges,
      "span",
      "",
      koreanLabel("candidatePresence", candidate.presence, "관측 미확인"),
    );
    presence.dataset.tone = candidate.presence === "present" ? "present" : "stale";
    appendTextElement(
      badges,
      "span",
      "",
      koreanLabel("candidateState", candidate.state, "상태 미확인"),
    );
    appendTextElement(
      badges,
      "span",
      "",
      koreanLabel("candidateAuth", candidate.authState, "인증 미확인"),
    );
    const packageBadge = appendTextElement(
      badges,
      "span",
      "",
      koreanLabel("candidatePackage", candidate.packageState, "패키지 미확인"),
    );
    packageBadge.dataset.tone = candidate.registrationReady ? "ready" : "blocked";
    if (registeredDevices.length) {
      const registered = appendTextElement(
        badges,
        "span",
        "",
        `EdgeX 등록됨 · ${registeredDevices.length}개`,
      );
      registered.dataset.tone = "ready";
    }

    const facts = documentRef.createElement("div");
    facts.className = "management-candidate-facts";
    [
      candidate.source === "node-scan" ? "노드 자동 관측" : "운영자 수동 입력",
      `전송 ${candidate.transport}`,
      candidate.matchedAdapterId ? `패키지 ${candidate.matchedAdapterId}` : "",
      candidate.matchedHardwareBindingId
        ? `연결 ${candidate.matchedHardwareBindingId}`
        : "",
      candidate.model ? `모델 ${candidate.model}` : "",
      candidate.recommendedProfile
        ? `프로필 ${candidate.recommendedProfile}`
        : "",
      candidate.hardwareId ? `하드웨어 ID ${candidate.hardwareId}` : "",
      `마지막 확인 ${formatManagementTimestamp(candidate.lastSeen)}`,
    ].filter(Boolean).forEach((fact) => appendTextElement(facts, "span", "", fact));

    appendTextElement(
      card,
      "p",
      "management-candidate-reason",
      candidate.packageReason || "프로토콜 패키지 상태를 확인할 수 없습니다.",
    );
    if (candidate.failureReason) {
      appendTextElement(
        card,
        "p",
        "management-candidate-warning",
        candidate.failureReason,
      );
    }
    if (candidate.evidence?.warning) {
      appendTextElement(
        card,
        "p",
        "management-candidate-warning",
        candidate.evidence.warning,
      );
    }
    if (candidate.decisionNote || candidate.note) {
      appendTextElement(
        card,
        "p",
        "management-candidate-decision-note",
        candidate.decisionNote || candidate.note,
      );
    }

    const actions = documentRef.createElement("div");
    actions.className = "management-candidate-actions";
    if (candidate.state === "PENDING_APPROVAL") {
      if (candidate.registrationReady === true) {
        appendCandidateAction(
          actions,
          "승인하고 자동 설치·등록",
          "accept",
          candidate.candidateId,
        );
      } else {
        appendCandidateAction(
          actions,
          "검증 패키지 등록 후 가능",
          "accept",
          candidate.candidateId,
          {
            disabled: true,
            title: candidate.packageReason
              || "검증된 Device Service 패키지가 필요합니다.",
          },
        );
      }
      appendCandidateAction(
        actions,
        "후보 거절",
        "ignore",
        candidate.candidateId,
      );
    } else if (candidate.state === "REJECTED") {
      appendCandidateAction(
        actions,
        "다시 검토",
        "restore",
        candidate.candidateId,
      );
    } else if (candidate.state === "FAILED") {
      appendCandidateAction(
        actions,
        "등록 재시도",
        "accept",
        candidate.candidateId,
      );
      appendCandidateAction(
        actions,
        "거절",
        "ignore",
        candidate.candidateId,
      );
    } else if (candidate.state === "BLOCKED") {
      if (["unavailable", "error"].includes(candidate.authState)) {
        appendCandidateAction(
          actions,
          "인증 재확인",
          "accept",
          candidate.candidateId,
        );
      }
      appendCandidateAction(
        actions,
        "후보 거절",
        "ignore",
        candidate.candidateId,
      );
    }
    if (candidate.source === "manual") {
      appendCandidateAction(
        actions,
        "후보 삭제",
        "delete",
        candidate.candidateId,
      );
    }
    card.prepend(header, badges, facts);
    card.appendChild(actions);
    container.appendChild(card);
  });
}


function renderDiscovery(documentRef = document) {
  renderDiscoveryStatus(documentRef);
  renderDiscoveryStats(documentRef);
  renderDiscoveryNodeHealth(documentRef);
  renderDiscoveryCandidates(documentRef);
}


function renderDeviceServiceInventory(documentRef = document) {
  const container = byId("managementDeviceServiceList", documentRef);
  const fixtureContainer = byId("managementFixtureServiceList", documentRef);
  const fixtureSection = byId("managementFixtureServiceSection", documentRef);
  const fixtureCount = byId("managementFixtureServiceCount", documentRef);
  clearElement(container);
  clearElement(fixtureContainer);
  if (!container) return;
  const observations = buildDeviceServiceObservations({
    adapters: managementState.adapters,
    runtimes: managementState.runtimes,
    devices: managementState.devices,
    nodeName: managementState.selectedNodeName,
  });
  const operationalObservations = observations.filter(
    (observation) => observation.purpose !== "development-fixture",
  );
  const fixtureObservations = observations.filter(
    (observation) => observation.purpose === "development-fixture",
  );
  if (fixtureSection) fixtureSection.hidden = fixtureObservations.length === 0;
  if (fixtureCount) fixtureCount.textContent = `${fixtureObservations.length}개`;
  if (!observations.length) {
    appendTextElement(
      container,
      "p",
      "management-empty",
      "이 노드에서 실행 중이거나 EdgeX에 등록된 Device Service가 없습니다.",
    );
    return;
  }
  if (!operationalObservations.length) {
    appendTextElement(
      container,
      "p",
      "management-empty",
      "이 노드에 등록된 실장비 Device Service가 없습니다.",
    );
  }
  observations.forEach((observation) => {
    const targetContainer = observation.purpose === "development-fixture"
      ? fixtureContainer
      : container;
    if (!targetContainer) return;
    const card = documentRef.createElement("article");
    card.className = "management-physical-card";
    card.dataset.purpose = observation.purpose;
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
      koreanLabel(
        "protocol",
        observation.protocolName,
        observation.adapterName || observation.serviceName,
      ),
    );
    appendTextElement(
      identity,
      "small",
      "",
      observation.serviceName,
    );
    const headerStatus = documentRef.createElement("div");
    headerStatus.className = "management-physical-head-status";
    if (observation.purpose === "development-fixture") {
      appendTextElement(
        headerStatus,
        "span",
        "management-purpose-pill",
        "개발용 시뮬레이터",
      );
    }
    appendTextElement(
      headerStatus,
      "span",
      "management-protocol-pill",
      koreanLabel("runtimePhase", observation.runtimePhase, "상태 미확인"),
    );
    header.append(identity, headerStatus);

    const summary = documentRef.createElement("div");
    summary.className = "management-physical-summary";
    const overall = appendTextElement(
      summary,
      "strong",
      "management-physical-overall",
      observation.status.label,
    );
    overall.dataset.state = observation.status.state;
    appendTextElement(
      summary,
      "small",
      "management-physical-compact-latest",
      observation.latestEventTimestamp
        ? `최신 ${formatManagementTimestamp(observation.latestEventTimestamp)}`
        : "최신 데이터 없음",
    );

    const details = documentRef.createElement("details");
    details.className = "management-physical-details";
    appendTextElement(details, "summary", "", "세부정보");
    const detailBody = documentRef.createElement("div");
    detailBody.className = "management-physical-detail-body";

    const evidence = documentRef.createElement("div");
    evidence.className = "management-evidence-grid";
    [
      {
        label: "Device Service",
        state: observation.runtimeState,
        value: koreanLabel("runtimeState", observation.runtimeState),
      },
      {
        label: "EdgeX 등록",
        state: observation.registrationState,
        value: observation.registrationState === "registered" ? "등록 확인" : "등록 미확인",
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
      `노드 ${observation.nodeName}`,
      `EdgeX Device ${observation.deviceCount}개`,
      observation.bindingIds.length
        ? `${observation.purpose === "development-fixture" ? "검증 연결" : "물리 연결"} `
          + `${observation.bindingIds.length}개`
        : `${observation.purpose === "development-fixture" ? "검증" : "물리"} 연결 정보 없음`,
      observation.managementOwner
        ? `${observation.managementOwner === "argocd" ? "Argo CD" : "Controller"} 관리`
        : "",
      koreanLabel("verification", observation.verificationState),
      observation.runtimeName && observation.runtimeName !== observation.serviceName
        ? `내부 Runtime ${observation.runtimeName}`
        : "",
      ...observation.bindingIds.map((bindingId) => `연결 ID ${bindingId}`),
      ...observation.devicePaths.map((devicePath) => `장치 경로 ${devicePath}`),
      ...observation.physicalDeviceIds.map(
        (physicalDeviceId) => `물리 소스 ${physicalDeviceId}`,
      ),
    ].filter(Boolean).forEach((fact) => appendTextElement(facts, "span", "", fact));

    appendTextElement(
      detailBody,
      "p",
      "management-physical-reason",
      observation.purpose === "development-fixture"
        ? `실장비 연결이 아닌 개발 검증용 데이터입니다. ${observation.reason}`
        : observation.reason,
    );
    appendTextElement(
      detailBody,
      "small",
      "management-physical-latest",
      observation.deviceNames.length
        ? `연결 디바이스 ${observation.deviceNames.join(", ")} · 최신 Event `
          + formatManagementTimestamp(observation.latestEventTimestamp)
        : "연결된 EdgeX Device와 Event가 아직 없습니다.",
    );
    detailBody.prepend(evidence, facts);

    const runtime = observation.runtime;
    if (runtime && runtimeCanMutate(runtime)) {
      const actions = documentRef.createElement("div");
      actions.className = "management-runtime-actions";
      const restart = documentRef.createElement("button");
      restart.type = "button";
      restart.textContent = "재시작";
      restart.dataset.runtimeAction = "restart";
      restart.dataset.runtimeName = observation.runtimeName;
      restart.title = "이 Device Service Runtime을 재시작합니다.";
      const retire = documentRef.createElement("button");
      retire.type = "button";
      retire.textContent = "퇴역";
      retire.dataset.runtimeAction = "retire";
      retire.dataset.runtimeName = observation.runtimeName;
      retire.disabled = observation.deviceCount > 0;
      retire.title = retire.disabled
        ? "연결된 EdgeX Device를 먼저 해제해야 합니다."
        : "이 Device Service Runtime을 퇴역합니다.";
      actions.append(restart, retire);
      detailBody.appendChild(actions);
    }

    details.appendChild(detailBody);
    card.append(header, summary, details);
    targetContainer.appendChild(card);
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
    if (!mutable || Number(runtime.consumers || 0) > 0) {
      const externallyOwned = runtime.managementMode !== "controller"
        || runtime.managementOwner === "argocd";
      appendTextElement(
        card,
        "p",
        "management-action-reason",
        !mutable
          ? externallyOwned
            ? "이 런타임은 Argo CD 또는 외부 배포 소유이므로 대시보드에서 재시작·퇴역할 수 없습니다."
            : "런타임 변경 기능이 비활성화되어 있어 대시보드에서 재시작·퇴역할 수 없습니다."
          : `연결된 EdgeX 디바이스 ${Number(runtime.consumers || 0)}개를 먼저 해제해야 퇴역할 수 있습니다.`,
      );
    }
    container.appendChild(card);
  });
}


function renderManagedDevices(documentRef = document) {
  const container = byId("managedDeviceList", documentRef);
  const fixtureContainer = byId("managementFixtureDeviceList", documentRef);
  const fixtureSection = byId("managementFixtureDeviceSection", documentRef);
  const fixtureCount = byId("managementFixtureDeviceCount", documentRef);
  const selector = byId("managementPatchDeviceSelect", documentRef);
  clearElement(container);
  clearElement(fixtureContainer);
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
  const operationalDevices = devices.filter(
    (device) => devicePurpose(device, managementState.runtimes) !== "development-fixture",
  );
  const fixtureDevices = devices.filter(
    (device) => devicePurpose(device, managementState.runtimes) === "development-fixture",
  );
  if (fixtureSection) fixtureSection.hidden = fixtureDevices.length === 0;
  if (fixtureCount) fixtureCount.textContent = `${fixtureDevices.length}개`;
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
  if (!operationalDevices.length && container) {
    appendTextElement(
      container,
      "p",
      "management-empty",
      "선택한 노드에 등록된 실장비 EdgeX 디바이스가 없습니다.",
    );
  }
  devices.forEach((device) => {
    const purpose = devicePurpose(device, managementState.runtimes);
    const targetContainer = purpose === "development-fixture"
      ? fixtureContainer
      : container;
    if (selector) {
      const option = documentRef.createElement("option");
      option.value = device.name;
      option.textContent = purpose === "development-fixture"
        ? `검증용 · ${device.name}`
        : device.name;
      option.selected = device.name === managementState.selectedPatchDeviceName;
      selector.appendChild(option);
    }
    const row = documentRef.createElement("article");
    row.className = "managed-device-row";
    row.dataset.purpose = purpose;
    const identity = documentRef.createElement("div");
    appendTextElement(identity, "strong", "", device.name || "이름 미확인 디바이스");
    if (purpose === "development-fixture") {
      appendTextElement(identity, "small", "management-fixture-label", "개발용 시뮬레이터");
    }
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
    targetContainer?.appendChild(row);
  });
}


function selectedAdapter() {
  return managementState.adapters.find(
    (item) => item.adapterId === managementState.selectedAdapterId,
  ) || null;
}


function mutationModeEnabled() {
  return managementState.adapters.some(
    (adapter) => adapter.mutationEnabled === true,
  ) || managementState.runtimes.some(
    (runtime) => runtime.mutationEnabled === true,
  );
}


function patchFormSnapshot(documentRef = document) {
  return JSON.stringify({
    name: byId("patchDeviceName", documentRef)?.value || "",
    description: byId("patchDeviceDescription", documentRef)?.value || "",
    adminState: byId("patchDeviceAdminState", documentRef)?.value || "",
    labels: byId("patchDeviceLabels", documentRef)?.value || "",
    tags: byId("patchDeviceTags", documentRef)?.value || "",
    protocol: byId("patchDeviceProtocol", documentRef)?.value || "",
  });
}


function updatePatchDirtyState(documentRef = document) {
  const enabled = mutationModeEnabled();
  const selected = Boolean(managementState.selectedPatchDeviceName);
  const dirty = selected
    && managementState.patchBaseline !== null
    && patchFormSnapshot(documentRef) !== managementState.patchBaseline;
  const patchButton = byId("managementPatchApply", documentRef);
  if (patchButton) patchButton.disabled = !(enabled && selected && dirty);
  return dirty;
}


function patchDirtyFeedback(dirty, selected = true) {
  if (!selected) {
    return {
      message: "디바이스를 선택하고 값을 변경하면 적용할 수 있습니다.",
      status: "ready",
    };
  }
  if (dirty) {
    return {
      message: "변경 사항이 있습니다. 적용 버튼을 눌러 저장하세요.",
      status: "warning",
    };
  }
  return {
    message: "현재 저장된 값과 같습니다. 변경할 항목을 수정하세요.",
    status: "ready",
  };
}


function renderPatchDirtyState(documentRef = document) {
  const selected = Boolean(managementState.selectedPatchDeviceName);
  const dirty = updatePatchDirtyState(documentRef);
  const feedback = patchDirtyFeedback(dirty, selected);
  renderPatchResult(feedback.message, {
    status: feedback.status,
    documentRef,
  });
  return dirty;
}


function renderMutationMode(documentRef = document) {
  const enabled = mutationModeEnabled();
  const mode = byId("managementMutationMode", documentRef);
  if (mode) {
    mode.textContent = enabled ? "변경 기능 활성화" : "검증 전용 · 변경 기능 비활성화";
    mode.dataset.status = enabled ? "enabled" : "disabled";
  }
  const manualButton = byId("managementOpenManualCandidate", documentRef);
  if (manualButton) {
    manualButton.disabled = !enabled;
    manualButton.title = enabled
      ? "자동 탐색이 어려운 엔드포인트를 후보로 추가합니다."
      : "현재 변경 기능이 비활성화되어 있습니다.";
  }
  const deleteButton = byId("managementDeleteDevice", documentRef);
  if (deleteButton) {
    deleteButton.disabled = !(
      enabled && managementState.selectedPatchDeviceName
    );
  }
  updatePatchDirtyState(documentRef);
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
  if (applyButton) {
    const view = connectionApplyButtonView(
      result,
      managementState.operation,
      adapterCanApply(selectedAdapter()),
    );
    applyButton.disabled = view.disabled;
    applyButton.textContent = view.label;
    applyButton.title = view.title;
  }
  renderRegistrationFeedback(
    result?.valid
      ? "연결 검증을 통과했습니다. 실행 계획을 확인한 뒤 디바이스 연결을 누르세요."
      : "연결 검증에 실패했습니다. 실행 계획의 오류 항목을 수정하세요.",
    {status: result?.valid ? "success" : "error", documentRef},
  );
  renderManagementActionFeedback(
    result?.valid ? "디바이스 연결 검증 완료" : "디바이스 연결 검증 실패",
    {status: result?.valid ? "success" : "error", documentRef},
  );
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
  renderManagementActionFeedback(
    `${view.label}: ${view.detail}`,
    {
      status: view.tone === "failed" ? "error" : view.terminal ? "success" : "waiting",
      documentRef,
    },
  );
  const applyButton = byId("managementApply", documentRef);
  if (applyButton && isConnection) {
    const buttonView = connectionApplyButtonView(
      managementState.validation,
      operation,
      adapterCanApply(selectedAdapter()),
    );
    applyButton.disabled = buttonView.disabled;
    applyButton.textContent = buttonView.label;
    applyButton.title = buttonView.title;
  }
}


function resetCompletedConnectionForFormEdit(target, documentRef = document) {
  if (managementState.operation?.status !== "ACTIVE") return false;
  managementState.operation = null;
  managementState.validation = null;
  managementState.runtimePlan = null;
  if (target?.id !== "managementIdempotencyKey") {
    const idempotencyInput = byId("managementIdempotencyKey", documentRef);
    if (idempotencyInput) idempotencyInput.value = "";
  }
  const operation = byId("managementOperation", documentRef);
  clearElement(operation);
  if (operation) {
    appendTextElement(
      operation,
      "p",
      "",
      "입력 내용이 변경되었습니다. 연결 검증을 다시 실행하세요.",
    );
  }
  const applyButton = byId("managementApply", documentRef);
  if (applyButton) {
    const view = connectionApplyButtonView(
      null,
      null,
      adapterCanApply(selectedAdapter()),
    );
    applyButton.disabled = view.disabled;
    applyButton.textContent = view.label;
    applyButton.title = view.title;
  }
  return true;
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
  renderManagementActionFeedback(
    `${action === "restart" ? "재시작" : "퇴역"} 요청 결과: ${koreanLabel("runtimePhase", runtime.phase || "UNKNOWN")}`,
    {
      status: runtime.phase === "FAILED" ? "error" : "success",
      documentRef,
    },
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
  renderManagementActionFeedback(
    error?.message || "관리 요청에 실패했습니다.",
    {
      status: error?.status === 404 ? "warning" : "error",
      documentRef,
    },
  );
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
  managementState.patchBaseline = device ? patchFormSnapshot(documentRef) : null;
  renderMutationMode(documentRef);
  renderPatchResult(
    device
      ? `${device.name}의 현재 값을 불러왔습니다. 값을 변경하면 적용 버튼이 활성화됩니다.`
      : "수정할 디바이스를 선택하세요.",
    {status: device ? "success" : "ready", documentRef},
  );
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


const MANUAL_PROTOCOL_FIELDS = {
  serial: [
    {name: "DevicePath", label: "고정 장치 경로", placeholder: "/dev/serial/by-id/...", required: true},
    {name: "BaudRate", label: "통신 속도", type: "number", value: "115200", required: true},
  ],
  i2c: [
    {name: "DevicePath", label: "I²C 버스 경로", placeholder: "/dev/i2c-1", required: true},
  ],
  mqtt: [
    {name: "Broker", label: "브로커 주소", placeholder: "mqtts://broker.example:8883", required: true, wide: true},
    {name: "Topic", label: "토픽", placeholder: "factory/line-1/temperature", required: true, wide: true},
  ],
  modbus: [
    {name: "Mode", label: "연결 방식", type: "select", options: [["tcp", "Modbus TCP"], ["rtu", "Modbus RTU"]], required: true},
    {name: "Host", label: "TCP 호스트", placeholder: "plc-01.factory.local"},
    {name: "Port", label: "TCP 포트", type: "number", value: "502"},
    {name: "UnitID", label: "Unit ID", type: "number", value: "1", required: true},
    {name: "DevicePath", label: "RTU 고정 장치 경로", placeholder: "/dev/serial/by-id/...", wide: true},
    {name: "BaudRate", label: "RTU 통신 속도", type: "number", value: "115200"},
  ],
  opcua: [
    {name: "Endpoint", label: "OPC-UA 엔드포인트", placeholder: "opc.tcp://plc-01.factory.local:4840", required: true, wide: true},
  ],
  onvif: [
    {name: "Endpoint", label: "ONVIF 장비 서비스 URL · 자격 증명 제외", placeholder: "https://camera-01.factory.local/onvif/device_service", required: true, wide: true},
  ],
  rtsp: [
    {name: "Endpoint", label: "RTSP URL · 자격 증명 제외", placeholder: "rtsp://camera-01.factory.local/stream", required: true, wide: true},
  ],
  rest: [
    {name: "Endpoint", label: "HTTP 엔드포인트", placeholder: "https://device-01.factory.local/api/telemetry", required: true, wide: true},
  ],
};


function renderManualNodeOptions(documentRef = document) {
  const select = byId("managementManualNode", documentRef);
  clearElement(select);
  managementNodeScopes().forEach((scope) => {
    const option = documentRef.createElement("option");
    option.value = scope.name;
    option.textContent = scope.name;
    option.selected = scope.name === managementState.selectedNodeName;
    select?.appendChild(option);
  });
}


function renderManualProtocolFields(documentRef = document) {
  const container = byId("managementManualProtocolFields", documentRef);
  clearElement(container);
  const protocol = byId("managementManualProtocol", documentRef)?.value || "serial";
  (MANUAL_PROTOCOL_FIELDS[protocol] || []).forEach((field) => {
    const label = documentRef.createElement("label");
    if (field.wide) label.className = "management-field-wide";
    appendTextElement(label, "span", "", field.label);
    let control;
    if (field.type === "select") {
      control = documentRef.createElement("select");
      (field.options || []).forEach(([value, text]) => {
        const option = documentRef.createElement("option");
        option.value = value;
        option.textContent = text;
        control.appendChild(option);
      });
    } else {
      control = documentRef.createElement("input");
      control.type = field.type || "text";
      control.placeholder = field.placeholder || "";
      if (field.value) control.value = field.value;
    }
    control.dataset.manualCandidateField = field.name;
    control.required = field.required === true;
    label.appendChild(control);
    container?.appendChild(label);
  });
}


function manualCandidateField(name, documentRef = document) {
  return byId("managementManualProtocolFields", documentRef)
    ?.querySelector(`[data-manual-candidate-field="${name}"]`)
    ?.value
    ?.trim() || "";
}


function collectManualCandidatePayload(documentRef = document) {
  const protocol = byId("managementManualProtocol", documentRef).value;
  const nodeName = byId("managementManualNode", documentRef).value;
  const displayName = byId("managementManualDisplayName", documentRef).value.trim();
  if (!nodeName || !displayName) {
    throw new Error("대상 노드와 표시 이름을 입력하세요.");
  }
  const properties = {};
  let devicePath = null;
  let transport = protocol;
  const putString = (name) => {
    const value = manualCandidateField(name, documentRef);
    if (value) properties[name] = value;
    return value;
  };
  const putNumber = (name) => {
    const value = manualCandidateField(name, documentRef);
    if (!value) return null;
    const parsed = Number(value);
    if (!Number.isInteger(parsed)) throw new Error(`${name} 값은 정수여야 합니다.`);
    properties[name] = parsed;
    return parsed;
  };
  if (protocol === "serial") {
    devicePath = manualCandidateField("DevicePath", documentRef);
    putNumber("BaudRate");
    transport = "usb-serial";
  } else if (protocol === "i2c") {
    devicePath = manualCandidateField("DevicePath", documentRef);
    transport = "i2c-bus";
  } else if (protocol === "mqtt") {
    const broker = putString("Broker");
    putString("Topic");
    transport = broker.split(":", 1)[0] || "mqtt";
  } else if (protocol === "modbus") {
    const mode = putString("Mode").toLowerCase();
    transport = `modbus-${mode || "unknown"}`;
    if (mode === "tcp") {
      putString("Host");
      putNumber("Port");
    } else {
      devicePath = manualCandidateField("DevicePath", documentRef);
      putNumber("BaudRate");
    }
    putNumber("UnitID");
  } else {
    const endpoint = putString("Endpoint");
    transport = endpoint.split(":", 1)[0] || protocol;
  }
  return {
    nodeName,
    protocol,
    transport,
    displayName,
    ...(devicePath ? {devicePath} : {}),
    properties,
    note: byId("managementManualNote", documentRef).value.trim(),
  };
}


function renderManualCandidateResult(message, {
  status = "applied",
  documentRef = document,
} = {}) {
  const container = byId("managementManualCandidateResult", documentRef);
  clearElement(container);
  if (!container) return;
  container.dataset.status = status;
  appendTextElement(container, "p", "", message);
}


function prefillRegistrationFromCandidate(candidate, documentRef = document) {
  if (!candidate?.registrationReady) return false;
  managementState.selectedNodeName = candidate.nodeName;
  managementState.selectedAdapterId = candidate.matchedAdapterId || "";
  managementState.validation = null;
  renderManagementNodes(documentRef);
  renderAdapterOptions(documentRef);
  renderRuntimeSelection(documentRef);
  const binding = byId("managementHardwareBinding", documentRef);
  if (binding) binding.value = candidate.matchedHardwareBindingId || "";
  syncRuntimeNodeFromBinding(documentRef);
  renderProtocolFields(documentRef);
  const labels = byId("managementDeviceLabels", documentRef);
  if (labels && !labels.value.trim()) {
    labels.value = `${candidate.protocol}, virtual-device`;
  }
  renderRegistrationReview(documentRef);
  setManagementView("register", documentRef);
  setRegistrationStep(1, documentRef);
  return true;
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
  const discoveryRequest = fetchDiscoveryInventory(fetchFn)
    .then((inventory) => {
      managementState.discoveryLoadError = null;
      return inventory;
    })
    .catch((error) => {
      managementState.discoveryLoadError = error;
      return {
        nodes: [],
        candidates: [],
        totalCandidates: 0,
        filteredCandidates: 0,
        staleAfterSeconds: 90,
      };
    });
  const [adapters, devices, runtimes, nodes, discovery] = await Promise.all([
    fetchManagementAdapters(fetchFn),
    fetchManagedDevices(fetchFn),
    runtimeRequest,
    nodeRequest,
    discoveryRequest,
  ]);
  managementState.adapters = adapters;
  managementState.nodes = nodes;
  managementState.devices = devices;
  managementState.runtimes = runtimes;
  managementState.discovery = discovery;
  const scopes = managementNodeScopes();
  if (!scopes.some((scope) => scope.name === managementState.selectedNodeName)) {
    managementState.selectedNodeName = preferredManagementNode(
      scopes,
      managementState.discovery.nodes,
    )?.name || "";
  }
  const selectedPatchDevice = devices.find(
    (device) => device.name === managementState.selectedPatchDeviceName
      && managementDeviceNode(device) === managementState.selectedNodeName,
  );
  managementState.selectedPatchDeviceName = selectedPatchDevice?.name || "";
  renderManagementNodes(documentRef);
  renderAdapterOptions(documentRef);
  renderDeviceServiceInventory(documentRef);
  renderManagedDevices(documentRef);
  renderDiscovery(documentRef);
  renderMutationMode(documentRef);
  renderRuntimeSelection(documentRef);
  renderProtocolFields(documentRef);
  renderManualNodeOptions(documentRef);
  renderManualProtocolFields(documentRef);
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
    if (button) {
      setManagementView(button.dataset.managementView, documentRef);
      renderManagementActionFeedback(`${button.textContent.trim()} 화면을 열었습니다.`, {
        status: "success",
        kind: "navigation",
        documentRef,
      });
    }
  });
  managementTabs?.addEventListener("keydown", (event) => {
    const button = event.target.closest?.("[data-management-view]");
    if (!button) return;
    const tabs = [...managementTabs.querySelectorAll("[data-management-view]")]
      .filter(
        (tab) => typeof globalThis.getComputedStyle !== "function"
          || globalThis.getComputedStyle(tab).display !== "none",
      );
    const nextIndex = managementTabIndexForKey(
      event.key,
      tabs.indexOf(button),
      tabs.length,
    );
    if (nextIndex === null) return;
    event.preventDefault();
    const nextTab = tabs[nextIndex];
    setManagementView(nextTab.dataset.managementView, documentRef);
    renderManagementActionFeedback(`${nextTab.textContent.trim()} 화면을 열었습니다.`, {
      status: "success",
      kind: "navigation",
      documentRef,
    });
    nextTab.focus();
  });
  documentRef.querySelectorAll?.("[data-management-open-register]").forEach((button) => {
    button.addEventListener("click", () => {
      setManagementView("register", documentRef);
      setRegistrationStep(1, documentRef);
      renderManagementActionFeedback("새 디바이스 등록 화면을 열었습니다.", {
        status: "success",
        kind: "navigation",
        documentRef,
      });
    });
  });
  [
    "managementDiscoverySearch",
    "managementDiscoveryProtocolFilter",
    "managementDiscoveryDecisionFilter",
    "managementDiscoveryShowStale",
    "managementDiscoveryIncludeIgnored",
    "managementDiscoveryShowRegistered",
  ].forEach((id) => {
    const input = byId(id, documentRef);
    input?.addEventListener(
      id === "managementDiscoverySearch" ? "input" : "change",
      () => renderDiscoveryCandidates(documentRef),
    );
  });
  byId("managementDiscoveryResetFilters", documentRef)?.addEventListener(
    "click",
    () => {
      [
        "managementDiscoverySearch",
        "managementDiscoveryProtocolFilter",
        "managementDiscoveryDecisionFilter",
      ].forEach((id) => {
        const input = byId(id, documentRef);
        if (input) input.value = "";
      });
      [
        "managementDiscoveryShowStale",
        "managementDiscoveryIncludeIgnored",
        "managementDiscoveryShowRegistered",
      ].forEach((id) => {
        const input = byId(id, documentRef);
        if (input) input.checked = false;
      });
      renderDiscoveryCandidates(documentRef);
      byId("managementDiscoverySearch", documentRef)?.focus();
    },
  );
  const manualDialog = byId("managementManualCandidateDialog", documentRef);
  byId("managementOpenManualCandidate", documentRef)?.addEventListener("click", () => {
    managementState.manualCandidateCreateKey = "";
    renderManualNodeOptions(documentRef);
    renderManualProtocolFields(documentRef);
    renderManualCandidateResult(
      "비밀번호·토큰·URL 내 자격 증명은 저장할 수 없습니다.",
      {status: "disabled", documentRef},
    );
    if (typeof manualDialog?.showModal === "function") manualDialog.showModal();
    else manualDialog?.setAttribute("open", "");
    renderManagementActionFeedback("엔드포인트 직접 추가 창을 열었습니다.", {
      status: "success",
      kind: "navigation",
      documentRef,
    });
  });
  manualDialog?.querySelectorAll("[data-management-close-dialog]").forEach((button) => {
    button.addEventListener("click", () => {
      if (typeof manualDialog.close === "function") manualDialog.close();
      else manualDialog.removeAttribute("open");
    });
  });
  byId("managementManualProtocol", documentRef)?.addEventListener(
    "change",
    () => renderManualProtocolFields(documentRef),
  );
  byId("managementManualCandidateForm", documentRef)?.addEventListener(
    "submit",
    async (event) => {
      event.preventDefault();
      const submit = byId("managementCreateManualCandidate", documentRef);
      const form = event.currentTarget;
      try {
        if (!form.checkValidity()) {
          form.reportValidity();
          renderManualCandidateResult(
            "필수 항목을 모두 입력한 뒤 다시 시도하세요.",
            {status: "failed", documentRef},
          );
          renderManagementActionFeedback("연결 후보의 필수 항목을 확인하세요.", {
            status: "error",
            documentRef,
          });
          return;
        }
        const payload = collectManualCandidatePayload(documentRef);
        setManagementButtonBusy(submit, true, "추가 중…");
        renderManualCandidateResult(
          "후보를 안전하게 저장하는 중입니다.",
          {status: "waiting", documentRef},
        );
        managementState.manualCandidateCreateKey = (
          managementState.manualCandidateCreateKey
          || globalThis.crypto?.randomUUID?.()
          || `candidate-create-${Date.now()}`
        );
        await createManualCandidate(payload, {
          idempotencyKey: managementState.manualCandidateCreateKey,
          fetchFn,
        });
        renderManualCandidateResult(
          "연결 후보를 추가했습니다.",
          {status: "verified", documentRef},
        );
        renderManagementActionFeedback(`${payload.displayName} 연결 후보를 추가했습니다.`, {
          status: "success",
          documentRef,
        });
        await loadDeviceManagement(documentRef, fetchFn);
        if (typeof manualDialog?.close === "function") manualDialog.close();
        else manualDialog?.removeAttribute("open");
        managementState.manualCandidateCreateKey = "";
        byId("managementManualDisplayName", documentRef).value = "";
        byId("managementManualNote", documentRef).value = "";
      } catch (error) {
        renderManualCandidateResult(
          error?.message || "연결 후보 추가에 실패했습니다.",
          {status: "failed", documentRef},
        );
        renderManagementActionFeedback(
          error?.message || "연결 후보 추가에 실패했습니다.",
          {status: "error", documentRef},
        );
      } finally {
        setManagementButtonBusy(submit, false);
      }
    },
  );
  byId("managementDiscoveryList", documentRef)?.addEventListener(
    "click",
    async (event) => {
      const button = event.target.closest?.("[data-candidate-action]");
      if (!button || button.disabled) return;
      const candidate = (managementState.discovery.candidates || []).find(
        (item) => item.candidateId === button.dataset.candidateId,
      );
      if (!candidate) return;
      const action = button.dataset.candidateAction;
      if (action === "register") {
        if (!prefillRegistrationFromCandidate(candidate, documentRef)) {
          renderDiscoveryFeedback(
            "이 후보는 아직 검증된 연결이 없어 EdgeX 등록을 시작할 수 없습니다.",
            {status: "degraded", documentRef},
          );
          renderManagementActionFeedback("후보 등록을 시작할 수 없습니다. 검증된 연결 여부를 확인하세요.", {
            status: "warning",
            documentRef,
          });
        } else {
          renderManagementActionFeedback(`${candidate.displayName} 등록 화면을 준비했습니다.`, {
            status: "success",
            kind: "navigation",
            documentRef,
          });
        }
        return;
      }
      if (
        action === "delete"
        && typeof globalThis.confirm === "function"
        && !globalThis.confirm(`${candidate.displayName} 수동 후보를 삭제하시겠습니까?`)
      ) {
        return;
      }
      const decisionByAction = {
        accept: "accepted",
        ignore: "ignored",
        restore: "pending",
      };
      const actionKey = `${action}:${candidate.candidateId}:${candidate.decision}`;
      const idempotencyKey = managementState.candidateActionKeys.get(actionKey)
        || globalThis.crypto?.randomUUID?.()
        || `candidate-${action}-${Date.now()}`;
      managementState.candidateActionKeys.set(actionKey, idempotencyKey);
      button.disabled = true;
      button.setAttribute("aria-busy", "true");
      renderDiscoveryFeedback("후보 상태를 적용하는 중입니다.", {
        status: "degraded",
        documentRef,
      });
      try {
        let changedCandidate = null;
        if (action === "delete") {
          await deleteCandidate(candidate.candidateId, {
            idempotencyKey,
            fetchFn,
          });
        } else {
          changedCandidate = await updateCandidateDecision(
            candidate.candidateId,
            {
              decision: decisionByAction[action],
              note: {
                accept: "대시보드에서 운영자가 연결 후보를 검토 승인했습니다.",
                ignore: "대시보드에서 운영자가 이 후보를 무시했습니다.",
                restore: "대시보드에서 후보를 검토 대기로 되돌렸습니다.",
              }[action],
            },
            {
              idempotencyKey,
              fetchFn,
            },
          );
        }
        managementState.candidateActionKeys.delete(actionKey);
        if (
          action === "accept"
          && candidateRegistrationStatusView(changedCandidate).active
        ) {
          const initialView = candidateRegistrationStatusView(changedCandidate);
          renderDiscoveryFeedback(initialView.label, {
            status: "degraded",
            documentRef,
          });
          renderManagementActionFeedback(initialView.label, {
            status: "waiting",
            documentRef,
          });
          const polled = await pollCandidateRegistration(
            candidate.candidateId,
            {
              fetchFn,
              onUpdate: ({inventory, view}) => {
                managementState.discovery = inventory;
                renderDiscovery(documentRef);
                renderDiscoveryFeedback(view.label, {
                  status: view.status === "success" ? "online" : "degraded",
                  documentRef,
                });
                renderManagementActionFeedback(view.label, {
                  status: view.status,
                  documentRef,
                });
              },
            },
          );
          changedCandidate = polled.candidate || changedCandidate;
        }
        await loadDeviceManagement(documentRef, fetchFn);
        const finalView = action === "accept"
          ? candidateRegistrationStatusView(changedCandidate)
          : null;
        renderDiscoveryFeedback(
          finalView?.label || "후보 상태를 반영했습니다.",
          {
            status: finalView?.status === "error"
              ? "error"
              : finalView?.status === "success"
                ? "online"
                : "degraded",
            documentRef,
          },
        );
        renderManagementActionFeedback(
          finalView?.label || `${candidate.displayName} 후보 상태를 반영했습니다.`,
          {
            status: finalView?.status || "success",
            documentRef,
          },
        );
      } catch (error) {
        renderDiscoveryFeedback(
          error?.message || "후보 상태 변경에 실패했습니다.",
          {status: "error", documentRef},
        );
        renderManagementActionFeedback(
          error?.message || "후보 상태 변경에 실패했습니다.",
          {status: "error", documentRef},
        );
        button.disabled = false;
        button.setAttribute("aria-busy", "false");
      }
    },
  );
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
    if (button) setRegistrationStepGuarded(button.dataset.managementStep, documentRef);
  });
  byId("deviceOnboardingForm", documentRef)?.addEventListener("click", (event) => {
    if (event.target.closest?.("[data-management-next-step]")) {
      setRegistrationStepGuarded(managementState.registrationStep + 1, documentRef);
    }
    if (event.target.closest?.("[data-management-previous-step]")) {
      setRegistrationStep(managementState.registrationStep - 1, documentRef);
      renderRegistrationFeedback(`${managementState.registrationStep}단계로 돌아갔습니다.`, {
        status: "success",
        documentRef,
      });
    }
  });
  byId("deviceOnboardingForm", documentRef)?.addEventListener("input", (event) => {
    resetCompletedConnectionForFormEdit(event.target, documentRef);
    renderRegistrationReview(documentRef);
  });
  byId("deviceOnboardingForm", documentRef)?.addEventListener("change", (event) => {
    resetCompletedConnectionForFormEdit(event.target, documentRef);
    renderRegistrationReview(documentRef);
  });
  adapterSelect.addEventListener("change", () => {
    managementState.selectedAdapterId = adapterSelect.value;
    managementState.validation = null;
    managementState.operation = null;
    renderRuntimeSelection(documentRef);
    renderProtocolFields(documentRef);
    renderRegistrationReview(documentRef);
    const validation = byId("managementValidation", documentRef);
    clearElement(validation);
    if (validation) appendTextElement(validation, "p", "", "연결 검증을 실행하면 등록 계획을 표시합니다.");
    const operation = byId("managementOperation", documentRef);
    clearElement(operation);
    if (operation) appendTextElement(operation, "p", "", "아직 연결 작업을 실행하지 않았습니다.");
    renderRegistrationFeedback("프로토콜 패키지를 선택했습니다. 물리 연결 값을 확인하세요.", {
      status: "success",
      documentRef,
    });
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
    renderDeviceServiceInventory(documentRef);
    renderDiscovery(documentRef);
    renderManagedDevices(documentRef);
    renderRuntimeSelection(documentRef);
    renderProtocolFields(documentRef);
    renderManualNodeOptions(documentRef);
    clearElement(byId("managementValidation", documentRef));
    setSelectedPatchDevice("", documentRef);
    renderRegistrationReview(documentRef);
    renderManagementActionFeedback(`${managementState.selectedNodeName} 노드를 선택했습니다.`, {
      status: "success",
      kind: "navigation",
      documentRef,
    });
  });
  byId("managementHardwareBinding", documentRef)?.addEventListener("change", () => {
    syncRuntimeNodeFromBinding(documentRef);
    managementState.validation = null;
    renderProtocolFields(documentRef);
    renderConnectionGuidance(documentRef);
    renderRegistrationReview(documentRef);
    const applyButton = byId("managementApply", documentRef);
    if (applyButton) applyButton.disabled = true;
    renderRegistrationFeedback("물리 연결을 변경했습니다. 다시 검증해야 합니다.", {
      status: "warning",
      documentRef,
    });
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
  byId("managementValidate", documentRef)?.addEventListener("click", async () => {
    const button = byId("managementValidate", documentRef);
    try {
      if (!validateRegistrationThrough(4, documentRef)) return;
      setManagementButtonBusy(button, true, "검증 중…");
      renderRegistrationFeedback("연결 계획을 검증하는 중입니다.", {
        status: "waiting",
        documentRef,
      });
      renderManagementActionFeedback("디바이스 연결 계획 검증 중…", {
        status: "waiting",
        documentRef,
      });
      const operation = byId("managementOperation", documentRef);
      clearElement(operation);
      if (operation) appendTextElement(operation, "p", "", "검증 완료 후 연결 작업을 실행할 수 있습니다.");
      const payload = collectConnectionPayload(documentRef);
      managementState.validation = await validateManagementConnection(payload, fetchFn);
      managementState.runtimePlan = managementState.validation.runtimePlan || null;
      renderManagementValidation(managementState.validation, documentRef);
    } catch (error) {
      renderManagementError(error, documentRef);
      renderRegistrationFeedback(error?.message || "연결 검증에 실패했습니다.", {
        status: "error",
        documentRef,
      });
    } finally {
      setManagementButtonBusy(button, false);
    }
  });
  byId("managementApply", documentRef)?.addEventListener("click", async () => {
    const button = byId("managementApply", documentRef);
    try {
      if (!validateRegistrationThrough(4, documentRef)) return;
      setManagementButtonBusy(button, true, "연결 중…");
      renderRegistrationFeedback("런타임과 EdgeX 등록 상태를 확인하는 중입니다.", {
        status: "waiting",
        documentRef,
      });
      renderManagementActionFeedback("디바이스 연결 작업을 시작했습니다.", {
        status: "waiting",
        documentRef,
      });
      const payload = collectConnectionPayload(documentRef);
      const validation = await validateManagementConnection(payload, fetchFn);
      managementState.validation = validation;
      managementState.runtimePlan = validation.runtimePlan || null;
      renderManagementValidation(validation, documentRef);
      if (!validation.valid) return;
      const operation = await createManagementConnection(payload, {
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
      renderRegistrationFeedback("디바이스 연결 작업 결과를 확인했습니다.", {
        status: connectionStatusView(managementState.operation).terminal ? "success" : "waiting",
        documentRef,
      });
    } catch (error) {
      renderManagementError(error, documentRef);
      renderRegistrationFeedback(error?.message || "디바이스 연결에 실패했습니다.", {
        status: "error",
        documentRef,
      });
    } finally {
      setManagementButtonBusy(button, false);
      const view = connectionApplyButtonView(
        managementState.validation,
        managementState.operation,
        adapterCanApply(selectedAdapter()),
      );
      button.disabled = view.disabled;
      button.textContent = view.label;
      button.title = view.title;
    }
  });
  byId("managementRefresh", documentRef)?.addEventListener("click", () => {
    const button = byId("managementRefresh", documentRef);
    setManagementButtonBusy(button, true, "새로고침 중…");
    renderManagementActionFeedback("디바이스 관리 상태를 새로고침하는 중입니다.", {
      status: "waiting",
      documentRef,
    });
    loadDeviceManagement(documentRef, fetchFn)
      .then(() => {
        renderManagementActionFeedback("디바이스 관리 상태를 새로고침했습니다.", {
          status: "success",
          documentRef,
        });
      })
      .catch((error) => {
        renderManagementError(error, documentRef);
      })
      .finally(() => setManagementButtonBusy(button, false));
  });
  ["managedDeviceList", "managementFixtureDeviceList"].forEach((id) => {
    byId(id, documentRef)?.addEventListener("click", (event) => {
      const button = event.target.closest?.("[data-management-edit-device]");
      if (button) {
        setSelectedPatchDevice(button.dataset.managementEditDevice, documentRef);
        setManagementView("edit", documentRef);
      }
    });
  });
  byId("managementPatchDeviceSelect", documentRef)?.addEventListener("change", (event) => {
    setSelectedPatchDevice(event.target.value, documentRef);
  });
  byId("devicePatchForm", documentRef)?.addEventListener("input", () => {
    renderPatchDirtyState(documentRef);
  });
  byId("devicePatchForm", documentRef)?.addEventListener("change", () => {
    renderPatchDirtyState(documentRef);
  });
  const deleteDeviceDialog = byId(
    "managementDeleteDeviceDialog",
    documentRef,
  );
  byId("managementDeleteDevice", documentRef)?.addEventListener(
    "click",
    () => {
      const name = managementState.selectedPatchDeviceName;
      if (!name) {
        renderPatchResult("삭제할 디바이스를 먼저 선택하세요.", {
          status: "error",
          documentRef,
        });
        return;
      }
      const view = deviceDeleteTargetView(name);
      deleteDeviceDialog.dataset.deviceName = name;
      byId("managementDeleteDialogTitle", documentRef).textContent = view.title;
      byId("managementDeleteDialogSummary", documentRef).textContent = view.summary;
      const confirmInput = byId("managementDeleteDeviceConfirm", documentRef);
      confirmInput.value = "";
      confirmInput.placeholder = name;
      byId("managementConfirmDeleteDevice", documentRef).disabled = true;
      managementState.deviceDeleteKey = "";
      renderDeleteDeviceResult(
        `확인을 위해 ${name}을(를) 정확히 입력하세요.`,
        {status: "warning", documentRef},
      );
      if (typeof deleteDeviceDialog?.showModal === "function") {
        deleteDeviceDialog.showModal();
      } else {
        deleteDeviceDialog?.setAttribute("open", "");
      }
      confirmInput.focus();
    },
  );
  deleteDeviceDialog
    ?.querySelectorAll("[data-management-close-delete-dialog]")
    .forEach((button) => {
      button.addEventListener("click", () => {
        managementState.deviceDeleteKey = "";
        if (typeof deleteDeviceDialog.close === "function") {
          deleteDeviceDialog.close();
        } else {
          deleteDeviceDialog.removeAttribute("open");
        }
      });
    });
  byId("managementDeleteDeviceConfirm", documentRef)?.addEventListener(
    "input",
    (event) => {
      const exact = event.target.value
        === (deleteDeviceDialog?.dataset.deviceName || "");
      byId("managementConfirmDeleteDevice", documentRef).disabled = !exact;
      renderDeleteDeviceResult(
        exact
          ? "이름이 일치합니다. 삭제하면 되돌릴 수 없습니다."
          : "디바이스 이름이 정확히 일치해야 합니다.",
        {status: exact ? "warning" : "error", documentRef},
      );
    },
  );
  byId("managementDeleteDeviceForm", documentRef)?.addEventListener(
    "submit",
    async (event) => {
      event.preventDefault();
      const name = deleteDeviceDialog?.dataset.deviceName || "";
      const confirmInput = byId("managementDeleteDeviceConfirm", documentRef);
      const submit = byId("managementConfirmDeleteDevice", documentRef);
      if (!name || confirmInput.value !== name) {
        renderDeleteDeviceResult("디바이스 이름이 일치하지 않습니다.", {
          status: "error",
          documentRef,
        });
        return;
      }
      try {
        setManagementButtonBusy(submit, true, "삭제 중…");
        renderDeleteDeviceResult(`${name} 삭제를 진행 중입니다.`, {
          status: "waiting",
          documentRef,
        });
        renderManagementActionFeedback(`${name} 삭제 요청 중…`, {
          status: "waiting",
          documentRef,
        });
        managementState.deviceDeleteKey = (
          managementState.deviceDeleteKey
          || globalThis.crypto?.randomUUID?.()
          || `device-delete-${Date.now()}`
        );
        const candidate = registeredCandidateForDevice(name);
        if (candidate) {
          await decommissionCandidate(candidate.candidateId, {
            idempotencyKey: managementState.deviceDeleteKey,
            reason: `대시보드에서 ${name} 등록 연결을 삭제했습니다.`,
            fetchFn,
          });
        } else {
          await deleteManagementDevice(name, {
            idempotencyKey: managementState.deviceDeleteKey,
            fetchFn,
          });
        }
        await loadDeviceManagement(documentRef, fetchFn);
        setSelectedPatchDevice("", documentRef);
        renderManagementActionFeedback(`${name} 삭제를 확인했습니다.`, {
          status: "success",
          documentRef,
        });
        if (typeof deleteDeviceDialog.close === "function") {
          deleteDeviceDialog.close();
        } else {
          deleteDeviceDialog.removeAttribute("open");
        }
      } catch (error) {
        renderDeleteDeviceResult(
          error?.message || "디바이스 삭제에 실패했습니다.",
          {status: "error", documentRef},
        );
        renderManagementError(error, documentRef);
      } finally {
        setManagementButtonBusy(submit, false);
        submit.disabled = confirmInput.value !== name;
      }
    },
  );
  byId("managementDeviceServiceList", documentRef)?.addEventListener("click", async (event) => {
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
    setManagementButtonBusy(
      button,
      true,
      action === "restart" ? "재시작 중…" : "퇴역 중…",
    );
    renderManagementActionFeedback(`${name} 런타임 ${action === "restart" ? "재시작" : "퇴역"} 요청 중…`, {
      status: "waiting",
      documentRef,
    });
    try {
      const options = {
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
      setManagementButtonBusy(button, false);
    }
  });
  byId("devicePatchForm", documentRef)?.addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = byId("managementPatchApply", documentRef);
    try {
      const name = byId("patchDeviceName", documentRef).value.trim();
      if (!name) {
        renderPatchResult("수정할 디바이스를 먼저 선택하세요.", {
          status: "error",
          documentRef,
        });
        return;
      }
      if (!updatePatchDirtyState(documentRef)) {
        renderPatchResult("변경된 값이 없습니다.", {status: "warning", documentRef});
        return;
      }
      setManagementButtonBusy(button, true, "적용 중…");
      renderPatchResult(`${name} 변경 사항을 적용하는 중입니다.`, {
        status: "waiting",
        documentRef,
      });
      renderManagementActionFeedback(`${name} 디바이스 변경 요청 중…`, {
        status: "waiting",
        documentRef,
      });
      const result = await patchManagementDevice(name, collectPatchPayload(documentRef), {
        idempotencyKey: ensureIdempotencyInput(
          byId("patchIdempotencyKey", documentRef),
        ),
        fetchFn,
      });
      renderOperation(result, documentRef);
      await loadDeviceManagement(documentRef, fetchFn);
      setSelectedPatchDevice(name, documentRef);
      renderPatchResult(`${name} 변경 사항을 적용했습니다.`, {
        status: "success",
        documentRef,
      });
    } catch (error) {
      renderManagementError(error, documentRef);
      renderPatchResult(error?.message || "디바이스 변경에 실패했습니다.", {
        status: "error",
        documentRef,
      });
    } finally {
      setManagementButtonBusy(button, false);
      updatePatchDirtyState(documentRef);
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
    buildDeviceServiceObservations,
    buildPhysicalConnectionObservations,
    buildManagementNodeScopes,
    candidateEndpointSummary,
    candidateRegistrationStatusView,
    candidateVisibleInDefaultList,
    discoveryFilterStatusView,
    normalizeDiscoverySearchTerm,
    canPatchSelectedDevice,
    connectionStatusView,
    connectionApplyButtonView,
    createManualCandidate,
    createManagementConnection,
    createManagementDevice,
    decommissionCandidate,
    deleteCandidate,
    deleteManagementDevice,
    deviceDeleteTargetView,
    devicePurpose,
    fetchDiscoveryInventory,
    fetchAdapterRuntimes,
    fetchConnectionOperation,
    fetchManagementAdapters,
    fetchManagementNodes,
    fetchManagementOperation,
    managementApiUrl,
    managementDeviceNode,
    managementPayload,
    managementTabIndexForKey,
    mutationHeaders,
    normalizeManagementView,
    normalizeRegistrationStep,
    operationStatusView,
    patchManagementDevice,
    patchDirtyFeedback,
    planAdapterRuntime,
    pollCandidateRegistration,
    pollConnectionOperation,
    pollManagementOperation,
    preferredManagementNode,
    physicalObservationStatus,
    protocolPackageStatus,
    restartAdapterRuntime,
    retireAdapterRuntime,
    runtimeCanMutate,
    runtimePurpose,
    updateCandidateDecision,
    validateManagementConnection,
    validateManagementDevice,
  };
}
