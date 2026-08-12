const assert = require("node:assert/strict");
const test = require("node:test");

const {filterResources, statusLabel} = require("../app/static/resource-pool.js");

const resources = [
  {
    id: "data:sensor-one",
    category: "data",
    name: "가속도 센서",
    description: "sensor-profile · 3/3 입력 준비",
    kind: "edgex_device_projection",
    node: "edge-one",
    status: "ready",
    capabilities: ["vibration"],
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
    filterResources(resources, {category: "data", status: "ready", search: "vibration"})
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
