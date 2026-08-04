const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  LIVE_INPUT_ALIGNMENT_TOLERANCE_MS,
  addNode,
  addServiceNode,
  buildServiceCatalog,
  buildExecutionPlan,
  canonicalDataType,
  connectNodes,
  createDefaultDesign,
  createDeployedServiceDesign,
  createMultiSensorScoreExampleDesign,
  createSensorAnomalyExampleDesign,
  deviceLatestTimestampMs,
  removeNode,
  resourcesForDevice,
  updateNode,
  validateDesign,
  wouldCreateCycle,
} = require("../app/static/service-designer-model.js");
const {
  INPUT_TELEMETRY_LIMIT,
  INPUT_TELEMETRY_WINDOW,
  SERVICE_DRAFT_STORAGE_PREFIX,
  STORAGE_KEY,
  accelerationAxisBindingCandidates,
  bindDeployedServiceDesign,
  bindMultiSensorScoreExample,
  bindSensorAnomalyExample,
  contextSourceBindingCandidate,
  deployedServiceFlow,
  deployedServiceView,
  designerTelemetryUrl,
  fetchDesignerTelemetry,
  fetchDesignerServices,
  fetchDesignerProfiles,
  loadStoredDesign,
  loadStoredServiceDraft,
  renderInputTelemetryPreview,
  saveStoredDesign,
  saveStoredServiceDraft,
  serviceDraftStorageKey,
  sourceBindingCandidate,
  summarizeDesignerTelemetry,
  telemetryAgeLabel,
} = require("../app/static/service-designer.js");
const {
  GRID_SIZE,
  MAX_ZOOM,
  MIN_ZOOM,
  centerOnWorldPoint,
  constrainNodePosition,
  dragAutoPanDelta,
  dragNodePosition,
  ensureWorldRectVisible,
  fitViewport,
  graphBounds,
  miniMapBounds,
  nudgeNodePosition,
  normalizeNodePosition,
  panViewport,
  snapNodePosition,
  visibleWorldRect,
  zoomAtPoint,
} = require("../app/static/service-designer-viewport.js");

const root = path.resolve(__dirname, "..");

function inventory() {
  return {
    devices: [
      {
        name: "virtual-temperature-001",
        profile_name: "temperature-v1",
        node_name: "etri-dev0001-jetorn",
        overall_status: "available",
        telemetry_freshness: "fresh",
        latest_readings: [],
      },
    ],
    profiles: [
      {
        name: "temperature-v1",
        resources: [
          {
            name: "Temperature",
            value_type: "Float64",
            units: "Cel",
          },
        ],
      },
    ],
    nodes: [
      {hostname: "etri-dev0001-jetorn"},
      {hostname: "etri-ser0002-cgnmsb"},
    ],
  };
}

function boundDesign({sourceMode = "local_recent"} = {}) {
  let design = createDefaultDesign();
  design = updateNode(design, "sensor-1", {
    config: {
      deviceName: "virtual-temperature-001",
      resourceName: "Temperature",
      sourceMode,
    },
  });
  design = updateNode(design, "preprocess-1", {
    config: {
      operation: "standardize",
      targetNode: sourceMode === "local_recent"
        ? "etri-dev0001-jetorn"
        : "etri-ser0002-cgnmsb",
    },
  });
  design = updateNode(design, "inference-1", {
    config: {
      algorithm: "online-gaussian-baseline-v1",
      targetNode: "etri-ser0002-cgnmsb",
    },
  });
  return design;
}

function accelerationInventory() {
  const axes = ["x", "y", "z"];
  return {
    devices: axes.map((axis) => ({
      name: `virtual-acceleration-${axis}-001`,
      profile_name: `etri-arduino-acceleration-${axis}`,
      node_name: "etri-dev0001-jetorn",
      overall_status: "available",
      telemetry_freshness: "fresh",
      latest_readings: [],
    })),
    profiles: axes.map((axis) => ({
      name: `etri-arduino-acceleration-${axis}`,
      resources: [{
        name: `acceleration_${axis}_raw`,
        value_type: "Int32",
        units: "raw",
      }],
    })),
    nodes: [
      {hostname: "etri-dev0001-jetorn"},
      {hostname: "etri-ser0002-cgnmsb", node_type: "server"},
    ],
  };
}

function multiSensorInventory() {
  const current = accelerationInventory();
  current.devices.push({
    name: "virtual-temperature-001",
    profile_name: "etri-arduino-temperature",
    node_name: "etri-dev0001-jetorn",
    overall_status: "available",
    telemetry_freshness: "fresh",
    latest_readings: [],
  });
  current.profiles.push({
    name: "etri-arduino-temperature",
    resources: [{
      name: "temperature_raw",
      value_type: "Int32",
      units: "raw",
    }],
  });
  return current;
}

