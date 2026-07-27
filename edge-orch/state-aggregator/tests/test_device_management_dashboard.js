const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  adapterCanApply,
  adapterConnectionGuidance,
  adapterSelectionOptions,
  adapterSupportsNode,
  bindingProtocolValue,
  buildPhysicalConnectionObservations,
  buildManagementNodeScopes,
  candidateEndpointSummary,
  candidateVisibleInDefaultList,
  connectionApplyButtonView,
  canPatchSelectedDevice,
  connectionStatusView,
  createManualCandidate,
  createManagementConnection,
  createManagementDevice,
  deleteCandidate,
  fetchAdapterRuntimes,
  fetchDiscoveryInventory,
  fetchConnectionOperation,
  fetchManagementAdapters,
  fetchManagementNodes,
  fetchManagementOperation,
  managementApiUrl,
  managementDeviceNode,
  managementPayload,
  managementTabIndexForKey,
  normalizeManagementView,
  normalizeRegistrationStep,
  operationStatusView,
  patchManagementDevice,
  patchDirtyFeedback,
  planAdapterRuntime,
  pollConnectionOperation,
  pollManagementOperation,
  preferredManagementNode,
  protocolPackageStatus,
  restartAdapterRuntime,
  retireAdapterRuntime,
  runtimeCanMutate,
  updateCandidateDecision,
  validateManagementConnection,
  validateManagementDevice,
} = require("../app/static/device-management.js");
const {
  dashboardViewModeButtonCopy,
  normalizeDashboardViewMode,
} = require("../app/static/navigation.js");


test("management API keeps the external ingress prefix without hard-coding an IP", () => {
  assert.equal(
    managementApiUrl("/management/adapters", "/aggregator/dashboard"),
    "/aggregator/management/adapters",
  );
  assert.equal(
    managementApiUrl("/state/nodes", "/aggregator"),
    "/aggregator/state/nodes",
  );
  assert.equal(
    managementApiUrl("/management/adapters", "/dashboard"),
    "/management/adapters",
  );
});

function response(payload, {ok = true, status = 200} = {}) {
  return {
    ok,
    status,
    json: async () => payload,
  };
}


test("only mutable installed or verified installable adapters can be applied", () => {
  assert.equal(adapterCanApply({status: "installed", mutationEnabled: true}), true);
  assert.equal(adapterCanApply({status: "installable", mutationEnabled: true}), true);
  assert.equal(adapterCanApply({status: "installable", mutationEnabled: false}), false);
  assert.equal(adapterCanApply({status: "installed", mutationEnabled: false}), false);
  assert.equal(adapterCanApply({status: "unavailable", mutationEnabled: true}), false);
  assert.equal(adapterCanApply({status: "unsupported", mutationEnabled: true}), false);
  assert.equal(adapterCanApply(null), false);
});


test("loads adapter catalog without browser cache", async () => {
  let request = null;
  const fetchFn = async (url, options) => {
    request = {url, options};
    return response([{adapterId: "serial-jetson", status: "installed"}]);
  };

  const adapters = await fetchManagementAdapters(fetchFn);

  assert.deepEqual(request, {
    url: "/management/adapters",
    options: {cache: "no-store"},
  });
  assert.equal(adapters[0].adapterId, "serial-jetson");
});


test("loads KubeEdge node inventory without browser cache", async () => {
  let request = null;
  const fetchFn = async (url, options) => {
    request = {url, options};
    return response([{
      hostname: "etri-dev0001-jetorn",
      node_health: "available",
    }]);
  };

  const nodes = await fetchManagementNodes(fetchFn);

  assert.deepEqual(request, {
    url: "/state/nodes",
    options: {cache: "no-store"},
  });
  assert.equal(nodes[0].hostname, "etri-dev0001-jetorn");
});


test("builds node scopes from Kubernetes nodes, runtimes, devices, and approved bindings", () => {
  const scopes = buildManagementNodeScopes({
    nodes: [
      {
        hostname: "server2",
        node_health: "available",
        node_type: "cloud_server",
      },
      {hostname: "etri-dev0001-jetorn", node_health: "available"},
    ],
    runtimes: [
      {targetNode: "etri-dev0001-jetorn"},
      {targetNode: "etri-dev0003-raspi5"},
    ],
    devices: [
      {name: "serial-01", node_name: "etri-dev0001-jetorn"},
      {name: "sensehat-01", tags: {nodeName: "etri-dev0003-raspi5"}},
      {name: "legacy-01"},
    ],
    adapters: [
      {
        adapterId: "serial-jetson",
        runtime: {
          hardwareBindings: [{nodeName: "etri-dev0001-jetorn"}],
        },
      },
      {
        adapterId: "sensehat-raspi",
        runtime: {
          hardwareBindings: [{nodeName: "etri-dev0003-raspi5"}],
        },
      },
    ],
  });

  assert.deepEqual(
    scopes.map((scope) => scope.name),
    [
      "etri-dev0001-jetorn",
      "etri-dev0003-raspi5",
      "미할당 노드",
    ],
  );
  assert.deepEqual(
    scopes.find((scope) => scope.name === "etri-dev0001-jetorn"),
    {
      name: "etri-dev0001-jetorn",
      health: "available",
      observed: true,
      runtimeCount: 1,
      deviceCount: 1,
      adapterCount: 1,
    },
  );
  assert.equal(
    scopes.find((scope) => scope.name === "etri-dev0003-raspi5").observed,
    false,
  );
  assert.equal(
    scopes.find((scope) => scope.name === "미할당 노드").deviceCount,
    1,
  );
});


