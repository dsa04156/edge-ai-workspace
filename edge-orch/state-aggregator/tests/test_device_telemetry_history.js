const test = require("node:test");
const assert = require("node:assert/strict");

const {
  cancelDeviceTelemetryHistorySelection,
  createDeviceTelemetryHistoryState,
  deviceTelemetryHistoryUrl,
  fetchDeviceTelemetryHistory,
  handleTelemetryHistoryAction,
  loadDeviceTelemetryHistory,
  renderDeviceTelemetryHistory,
  state,
} = require("../app/static/dashboard.js");

function deferredResponse() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return {promise, resolve};
}

test.beforeEach(() => {
  state.selectedDeviceName = null;
  state.deviceTelemetryHistory = createDeviceTelemetryHistoryState();
});


test("requests one selected device history through state-aggregator", async () => {
  assert.equal(
    deviceTelemetryHistoryUrl("sensor / 01", "-30m"),
    "/state/devices/sensor%20%2F%2001/telemetry?window=-30m&limit=1000",
  );

  let request = null;
  const points = await fetchDeviceTelemetryHistory(
    "sensor / 01",
    "-30m",
    async (url, options) => {
      request = {url, options};
      return {
        ok: true,
        json: async () => [{device_name: "sensor / 01", value: 1}],
      };
    },
  );

  assert.deepEqual(request, {
    url: "/state/devices/sensor%20%2F%2001/telemetry?window=-30m&limit=1000",
    options: {cache: "no-store"},
  });
  assert.deepEqual(points, [{device_name: "sensor / 01", value: 1}]);
});


test("rejects HTTP failure without inventing history", async () => {
  await assert.rejects(
    fetchDeviceTelemetryHistory("sensor-01", "-5m", async () => ({
      ok: false,
      status: 503,
      json: async () => [],
    })),
    /telemetry history request failed: 503/,
  );
});


test("rejects a non-array history payload", async () => {
  await assert.rejects(
    fetchDeviceTelemetryHistory("sensor-01", "-5m", async () => ({
      ok: true,
      status: 200,
      json: async () => ({points: []}),
    })),
    /telemetry history response must be an array/,
  );
});


test("keeps the newest device when an older request finishes last", async () => {
  const first = deferredResponse();
  const second = deferredResponse();
  const renders = [];
  const fetchFn = (url) => (url.includes("device-a") ? first.promise : second.promise);
  const renderFn = (device, history) => {
    renders.push({device: device.name, history: {...history}});
  };

  const firstLoad = loadDeviceTelemetryHistory(
    {name: "device-a"},
    "-30m",
    fetchFn,
    renderFn,
  );
  const secondLoad = loadDeviceTelemetryHistory(
    {name: "device-b"},
    "-5m",
    fetchFn,
    renderFn,
  );

  second.resolve({
    ok: true,
    json: async () => [{device_name: "device-b", value: 2}],
  });
  assert.equal(await secondLoad, true);

  first.resolve({
    ok: true,
    json: async () => [{device_name: "device-a", value: 1}],
  });
  assert.equal(await firstLoad, false);

  assert.equal(state.selectedDeviceName, "device-b");
  assert.equal(state.deviceTelemetryHistory.deviceName, "device-b");
  assert.equal(state.deviceTelemetryHistory.window, "-5m");
  assert.deepEqual(state.deviceTelemetryHistory.points, [
    {device_name: "device-b", value: 2},
  ]);
  assert.equal(state.deviceTelemetryHistory.loading, false);
  assert.equal(state.deviceTelemetryHistory.error, null);
  assert.equal(renders.at(-1).device, "device-b");
});


test("isolates the current device history request failure", async () => {
  const renders = [];
  const applied = await loadDeviceTelemetryHistory(
    {name: "device-error"},
    "-1h",
    async () => ({ok: false, status: 502, json: async () => []}),
    (device, history) => renders.push({device: device.name, history: {...history}}),
  );

  assert.equal(applied, true);
  assert.equal(state.selectedDeviceName, "device-error");
  assert.equal(state.deviceTelemetryHistory.loading, false);
  assert.deepEqual(state.deviceTelemetryHistory.points, []);
  assert.match(state.deviceTelemetryHistory.error, /failed: 502/);
  assert.equal(renders.at(-1).device, "device-error");
});


