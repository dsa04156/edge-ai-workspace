const assert = require("node:assert/strict");
const test = require("node:test");

const {
  filterTwins,
  sortTwins,
  twinConnection,
} = require("../app/static/device-twins.js");

const twins = [
  {
    id: "twin:acceleration-x",
    name: "acceleration-x",
    physical_device_id: "arduino-001",
    node: "etri-dev0001-jetorn",
    profile_name: "acceleration-profile",
    observed_resources: ["acceleration_x_raw"],
    health: "ready",
    service_bindings: [
      {
        service_id: "sensor-anomaly-demo",
        service_name: "센서 이상 탐지",
        status: "active",
      },
    ],
  },
  {
    id: "twin:humidity",
    name: "humidity",
    physical_device_id: "sensehat-001",
    node: "etri-dev0003-raspi5",
    profile_name: "humidity-profile",
    observed_resources: ["humidity"],
    health: "ready",
    service_bindings: [],
  },
];

test("device twin connection is independent from twin health", () => {
  assert.equal(twinConnection(twins[0]).state, "bound");
  assert.equal(twins[0].health, "ready");
  assert.equal(twinConnection(twins[1]).state, "unbound");
});

test("device twin inventory filters service connections", () => {
  assert.deepEqual(
    filterTwins(twins, {binding: "bound"}).map((twin) => twin.id),
    ["twin:acceleration-x"],
  );
  assert.deepEqual(
    filterTwins(twins, {binding: "unbound"}).map((twin) => twin.id),
    ["twin:humidity"],
  );
});

test("device twin search covers physical source, data, and service", () => {
  assert.equal(filterTwins(twins, {search: "arduino-001"}).length, 1);
  assert.equal(filterTwins(twins, {search: "acceleration_x_raw"}).length, 1);
  assert.equal(filterTwins(twins, {search: "센서 이상 탐지"}).length, 1);
});

test("device twin inventory puts service-bound twins first", () => {
  assert.deepEqual(
    sortTwins([twins[1], twins[0]]).map((twin) => twin.id),
    ["twin:acceleration-x", "twin:humidity"],
  );
});
