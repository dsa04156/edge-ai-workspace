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
  buildDeviceServiceObservations,
  buildPhysicalConnectionObservations,
  buildManagementNodeScopes,
  candidateActionItems,
  candidateSetupLock,
  candidateEndpointSummary,
  candidateRegistrationStatusView,
  candidateVisibleInDefaultList,
  discoveryFilterStatusView,
  normalizeDiscoverySearchTerm,
  connectionApplyButtonView,
  canPatchSelectedDevice,
  connectionStatusView,
  createManagementProfile,
  createManualCandidate,
  createManagementConnection,
  createManagementDevice,
  decommissionCandidate,
  deleteCandidate,
  deleteManagementDevice,
  deviceDeleteTargetView,
  devicePurpose,
  fetchAdapterRuntimes,
  fetchDiscoveryInventory,
  fetchConnectionOperation,
  fetchManagementAdapters,
  fetchManagementNodes,
  fetchManagementOperation,
  fetchManagementProfiles,
  managementApiUrl,
  managementDeviceNode,
  managementPayload,
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
  profileDraftFromCandidate,
  profilePayloadFingerprint,
  profileSafeName,
  protocolPackageStatus,
  restartAdapterRuntime,
  retireAdapterRuntime,
  runtimeCanMutate,
  runtimePurpose,
  updateCandidateDecision,
  validateManagementConnection,
  validateManagementDevice,
  validateManagementProfile,
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


test("lists, validates, and creates Device Profiles through the token-free BFF", async () => {
  const requests = [];
  const profile = {
    name: "arduino-multisensor-v1",
    description: "Arduino multisensor",
    manufacturer: "Arduino",
    model: "uno-r4",
    labels: ["serial"],
    resources: [{
      name: "temperature",
      valueType: "Float64",
      units: "Cel",
      description: "Temperature",
    }],
  };
  const fetchFn = async (url, options = {}) => {
    requests.push({url, options});
    if (options.method === "POST" && url.endsWith("/validate")) {
      return response({
        valid: true,
        issues: [],
        warnings: [],
        profile: {deviceResources: [{}]},
      });
    }
    if (options.method === "POST") {
      return response({
        requestId: "a".repeat(64),
        payloadHash: "b".repeat(64),
        name: profile.name,
        created: true,
        status: "created",
        profile: {name: profile.name},
      }, {status: 201});
    }
    return response([{
      name: profile.name,
      resourceCount: 1,
    }]);
  };

  const profiles = await fetchManagementProfiles(fetchFn);
  const validation = await validateManagementProfile(profile, fetchFn);
  const applied = await createManagementProfile(profile, {
    idempotencyKey: "profile-create-1",
    fetchFn,
  });

  assert.equal(profiles[0].name, profile.name);
  assert.equal(validation.valid, true);
  assert.equal(applied.status, "created");
  assert.deepEqual(requests[0], {
    url: "/management/profiles",
    options: {cache: "no-store"},
  });
  assert.equal(requests[1].url, "/management/profiles/validate");
  assert.equal(requests[1].options.method, "POST");
  assert.equal(requests[2].url, "/management/profiles");
  assert.equal(requests[2].options.headers["Idempotency-Key"], "profile-create-1");
  assert.equal(
    Object.prototype.hasOwnProperty.call(
      requests[2].options.headers,
      "Authorization",
    ),
    false,
  );
});


