const test = require("node:test");
const assert = require("node:assert/strict");

const {
  buildDashboardAlerts,
  deviceFilterEmptyText,
  deviceObservationUnavailable,
  formatDashboardKpiValue,
} = require("../app/static/dashboard.js");

test("shows EdgeX observation failure instead of empty inventory", () => {
  const data = {
    device_observation_error:
      "EdgeX device observation unavailable: EdgeXBackendError",
    nodes: [],
    devices: [],
  };

  assert.equal(deviceObservationUnavailable(data), true);
  assert.equal(deviceFilterEmptyText(data), "EdgeX device 관측 불가");
  assert.deepEqual(buildDashboardAlerts(data), [
    {
      kind: "source",
      level: "high",
      title: "EdgeX device observation unavailable",
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
    "EdgeX Core Metadata device가 없습니다.",
  );
  assert.deepEqual(buildDashboardAlerts(data), []);
  assert.equal(formatDashboardKpiValue("registered_device_count", 0, false), "0");
});