test("prefers a node with a live discovery report for the first management view", () => {
  const scopes = [
    {name: "jetson", runtimeCount: 1, adapterCount: 1},
    {name: "raspi", runtimeCount: 1, adapterCount: 1},
  ];
  assert.equal(
    preferredManagementNode(scopes, [
      {nodeName: "jetson", presence: "stale"},
      {nodeName: "raspi", presence: "online"},
    ]).name,
    "raspi",
  );
  assert.equal(preferredManagementNode(scopes, []).name, "jetson");
});


test("hides stale and rejected discovery noise until explicitly requested", () => {
  assert.equal(
    candidateVisibleInDefaultList({presence: "present", state: "DETECTED"}),
    true,
  );
  assert.equal(
    candidateVisibleInDefaultList({presence: "stale", state: "STALE"}),
    false,
  );
  assert.equal(
    candidateVisibleInDefaultList(
      {presence: "stale", state: "STALE"},
      {showStale: true},
    ),
    true,
  );
  assert.equal(
    candidateVisibleInDefaultList({presence: "present", state: "REJECTED"}),
    false,
  );
  assert.equal(
    candidateVisibleInDefaultList(
      {presence: "present", state: "REJECTED"},
      {includeIgnored: true},
    ),
    true,
  );
});


test("dashboard view mode defaults to simple and exposes clear toggle copy", () => {
  assert.equal(normalizeDashboardViewMode(), "simple");
  assert.equal(normalizeDashboardViewMode("unexpected"), "simple");
  assert.equal(normalizeDashboardViewMode("detailed"), "detailed");
  assert.deepEqual(dashboardViewModeButtonCopy("simple"), {
    label: "전체 보기",
    ariaLabel: "대시보드 전체 보기로 전환",
    pressed: false,
  });
  assert.deepEqual(dashboardViewModeButtonCopy("detailed"), {
    label: "간편 보기",
    ariaLabel: "대시보드 간편 보기로 전환",
    pressed: true,
  });
});


test("device patch stays disabled until a device in the selected node is chosen", () => {
  assert.equal(canPatchSelectedDevice(true, "virtual-temperature-001"), true);
  assert.equal(canPatchSelectedDevice(true, ""), false);
  assert.equal(canPatchSelectedDevice(false, "virtual-temperature-001"), false);
});


test("device patch feedback clears the dirty warning after values are restored", () => {
  assert.deepEqual(patchDirtyFeedback(true), {
    message: "변경 사항이 있습니다. 적용 버튼을 눌러 저장하세요.",
    status: "warning",
  });
  assert.deepEqual(patchDirtyFeedback(false), {
    message: "현재 저장된 값과 같습니다. 변경할 항목을 수정하세요.",
    status: "ready",
  });
  assert.deepEqual(patchDirtyFeedback(false, false), {
    message: "디바이스를 선택하고 값을 변경하면 적용할 수 있습니다.",
    status: "ready",
  });
});


test("management navigation only accepts known views and registration steps", () => {
  assert.equal(normalizeManagementView("discovery"), "discovery");
  assert.equal(normalizeManagementView("overview"), "overview");
  assert.equal(normalizeManagementView("register"), "register");
  assert.equal(normalizeManagementView("edit"), "edit");
  assert.equal(normalizeManagementView("unknown"), "overview");
  assert.equal(normalizeRegistrationStep(1), 1);
  assert.equal(normalizeRegistrationStep("4"), 4);
  assert.equal(normalizeRegistrationStep(0), 1);
  assert.equal(normalizeRegistrationStep(9), 1);
});