function deployedSensorAnomalyService() {
  return {
    service_id: "sensor-anomaly-demo",
    display_name: "센서 이상 탐지",
    description: "테스트베드 가속도 3축·온도 기반 기준선 서비스",
    node: "etri-dev0001-jetorn",
    physical_source: "arduino-001",
    device_service: "device-serial-jetson",
    model_version: "baseline-1.0.0",
    input_devices: [
      "virtual-acceleration-x-001",
      "virtual-acceleration-y-001",
      "virtual-acceleration-z-001",
      "virtual-temperature-001",
    ],
    design_contract: {
      contract_id: "sensor-anomaly-demo-v1",
      source_mode: "local_recent",
      pipeline_algorithm: "weighted-multi-sensor-feature-score-v1",
      vibration_algorithm: "online-vibration-feature-gaussian-v1",
      temperature_algorithm: "online-temperature-feature-gaussian-v1",
      vibration_window_samples: 20,
      temperature_window_samples: 10,
      warmup_samples: 30,
      threshold: 4,
      vibration_weight: 0.7,
      temperature_weight: 0.3,
      inputs: [
        {stage_id: "sensor-x", device_name: "virtual-acceleration-x-001", resource_name: "acceleration_x_raw"},
        {stage_id: "sensor-y", device_name: "virtual-acceleration-y-001", resource_name: "acceleration_y_raw"},
        {stage_id: "sensor-z", device_name: "virtual-acceleration-z-001", resource_name: "acceleration_z_raw"},
        {stage_id: "sensor-context", device_name: "virtual-temperature-001", resource_name: "temperature_raw"},
      ],
    },
  };
}

test("uses EdgeX Device Profile resources even before a latest Event exists", () => {
  const current = inventory();
  const resources = resourcesForDevice(current.devices[0], current.profiles);

  assert.deepEqual(resources, [{
    name: "Temperature",
    valueType: "Float64",
    units: "Cel",
    source: "profile",
  }]);
  assert.equal(canonicalDataType(resources[0].valueType), "number");
});

test("validates an edge-local sensor-to-service design against current inventory", () => {
  const result = validateDesign(boundDesign(), inventory());

  assert.equal(result.valid, true);
  assert.deepEqual(result.errors, []);
  assert.deepEqual(result.warnings, []);
});

test("blocks a service input when EdgeX has no Event or only stale telemetry", () => {
  const noEvents = inventory();
  noEvents.devices[0].telemetry_freshness = "no_events";
  const missingResult = validateDesign(boundDesign(), noEvents);

  assert.equal(missingResult.valid, false);
  assert.ok(missingResult.errors.some((issue) => issue.code === "telemetry_missing"));

  const stale = inventory();
  stale.devices[0].telemetry_freshness = "stale";
  const staleResult = validateDesign(boundDesign(), stale);

  assert.equal(staleResult.valid, false);
  assert.ok(staleResult.errors.some((issue) => issue.code === "telemetry_stale"));
});

test("blocks direct live multi-inputs across nodes or outside the time alignment window", () => {
  const current = accelerationInventory();
  const baseTime = Date.parse("2026-08-04T02:00:00.000Z");
  current.devices.forEach((device, index) => {
    device.latest_event_timestamp = new Date(baseTime + index * 500).toISOString();
  });
  const bound = bindSensorAnomalyExample(
    createSensorAnomalyExampleDesign(),
    current,
  ).design;

  current.devices[2].node_name = "etri-dev0003-raspi5";
  const nodeResult = validateDesign(bound, current);
  assert.ok(nodeResult.errors.some(
    (issue) => issue.code === "multi_input_node_mismatch",
  ));

  current.devices[2].node_name = "etri-dev0001-jetorn";
  current.devices[2].latest_event_timestamp = new Date(
    baseTime + LIVE_INPUT_ALIGNMENT_TOLERANCE_MS + 1,
  ).toISOString();
  const skewResult = validateDesign(bound, current);
  assert.ok(skewResult.errors.some(
    (issue) => issue.code === "multi_input_time_skew",
  ));
});

test("uses the newest valid Event or Reading timestamp for alignment", () => {
  const device = {
    latest_event_timestamp: "2026-08-04T02:00:00.000Z",
    latest_readings: [
      {resource_name: "Temperature", timestamp: "2026-08-04T02:00:01.000Z"},
      {resource_name: "Pressure", timestamp: "2026-08-04T02:00:02.000Z"},
      {resource_name: "Temperature", timestamp: "invalid"},
    ],
  };
  assert.equal(
    deviceLatestTimestampMs(device),
    Date.parse("2026-08-04T02:00:02.000Z"),
  );
  assert.equal(
    deviceLatestTimestampMs(device, "temperature"),
    Date.parse("2026-08-04T02:00:01.000Z"),
  );
});

test("requires the first consumer of Local Data API to stay on the source node", () => {
  const design = updateNode(boundDesign(), "preprocess-1", {
    config: {targetNode: "etri-ser0002-cgnmsb"},
  });
  const result = validateDesign(design, inventory());

  assert.equal(result.valid, false);
  assert.ok(result.errors.some((issue) => issue.code === "local_node_mismatch"));
});

test("blocks cycles, duplicate edges, incompatible ports, and missing bindings", () => {
  const current = inventory();
  const design = boundDesign();

  assert.equal(wouldCreateCycle(design, "inference-1", "preprocess-1"), true);
  assert.match(
    connectNodes(design, "inference-1", "preprocess-1", current).error,
    /순환/,
  );
  assert.match(
    connectNodes(design, "sensor-1", "preprocess-1", current).error,
    /이미 연결/,
  );
  assert.equal(validateDesign(createDefaultDesign(), current).valid, false);
});

