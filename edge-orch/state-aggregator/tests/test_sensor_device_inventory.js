const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  resourceCategoryItems,
  resourceCategoryView,
  physicalDeviceOverviewModel,
  renderPhysicalDeviceStatusRows,
  renderResourceInventorySection,
  renderResourceInventoryRows,
  renderServerStatusRows,
  renderSensorDeviceRows,
  sensorDeviceStatusLabel,
  serverOverviewModel,
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

test("dashboard exposes all device categories in one continuous inventory", () => {
  const html = fs.readFileSync(path.join(root, "app/static/index.html"), "utf8");
  const css = fs.readFileSync(
    path.join(root, "app/static/operations-dashboard.css"),
    "utf8",
  );

  assert.match(html, />디바이스</);
  assert.match(html, /<h2 id="inventoryTitle">전체 디바이스<\/h2>/);
  assert.match(html, /id="resourceInventorySections"/);
  assert.match(html, /서버, 현장 엣지 노드, 가상 자원과 EdgeX 센서를 한 화면에서 확인합니다/);
  assert.doesNotMatch(html, /class="resource-category-tabs"/);
  assert.doesNotMatch(html, /data-resource-category="server"/);
  assert.doesNotMatch(html, /EdgeX 디바이스/);
  assert.match(css, /\.resource-inventory-sections/);
  assert.match(css, /\.resource-inventory-section/);
  assert.match(css, /\.resource-inventory-body\s*\{\s*display: table-row-group !important;/);
  assert.match(css, /@media \(max-width: 680px\)/);
});

test("renders the four categories as simultaneous concise tables", () => {
  const categoryItems = {
    server: "etri-ser0001",
    physical: "etri-dev0001",
    virtual: "vd-gpu-001",
    sensor: "virtual-temperature-001",
  };
  const markup = Object.entries(categoryItems).map(([category, name]) => (
    renderResourceInventorySection({
      category,
      items: [{
        id: name,
        name,
        kind: category,
        status: "available",
        statusLabel: "Available",
        observedAt: "2099-01-01T00:00:00Z",
      }],
    })
  )).join("");

  assert.match(markup, /id="resourceInventory-server"/);
  assert.match(markup, />엣지 AI 서버<\/h3>/);
  assert.match(markup, /id="resourceInventory-physical"/);
  assert.match(markup, />물리 디바이스<\/h3>/);
  assert.match(markup, /id="resourceInventory-virtual"/);
  assert.match(markup, />가상 디바이스<\/h3>/);
  assert.match(markup, /id="resourceInventory-sensor"/);
  assert.match(markup, />센서 디바이스<\/h3>/);
  assert.equal((markup.match(/class="sensor-device-table"/g) || []).length, 4);
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

test("builds an honest server observability summary from current node metrics", () => {
  const data = {
    nodes: [
      {
        hostname: "etri-ser0001",
        node_type: "cloud_server",
        node_health: "healthy",
        collected_at: "2099-01-01T00:00:00Z",
        raw_metrics: {
          cpu_utilization: 0.2,
          memory_usage_ratio: 0.4,
          gpu_utilization: 0.5,
        },
        compute_pressure: "low",
        memory_pressure: "low",
        network_pressure: "low",
      },
      {
        hostname: "etri-ser0002",
        node_type: "server",
        node_health: "degraded",
        collected_at: "2099-01-01T00:00:01Z",
        raw_metrics: {
          cpu_utilization: 0.4,
          memory_usage_ratio: 0.6,
        },
        compute_pressure: "medium",
        memory_pressure: "low",
        network_pressure: "low",
      },
      {
        hostname: "etri-dev0001",
        node_type: "edge_ai_device",
        node_health: "healthy",
        raw_metrics: {
          cpu_utilization: 0.9,
          memory_usage_ratio: 0.9,
        },
      },
    ],
  };

  const model = serverOverviewModel(data);

  assert.equal(model.total, 2);
  assert.equal(model.available, 1);
  assert.ok(Math.abs(model.averageCpu - 0.3) < 1e-9);
  assert.equal(model.averageMemory, 0.5);
  assert.equal(model.gpuObserved, 1);
  assert.equal(model.pressureAttention, 1);
  assert.equal(model.latestObservedAt, "2099-01-01T00:00:01.000Z");
});

test("renders Grafana-style server rows without inventing missing GPU values", () => {
  const markup = renderServerStatusRows([
    {
      id: "etri-ser0001",
      name: "etri-ser0001",
      kind: "server",
      status: "available",
      statusLabel: "Available",
      observedAt: "2099-01-01T00:00:00Z",
      raw: {
        raw_metrics: {
          cpu_utilization: 0.2,
          memory_usage_ratio: 0.4,
        },
        compute_pressure: "low",
        memory_pressure: "low",
        network_pressure: "low",
      },
    },
  ]);

  assert.match(markup, /etri-ser0001/);
  assert.match(markup, /Available/);
  assert.match(markup, /role="progressbar"/);
  assert.match(markup, />20%</);
  assert.match(markup, />40%</);
  assert.match(markup, />N\/A</);
  assert.match(markup, /aria-valuetext="관측 불가"/);
  assert.doesNotMatch(markup, /서비스 데모|Jetson 센서 이상 탐지/);
});

test("builds physical device status separately from server status", () => {
  const data = {
    nodes: [
      {
        hostname: "etri-ser0001",
        node_type: "cloud_server",
        node_health: "healthy",
        collected_at: "2099-01-01T00:00:00Z",
        raw_metrics: {
          cpu_utilization: 0.1,
          memory_usage_ratio: 0.2,
        },
      },
      {
        hostname: "etri-dev0001-jetorn",
        node_type: "edge_ai_device",
        node_health: "healthy",
        collected_at: "2099-01-01T00:00:01Z",
        raw_metrics: {
          cpu_utilization: 0.3,
          memory_usage_ratio: 0.5,
          gpu_utilization: 0.6,
        },
        compute_pressure: "low",
        memory_pressure: "low",
        network_pressure: "low",
      },
      {
        hostname: "etri-dev0003-raspi5",
        node_type: "edge_light_device",
        node_health: "degraded",
        collected_at: "2099-01-01T00:00:02Z",
        raw_metrics: {
          cpu_utilization: 0.5,
          memory_usage_ratio: 0.7,
        },
        compute_pressure: "medium",
        memory_pressure: "low",
        network_pressure: "low",
      },
    ],
  };

  const model = physicalDeviceOverviewModel(data);
  const markup = renderPhysicalDeviceStatusRows(model.items);

  assert.equal(model.total, 2);
  assert.equal(model.available, 1);
  assert.equal(model.averageCpu, 0.4);
  assert.equal(model.averageMemory, 0.6);
  assert.equal(model.gpuObserved, 1);
  assert.equal(model.pressureAttention, 1);
  assert.match(markup, /etri-dev0001-jetorn/);
  assert.match(markup, /AI 엣지 노드/);
  assert.match(markup, /etri-dev0003-raspi5/);
  assert.match(markup, /경량 엣지 노드/);
  assert.doesNotMatch(markup, /etri-ser0001/);
});

test("places server and physical observability before the expanded service demo", () => {
  const html = fs.readFileSync(path.join(root, "app/static/index.html"), "utf8");

  const serverIndex = html.indexOf('id="serverOverviewTitle"');
  const physicalIndex = html.indexOf('id="physicalDeviceOverviewTitle"');
  const serviceDemoIndex = html.indexOf('id="serviceDemoTitle"');

  assert.ok(serverIndex < physicalIndex);
  assert.ok(physicalIndex < serviceDemoIndex);
  assert.match(html, /<h2 id="serverOverviewTitle">서버 상태<\/h2>/);
  assert.match(html, /id="serverStatusList"/);
  assert.match(html, /<h2 id="physicalDeviceOverviewTitle">물리 디바이스 상태<\/h2>/);
  assert.match(html, /id="physicalDeviceStatusList"/);
  assert.match(html, /data-resource-category-link="physical">물리 디바이스 목록/);
  assert.match(html, /<details class="panel service-demo-panel overview-service-demo/);
  assert.match(
    html,
    /<details class="panel service-demo-panel overview-service-demo[^>]*\sopen(?:\s|>)/,
  );
  assert.match(html, /dashboard\.js\?v=cpu-aware-pressure-v3-20260804/);
  assert.match(html, /operations-dashboard\.css\?v=unified-device-inventory-v2-20260804/);
});