test("discovery inventory and token-free candidate mutations use the management BFF", async () => {
  const requests = [];
  const fetchFn = async (url, options = {}) => {
    requests.push({url, options});
    if (url.includes("?includeIgnored")) {
      return response({
        generatedAt: "2026-07-24T10:00:00Z",
        staleAfterSeconds: 90,
        nodes: [],
        candidates: [],
      });
    }
    return response({
      candidateId: "candidate-aaaaaaaaaaaaaaaaaaaaaaaa",
      source: "manual",
      nodeName: "edge-a",
      protocol: "mqtt",
      transport: "mqtts",
      displayName: "Line sensor",
      decision: "pending",
      presence: "declared",
      packageState: "verification-required",
      packageReason: "검증 필요",
      firstSeen: "2026-07-24T10:00:00Z",
      lastSeen: "2026-07-24T10:00:00Z",
      updatedAt: "2026-07-24T10:00:00Z",
    });
  };

  await fetchDiscoveryInventory(fetchFn);
  await createManualCandidate(
    {
      nodeName: "edge-a",
      protocol: "mqtt",
      transport: "mqtts",
      displayName: "Line sensor",
      properties: {
        Broker: "mqtts://broker.example:8883",
        Topic: "factory/line/temp",
      },
    },
    {idempotencyKey: "create-1", fetchFn},
  );
  await updateCandidateDecision(
    "candidate-aaaaaaaaaaaaaaaaaaaaaaaa",
    {decision: "accepted", note: "checked"},
    {idempotencyKey: "decision-1", fetchFn},
  );
  await deleteCandidate(
    "candidate-aaaaaaaaaaaaaaaaaaaaaaaa",
    {idempotencyKey: "delete-1", fetchFn},
  );

  assert.equal(
    requests[0].url,
    "/management/discovery?includeIgnored=true&limit=2000",
  );
  assert.equal(requests[1].url, "/management/discovery/manual");
  assert.equal("Authorization" in requests[1].options.headers, false);
  assert.equal(requests[1].options.headers["Idempotency-Key"], "create-1");
  assert.equal(requests[2].options.method, "PATCH");
  assert.equal(requests[3].options.method, "DELETE");
});

test("candidate decisions omit the Authorization header", async () => {
  let request = null;
  const fetchFn = async (url, options = {}) => {
    request = {url, options};
    return response({
      candidateId: "candidate-aaaaaaaaaaaaaaaaaaaaaaaa",
      source: "node-scan",
      nodeName: "edge-a",
      protocol: "serial",
      transport: "usb-serial",
      displayName: "Arduino",
      decision: "accepted",
      presence: "present",
      packageState: "registration-ready",
      packageReason: "검증 완료",
      firstSeen: "2026-07-24T10:00:00Z",
      lastSeen: "2026-07-24T10:00:00Z",
      updatedAt: "2026-07-24T10:00:00Z",
    });
  };

  await updateCandidateDecision(
    "candidate-aaaaaaaaaaaaaaaaaaaaaaaa",
    {decision: "accepted", note: "PoC 운영자 승인"},
    {idempotencyKey: "decision-request", fetchFn},
  );

  assert.equal(request.options.method, "PATCH");
  assert.equal(request.options.headers["Idempotency-Key"], "decision-request");
  assert.equal(
    Object.prototype.hasOwnProperty.call(request.options.headers, "Authorization"),
    false,
  );
});


test("discovery candidate cards show a safe protocol endpoint summary", () => {
  assert.equal(
    candidateEndpointSummary({
      protocol: "serial",
      devicePath: "/dev/serial/by-id/usb-Arduino",
      transport: "usb-serial",
    }),
    "/dev/serial/by-id/usb-Arduino",
  );
  assert.equal(
    candidateEndpointSummary({
      protocol: "mqtt",
      transport: "mqtts",
      properties: {
        Broker: "mqtts://broker.example:8883",
        Topic: "factory/line/temp",
      },
    }),
    "mqtts://broker.example:8883 · factory/line/temp",
  );
  assert.equal(
    candidateEndpointSummary({
      protocol: "modbus",
      transport: "modbus-tcp",
      properties: {Mode: "tcp", Host: "plc-01.local", Port: 502, UnitID: 1},
    }),
    "tcp · plc-01.local:502 · Unit 1",
  );
});


test("management tabs support wrapped arrow and boundary keyboard navigation", () => {
  assert.equal(managementTabIndexForKey("ArrowRight", 3, 4), 0);
  assert.equal(managementTabIndexForKey("ArrowLeft", 0, 4), 3);
  assert.equal(managementTabIndexForKey("Home", 3, 4), 0);
  assert.equal(managementTabIndexForKey("End", 0, 4), 3);
  assert.equal(managementTabIndexForKey("Enter", 1, 4), null);
  assert.equal(managementTabIndexForKey("ArrowRight", 0, 0), null);
  assert.equal(managementTabIndexForKey("ArrowRight", -1, 3), null);
});


test("node scope recognizes device node aliases and only matching approved bindings", () => {
  assert.equal(
    managementDeviceNode({node_name: "edge-a", tags: {nodeName: "wrong"}}),
    "edge-a",
  );
  assert.equal(
    managementDeviceNode({tags: {nodeName: "edge-b"}}),
    "edge-b",
  );
  assert.equal(managementDeviceNode({}), "미할당 노드");

  const adapter = {
    status: "installed",
    runtime: {
      hardwareBindings: [
        {bindingId: "edge-a-serial", nodeName: "edge-a"},
      ],
    },
  };
  assert.equal(adapterSupportsNode(adapter, "edge-a"), true);
  assert.equal(adapterSupportsNode(adapter, "edge-b"), false);
  assert.equal(
    adapterSupportsNode({...adapter, status: "unsupported"}, "edge-a"),
    false,
  );
});