test("removes a stage and all of its incident edges", () => {
  const design = removeNode(boundDesign(), "preprocess-1");

  assert.equal(design.nodes.some((node) => node.id === "preprocess-1"), false);
  assert.equal(
    design.edges.some((edge) => (
      edge.from === "preprocess-1" || edge.to === "preprocess-1"
    )),
    false,
  );
});

test("adds unique stages and builds a deterministic dry-run plan", () => {
  const design = addNode(boundDesign({sourceMode: "core_history"}), "preprocess");
  assert.equal(new Set(design.nodes.map((node) => node.id)).size, design.nodes.length);

  const plan = buildExecutionPlan(boundDesign(), inventory());
  assert.equal(plan.mode, "dry-run");
  assert.equal(plan.valid, true);
  assert.deepEqual(
    plan.stages.map((stage) => stage.type),
    ["sensor", "preprocess", "inference", "output"],
  );
  assert.match(plan.stages[0].detail, /virtual-temperature-001/);
  assert.match(plan.stages[0].detail, /엣지 최근 데이터/);
});

test("lists concrete workflow services and reports real EdgeX input availability", () => {
  const catalog = buildServiceCatalog(inventory());

  assert.equal(catalog.length, 13);
  assert.deepEqual(
    [...new Set(catalog.map((service) => service.category))],
    ["input", "preprocess", "inference", "fusion", "output"],
  );
  assert.deepEqual(
    catalog.filter((service) => service.category === "input").map((service) => ({
      id: service.id,
      enabled: service.enabled,
      badge: service.badge,
    })),
    [
      {id: "edgex-local-recent", enabled: true, badge: "입력 1"},
      {id: "edgex-core-history", enabled: true, badge: "입력 1"},
    ],
  );
  assert.equal(
    catalog.find((service) => service.id === "inference-online-gaussian").badge,
    "설계용",
  );
  assert.equal(
    buildServiceCatalog({devices: [], profiles: [], nodes: []})[0].enabled,
    false,
  );
});

test("adds a catalog service with its exact operation contract", () => {
  const design = addServiceNode(createDefaultDesign(), "preprocess-rolling-mean");
  const added = design.nodes[design.nodes.length - 1];

  assert.equal(added.type, "preprocess");
  assert.equal(added.title, "이동 평균");
  assert.equal(added.config.operation, "rolling_mean");
  assert.throws(
    () => addServiceNode(design, "arbitrary-container"),
    /지원하지 않는 서비스/,
  );
});

test("selects a live numeric EdgeX resource instead of a hard-coded source", () => {
  const current = inventory();
  current.devices.unshift({
    name: "stale-string-device",
    profile_name: "string-v1",
    overall_status: "degraded",
    telemetry_freshness: "stale",
    latest_readings: [{
      resource_name: "Status",
      value_type: "String",
    }],
  });

  const candidate = sourceBindingCandidate(current);

  assert.equal(candidate.device.name, "virtual-temperature-001");
  assert.equal(candidate.resource.name, "Temperature");
});

test("builds the real three-axis anomaly demo as a six-stage example", () => {
  const design = createSensorAnomalyExampleDesign();

  assert.equal(design.name, "설비 진동 이상 감지");
  assert.deepEqual(
    design.nodes.map((node) => node.type),
    ["sensor", "sensor", "sensor", "preprocess", "inference", "output"],
  );
  assert.equal(design.edges.length, 5);
  assert.equal(
    design.nodes.find((node) => node.id === "vector-magnitude").config.operation,
    "vector_magnitude",
  );
  assert.equal(
    design.nodes.find((node) => node.id === "anomaly-inference").config.algorithm,
    "online-gaussian-baseline-v1",
  );
});

test("binds the anomaly example to all three live Jetson acceleration sources", () => {
  const current = accelerationInventory();
  const candidates = accelerationAxisBindingCandidates(current);
  const bound = bindSensorAnomalyExample(
    createSensorAnomalyExampleDesign(),
    current,
  );

  assert.deepEqual(
    Object.fromEntries(Object.entries(candidates).map(([axis, candidate]) => [
      axis,
      `${candidate.device.name}/${candidate.resource.name}`,
    ])),
    {
      x: "virtual-acceleration-x-001/acceleration_x_raw",
      y: "virtual-acceleration-y-001/acceleration_y_raw",
      z: "virtual-acceleration-z-001/acceleration_z_raw",
    },
  );
  assert.deepEqual(bound.boundAxes, ["x", "y", "z"]);
  assert.equal(bound.sourceNode, "etri-dev0001-jetorn");
  assert.equal(
    bound.design.nodes.find((node) => node.id === "vector-magnitude")
      .config.targetNode,
    "etri-dev0001-jetorn",
  );
  assert.equal(
    bound.design.nodes.find((node) => node.id === "anomaly-inference")
      .config.targetNode,
    "etri-dev0001-jetorn",
  );
  assert.equal(validateDesign(bound.design, current).valid, true);
});