test("candidate Profile draft preserves identity hints but does not guess data types", () => {
  assert.equal(profileSafeName(" Arduino UNO / Temp "), "arduino-uno-temp");
  const draft = profileDraftFromCandidate({
    displayName: "UNO 환경 센서",
    protocol: "serial",
    vendor: "Arduino",
    model: "uno-multisensor",
    capabilities: ["temperature", "humidity", "temperature"],
  });

  assert.equal(draft.name, "uno-multisensor-v1");
  assert.equal(draft.manufacturer, "Arduino");
  assert.equal(draft.model, "uno-multisensor");
  assert.deepEqual(
    draft.resources.map((resource) => resource.name),
    ["temperature", "humidity"],
  );
  assert.ok(draft.resources.every((resource) => resource.valueType === ""));
  assert.notEqual(
    profilePayloadFingerprint({...draft, model: "uno-multisensor-v2"}),
    profilePayloadFingerprint(draft),
  );
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
      {
        targetNode: "etri-dev0001-jetorn",
        serviceName: "device-serial-jetson",
        purpose: "operational",
      },
      {
        targetNode: "etri-dev0001-jetorn",
        serviceName: "device-modbus_test",
        purpose: "development-fixture",
      },
      {
        targetNode: "etri-dev0003-raspi5",
        serviceName: "device-sensehat-raspi",
      },
    ],
    devices: [
      {
        name: "serial-01",
        node_name: "etri-dev0001-jetorn",
        device_service_name: "device-serial-jetson",
      },
      {
        name: "modbus-sim-01",
        node_name: "etri-dev0001-jetorn",
        device_service_name: "device-modbus_test",
      },
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
      fixtureRuntimeCount: 1,
      fixtureDeviceCount: 1,
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


test("hides completed, stale, and rejected discovery noise until requested", () => {
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
  assert.equal(
    candidateVisibleInDefaultList(
      {presence: "present", state: "EVENT_CONFIRMED"},
    ),
    false,
  );
  assert.equal(
    candidateVisibleInDefaultList(
      {presence: "present", state: "EVENT_CONFIRMED"},
      {showRegistered: true},
    ),
    true,
  );
});


test("candidate search ignores spacing and separators in device names", () => {
  assert.equal(
    normalizeDiscoverySearchTerm("가상 온도 센서 003"),
    normalizeDiscoverySearchTerm("가상온도센서-003"),
  );
  assert.equal(
    normalizeDiscoverySearchTerm("Modbus_TCP"),
    "modbustcp",
  );
});


test("discovery filter status explains hidden candidates and reset state", () => {
  assert.deepEqual(
    discoveryFilterStatusView({
      total: 1,
      visible: 0,
      search: "가상온도센서004",
    }),
    {
      active: true,
      hidden: 1,
      resetDisabled: false,
      label: "1개 중 0개 표시 · 검색 조건으로 1개 숨김",
    },
  );
  assert.deepEqual(
    discoveryFilterStatusView({total: 1, visible: 1}),
    {
      active: false,
      hidden: 0,
      resetDisabled: true,
      label: "1개 후보 표시",
    },
  );
  assert.equal(
    discoveryFilterStatusView({
      total: 2,
      visible: 2,
      showRegistered: true,
    }).resetDisabled,
    false,
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
  assert.equal(normalizeManagementView("discovery"), "overview");
  assert.equal(normalizeManagementView("overview"), "overview");
  assert.equal(normalizeManagementView("register"), "register");
  assert.equal(normalizeManagementView("edit"), "edit");
  assert.equal(normalizeManagementView("unknown"), "overview");
  assert.equal(normalizeRegistrationStep(1), 1);
  assert.equal(normalizeRegistrationStep("4"), 4);
  assert.equal(normalizeRegistrationStep(0), 1);
  assert.equal(normalizeRegistrationStep(9), 1);
});


test("device management uses one overview instead of separate menu tabs", () => {
  const root = path.resolve(__dirname, "..");
  const html = fs.readFileSync(path.join(root, "app/static/index.html"), "utf8");
  const javascript = fs.readFileSync(
    path.join(root, "app/static/device-management.js"),
    "utf8",
  );
  const overviewIndex = html.indexOf('id="managementOverviewPanel"');
  const deviceInventoryIndex = html.indexOf('id="managedDeviceTitle"');
  const discoveryIndex = html.indexOf('id="managementDiscoveryPanel"');

  assert.ok(overviewIndex >= 0);
  assert.ok(deviceInventoryIndex > overviewIndex);
  assert.ok(discoveryIndex > deviceInventoryIndex);
  assert.doesNotMatch(html, /id="managementViewTabs"/);
  assert.doesNotMatch(html, /id="managementDiscoveryTab"/);
  assert.doesNotMatch(html, /id="managementRegisterTab"/);
  assert.doesNotMatch(html, /id="managementEditTab"/);
  assert.match(
    html,
    /id="managementOverviewPanel"[^>]+aria-label="등록 현황"[^>]+data-management-view-panel="overview">/,
  );
  assert.match(html, /id="managementDiscoveryTitle">연결 대기</);
  assert.match(html, /data-management-return-overview>등록 현황으로</);
  assert.match(html, /id="managementOpenProfileDialog"[^>]*>프로필 만들기</);
  assert.match(html, /id="managementProfileDialog"/);
  assert.match(html, /id="managementProfileResourceRows"/);
  assert.match(html, /pattern="\[A-Za-z0-9\._~\\-\]\+"/);
  assert.match(javascript, /pattern: "\[A-Za-z0-9\._~\\\\-\]\+"/);
  assert.match(
    html,
    /command, parser, Device Service 이미지와 장치 경로는 이 화면에서 만들거나 변경하지 않습니다/,
  );
  assert.match(javascript, /activeView: "overview"/);
  assert.match(javascript, /deleteButton\.dataset\.managementDeleteDevice/);
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


test("candidate approval status explains automatic install and EdgeX registration", () => {
  assert.deepEqual(
    candidateRegistrationStatusView({state: "APPROVED"}),
    {
      label: "Device Service 설치 시작",
      status: "waiting",
      active: true,
      terminal: false,
    },
  );
  assert.equal(
    candidateRegistrationStatusView({state: "METADATA_REGISTERED"}).label,
    "EdgeX 등록 완료 · 첫 Event 확인 중",
  );
  assert.deepEqual(
    candidateRegistrationStatusView({state: "EVENT_CONFIRMED"}),
    {
      label: "자동 설치·등록 완료",
      status: "success",
      active: false,
      terminal: true,
    },
  );
});

test("blocked discovery candidates offer connection setup instead of only rejection", () => {
  assert.deepEqual(
    candidateActionItems({
      state: "BLOCKED",
      authState: "not_checked",
      packageState: "binding-required",
      packageReason: "stable identity와 Profile의 exact match가 필요합니다.",
      source: "node-scan",
    }),
    [
      {
        label: "연결 설정",
        action: "configure",
        title: "stable identity와 Profile의 exact match가 필요합니다.",
      },
      {label: "후보 거절", action: "ignore"},
    ],
  );
});

test("blocked candidate setup preserves its protocol instead of selecting an unrelated adapter", () => {
  assert.deepEqual(
    candidateSetupLock({
      protocol: "serial",
      registrationReady: false,
      packageReason: "stable identity와 Profile의 exact match가 필요합니다.",
    }),
    {
      label: "Serial / USB 후보 · Profile/연결 카탈로그 필요",
      title: "Serial / USB 연결 준비 필요",
      text: "stable identity와 Profile의 exact match가 필요합니다.",
    },
  );
  assert.equal(
    candidateSetupLock({protocol: "serial", registrationReady: true}),
    null,
  );
});

test("ready discovery candidates keep the explicit approval action", () => {
  assert.deepEqual(
    candidateActionItems({
      state: "PENDING_APPROVAL",
      registrationReady: true,
      source: "node-scan",
    }),
    [
      {label: "승인하고 자동 설치·등록", action: "accept"},
      {label: "후보 거절", action: "ignore"},
    ],
  );
});


test("candidate registration polling follows install through first Event", async () => {
  const states = ["APPROVED", "SERVICE_READY", "METADATA_REGISTERED", "EVENT_CONFIRMED"];
  const updates = [];
  let requestCount = 0;
  const fetchFn = async () => {
    const state = states[Math.min(requestCount, states.length - 1)];
    requestCount += 1;
    return response({
      nodes: [],
      candidates: [{
        candidateId: "candidate-aaaaaaaaaaaaaaaaaaaaaaaa",
        state,
      }],
      totalCandidates: 1,
      filteredCandidates: 1,
      staleAfterSeconds: 90,
    });
  };

  const result = await pollCandidateRegistration(
    "candidate-aaaaaaaaaaaaaaaaaaaaaaaa",
    {
      fetchFn,
      sleepFn: async () => {},
      intervalMs: 0,
      maxAttempts: 5,
      onUpdate: ({candidate}) => updates.push(candidate.state),
    },
  );

  assert.equal(result.candidate.state, "EVENT_CONFIRMED");
  assert.equal(result.timedOut, false);
  assert.deepEqual(updates, states);
  assert.equal(requestCount, 4);
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


test("protocol choices only show supported Device Services and enable node-ready bindings", () => {
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
      {
        adapterId: "opcua",
        displayName: "OPC-UA",
        protocolName: "opcua",
        status: "unavailable",
        reason: "Device Service 상태 확인 필요",
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

test("device service inventory merges runtime, adapter, and physical bindings into one row", () => {
  const adapters = [{
    adapterId: "serial-jetson",
    displayName: "Jetson Arduino Serial",
    serviceName: "device-serial-jetson",
    protocolName: "serial",
    runtime: {
      verificationState: "hardware-verified",
      hardwareBindings: [
        {
          bindingId: "serial-a",
          displayName: "Arduino A",
          nodeName: "edge-a",
          devicePath: "/dev/arduino-a",
          protocolProperties: {DeviceID: "arduino-a"},
        },
        {
          bindingId: "serial-b",
          displayName: "Arduino B",
          nodeName: "edge-a",
          devicePath: "/dev/arduino-b",
          protocolProperties: {DeviceID: "arduino-b"},
        },
      ],
    },
  }];
  const runtimes = [{
    adapterId: "serial-jetson",
    runtimeName: "device-serial-jetson",
    serviceName: "device-serial-jetson",
    targetNode: "edge-a",
    hardwareBindingIds: ["serial-a", "serial-b"],
    phase: "SERVICE_READY",
    edgeXServiceObserved: true,
    managementOwner: "argocd",
    verificationState: "hardware-verified",
  }];
  const devices = ["a", "b"].map((suffix) => ({
    name: `virtual-temperature-${suffix}`,
    node_name: "edge-a",
    device_service_name: "device-serial-jetson",
    protocol_names: ["serial"],
    physical_device_id: `arduino-${suffix}`,
    hardware_binding_id: `serial-${suffix}`,
    admin_state: "UNLOCKED",
    operating_state: "UP",
    connection_state: "connected",
    device_service_available: true,
    telemetry_freshness: "fresh",
    latest_event_timestamp: `2026-07-23T10:00:0${suffix === "a" ? 1 : 2}Z`,
  }));

  const services = buildDeviceServiceObservations({
    adapters,
    runtimes,
    devices,
    nodeName: "edge-a",
  });

  assert.equal(services.length, 1);
  assert.equal(services[0].serviceName, "device-serial-jetson");
  assert.equal(services[0].runtimeName, "device-serial-jetson");
  assert.equal(services[0].deviceCount, 2);
  assert.deepEqual(services[0].bindingIds, ["serial-a", "serial-b"]);
  assert.deepEqual(services[0].status, {state: "healthy", label: "정상"});
});

test("device service inventory includes a controller runtime without legacy adapter binding", () => {
  const [service] = buildDeviceServiceObservations({
    adapters: [{
      adapterId: "modbus",
      displayName: "Modbus",
      serviceName: null,
      protocolName: "modbus",
      runtime: {hardwareBindings: []},
    }],
    runtimes: [{
      adapterId: "modbus",
      runtimeName: "adapter-modbus-1234",
      serviceName: "device-modbus_1234",
      targetNode: "edge-a",
      hardwareBindingId: "modbus-a",
      phase: "SERVICE_READY",
      edgeXServiceObserved: true,
      managementOwner: "controller",
      purpose: "development-fixture",
      verificationState: "template-verified",
    }],
    devices: [{
      name: "motor-temperature-01",
      node_name: "edge-a",
      device_service_name: "device-modbus_1234",
      protocol_names: ["modbus-tcp"],
      admin_state: "UNLOCKED",
      operating_state: "UNKNOWN",
      connection_state: "unknown",
      device_service_available: false,
      telemetry_freshness: "fresh",
      latest_event_timestamp: "2026-07-23T10:00:00Z",
    }],
    nodeName: "edge-a",
  });

  assert.equal(service.serviceName, "device-modbus_1234");
  assert.equal(service.runtimeName, "adapter-modbus-1234");
  assert.equal(service.purpose, "development-fixture");
  assert.equal(service.runtimeState, "ready");
  assert.equal(service.telemetryState, "fresh");
  assert.deepEqual(service.status, {state: "warning", label: "확인 필요"});
});

test("device service inventory omits retired runtimes without registered devices", () => {
  const services = buildDeviceServiceObservations({
    adapters: [{
      adapterId: "modbus",
      serviceName: null,
      protocolName: "modbus",
      runtime: {
        hardwareBindings: [{
          bindingId: "modbus-a",
          displayName: "Modbus fixture",
          nodeName: "edge-a",
        }],
      },
    }],
    runtimes: [{
      adapterId: "modbus",
      runtimeName: "adapter-modbus-retired",
      serviceName: "device-modbus_retired",
      targetNode: "edge-a",
      hardwareBindingId: "modbus-a",
      phase: "RETIRED",
      purpose: "development-fixture",
    }],
    devices: [],
    nodeName: "edge-a",
  });

  assert.deepEqual(services, []);
});

test("device deletion only decommissions an exact controller candidate owner", () => {
  const candidate = {
    candidateId: `candidate-${"a".repeat(64)}`,
    state: "EVENT_CONFIRMED",
  };
  const devices = [
    {
      name: "legacy-temperature",
      device_service_name: "device-serial",
    },
    {
      name: "aggregate-arduino",
      device_service_name: "device-serial",
      controller_candidate_id: candidate.candidateId,
    },
  ];

  const legacy = deviceDeleteTargetView("legacy-temperature", {
    devices,
    candidates: [candidate],
  });
  const owned = deviceDeleteTargetView("aggregate-arduino", {
    devices,
    candidates: [candidate],
  });

  assert.equal(legacy.candidate, null);
  assert.equal(legacy.title, "EdgeX 디바이스 삭제");
  assert.equal(owned.candidate.candidateId, candidate.candidateId);
  assert.equal(owned.title, "등록 연결 전체 삭제");
});

test("runtime purpose explicitly separates operational hardware from fixtures", () => {
  assert.equal(runtimePurpose({purpose: "operational"}), "operational");
  assert.equal(
    runtimePurpose({purpose: "development-fixture"}),
    "development-fixture",
  );
  assert.equal(runtimePurpose({}), "operational");
  assert.equal(
    devicePurpose(
      {device_service_name: "device-modbus_test"},
      [{
        serviceName: "device-modbus_test",
        purpose: "development-fixture",
      }],
    ),
    "development-fixture",
  );
  assert.equal(
    devicePurpose(
      {device_service_name: "device-serial-jetson"},
      [{
        serviceName: "device-serial-jetson",
        purpose: "operational",
      }],
    ),
    "operational",
  );
});

test("physical connection card condenses healthy and degraded evidence", () => {
  assert.deepEqual(physicalObservationStatus({
    registrationState: "registered",
    presenceState: "detected",
    communicationState: "connected",
    telemetryState: "fresh",
    runtimeState: "ready",
  }), {state: "healthy", label: "정상"});
  assert.deepEqual(physicalObservationStatus({
    registrationState: "registered",
    presenceState: "detected",
    communicationState: "connected",
    telemetryState: "stale",
    runtimeState: "ready",
  }), {state: "warning", label: "데이터 지연"});
  assert.deepEqual(physicalObservationStatus({
    registrationState: "registered",
    presenceState: "not_detected",
    communicationState: "disconnected",
    telemetryState: "missing",
    runtimeState: "ready",
  }), {state: "error", label: "연결 끊김"});
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


test("device delete and candidate decommission require exact confirmation headers", async () => {
  const requests = [];
  const fetchFn = async (url, options) => {
    requests.push({url, options});
    return response({status: "verified", action: "delete"});
  };
  const candidateId = `candidate-${"a".repeat(24)}`;

  await deleteManagementDevice("device 01", {
    idempotencyKey: "device-delete-key",
    fetchFn,
  });
  await decommissionCandidate(candidateId, {
    idempotencyKey: "candidate-delete-key",
    reason: "fixture cleanup",
    fetchFn,
  });

  assert.equal(requests[0].url, "/management/devices/device%2001");
  assert.equal(requests[0].options.method, "DELETE");
  assert.equal(requests[0].options.headers["X-Confirm-Device"], "device 01");
  assert.equal(requests[0].options.headers["Idempotency-Key"], "device-delete-key");
  assert.equal(
    requests[1].url,
    `/management/discovery/${candidateId}/decommission`,
  );
  assert.equal(requests[1].options.method, "POST");
  assert.equal(
    requests[1].options.headers["X-Confirm-Candidate"],
    candidateId,
  );
  assert.deepEqual(
    JSON.parse(requests[1].options.body),
    {reason: "fixture cleanup"},
  );
  assert.equal("Authorization" in requests[1].options.headers, false);
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
  assert.deepEqual(
    operationStatusView({status: "verified", action: "delete"}),
    {
      label: "삭제 완료",
      tone: "verified",
      detail: "EdgeX Core Metadata 재조회에서 디바이스 삭제를 확인했습니다.",
      terminal: true,
    },
  );
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
    "managementDeviceServiceList",
    "managementFixtureServiceSection",
    "managementFixtureServiceList",
    "managementFixtureServiceCount",
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
    "managementFixtureDeviceSection",
    "managementFixtureDeviceList",
    "managementFixtureDeviceCount",
    "devicePatchForm",
    "managementOverviewPanel",
    "managementRegisterPanel",
    "managementEditPanel",
    "managementRegistrationStepper",
    "managementRegistrationStep1",
    "managementRegistrationStep2",
    "managementRegistrationStep3",
    "managementRegistrationStep4",
    "managementPatchDeviceSelect",
    "managementDeleteDevice",
    "managementDeleteDeviceDialog",
    "managementDeleteDeviceConfirm",
    "managementConfirmDeleteDevice",
    "managementDiscoveryPanel",
    "managementDiscoveryList",
    "managementDiscoverySearch",
    "managementDiscoveryProtocolFilter",
    "managementDiscoveryDecisionFilter",
    "managementDiscoveryFilterStatus",
    "managementDiscoveryResetFilters",
    "managementDiscoveryShowStale",
    "managementDiscoveryShowRegistered",
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
  assert.match(html, /simple-mode\.css\?v=device-management-unified-v2-20260728/);
  assert.match(html, /device-management\.css\?v=device-profile-editor-v2-20260728/);
  assert.match(html, /device-management\.js\?v=device-profile-editor-v2-20260728/);
  assert.doesNotMatch(html, /managementAdminToken|managementDiscoveryAdminToken/);
  assert.doesNotMatch(html, /관리자 Bearer 토큰/);
  assert.doesNotMatch(javascript, /Authorization\s*:\s*`Bearer/);
  assert.match(html, />장비 관리</);
  assert.match(html, /id="deviceManagementTitle">장비 관리</);
  assert.match(html, /id="managementNodeTitle">노드 선택</);
  assert.match(html, /id="managementDiscoveryTitle">연결 대기</);
  assert.match(html, /id="managementOpenManualCandidate"[^>]*>장비 추가</);
  assert.match(html, /service-demo-value-detail/);
  assert.match(html, /id="managementDeviceServiceTitle">수집 서비스</);
  assert.match(html, /실제 장비가 아닌 개발·연동 시험용 시뮬레이터/);
  assert.doesNotMatch(html, /선택 노드의 런타임/);
  assert.doesNotMatch(html, /id="managementCatalogTitle">프로토콜 패키지/);
  assert.match(html, /연결 구성 마법사/);
  assert.match(html, /새 장비 추가/);
  assert.match(html, /연결 프로토콜 · Device Service/);
  assert.match(html, /Device Service 준비 방식/);
  assert.match(html, /등록된 물리 연결/);
  assert.doesNotMatch(html, /승인된 하드웨어 연결/);
  assert.match(html, /id="managedDeviceTitle">등록 장비/);
  assert.match(html, /검증용 EdgeX 디바이스/);
  assert.match(css, /@media \(max-width: 760px\)/);
  assert.match(css, /@media \(prefers-reduced-motion: reduce\)/);
  assert.match(css, /#managementOverviewPanel:not\(\[hidden\]\)/);
  assert.match(css, /\.managed-device-actions/);
  assert.match(css, /\.management-stepper/);
  assert.match(css, /\.management-node-card/);
  assert.match(css, /\.management-physical-card/);
  assert.match(css, /\.management-physical-summary/);
  assert.match(css, /\.management-physical-details/);
  assert.match(css, /\.management-fixture-section/);
  assert.match(css, /data-purpose="development-fixture"/);
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
  assert.match(javascript, /function renderDeviceServiceInventory\(/);
  assert.match(javascript, /function buildDeviceServiceObservations\(/);
  assert.match(javascript, /function renderDiscoveryCandidates\(/);
  assert.match(javascript, /등록 물리 연결/);
  assert.doesNotMatch(javascript, /function renderValidation\(/);
  assert.match(simpleCss, /body\[data-view-mode="simple"\] \.dashboard-detail/);
  assert.match(simpleCss, /body\[data-view-mode="simple"\] \.management-node-card-facts/);
  assert.match(simpleCss, /body\[data-view-mode="simple"\] \.management-page-summary/);
  assert.match(simpleCss, /\.management-action-feedback\[data-kind="navigation"\]/);
  assert.match(simpleCss, /\.management-connection-legend/);
  assert.match(simpleCss, /body\[data-view-mode="simple"\] \.service-demo-route/);
  assert.match(simpleCss, /body\[data-view-mode="simple"\] \.service-demo-value-detail/);
  assert.match(simpleCss, /body\[data-view-mode="simple"\] #updatedAt/);
  assert.match(simpleCss, /@media \(max-width: 760px\)/);
  assert.match(simpleCss, /@media \(prefers-reduced-motion: reduce\)/);
});