test("protocol choices stay visible while only node-ready Device Services are selectable", () => {
  const options = adapterSelectionOptions(
    [
      {
        adapterId: "serial-jetson",
        displayName: "Jetson Arduino Serial",
        protocolName: "serial",
        status: "installed",
        runtime: {
          hardwareBindings: [{nodeName: "edge-a"}],
        },
      },
      {
        adapterId: "sensehat-raspi",
        displayName: "Sense HAT",
        protocolName: "i2c",
        status: "installed",
        runtime: {
          hardwareBindings: [{nodeName: "edge-b"}],
        },
      },
      {
        adapterId: "modbus",
        displayName: "Modbus",
        protocolName: "modbus",
        status: "unsupported",
        reason: "실장비 검증 전",
      },
    ],
    "edge-a",
  );

  assert.deepEqual(
    options.map((option) => ({
      adapterId: option.adapter.adapterId,
      enabled: option.enabled,
      availability: option.availability,
    })),
    [
      {
        adapterId: "serial-jetson",
        enabled: true,
        availability: "기존 Device Service 재사용",
      },
      {
        adapterId: "sensehat-raspi",
        enabled: false,
        availability: "다른 노드에만 연결 등록됨",
      },
      {
        adapterId: "modbus",
        enabled: false,
        availability: "지원 준비 필요",
      },
    ],
  );
});


test("physical connection observation separates registration, presence, communication, and data", () => {
  const adapters = [{
    adapterId: "serial-jetson",
    displayName: "Jetson Arduino Serial",
    serviceName: "device-serial-jetson",
    protocolName: "serial",
    status: "installed",
    runtime: {
      hardwareBindings: [{
        bindingId: "jetson-arduino-serial-001",
        displayName: "Jetson Arduino USB Serial",
        nodeName: "edge-a",
        devicePath: "/dev/arduino-001",
        protocolProperties: {
          Port: "/dev/arduino-001",
          BaudRate: 115200,
          DeviceID: "arduino-001",
        },
      }],
    },
  }];
  const runtimes = [{
    adapterId: "serial-jetson",
    runtimeName: "device-serial-jetson",
    serviceName: "device-serial-jetson",
    targetNode: "edge-a",
    hardwareBindingId: "jetson-arduino-serial-001",
    hardwareBindingIds: ["jetson-arduino-serial-001"],
    phase: "SERVICE_READY",
    edgeXServiceObserved: true,
  }];
  const devices = [{
    name: "virtual-temperature-001",
    node_name: "edge-a",
    device_service_name: "device-serial-jetson",
    protocol_names: ["serial"],
    physical_device_id: "arduino-001",
    hardware_binding_id: "jetson-arduino-serial-001",
    admin_state: "UNLOCKED",
    operating_state: "UP",
    telemetry_freshness: "fresh",
    latest_event_timestamp: "2026-07-23T10:00:00Z",
  }];

  const [observed] = buildPhysicalConnectionObservations({
    adapters,
    runtimes,
    devices,
    nodeName: "edge-a",
  });

  assert.equal(observed.registrationState, "registered");
  assert.equal(observed.presenceState, "detected");
  assert.equal(observed.communicationState, "connected");
  assert.equal(observed.telemetryState, "fresh");
  assert.equal(observed.runtimeState, "ready");
  assert.equal(observed.deviceCount, 1);
  assert.deepEqual(observed.deviceNames, ["virtual-temperature-001"]);
  assert.match(observed.reason, /Device Service 연결과 최신 Event/);
});


test("registered connection does not claim physical presence without EdgeX evidence", () => {
  const adapters = [{
    adapterId: "serial-jetson",
    serviceName: "device-serial-jetson",
    protocolName: "serial",
    status: "installed",
    runtime: {
      hardwareBindings: [{
        bindingId: "edge-a-serial",
        displayName: "Serial candidate",
        nodeName: "edge-a",
        protocolProperties: {DeviceID: "sensor-01"},
      }],
    },
  }];

  const [unknown] = buildPhysicalConnectionObservations({
    adapters,
    runtimes: [],
    devices: [],
    nodeName: "edge-a",
  });
  assert.equal(unknown.registrationState, "registered");
  assert.equal(unknown.presenceState, "unknown");
  assert.equal(unknown.communicationState, "unknown");
  assert.equal(unknown.telemetryState, "unknown");
  assert.match(unknown.reason, /등록되어 있지만 실제 장비 관측 증거가 없습니다/);

  const [down] = buildPhysicalConnectionObservations({
    adapters,
    runtimes: [{
      adapterId: "serial-jetson",
      runtimeName: "device-serial-jetson",
      serviceName: "device-serial-jetson",
      targetNode: "edge-a",
      hardwareBindingIds: ["edge-a-serial"],
      phase: "SERVICE_READY",
      edgeXServiceObserved: true,
    }],
    devices: [{
      name: "virtual-sensor-01",
      node_name: "edge-a",
      device_service_name: "device-serial-jetson",
      protocol_names: ["serial"],
      physical_device_id: "sensor-01",
      operating_state: "DOWN",
      admin_state: "UNLOCKED",
      telemetry_freshness: "no_events",
    }],
    nodeName: "edge-a",
  });
  assert.equal(down.presenceState, "not_detected");
  assert.equal(down.communicationState, "disconnected");
  assert.equal(down.telemetryState, "missing");
});