test("does not invent a missing acceleration axis", () => {
  const current = accelerationInventory();
  current.devices = current.devices.filter(
    (device) => device.name !== "virtual-acceleration-z-001",
  );
  current.profiles = current.profiles.filter(
    (profile) => profile.name !== "etri-arduino-acceleration-z",
  );
  const bound = bindSensorAnomalyExample(
    createSensorAnomalyExampleDesign(),
    current,
  );

  assert.deepEqual(bound.boundAxes, ["x", "y"]);
  assert.equal(bound.sourceNode, "");
  assert.equal(
    bound.design.nodes.find((node) => node.id === "sensor-z").config.deviceName,
    "",
  );
  assert.equal(validateDesign(bound.design, current).valid, false);
});

test("builds a multi-sensor score example with explicit feature and fusion stages", () => {
  const design = createMultiSensorScoreExampleDesign();

  assert.equal(design.name, "설비 복합 이상 점수");
  assert.deepEqual(
    design.nodes.map((node) => node.type),
    [
      "sensor",
      "sensor",
      "sensor",
      "sensor",
      "preprocess",
      "preprocess",
      "inference",
      "inference",
      "fusion",
      "output",
    ],
  );
  assert.equal(design.edges.length, 9);
  assert.equal(
    design.nodes.find((node) => node.id === "vibration-features").config.operation,
    "vibration_features",
  );
  assert.equal(
    design.nodes.find((node) => node.id === "score-fusion").config.method,
    "weighted_average",
  );
});

test("binds three acceleration axes and a same-node temperature source", () => {
  const current = multiSensorInventory();
  const context = contextSourceBindingCandidate(current, {
    preferredNode: "etri-dev0001-jetorn",
    excludedDeviceNames: current.devices
      .filter((device) => device.name.includes("acceleration"))
      .map((device) => device.name),
  });
  const bound = bindMultiSensorScoreExample(
    createMultiSensorScoreExampleDesign(),
    current,
  );

  assert.equal(context.device.name, "virtual-temperature-001");
  assert.equal(context.resource.name, "temperature_raw");
  assert.equal(bound.sourceNode, "etri-dev0001-jetorn");
  assert.equal(bound.configuredInputs.length, 4);
  assert.equal(
    bound.design.nodes.find((node) => node.id === "sensor-context").config.deviceName,
    "virtual-temperature-001",
  );
  [
    "vibration-features",
    "context-features",
    "vibration-score",
    "context-score",
    "score-fusion",
  ].forEach((nodeId) => {
    assert.equal(
      bound.design.nodes.find((node) => node.id === nodeId).config.targetNode,
      "etri-dev0001-jetorn",
    );
  });
  assert.equal(validateDesign(bound.design, current).valid, true);
});

test("builds and binds the selected deployed service from its versioned contract", () => {
  const service = deployedSensorAnomalyService();
  const design = createDeployedServiceDesign(service);
  const bound = bindDeployedServiceDesign(design, service, multiSensorInventory());

  assert.equal(design.id, "deployed-sensor-anomaly-demo");
  assert.equal(design.nodes.length, 10);
  assert.equal(design.edges.length, 9);
  assert.equal(
    design.nodes.find((node) => node.id === "sensor-x").config.deviceName,
    "virtual-acceleration-x-001",
  );
  assert.equal(
    design.nodes.find((node) => node.id === "vibration-features").config.windowSize,
    20,
  );
  assert.equal(
    design.nodes.find((node) => node.id === "context-features").config.windowSize,
    10,
  );
  assert.equal(
    design.nodes.find((node) => node.id === "vibration-score").config.algorithm,
    "online-vibration-feature-gaussian-v1",
  );
  assert.equal(
    design.nodes.find((node) => node.id === "context-score").config.algorithm,
    "online-temperature-feature-gaussian-v1",
  );
  assert.deepEqual(
    design.nodes.find((node) => node.id === "score-fusion").config.weights,
    {"vibration-score": 0.7, "context-score": 0.3},
  );
  assert.equal(bound.configuredInputs.length, 4);
  assert.equal(validateDesign(bound.design, multiSensorInventory()).valid, true);
  assert.equal(
    createDeployedServiceDesign({...service, model_version: null})
      .nodes.find((node) => node.id === "vibration-score").config.modelVersion,
    "",
  );
  assert.equal(createDeployedServiceDesign({design_contract: null}), null);

  const edited = updateNode(design, "vibration-features", {
    config: {windowSize: 40},
  });
  assert.equal(
    edited.nodes.find((node) => node.id === "vibration-features").config.windowSize,
    40,
  );
  assert.equal(
    design.nodes.find((node) => node.id === "vibration-features").config.windowSize,
    20,
  );
});

test("summarizes a deployed service as an input-to-result flow", () => {
  const flow = deployedServiceFlow(deployedSensorAnomalyService());

  assert.deepEqual(flow.map((stage) => stage.label), [
    "입력",
    "전처리",
    "AI 분석",
    "결과",
  ]);
  assert.deepEqual(flow.map((stage) => stage.title), [
    "가속도 3축 + 온도",
    "진동 특징 · 온도 특징",
    "이상 점수 결합",
    "대시보드 결과",
  ]);
  assert.equal(flow[0].detail, "4개 센서");
  assert.equal(flow[2].detail, "모델 baseline-1.0.0");
});

