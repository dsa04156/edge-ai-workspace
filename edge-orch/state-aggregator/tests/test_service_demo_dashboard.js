const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  buildServiceDemoAlertView,
  buildServiceDemoView,
  refreshServiceDemo,
  refreshServiceDemoAlerts,
  renderServiceDemo,
  renderServiceDemoAlerts,
} = require("../app/static/service-demo.js");


test("builds an honest live device-to-consumer anomaly view", () => {
  const view = buildServiceDemoView({
    mode: "live",
    status: "anomaly",
    input_state: "fresh",
    model_state: "ready",
    binding: {
      physical_source: "arduino-001",
      device_service: "device-serial-jetson",
      devices: [
        "virtual-acceleration-x-001",
        "virtual-acceleration-y-001",
        "virtual-acceleration-z-001",
      ],
      consumer: "sensor-anomaly-demo",
      node: "etri-dev0001-jetorn",
    },
    latest: {
      origin: 1_784_600_000_000_000_000,
      values: {x: 1, y: 2, z: 3},
      magnitude: 3.742,
      score: 5.1,
      anomaly: true,
      component_scores: {vibration: 6.0, temperature: 3.0},
      temperature_features: {
        raw: 301,
        alignment_lag_ms: 12.5,
      },
    },
    model: {
      algorithm: "online-gaussian-baseline-v1",
      sample_count: 40,
      warmup_samples: 30,
      threshold: 4.0,
    },
    counters: {frames_processed: 40, input_errors: 0},
    observation_error: null,
  });

  assert.equal(view.badge, "ANOMALY");
  assert.equal(view.tone, "anomaly");
  assert.equal(view.flow, "arduino-001 → device-serial-jetson → sensor-anomaly-demo");
  assert.equal(view.values, "X 1 · Y 2 · Z 3");
  assert.equal(view.magnitude, "3.742 raw");
  assert.equal(view.vibrationScore, "6.00");
  assert.equal(view.temperatureScore, "3.00");
  assert.equal(view.score, "5.10 / 4.00");
  assert.equal(view.temperatureContext, "raw 301 · 정렬 12.5 ms");
  assert.equal(view.model, "online-gaussian-baseline-v1 · 40 samples · ready");
  assert.equal(view.copy, "진동·온도 복합 이상 점수 · Jetson local inference");
  assert.equal(view.error, "");
});


test("shows unavailable observation without inventing zero values", () => {
  const view = buildServiceDemoView({
    mode: "unavailable",
    status: "degraded",
    input_state: "error",
    model_state: "unavailable",
    binding: {
      devices: [],
      consumer: "sensor-anomaly-demo",
      node: "etri-dev0001-jetorn",
    },
    latest: null,
    model: null,
    observation_error: "sensor anomaly demo unavailable: ConnectTimeout",
  });

  assert.equal(view.badge, "DEGRADED");
  assert.equal(view.tone, "degraded");
  assert.equal(view.values, "관측 불가");
  assert.equal(view.magnitude, "관측 불가");
  assert.equal(view.vibrationScore, "관측 불가");
  assert.equal(view.temperatureScore, "관측 불가");
  assert.equal(view.score, "관측 불가");
  assert.equal(view.temperatureContext, "관측 불가");
  assert.equal(view.model, "model 관측 불가");
  assert.match(view.error, /ConnectTimeout/);
});


test("formats the latest input age from the observed timestamp", () => {
  const view = buildServiceDemoView({
    status: "normal",
    input_state: "fresh",
    latest: {
      observed_at: "2026-07-22T10:00:00.000Z",
      values: {x: 1, y: 2, z: 3},
      magnitude: 3.742,
      score: 0.5,
    },
    model: {threshold: 4},
  }, Date.parse("2026-07-22T10:00:02.500Z"));

  assert.equal(view.inputAge, "2.5 s");
  assert.equal(view.vibrationScore, "0.50");
  assert.equal(view.temperatureScore, "관측 불가");
  assert.equal(view.copy, "3축 진동 이상 점수 · Jetson local inference");
});


test("renders with textContent and a non-color status label", () => {
  const ids = [
    "serviceDemoState",
    "serviceDemoInputState",
    "serviceDemoFlow",
    "serviceDemoPhysicalSource",
    "serviceDemoDeviceService",
    "serviceDemoConsumer",
    "serviceDemoNode",
    "serviceDemoDevices",
    "serviceDemoValues",
    "serviceDemoMagnitude",
    "serviceDemoVibrationScore",
    "serviceDemoTemperatureScore",
    "serviceDemoScore",
    "serviceDemoTemperatureContext",
    "serviceDemoModel",
    "serviceDemoOrigin",
    "serviceDemoInputAge",
    "serviceDemoError",
  ];
  const elements = Object.fromEntries(ids.map((id) => [
    id,
    {textContent: "", hidden: false, dataset: {}},
  ]));
  const documentRef = {getElementById: (id) => elements[id]};

  renderServiceDemo({
    status: "normal",
    input_state: "fresh",
    model_state: "ready",
    binding: {
      physical_source: "arduino-001",
      device_service: "device-serial-jetson",
      devices: ["virtual-acceleration-x-001"],
      consumer: "sensor-anomaly-demo",
      node: "etri-dev0001-jetorn",
    },
    latest: {
      origin: 100,
      observed_at: "2999-01-01T00:00:00Z",
      values: {x: 1, y: 2, z: 3},
      magnitude: 3.742,
      score: 0.5,
      component_scores: {vibration: 0.4, temperature: 0.7},
      temperature_features: {raw: 300, alignment_lag_ms: 8},
    },
    model: {algorithm: "online-gaussian-baseline-v1", sample_count: 30, threshold: 4},
  }, documentRef);

  assert.equal(elements.serviceDemoState.textContent, "NORMAL");
  assert.equal(elements.serviceDemoState.dataset.state, "normal");
  assert.equal(elements.serviceDemoValues.textContent, "X 1 · Y 2 · Z 3");
  assert.equal(elements.serviceDemoVibrationScore.textContent, "0.40");
  assert.equal(elements.serviceDemoTemperatureScore.textContent, "0.70");
  assert.equal(elements.serviceDemoTemperatureContext.textContent, "raw 300 · 정렬 8.0 ms");
  assert.equal(elements.serviceDemoInputAge.textContent, "0.0 s");
  assert.equal(elements.serviceDemoError.hidden, true);
});