test("protocol package state distinguishes reuse, install, connection registration, and verification", () => {
  const reusable = {
    adapterId: "serial",
    status: "installed",
    runtime: {
      verificationState: "hardware-verified",
      deploymentEnabled: false,
      hardwareBindings: [{bindingId: "serial-a", nodeName: "edge-a"}],
    },
  };
  const installable = {
    adapterId: "modbus",
    status: "installable",
    runtime: {
      verificationState: "template-verified",
      deploymentEnabled: true,
      hardwareBindings: [{bindingId: "modbus-a", nodeName: "edge-a"}],
    },
  };
  const unverified = {
    adapterId: "opcua",
    status: "unsupported",
    runtime: {
      verificationState: "unverified",
      deploymentEnabled: false,
      hardwareBindings: [],
    },
  };

  assert.deepEqual(
    protocolPackageStatus(reusable, "edge-a", []),
    {
      state: "reuse_ready",
      action: "reuse",
      label: "재사용 가능",
      reason: "등록된 Device Service와 물리 연결을 재사용합니다.",
    },
  );
  assert.deepEqual(
    protocolPackageStatus(installable, "edge-a", []),
    {
      state: "install_ready",
      action: "install",
      label: "설치 가능",
      reason: "검증된 Device Service 패키지를 이 노드에 설치할 수 있습니다.",
    },
  );
  assert.equal(
    protocolPackageStatus(reusable, "edge-b", []).state,
    "connection_required",
  );
  assert.equal(
    protocolPackageStatus(unverified, "edge-a", []).state,
    "verification_required",
  );
});


test("binding values override adapter defaults and explain a second Serial endpoint", () => {
  const binding = {
    protocolProperties: {
      Port: "/dev/arduino-002",
      BaudRate: 57600,
      DeviceID: "arduino-002",
    },
  };
  assert.deepEqual(
    bindingProtocolValue({name: "Port", default: "/dev/arduino-001"}, binding),
    {value: "/dev/arduino-002", locked: true},
  );
  assert.deepEqual(
    bindingProtocolValue({name: "ResourceName", default: "temperature_raw"}, binding),
    {value: "temperature_raw", locked: false},
  );

  const guidance = adapterConnectionGuidance({
    protocolName: "serial",
    serviceName: "device-serial-jetson",
    status: "installed",
    runtime: {
      reusePolicy: {
        multiDevice: true,
        bindingFields: ["Port", "BaudRate", "DeviceID"],
        routeFields: ["ResourceName"],
      },
    },
  }, 1);

  assert.equal(guidance.title, "Serial 다중 연결 방식");
  assert.match(guidance.text, /같은 USB 포트/);
  assert.match(guidance.text, /두 번째 USB Serial/);
  assert.match(guidance.text, /Pod 장치 마운트/);
  assert.match(guidance.text, /포맷이 다르면 parser/);
});


test("loads runtime inventory and plans without mutation credentials", async () => {
  const requests = [];
  const fetchFn = async (url, options) => {
    requests.push({url, options});
    if (url.endsWith("/plan")) {
      return response({action: "REUSE", allowed: true, planHash: "a".repeat(64)});
    }
    return response([{runtimeName: "device-serial-jetson", managementMode: "external"}]);
  };
  const payload = {
    adapterId: "serial-jetson",
    targetNode: "etri-dev0001-jetorn",
    hardwareBindingId: "jetson-arduino-serial-001",
    mode: "auto",
  };

  const runtimes = await fetchAdapterRuntimes(fetchFn);
  const plan = await planAdapterRuntime(payload, fetchFn);

  assert.equal(runtimes[0].runtimeName, "device-serial-jetson");
  assert.equal(plan.action, "REUSE");
  assert.deepEqual(requests[0], {
    url: "/management/adapter-runtimes",
    options: {cache: "no-store"},
  });
  assert.equal(requests[1].url, "/management/adapter-runtimes/plan");
  assert.deepEqual(requests[1].options.headers, {"Content-Type": "application/json"});
  assert.equal("Authorization" in requests[1].options.headers, false);
});