test("requires all three vibration axes and at least two valid score weights", () => {
  const current = multiSensorInventory();
  const bound = bindMultiSensorScoreExample(
    createMultiSensorScoreExampleDesign(),
    current,
  ).design;
  const missingAxis = {
    ...bound,
    edges: bound.edges.filter((edge) => edge.id !== "edge-z-features"),
  };
  const missingAxisResult = validateDesign(missingAxis, current);
  assert.ok(missingAxisResult.errors.some(
    (issue) => issue.code === "too_few_inputs" && issue.nodeId === "vibration-features",
  ));

  const invalidWeights = updateNode(bound, "score-fusion", {
    config: {
      weights: {"vibration-score": 0, "context-score": 0},
    },
  });
  assert.ok(validateDesign(invalidWeights, current).errors.some(
    (issue) => issue.code === "fusion_weight_total_invalid",
  ));
});

test("does not cascade runtime warnings from an unbound multi-sensor input", () => {
  const result = validateDesign(
    createMultiSensorScoreExampleDesign(),
    {devices: [], profiles: [], nodes: []},
  );

  assert.deepEqual(result.warnings, []);
  assert.equal(
    result.errors.some((issue) => issue.code === "source_node_missing"),
    false,
  );
});

test("loads and saves only the versioned browser-local draft", () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
  };

  assert.equal(loadStoredDesign(storage), null);
  assert.equal(saveStoredDesign(boundDesign(), storage), true);
  assert.ok(values.has(STORAGE_KEY));
  assert.equal(loadStoredDesign(storage).name, "센서 이상 탐지 서비스");

  values.set(STORAGE_KEY, JSON.stringify({version: 999, nodes: []}));
  assert.equal(loadStoredDesign(storage), null);
});

test("stores service edits separately and rejects a stale contract draft", () => {
  const values = new Map();
  const storage = {
    getItem: (key) => values.get(key) || null,
    setItem: (key, value) => values.set(key, value),
  };
  const service = deployedSensorAnomalyService();
  const design = updateNode(
    createDeployedServiceDesign(service),
    "vibration-features",
    {config: {windowSize: 40}},
  );

  assert.equal(saveStoredServiceDraft(service, design, storage), true);
  assert.equal(
    serviceDraftStorageKey(service.service_id),
    `${SERVICE_DRAFT_STORAGE_PREFIX}sensor-anomaly-demo`,
  );
  assert.equal(
    loadStoredServiceDraft(service, storage).design.nodes
      .find((node) => node.id === "vibration-features").config.windowSize,
    40,
  );
  assert.equal(
    loadStoredServiceDraft({
      ...service,
      design_contract: {...service.design_contract, contract_id: "future-v2"},
    }, storage),
    null,
  );
});

test("fetches Device Profile contracts from the read-only state endpoint", async () => {
  let request = null;
  const profiles = await fetchDesignerProfiles(async (url, options) => {
    request = {url, options};
    return {
      ok: true,
      json: async () => [{name: "temperature-v1", resources: []}],
    };
  });

  assert.deepEqual(request, {
    url: "/state/device-profiles",
    options: {cache: "no-store"},
  });
  assert.equal(profiles[0].name, "temperature-v1");
});

test("fetches the selected EdgeX input history through the read-only telemetry API", async () => {
  let request = null;
  const points = await fetchDesignerTelemetry(
    "virtual temperature/001",
    INPUT_TELEMETRY_WINDOW,
    async (url, options) => {
      request = {url, options};
      return {
        ok: true,
        json: async () => [{
          resource_name: "Temperature",
          timestamp: "2026-08-04T02:00:00.000Z",
          value: 24.5,
        }],
      };
    },
    INPUT_TELEMETRY_LIMIT,
  );

  assert.deepEqual(request, {
    url: "/state/devices/virtual%20temperature%2F001/telemetry?window=-5m&limit=300",
    options: {cache: "no-store"},
  });
  assert.equal(
    designerTelemetryUrl("device-1", "-10m", 5000),
    "/state/devices/device-1/telemetry?window=-10m&limit=1000",
  );
  assert.equal(points.length, 1);
});

test("summarizes only the selected resource and computes its median collection interval", () => {
  const points = [
    {resource_name: "Other", timestamp: "2026-08-04T02:00:00.500Z", value: 99},
    {resource_name: "Temperature", timestamp: "2026-08-04T02:00:03.000Z", value: 23},
    {source_name: "temperature", timestamp: "2026-08-04T02:00:00.000Z", value: 21},
    {resource_name: "TEMPERATURE", timestamp: "2026-08-04T02:00:01.000Z", value: 22},
    {resource_name: "Temperature", timestamp: "invalid", value: 100},
  ];
  const summary = summarizeDesignerTelemetry(points, "Temperature");

  assert.equal(summary.sampleCount, 3);
  assert.equal(summary.latest.value, 23);
  assert.deepEqual(summary.recent.map((point) => point.value), [23, 22, 21]);
  assert.equal(summary.medianIntervalMs, 1500);
  assert.equal(
    telemetryAgeLabel("2026-08-04T02:00:00.000Z", Date.parse("2026-08-04T02:00:30.000Z")),
    "30초 전",
  );
});