test("refreshes from the failure-isolated service demo endpoint", async () => {
  const ids = [
    "serviceDemoState", "serviceDemoInputState", "serviceDemoFlow",
    "serviceDemoPhysicalSource", "serviceDemoDeviceService", "serviceDemoConsumer",
    "serviceDemoNode", "serviceDemoDevices", "serviceDemoValues",
    "serviceDemoMagnitude", "serviceDemoVibrationScore",
    "serviceDemoTemperatureScore", "serviceDemoScore",
    "serviceDemoTemperatureContext", "serviceDemoModel",
    "serviceDemoOrigin", "serviceDemoError",
  ];
  const elements = Object.fromEntries(ids.map((id) => [
    id,
    {textContent: "", hidden: false, dataset: {}},
  ]));
  const documentRef = {getElementById: (id) => elements[id]};
  let request = null;
  const fetchFn = async (url, options) => {
    request = {url, options};
    return {
      ok: true,
      json: async () => ({
        status: "warming_up",
        input_state: "fresh",
        model_state: "warming_up",
        binding: {consumer: "sensor-anomaly-demo", node: "etri-dev0001-jetorn"},
        latest: null,
        model: null,
      }),
    };
  };

  await refreshServiceDemo(fetchFn, documentRef);

  assert.deepEqual(request, {
    url: "/state/service-demo",
    options: {cache: "no-store"},
  });
  assert.equal(elements.serviceDemoState.textContent, "WARMING_UP");
});


test("renders persisted alert transitions without injecting markup", async () => {
  const view = buildServiceDemoAlertView({
    mode: "live",
    count: 2,
    alerts: [{
      transition: "cleared",
      status: "closed",
      score: 0.25,
      observed_at: "2026-08-03T10:00:00Z",
    }],
  });
  assert.equal(view.count, "2건");
  assert.match(view.latest, /정상 복귀 · 점수 0\.25/);

  const elements = {
    serviceDemoAlertCount: {textContent: ""},
    serviceDemoAlertLatest: {textContent: ""},
  };
  const documentRef = {getElementById: (id) => elements[id]};
  renderServiceDemoAlerts({mode: "live", count: 0, alerts: []}, documentRef);
  assert.equal(elements.serviceDemoAlertCount.textContent, "0건");
  assert.equal(elements.serviceDemoAlertLatest.textContent, "알림 없음");

  let request = null;
  await refreshServiceDemoAlerts(async (url, options) => {
    request = {url, options};
    return {
      ok: true,
      json: async () => ({mode: "live", count: 0, alerts: []}),
    };
  }, documentRef);
  assert.deepEqual(request, {
    url: "/state/service-demo/alerts?limit=10",
    options: {cache: "no-store"},
  });
});


test("dashboard ships a responsive accessible live demo panel", () => {
  const root = path.resolve(__dirname, "..");
  const html = fs.readFileSync(path.join(root, "app/static/index.html"), "utf8");
  const css = fs.readFileSync(path.join(root, "app/static/service-demo.css"), "utf8");
  const javascript = fs.readFileSync(path.join(root, "app/static/service-demo.js"), "utf8");

  assert.match(html, /aria-labelledby="serviceDemoTitle"/);
  for (const id of [
    "serviceDemoState", "serviceDemoFlow", "serviceDemoPhysicalSource",
    "serviceDemoDeviceService", "serviceDemoConsumer", "serviceDemoNode",
    "serviceDemoDevices", "serviceDemoValues", "serviceDemoMagnitude",
    "serviceDemoVibrationScore", "serviceDemoTemperatureScore", "serviceDemoScore",
    "serviceDemoTemperatureContext", "serviceDemoModel", "serviceDemoOrigin", "serviceDemoError",
    "serviceDemoInputAge",
    "serviceDemoAlertCount", "serviceDemoAlertLatest",
  ]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /service-demo\.css\?v=persistent-alerts-20260803/);
  assert.match(html, /service-demo\.js\?v=persistent-alerts-20260803/);
  assert.match(css, /\[data-state="anomaly"\]/);
  assert.match(css, /grid-template-columns: repeat\(5, minmax\(0, 1fr\)\);/);
  assert.match(css, /@media \(max-width: 760px\)/);
  assert.match(css, /\.service-demo-alert-summary/);
  assert.match(css, /\.service-demo-route > div > span,/);
  assert.doesNotMatch(css, /\.service-demo-route span,/);
  assert.doesNotMatch(javascript, /\.innerHTML\s*=/);
});
