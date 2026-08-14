const assert = require("node:assert/strict");
const test = require("node:test");

const {filterResources, resourceUsage, statusLabel} = require("../app/static/resource-pool.js");

const resources = [
  {
    id: "data:sensor-one",
    category: "data",
    name: "가속도 센서",
    description: "sensor-profile · 3/3 입력 준비",
    kind: "edgex_virtual_device",
    node: "edge-one",
    status: "ready",
    capabilities: ["vibration"],
    current_bindings: ["sensor-anomaly-demo"],
    metadata: {physical_device_id: "arduino-001"},
  },
  {
    id: "compute:gpu-one",
    category: "compute",
    name: "GPU 추론",
    description: "1/1 인스턴스 관측",
    kind: "gpu",
    node: "server-one",
    status: "configured",
    capabilities: ["gpu_inference"],
  },
];

test("resource pool filters by category, status and searchable capability", () => {
  assert.deepEqual(
    filterResources(resources, {category: "data", status: "in-use", search: "vibration"})
      .map((item) => item.id),
    ["data:sensor-one"],
  );
  assert.deepEqual(
    filterResources(resources, {search: "SERVER-ONE"}).map((item) => item.id),
    ["compute:gpu-one"],
  );
});

test("resource pool status labels are operator-facing Korean", () => {
  assert.equal(statusLabel("ready"), "사용 가능");
  assert.equal(statusLabel("configured"), "구성됨");
  assert.equal(statusLabel("unexpected"), "상태 미확인");
});

test("resource pool distinguishes virtual devices in use from available devices", () => {
  assert.deepEqual(resourceUsage(resources[0]), {
    state: "in-use",
    label: "사용 중",
    bindingIds: ["sensor-anomaly-demo"],
  });
  assert.equal(resourceUsage({...resources[0], current_bindings: []}).label, "사용 가능");
  assert.deepEqual(
    filterResources(resources, {category: "data", status: "in-use"}).map((item) => item.id),
    ["data:sensor-one"],
  );
  assert.deepEqual(
    filterResources(resources, {category: "data", status: "available"}),
    [],
  );
});