test("renders an accessible read-only preview of the actual selected input", () => {
  const node = boundDesign().nodes.find((item) => item.id === "sensor-1");
  const current = inventory();
  const summary = summarizeDesignerTelemetry([
    {
      resource_name: "Temperature",
      source_name: "Temperature",
      timestamp: new Date(Date.now() - 2000).toISOString(),
      value: 24.5,
      units: "Cel",
    },
    {
      resource_name: "Temperature",
      source_name: "Temperature",
      timestamp: new Date(Date.now() - 1000).toISOString(),
      value: 24.7,
      units: "Cel",
    },
  ], "Temperature");
  const markup = renderInputTelemetryPreview(
    node,
    current.devices[0],
    resourcesForDevice(current.devices[0], current.profiles)[0],
    {
      key: `${node.id}|virtual-temperature-001|Temperature`,
      status: "ready",
      summary,
      error: "",
    },
  );

  assert.match(markup, /실제 입력 데이터/);
  assert.match(markup, /최근 5분 · EdgeX Core Data/);
  assert.match(markup, /role="status" aria-live="polite"/);
  assert.match(markup, /24\.7 Cel/);
  assert.match(markup, /수집 간격 중앙값/);
  assert.match(markup, /1초/);
  assert.match(markup, /data-designer-telemetry-refresh/);
  assert.match(markup, /읽기 전용 미리보기/);
});

test("fetches and labels the current deployed service inventory", async () => {
  let request = null;
  const services = await fetchDesignerServices(async (url, options) => {
    request = {url, options};
    return {
      ok: true,
      json: async () => ({
        services: [{
          service_id: "sensor-anomaly-demo",
          display_name: "센서 이상 탐지",
          status: "normal",
          input_state: "fresh",
          model_state: "ready",
          input_devices: ["x", "y", "z", "temperature"],
          node: "etri-dev0001-jetorn",
          model_version: "baseline-1.0.0",
          design_contract: deployedSensorAnomalyService().design_contract,
        }],
      }),
    };
  });

  assert.deepEqual(request, {
    url: "/state/services",
    options: {cache: "no-store"},
  });
  const view = deployedServiceView(services[0]);
  assert.equal(view.statusLabel, "정상");
  assert.equal(view.inputLabel, "데이터 최신");
  assert.equal(view.modelLabel, "모델 준비");
  assert.equal(view.inputCount, 4);
  assert.equal(view.flow[0].title, "가속도 3축 + 온도");
  assert.equal(view.flow[2].title, "이상 점수 결합");
  assert.equal(view.designAvailable, true);
});

test("fits the complete default graph inside the visible canvas", () => {
  const design = createDefaultDesign();
  const bounds = graphBounds(design.nodes);
  const viewport = fitViewport(design.nodes, 920, 560, {padding: 44});

  assert.ok(viewport.zoom >= MIN_ZOOM);
  assert.ok(viewport.zoom <= MAX_ZOOM);
  assert.ok(viewport.x + bounds.left * viewport.zoom >= 43);
  assert.ok(viewport.y + bounds.top * viewport.zoom >= 43);
  assert.ok(viewport.x + bounds.right * viewport.zoom <= 877);
  assert.ok(viewport.y + bounds.bottom * viewport.zoom <= 517);
});

test("fits freely positioned distant nodes back inside the visible canvas", () => {
  const nodes = [
    {id: "near", x: 32, y: 32},
    {id: "far", x: 3310, y: 32},
  ];
  const bounds = graphBounds(nodes);
  const viewport = fitViewport(nodes, 762, 453, {padding: 44});

  assert.ok(viewport.zoom >= MIN_ZOOM);
  assert.ok(viewport.x + bounds.left * viewport.zoom >= 43);
  assert.ok(viewport.y + bounds.top * viewport.zoom >= 43);
  assert.ok(viewport.x + bounds.right * viewport.zoom <= 719);
  assert.ok(viewport.y + bounds.bottom * viewport.zoom <= 410);
});

test("keeps the world point under the pointer while zooming", () => {
  const current = {x: 80, y: 40, zoom: 0.8};
  const pointer = {x: 320, y: 220};
  const before = {
    x: (pointer.x - current.x) / current.zoom,
    y: (pointer.y - current.y) / current.zoom,
  };
  const next = zoomAtPoint(current, pointer.x, pointer.y, 1.25);
  const after = {
    x: (pointer.x - next.x) / next.zoom,
    y: (pointer.y - next.y) / next.zoom,
  };

  assert.deepEqual(after, before);
});

test("pans, centers, and reports the visible world rectangle", () => {
  const panned = panViewport({x: 10, y: 20, zoom: 0.5}, 35, -5);
  assert.deepEqual(panned, {x: 45, y: 15, zoom: 0.5});

  const centered = centerOnWorldPoint(panned, 560, 350, 800, 500);
  const visible = visibleWorldRect(centered, 800, 500);
  assert.equal(Math.round(visible.x + visible.width / 2), 560);
  assert.equal(Math.round(visible.y + visible.height / 2), 350);
});

