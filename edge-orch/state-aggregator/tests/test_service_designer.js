const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  addNode,
  addServiceNode,
  buildServiceCatalog,
  buildExecutionPlan,
  canonicalDataType,
  connectNodes,
  createDefaultDesign,
  createMultiSensorScoreExampleDesign,
  createSensorAnomalyExampleDesign,
  removeNode,
  resourcesForDevice,
  updateNode,
  validateDesign,
  wouldCreateCycle,
} = require("../app/static/service-designer-model.js");
const {
  STORAGE_KEY,
  accelerationAxisBindingCandidates,
  bindMultiSensorScoreExample,
  bindSensorAnomalyExample,
  contextSourceBindingCandidate,
  deployedServiceView,
  fetchDesignerServices,
  fetchDesignerProfiles,
  loadStoredDesign,
  saveStoredDesign,
  sourceBindingCandidate,
} = require("../app/static/service-designer.js");
const {
  GRID_SIZE,
  MAX_ZOOM,
  MIN_ZOOM,
  centerOnWorldPoint,
  clampNodePosition,
  clampNodeToViewport,
  constrainNodePosition,
  ensureWorldRectVisible,
  fitViewport,
  graphBounds,
  nudgeNodePosition,
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

test("keeps the complete node inside the currently visible canvas viewport", () => {
  const viewport = {x: -300, y: -100, zoom: 1.6};
  const nodeSize = {nodeWidth: 218, nodeHeight: 161};
  const placed = clampNodeToViewport(
    {x: 900, y: 500},
    viewport,
    958,
    453,
    {...nodeSize, padding: 12},
  );
  const screen = {
    left: viewport.x + placed.x * viewport.zoom,
    right: viewport.x + (placed.x + nodeSize.nodeWidth) * viewport.zoom,
    top: viewport.y + placed.y * viewport.zoom,
    bottom: viewport.y + (placed.y + nodeSize.nodeHeight) * viewport.zoom,
  };

  assert.ok(screen.left >= 12);
  assert.ok(screen.right <= 958 - 12);
  assert.ok(screen.top >= 12);
  assert.ok(screen.bottom <= 453 - 12);
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
  assert.deepEqual(clampNodePosition({x: -20, y: 900}), {x: 16, y: 528});
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
  assert.match(html, /실제 배포 상태 · 읽기 전용/);
  assert.match(html, /설계 블록/);
  assert.match(html, /id="serviceDesignerReset"[\s\S]*?>3축 데모</);
  assert.match(html, /id="serviceDesignerMultiSensorExample"[\s\S]*?>복합 점수 예시</);
  assert.match(html, /id="serviceDesignerCatalogState"/);
  assert.match(html, /빠른 드래그 · 화면 안에 고정 · 놓을 때 정렬 · Alt 정렬 해제/);
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
  assert.match(ui, /renderDeployedServices/);
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
  assert.match(ui, /const directPlacement = viewportModel\.clampNodeToViewport\(/);
  assert.match(ui, /leftInset:\s*Math\.max\(0,\s*-canvasBounds\.left\)/);
  assert.match(ui, /rightInset:\s*Math\.max\(0,\s*canvasBounds\.right - browserWidth\)/);
  assert.match(ui, /const snappedDropPlacement = viewportModel\.snapNodePosition\(/);
  assert.match(ui, /snap:\s*!event\.altKey,\s*[\s\S]*?grid:\s*false,/);
  assert.match(ui, /state\.dragging\.dropX = dropPlacement\.x/);
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
  assert.match(css, /grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/);
  assert.equal(fs.existsSync(cssPath), true);
  assert.equal(fs.existsSync(uiPath), true);
  assert.equal(fs.existsSync(viewportPath), true);
});
