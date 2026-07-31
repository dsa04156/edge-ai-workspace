const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  addNode,
  buildExecutionPlan,
  canonicalDataType,
  connectNodes,
  createDefaultDesign,
  removeNode,
  resourcesForDevice,
  updateNode,
  validateDesign,
  wouldCreateCycle,
} = require("../app/static/service-designer-model.js");
const {
  STORAGE_KEY,
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
  assert.equal(fs.existsSync(cssPath), true);
  assert.equal(fs.existsSync(uiPath), true);
  assert.equal(fs.existsSync(viewportPath), true);
});