test("supports optional grid snapping and smooth pointer placement", () => {
  const snapped = snapNodePosition({x: 53, y: 61}, [], "sensor-1");
  const smooth = snapNodePosition(
    {x: 53, y: 61},
    [],
    "sensor-1",
    {grid: false},
  );
  const free = snapNodePosition(
    {x: 53, y: 61},
    [],
    "sensor-1",
    {snap: false},
  );

  assert.deepEqual(
    {x: snapped.x, y: snapped.y},
    {x: 2 * GRID_SIZE, y: 3 * GRID_SIZE},
  );
  assert.deepEqual({x: smooth.x, y: smooth.y}, {x: 53, y: 61});
  assert.deepEqual({x: free.x, y: free.y}, {x: 53, y: 61});
});

test("auto-pans at canvas edges without clamping the dragged node to the viewport", () => {
  assert.deepEqual(
    dragAutoPanDelta(
      {x: 810, y: 250},
      {left: 0, top: 0, right: 800, bottom: 500},
    ),
    {x: -14, y: 0},
  );
  assert.deepEqual(
    dragAutoPanDelta(
      {x: 400, y: 250},
      {left: 0, top: 0, right: 800, bottom: 500},
    ),
    {x: 0, y: 0},
  );
  assert.deepEqual(
    dragNodePosition(
      {x: 100, y: 80},
      {x: 200, y: 200},
      {x: 760, y: 200},
      {x: 0, y: 0, zoom: 1},
      {x: -28, y: 0, zoom: 1},
    ),
    {x: 688, y: 80},
  );
});

test("keeps free-position nodes visible in the dynamic minimap bounds", () => {
  const free = normalizeNodePosition({x: -240, y: 980});
  const snapped = snapNodePosition(free, [], "moving", {snap: false});
  const bounds = miniMapBounds(
    [{id: "moving", ...snapped}],
    {x: 400, y: 200, width: 800, height: 500},
    40,
  );

  assert.deepEqual({x: snapped.x, y: snapped.y}, free);
  assert.ok(bounds.left < -240);
  assert.ok(bounds.bottom > 980 + 156);
  assert.ok(bounds.right > 1200);
});

test("aligns node anchors to peers and reports visible guide coordinates", () => {
  const aligned = snapNodePosition(
    {x: 237, y: 117},
    [{id: "peer", x: 240, y: 120}],
    "moving",
    {grid: false},
  );

  assert.equal(aligned.x, 240);
  assert.equal(aligned.y, 120);
  assert.ok(Number.isFinite(aligned.guides.vertical));
  assert.ok(Number.isFinite(aligned.guides.horizontal));
});

test("does not snap a node center to an unrelated peer edge", () => {
  const placed = snapNodePosition(
    {x: 221, y: 220},
    [{id: "peer", x: 330, y: 120}],
    "moving",
    {tolerance: 10},
  );

  assert.equal(placed.x, 216);
  assert.equal(placed.guides.vertical, null);
});

test("constrains Shift drags to one axis and nudges nodes by keyboard", () => {
  assert.deepEqual(
    constrainNodePosition({x: 48, y: 128}, {x: 138, y: 162}),
    {x: 138, y: 128, lockedAxis: "horizontal"},
  );
  assert.deepEqual(
    constrainNodePosition({x: 48, y: 128}, {x: 60, y: 210}),
    {x: 48, y: 210, lockedAxis: "vertical"},
  );
  assert.deepEqual(
    nudgeNodePosition({x: 48, y: 128}, "ArrowRight", true),
    {x: 48 + GRID_SIZE, y: 128},
  );
  assert.deepEqual(
    nudgeNodePosition({x: -20, y: 900}, "ArrowLeft"),
    {x: -21, y: 900},
  );
});

test("reveals a selected node beside the inspector without changing zoom", () => {
  const current = {x: 40, y: 20, zoom: 0.8};
  const revealed = ensureWorldRectVisible(
    current,
    {x: 860, y: 240, width: 218, height: 156},
    920,
    540,
    {padding: 36, rightInset: 350},
  );

  assert.equal(revealed.zoom, current.zoom);
  assert.ok(revealed.x < current.x);
  assert.ok(revealed.x + (860 + 218) * revealed.zoom <= 920 - 350 - 36);
});