test("only controller-owned enabled runtime can mutate", () => {
  assert.equal(runtimeCanMutate({
    managementMode: "controller",
    mutable: true,
    mutationEnabled: true,
  }), true);
  assert.equal(runtimeCanMutate({
    managementMode: "external",
    mutable: true,
    mutationEnabled: true,
  }), false);
  assert.equal(runtimeCanMutate({
    managementMode: "controller",
    mutable: true,
    mutationEnabled: false,
  }), false);
  assert.equal(runtimeCanMutate(null), false);
});


test("dry-run posts no authentication or mutation headers", async () => {
  let request = null;
  const payload = {adapterId: "serial-jetson", device: {name: "device-01"}};
  const fetchFn = async (url, options) => {
    request = {url, options};
    return response({valid: true, issues: [], plan: {mutations: ["create_device"]}});
  };

  const result = await validateManagementDevice(payload, fetchFn);

  assert.equal(result.valid, true);
  assert.equal(request.url, "/management/devices/validate");
  assert.equal(request.options.method, "POST");
  assert.deepEqual(request.options.headers, {"Content-Type": "application/json"});
  assert.deepEqual(JSON.parse(request.options.body), payload);
  assert.equal("Authorization" in request.options.headers, false);
  assert.equal("Idempotency-Key" in request.options.headers, false);
});


test("create sends idempotency without an Authorization header", async () => {
  let request = null;
  const payload = {adapterId: "serial-jetson", device: {name: "device-01"}};
  const fetchFn = async (url, options) => {
    request = {url, options};
    return response({requestId: "request-01", status: "waiting_for_event"}, {status: 201});
  };

  const result = await createManagementDevice(payload, {
    idempotencyKey: "retry-key",
    fetchFn,
  });

  assert.equal(result.requestId, "request-01");
  assert.equal(request.url, "/management/devices");
  assert.equal("Authorization" in request.options.headers, false);
  assert.equal(request.options.headers["Idempotency-Key"], "retry-key");
  assert.doesNotMatch(request.options.body, /retry-key/);
});


test("connection validate is read-only and apply uses idempotency headers", async () => {
  const requests = [];
  const payload = {
    adapterId: "serial-jetson",
    runtime: {
      mode: "auto",
      targetNode: "etri-dev0001-jetorn",
      hardwareBindingId: "jetson-arduino-serial-001",
    },
    device: {name: "virtual-temperature-002"},
    profile: {mode: "existing", name: "etri-arduino-temperature"},
  };
  const fetchFn = async (url, options) => {
    requests.push({url, options});
    return response(
      url.endsWith("/validate")
        ? {valid: true, runtimePlan: {action: "REUSE"}}
        : {requestId: "connection-01", status: "WAITING_EVENT"},
      {status: url.endsWith("/validate") ? 200 : 201},
    );
  };

  await validateManagementConnection(payload, fetchFn);
  await createManagementConnection(payload, {
    idempotencyKey: "connection-key",
    fetchFn,
  });

  assert.equal(requests[0].url, "/management/connections/validate");
  assert.equal("Authorization" in requests[0].options.headers, false);
  assert.equal(requests[1].url, "/management/connections");
  assert.equal("Authorization" in requests[1].options.headers, false);
  assert.equal(requests[1].options.headers["Idempotency-Key"], "connection-key");
  assert.doesNotMatch(requests[1].options.body, /connection-key/);
});


test("runtime restart and retire use idempotency and exact confirmation", async () => {
  const requests = [];
  const fetchFn = async (url, options) => {
    requests.push({url, options});
    return response({runtimeName: "adapter-serial-02", phase: "SERVICE_READY"});
  };

  await restartAdapterRuntime("adapter-serial-02", {
    idempotencyKey: "restart-key",
    fetchFn,
  });
  await retireAdapterRuntime("adapter-serial-02", {
    idempotencyKey: "retire-key",
    fetchFn,
  });

  assert.equal(requests[0].options.method, "POST");
  assert.equal("Authorization" in requests[0].options.headers, false);
  assert.equal(requests[1].options.method, "DELETE");
  assert.equal(
    requests[1].options.headers["X-Confirm-Runtime"],
    "adapter-serial-02",
  );
});


test("patch URL-encodes device identity and uses idempotency headers", async () => {
  let request = null;
  const fetchFn = async (url, options) => {
    request = {url, options};
    return response({requestId: "patch-01", action: "patch", status: "verified"});
  };

  await patchManagementDevice(
    "device / 01",
    {description: "updated"},
    {idempotencyKey: "patch-key", fetchFn},
  );

  assert.equal(request.url, "/management/devices/device%20%2F%2001");
  assert.equal(request.options.method, "PATCH");
  assert.equal("Authorization" in request.options.headers, false);
  assert.equal(request.options.headers["Idempotency-Key"], "patch-key");
});


test("management errors preserve safe server detail", async () => {
  const fetchFn = async () => response(
    {detail: {requestId: "request-01", status: "failed", message: "apply failed"}},
    {ok: false, status: 502},
  );

  await assert.rejects(
    createManagementDevice({}, {
      idempotencyKey: "retry-key",
      fetchFn,
    }),
    /apply failed/,
  );
});