test("renders all history ranges and a refresh action while loading", () => {
  const markup = renderDeviceTelemetryHistory(
    createDeviceTelemetryHistoryState({
      deviceName: "device-a",
      window: "-30m",
      loading: true,
    }),
  );

  for (const [windowValue, label] of [
    ["-5m", "5분"],
    ["-30m", "30분"],
    ["-1h", "1시간"],
    ["-24h", "24시간"],
  ]) {
    assert.match(markup, new RegExp(`data-telemetry-window="${windowValue}"`));
    assert.match(markup, new RegExp(`>${label}<`));
  }
  assert.match(markup, /data-telemetry-window="-30m" aria-pressed="true"/);
  assert.match(markup, /data-telemetry-refresh/);
  assert.match(markup, /Core Data 이력을 조회 중입니다/);
  assert.doesNotMatch(markup, /chart-svg/);
});


test("renders historical readings with requested and actual coverage", () => {
  const markup = renderDeviceTelemetryHistory(
    createDeviceTelemetryHistoryState({
      deviceName: "device-a",
      window: "-1h",
      points: [
        {timestamp: "2026-07-22T00:00:00Z", source_name: "source-a", resource_name: "temperature", value: "21.5"},
        {timestamp: "2026-07-22T00:01:00Z", source_name: "source-a", resource_name: "humidity", value: "45"},
        {timestamp: "2026-07-22T00:02:00Z", source_name: "source-a", resource_name: "temperature", value: "21.8"},
      ],
    }),
  );

  assert.match(markup, /Core Data history/);
  assert.match(markup, /요청 범위 1시간/);
  assert.match(markup, /3 readings/);
  assert.match(markup, /실제 구간/);
  assert.match(markup, /최신 1000 events 제한/);
  assert.match(markup, /source-a\.temperature/);
  assert.match(markup, /source-a\.humidity/);
  assert.match(markup, /chart-svg/);
});


test("keeps empty and error history honest without latest-reading fallback", () => {
  const emptyMarkup = renderDeviceTelemetryHistory(
    createDeviceTelemetryHistoryState({deviceName: "device-empty", window: "-5m"}),
  );
  assert.match(emptyMarkup, /선택한 범위에 저장된 이력이 없습니다/);
  assert.doesNotMatch(emptyMarkup, /latest readings/);

  const errorMarkup = renderDeviceTelemetryHistory(
    createDeviceTelemetryHistoryState({
      deviceName: "device-error",
      window: "-24h",
      error: "gateway <unavailable>",
    }),
  );
  assert.match(errorMarkup, /이력 조회 실패/);
  assert.match(errorMarkup, /gateway &lt;unavailable&gt;/);
  assert.doesNotMatch(errorMarkup, /latest readings/);
});


test("routes range and refresh controls to the selected device only", () => {
  state.data = {devices: [{name: "device-a"}, {name: "device-b"}]};
  state.selectedDeviceName = "device-b";
  state.deviceTelemetryHistory = createDeviceTelemetryHistoryState({
    deviceName: "device-b",
    window: "-30m",
  });
  const calls = [];
  const loadFn = (device, windowValue) => calls.push([device.name, windowValue]);

  const rangeTarget = {
    closest: (selector) => selector === "[data-telemetry-window]"
      ? {dataset: {telemetryWindow: "-1h"}}
      : null,
  };
  assert.equal(handleTelemetryHistoryAction(rangeTarget, loadFn), true);

  const refreshTarget = {
    closest: (selector) => selector === "[data-telemetry-refresh]"
      ? {dataset: {}}
      : null,
  };
  assert.equal(handleTelemetryHistoryAction(refreshTarget, loadFn), true);
  assert.deepEqual(calls, [["device-b", "-1h"], ["device-b", "-30m"]]);
});


test("ignores an in-flight history response after leaving device detail", async () => {
  const pending = deferredResponse();
  const renders = [];
  const load = loadDeviceTelemetryHistory(
    {name: "device-a"},
    "-30m",
    async () => pending.promise,
    (device, history) => renders.push({device: device.name, history: {...history}}),
  );

  cancelDeviceTelemetryHistorySelection();
  pending.resolve({
    ok: true,
    json: async () => [{device_name: "device-a", value: 1}],
  });

  assert.equal(await load, false);
  assert.equal(state.selectedDeviceName, null);
  assert.equal(state.deviceTelemetryHistory.loading, false);
  assert.deepEqual(state.deviceTelemetryHistory.points, []);
  assert.equal(renders.length, 1);
});