test("dashboard exposes one scoped service design page without an execution action", () => {
  const html = fs.readFileSync(path.join(root, "app/static/index.html"), "utf8");
  const cssPath = path.join(root, "app/static/service-designer.css");
  const uiPath = path.join(root, "app/static/service-designer.js");
  const viewportPath = path.join(
    root,
    "app/static/service-designer-viewport.js",
  );
  const ui = fs.readFileSync(uiPath, "utf8");
  const css = fs.readFileSync(cssPath, "utf8");

  assert.match(html, /data-dashboard-page="designer"/);
  assert.match(html, /data-page="designer"/);
  assert.match(html, /id="serviceDesignerCanvas"/);
  assert.match(html, /id="serviceDesignerInspector"/);
  assert.match(html, /id="serviceDesignerValidation"/);
  assert.match(html, /id="serviceDesignerFitView"/);
  assert.match(html, /id="serviceDesignerMiniMap"/);
  assert.match(html, /id="serviceDesignerGuideVertical"/);
  assert.match(html, /현재 실행 서비스/);
  assert.match(html, /id="serviceDesignerDeployedList"/);
  assert.match(html, /실제 배포 상태 · 데이터 흐름/);
  assert.match(html, /id="serviceDesignerReturnDraft"/);
  assert.match(html, /id="serviceDesignerReloadService"/);
  assert.match(html, /기존 초안으로 돌아가기/);
  assert.match(html, /원본으로 초기화/);
  assert.match(html, /설계 블록/);
  assert.match(html, /id="serviceDesignerReset"[\s\S]*?>3축 데모</);
  assert.match(html, /id="serviceDesignerMultiSensorExample"[\s\S]*?>복합 점수 예시</);
  assert.match(html, /id="serviceDesignerCatalogState"/);
  assert.match(html, /자유 드래그 · 가장자리 자동 이동 · 놓을 때 정렬 · Alt 정렬 해제/);
  assert.match(html, /service-designer-viewport\.js/);
  assert.match(html, /실행 계획 미리보기/);
  assert.doesNotMatch(html, /id="serviceDesignerExecute"/);
  assert.match(
    ui,
    /const dragNode = event\.target\.closest\?\.\("\[data-designer-node\]"\)/,
  );
  assert.match(
    ui,
    /startDrag\(event, dragNode\.dataset\.designerNode, documentRef\)/,
  );
  assert.match(ui, /const DRAG_ACTIVATION_PX = 3/);
  assert.match(ui, /const DRAG_CLICK_SUPPRESSION_MS = 600/);
  assert.match(ui, /data-designer-service/);
  assert.match(ui, /fetchFn\("\/state\/services", \{cache: "no-store"\}\)/);
  assert.match(ui, /\/state\/devices\/\$\{encodeURIComponent/);
  assert.match(ui, /data-designer-telemetry-refresh/);
  assert.match(ui, /실행 계획 차단/);
  assert.match(ui, /BLOCKED/);
  assert.match(ui, /renderDeployedServices/);
  assert.match(ui, /data-deployed-service-design/);
  assert.match(ui, /editDeployedServiceDesign/);
  assert.match(ui, /서비스 초안 · 변경됨/);
  assert.match(ui, /편집 중/);
  assert.match(ui, /편집 계속/);
  assert.match(ui, /설계 편집/);
  assert.doesNotMatch(ui, /보고 있음/);
  assert.doesNotMatch(ui, /isDeployedDesignView/);
  assert.match(ui, /model\.addServiceNode\(state\.design, serviceId\)/);
  assert.match(
    ui,
    /state\.suppressNodeClickUntil = Date\.now\(\) \+ DRAG_CLICK_SUPPRESSION_MS/,
  );
  assert.match(
    ui,
    /if \(state\.dragging\) \{\s*state\.pendingFullRender = true;\s*return;/,
  );
  assert.match(ui, /const node = state\.inspectorOpen/);
  assert.match(
    ui,
    /function selectNodeForDrag[\s\S]*?state\.inspectorOpen = false;/,
  );
  assert.match(ui, /flushPendingFullRender\(documentRef\)/);
  assert.doesNotMatch(ui, /clampNodeToViewport/);
  assert.match(ui, /viewportModel\.dragAutoPanDelta\(/);
  assert.match(ui, /viewportModel\.dragNodePosition\(/);
  assert.match(ui, /function scheduleDragAutoPan/);
  assert.match(ui, /const dropPlacement = viewportModel\.snapNodePosition\(/);
  assert.match(ui, /snap:\s*!altKey,\s*[\s\S]*?grid:\s*false,/);
  assert.match(ui, /drag\.dropX = dropPlacement\.x/);
  assert.match(ui, /style\.transform = `translate3d\(/);
  assert.match(ui, /scheduleDragAuxiliaryRender\(documentRef\)/);
  const moveDragSource = ui.slice(
    ui.indexOf("function moveDrag"),
    ui.indexOf("function finishDrag"),
  );
  assert.doesNotMatch(moveDragSource, /renderEdges\(/);
  assert.doesNotMatch(moveDragSource, /renderMiniMap\(/);
  assert.match(
    css,
    /\.service-designer-node\s*\{[^}]*cursor:\s*grab;[^}]*touch-action:\s*none;/s,
  );
  assert.match(
    css,
    /\.service-designer-node\.is-dragging\s*\{[^}]*will-change:\s*transform;/s,
  );
  assert.match(css, /\.service-designer-node\[data-node-type="fusion"\]/);
  assert.match(css, /\.service-designer-deployed-item/);
  assert.match(css, /\.service-designer-deployed-item\.selected/);
  assert.match(css, /\.service-designer-deployed-action:focus-visible/);
  assert.match(css, /\.service-designer-service-flow/);
  assert.match(css, /\.service-designer-flow-stage\[data-stage="analysis"\]/);
  assert.match(css, /@media \(max-width: 680px\)/);
  assert.match(css, /\.service-designer-service-draft-note/);
  assert.match(css, /\.service-designer-input-preview/);
  assert.match(css, /\.service-designer-input-state\[data-state="error"\]/);
  assert.match(css, /\.service-designer-plan-gate/);
  assert.match(css, /\.service-designer-plan-blocker/);
  assert.match(css, /grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/);
  assert.equal(fs.existsSync(cssPath), true);
  assert.equal(fs.existsSync(uiPath), true);
  assert.equal(fs.existsSync(viewportPath), true);
});
