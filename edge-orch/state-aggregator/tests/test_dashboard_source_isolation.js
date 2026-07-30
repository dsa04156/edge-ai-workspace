const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildDashboardAlerts,
  buildGlobalSearchResults,
  deviceFilterEmptyText,
  deviceObservationUnavailable,
  formatDashboardKpiValue,
} = require("../app/static/dashboard.js");

test("global search returns matching nodes, devices, and services", () => {
  const data = {
    nodes: [{hostname: "factory-edge-01", node_type: "edge_device"}],
    devices: [{
      name: "virtual-temperature-001",
      profile_name: "temperature-v1",
      device_service_name: "device-serial",
      protocol_names: ["serial"],
      node_name: "factory-edge-01",
    }],
    resource_profiles: {
      service_resource_profiles: [{
        namespace: "edgex-system",
        service: "edgex-core-data",
        pod_count: 1,
        nodes: ["server2"],
        containers: [{pod: "core-data-0", container: "core-data", node: "server2"}],
      }],
    },
  };

  assert.deepEqual(
    buildGlobalSearchResults("factory-edge", data).map((item) => item.kind),
    ["node", "device"],
  );
  assert.deepEqual(
    buildGlobalSearchResults("core-data", data).map((item) => item.id),
    ["edgex-system/edgex-core-data"],
  );
  assert.deepEqual(buildGlobalSearchResults("", data), []);
});

test("shows EdgeX observation failure instead of empty inventory", () => {
  const data = {
    device_observation_error:
      "EdgeX device observation unavailable: EdgeXBackendError",
    nodes: [],
    devices: [],
  };

  assert.equal(deviceObservationUnavailable(data), true);
  assert.equal(deviceFilterEmptyText(data), "센서 디바이스 관측 불가");
  assert.deepEqual(buildDashboardAlerts(data), [
    {
      kind: "source",
      level: "high",
      title: "센서 디바이스 관측 불가",
      text: "EdgeX device observation unavailable: EdgeXBackendError",
    },
  ]);
  assert.equal(formatDashboardKpiValue("registered_device_count", 0, true), "관측 불가");
  assert.equal(formatDashboardKpiValue("core_data_freshness_ratio", 0, true), "관측 불가");
  assert.equal(formatDashboardKpiValue("active_node_count", 5, true), "5");
});

test("keeps the empty inventory state when EdgeX observation succeeds", () => {
  const data = { device_observation_error: null };

  assert.equal(deviceObservationUnavailable(data), false);
  assert.equal(
    deviceFilterEmptyText(data),
    "등록된 센서 디바이스가 없습니다.",
  );
  assert.deepEqual(buildDashboardAlerts(data), []);
  assert.equal(formatDashboardKpiValue("registered_device_count", 0, false), "0");
});
