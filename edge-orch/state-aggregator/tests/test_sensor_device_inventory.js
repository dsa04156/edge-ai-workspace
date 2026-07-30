const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  resourceCategoryItems,
  resourceCategoryView,
  renderResourceInventoryRows,
  renderSensorDeviceRows,
  sensorDeviceStatusLabel,
} = require("../app/static/dashboard.js");

const root = path.resolve(__dirname, "..");

test("renders a scalable four-column sensor inventory row", () => {
  const device = {
    name: "virtual-temperature-001",
    overall_status: "available",
    latest_event_timestamp: "2099-01-01T00:00:00Z",
  };

  const markup = renderSensorDeviceRows([device]);

  assert.match(markup, /<tr class="sensor-device-row/);
  assert.match(markup, />virtual-temperature-001</);
  assert.match(markup, /Available/);
  assert.match(markup, /data-label="최신 이벤트"/);
  assert.match(markup, />상세보기</);
  assert.doesNotMatch(markup, /프로토콜|수집 서비스|배치 노드/);
});

test("maps all sensor availability states to operator labels", () => {
  assert.equal(sensorDeviceStatusLabel({overall_status: "available"}), "Available");
  assert.equal(sensorDeviceStatusLabel({overall_status: "degraded"}), "Degraded");
  assert.equal(sensorDeviceStatusLabel({overall_status: "unavailable"}), "Unavailable");
  assert.equal(sensorDeviceStatusLabel({overall_status: "unexpected"}), "Degraded");
});

test("dashboard exposes sensor language and table-first inventory structure", () => {
  const html = fs.readFileSync(path.join(root, "app/static/index.html"), "utf8");
  const css = fs.readFileSync(
    path.join(root, "app/static/operations-dashboard.css"),
    "utf8",
  );

  assert.match(html, />디바이스</);
  assert.match(html, /data-resource-category="server"[^>]*>[\s\S]*엣지 AI 서버/);
  assert.match(html, /data-resource-category="physical"[^>]*>[\s\S]*물리 디바이스/);
  assert.match(html, /data-resource-category="virtual"[^>]*>[\s\S]*가상 디바이스/);
  assert.match(html, /data-resource-category="sensor"[^>]*>[\s\S]*센서 디바이스/);
  assert.match(html, /class="sensor-device-table"/);
  assert.match(html, /<th scope="col">이름<\/th>/);
  assert.match(html, /<th scope="col">상태<\/th>/);
  assert.match(html, /<th id="inventoryLatestHeading" scope="col">최신 이벤트<\/th>/);
  assert.doesNotMatch(html, /EdgeX 디바이스/);
  assert.match(css, /#deviceList\s*\{\s*display: table-row-group !important;/);
  assert.match(css, /@media \(max-width: 680px\)/);
});

test("classifies dashboard resources into four explicit operator categories", () => {
  const data = {
    nodes: [
      {hostname: "etri-ser0001", node_type: "cloud_server", node_health: "healthy"},
      {hostname: "etri-ser0002", node_type: "server", node_health: "healthy"},
      {hostname: "etri-dev0001", node_type: "edge_ai_device", node_health: "healthy"},
      {hostname: "etri-dev0002", node_type: "edge_light_device", node_health: "degraded"},
    ],
    devices: [
      {name: "sensor-temperature-001", overall_status: "available"},
      {name: "sensor-vibration-001", overall_status: "degraded"},
    ],
    virtual_resources: {
      generated_at: "2099-01-01T00:00:00Z",
      resources: [
        {id: "vd-gpu-001", display_name: "GPU Inference", status: "idle", node: "etri-ser0002"},
      ],
    },
  };

  assert.deepEqual(
    resourceCategoryItems(data, "server").map((item) => item.name),
    ["etri-ser0001", "etri-ser0002"],
  );
  assert.deepEqual(
    resourceCategoryItems(data, "physical").map((item) => item.name),
    ["etri-dev0001", "etri-dev0002"],
  );
  assert.deepEqual(
    resourceCategoryItems(data, "virtual").map((item) => item.name),
    ["GPU Inference"],
  );
  assert.deepEqual(
    resourceCategoryItems(data, "sensor").map((item) => item.name),
    ["sensor-temperature-001", "sensor-vibration-001"],
  );
});

test("renders every category as the same concise list with contextual observation label", () => {
  const nodeRows = renderResourceInventoryRows([
    {
      id: "etri-ser0001",
      name: "etri-ser0001",
      kind: "server",
      status: "available",
      statusLabel: "Available",
      observedAt: "2099-01-01T00:00:00Z",
    },
  ], {category: "server"});
  const virtualRows = renderResourceInventoryRows([
    {
      id: "vd-gpu-001",
      name: "GPU Inference",
      kind: "virtual",
      status: "available",
      statusLabel: "Available",
      observedAt: "2099-01-01T00:00:00Z",
    },
  ], {category: "virtual"});

  assert.match(nodeRows, /data-resource-kind="server"/);
  assert.match(nodeRows, /data-label="최신 관측"/);
  assert.match(nodeRows, />상세보기</);
  assert.match(virtualRows, /data-resource-kind="virtual"/);
  assert.match(virtualRows, /GPU Inference/);
});

test("provides concise Korean labels for each resource category", () => {
  assert.equal(resourceCategoryView("server").label, "엣지 AI 서버");
  assert.equal(resourceCategoryView("physical").label, "물리 디바이스");
  assert.equal(resourceCategoryView("virtual").label, "가상 디바이스");
  assert.equal(resourceCategoryView("sensor").label, "센서 디바이스");
  assert.equal(resourceCategoryView("sensor").latestLabel, "최신 이벤트");
  assert.equal(resourceCategoryView("server").latestLabel, "최신 관측");
});