test("validation errors identify the invalid request fields", async () => {
  await assert.rejects(
    managementPayload(response(
      {
        detail: [
          {loc: ["body", "device", "name"], msg: "Field required", type: "missing"},
          {loc: ["body", "profile", "name"], msg: "Field required", type: "missing"},
        ],
      },
      {ok: false, status: 422},
    )),
    /device\.name: Field required · profile\.name: Field required/,
  );
});


test("operation status distinguishes metadata wait, verified, and failure", () => {
  assert.deepEqual(operationStatusView({status: "waiting_for_event"}), {
    label: "첫 이벤트 대기",
    tone: "waiting",
    detail: "EdgeX 메타데이터 적용 완료 · 첫 Core Data 이벤트 대기",
    terminal: false,
  });
  assert.equal(operationStatusView({status: "verified"}).terminal, true);
  assert.match(operationStatusView({status: "verified"}).detail, /이벤트 검증 완료/);
  assert.equal(operationStatusView({status: "failed"}).terminal, true);
  assert.match(operationStatusView({status: "failed", error: "readback mismatch"}).detail, /readback mismatch/);
  assert.match(
    operationStatusView({status: "waiting_for_event", error: "Core Data unavailable"}).detail,
    /Core Data unavailable/,
  );
});


test("connection status separates runtime, metadata, event, and terminal states", () => {
  assert.match(
    connectionStatusView({status: "RUNTIME_REQUESTED"}).detail,
    /런타임/,
  );
  assert.equal(
    connectionStatusView({status: "WAITING_EVENT"}).terminal,
    false,
  );
  assert.equal(connectionStatusView({status: "ACTIVE"}).terminal, true);
  assert.equal(connectionStatusView({status: "FAILED"}).terminal, true);
  assert.equal(connectionStatusView({status: "COMPENSATED"}).terminal, true);
});


test("completed registration disables duplicate apply until the form changes", () => {
  assert.deepEqual(
    connectionApplyButtonView(
      {valid: true},
      {status: "ACTIVE"},
      true,
    ),
    {
      disabled: true,
      label: "연결 완료",
      title: "EdgeX 등록과 첫 Event 검증이 완료되었습니다. 다른 연결을 등록하려면 입력값을 변경하세요.",
    },
  );
  assert.deepEqual(
    connectionApplyButtonView({valid: true}, null, true),
    {
      disabled: false,
      label: "디바이스 연결",
      title: "",
    },
  );
});


test("connection polling stops when ACTIVE", async () => {
  const payloads = [
    {requestId: "connection-01", status: "RUNTIME_REQUESTED"},
    {requestId: "connection-01", status: "WAITING_EVENT"},
    {requestId: "connection-01", status: "ACTIVE"},
  ];
  const urls = [];
  const fetchFn = async (url) => {
    urls.push(url);
    return response(payloads.shift());
  };

  const result = await pollConnectionOperation("connection-01", {
    fetchFn,
    sleepFn: async () => {},
    maxAttempts: 4,
  });

  assert.equal(result.status, "ACTIVE");
  assert.deepEqual(urls, [
    "/management/connections/operations/connection-01",
    "/management/connections/operations/connection-01",
    "/management/connections/operations/connection-01",
  ]);
});


test("fetches one connection operation without cache", async () => {
  let options = null;
  const fetchFn = async (_url, requestOptions) => {
    options = requestOptions;
    return response({requestId: "connection-01", status: "ACTIVE"});
  };

  await fetchConnectionOperation("connection-01", fetchFn);

  assert.deepEqual(options, {cache: "no-store"});
});


test("polling stops when first Event verification becomes terminal", async () => {
  const payloads = [
    {requestId: "request-01", status: "waiting_for_event"},
    {requestId: "request-01", status: "verified"},
  ];
  const urls = [];
  let sleeps = 0;
  const fetchFn = async (url) => {
    urls.push(url);
    return response(payloads.shift());
  };

  const result = await pollManagementOperation("request-01", {
    fetchFn,
    sleepFn: async () => { sleeps += 1; },
    maxAttempts: 3,
  });

  assert.equal(result.status, "verified");
  assert.equal(sleeps, 1);
  assert.deepEqual(urls, [
    "/management/operations/request-01",
    "/management/operations/request-01",
  ]);
});


test("fetches one operation without cache", async () => {
  let options = null;
  const fetchFn = async (_url, requestOptions) => {
    options = requestOptions;
    return response({requestId: "request-01", status: "verified"});
  };

  await fetchManagementOperation("request-01", fetchFn);

  assert.deepEqual(options, {cache: "no-store"});
});


test("dashboard ships an accessible token-free device management page", () => {
  const root = path.resolve(__dirname, "..");
  const html = fs.readFileSync(path.join(root, "app/static/index.html"), "utf8");
  const css = fs.readFileSync(path.join(root, "app/static/device-management.css"), "utf8");
  const simpleCss = fs.readFileSync(path.join(root, "app/static/simple-mode.css"), "utf8");
  const javascript = fs.readFileSync(path.join(root, "app/static/device-management.js"), "utf8");

  assert.match(html, /data-dashboard-page="management"/);
  assert.match(html, /data-page="management"/);
  for (const id of [
    "managementNodeList",
    "managementSelectedNode",
    "managementAdapterList",
    "managementPhysicalConnectionList",
    "managementConnectionLegend",
    "managementRuntimeList",
    "managementRuntimeMode",
    "managementTargetNode",
    "managementHardwareBinding",
    "deviceOnboardingForm",
    "managementAdapter",
    "managementConnectionGuidance",
    "managementProtocolFields",
    "managementValidation",
    "managementOperation",
    "managementActionFeedback",
    "managementRegistrationFeedback",
    "managementPatchResult",
    "managementMutationMode",
    "managedDeviceList",
    "devicePatchForm",
    "managementViewTabs",
    "managementOverviewPanel",
    "managementRegisterPanel",
    "managementEditPanel",
    "managementRegistrationStepper",
    "managementRegistrationStep1",
    "managementRegistrationStep2",
    "managementRegistrationStep3",
    "managementRegistrationStep4",
    "managementPatchDeviceSelect",
    "managementUnsupportedAdapterList",
    "managementDiscoveryPanel",
    "managementDiscoveryList",
    "managementDiscoverySearch",
    "managementDiscoveryProtocolFilter",
    "managementDiscoveryDecisionFilter",
    "managementDiscoveryShowStale",
    "managementOpenManualCandidate",
    "managementManualCandidateDialog",
    "managementManualCandidateForm",
    "managementManualProtocolFields",
  ]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /id="managementPatchApply"[^>]+disabled/);
  assert.match(html, /<body data-view-mode="simple">/);
  assert.match(html, /id="dashboardViewModeToggle"/);
  assert.match(html, /simple-mode\.css\?v=simple-dashboard-20260727/);
  assert.match(html, /device-management\.css\?v=simple-dashboard-20260727/);
  assert.match(html, /device-management\.js\?v=simple-dashboard-20260727/);
  assert.doesNotMatch(html, /managementAdminToken|managementDiscoveryAdminToken/);
  assert.doesNotMatch(html, /관리자 Bearer 토큰/);
  assert.doesNotMatch(javascript, /Authorization\s*:\s*`Bearer/);
  assert.match(html, />장비 연결</);
  assert.match(html, /장비 연결 관리/);
  assert.match(html, /관리할 엣지 노드/);
  assert.match(html, /연결 후보 찾기/);
  assert.match(html, /엔드포인트 직접 추가/);
  assert.match(html, /선택 노드의 런타임/);
  assert.match(html, /등록 연결과 실제 장비 상태/);
  assert.match(html, /연결 구성 마법사/);
  assert.match(html, /새 디바이스 등록/);
  assert.match(html, /연결 프로토콜 · Device Service/);
  assert.match(html, /Device Service 준비 방식/);
  assert.match(html, /설치 전 확인이 필요한 프로토콜/);
  assert.match(html, /등록된 물리 연결/);
  assert.doesNotMatch(html, /승인된 하드웨어 연결/);
  assert.match(html, /기존 EdgeX 디바이스/);
  assert.match(css, /@media \(max-width: 760px\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /\.management-view-tabs/);
  assert.match(css, /\.management-stepper/);
  assert.match(css, /\.management-node-card/);
  assert.match(css, /\.management-runtime-card/);
  assert.match(css, /\.management-physical-card/);
  assert.match(css, /\.management-candidate-card/);
  assert.match(css, /\.management-discovery-filters/);
  assert.match(css, /\.management-dialog/);
  assert.match(css, /body\[data-dashboard-page="management"\] \.side-rail/);
  assert.doesNotMatch(javascript, /localStorage|sessionStorage/);
  assert.doesNotMatch(javascript, /\.innerHTML\s*=/);
  assert.match(javascript, /function renderManagementValidation\(/);
  assert.match(javascript, /function validateRegistrationThrough\(/);
  assert.match(javascript, /function renderManagementActionFeedback\(/);
  assert.match(javascript, /function renderPatchResult\(/);
  assert.match(javascript, /function renderRuntimeInventory\(/);
  assert.match(javascript, /function renderDiscoveryCandidates\(/);
  assert.match(javascript, /등록 물리 연결/);
  assert.doesNotMatch(javascript, /function renderValidation\(/);
  assert.match(simpleCss, /body\[data-view-mode="simple"\] \.dashboard-detail/);
  assert.match(simpleCss, /body\[data-view-mode="simple"\] \.management-node-card-facts/);
  assert.match(simpleCss, /@media \(max-width: 760px\)/);
  assert.match(simpleCss, /@media \(prefers-reduced-motion: reduce\)/);
});
