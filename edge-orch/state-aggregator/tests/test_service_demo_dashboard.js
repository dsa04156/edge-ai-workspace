const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  buildServiceAugmentationView,
  buildServiceOperationsTimelineView,
  buildServiceRoutingView,
  buildServiceDemoAlertView,
  buildServiceCatalogView,
  buildServiceInventoryView,
  buildServiceDemoResultsView,
  buildServiceDemoView,
  refreshServiceDemo,
  refreshServiceDemoAlerts,
  refreshServiceDemoResults,
  refreshServiceAugmentation,
  renderServiceDemo,
  renderServiceCatalog,
  renderServiceDemoAlerts,
  renderServiceDemoResults,
  renderServiceAugmentation,
  applyServiceDescriptor,
} = require("../app/static/service-demo.js");


test("builds an observed Device1 and Server1 traffic split from persisted results", () => {
  const view = buildServiceRoutingView({
    mode: "live",
    results: [
      {inference_target: "edge-local"},
      {inference_target: "server1"},
      {inference_target: "edge-local"},
      {inference_target: "edge-local"},
    ],
  });

  assert.equal(view.deviceCount, 3);
  assert.equal(view.serverCount, 1);
  assert.equal(view.deviceRatio, 75);
  assert.equal(view.serverRatio, 25);
  assert.equal(view.summary, "최근 4건 기준");
});


test("keeps the traffic split unknown when there are no observed results", () => {
  const view = buildServiceRoutingView({mode: "live", results: []});
  assert.equal(view.deviceRatio, null);
  assert.equal(view.serverRatio, null);
  assert.equal(view.summary, "처리 표본 대기");
});


test("combines augmentation transitions and equipment alerts into one newest-first timeline", () => {
  const view = buildServiceOperationsTimelineView({
    transitions: [
      {
        occurred_at: "2026-08-13T10:00:03Z",
        from_state: "RECOMMENDED",
        to_state: "AUGMENTED",
        reason: "approved_augmentation_observed",
      },
    ],
  }, {
    alerts: [
      {
        observed_at: "2026-08-13T10:00:01Z",
        transition: "opened",
        score: 5.2,
      },
    ],
  });

  assert.equal(view.events.length, 2);
  assert.equal(view.events[0].kind, "augmentation");
  assert.equal(view.events[0].title, "자원 증강 실행");
  assert.equal(view.events[1].kind, "equipment");
  assert.equal(view.events[1].title, "설비 이상 발생");
});


test("builds a service list row from live operating evidence", () => {
  const view = buildServiceCatalogView({
    status: "anomaly",
    input_state: "fresh",
    model_state: "ready",
    binding: {
      consumer: "sensor-anomaly-demo",
      node: "etri-dev0001-jetorn",
    },
    latest: {
      anomaly: true,
      model_version: "baseline-1.0.0",
      inference_target: "edge-local",
    },
  });

  assert.equal(view.name, "sensor-anomaly-demo");
  assert.equal(view.operatingState, "running");
  assert.equal(view.operatingLabel, "실행 중");
  assert.equal(view.input, "fresh");
  assert.equal(view.node, "etri-dev0001-jetorn");
  assert.equal(view.model, "baseline-1.0.0");
  assert.equal(view.decision, "이상 감지");
  assert.equal(view.routing, "edge-local");
});


test("builds service catalog rows from Git descriptors without hardcoded HTML", () => {
  const view = buildServiceInventoryView({
    services: [{
      service_id: "sensor-anomaly-demo",
      display_name: "펌프·모터 진동·온도 이상감지",
      description: "기준선",
      mode: "live",
      status: "normal",
      input_state: "fresh",
      model_state: "ready",
      node: "etri-dev0001-jetorn",
      model_version: "baseline-1.0.0",
      inference_target: "edge-local",
      definition_source: "git:service_catalog.json",
      catalog_version: "edgeai.etri/service-catalog/v1",
      descriptor: {observability: {adapter: "sensor-anomaly-v1"}},
    }],
  });

  assert.equal(view.rows.length, 1);
  assert.equal(view.rows[0].displayName, "펌프·모터 진동·온도 이상감지");
  assert.equal(view.rows[0].operatingState, "running");
  assert.equal(view.definitionSource, "git:service_catalog.json · edgeai.etri/service-catalog/v1");
});


test("applies descriptor stage and target labels to the operations DAG", () => {
  const elements = Object.fromEntries([
    "serviceDemoTitle", "serviceOperationsServiceId", "serviceOperationsDagTitle",
    "serviceDemoStepInputLabel", "serviceDemoStepInferenceLabel",
    "serviceDagDevice1Label", "serviceDagDevice1Description",
  ].map((id) => [id, {textContent: ""}]));
  applyServiceDescriptor({
    service_id: "pump-monitor",
    display_name: "펌프 감시",
    descriptor: {
      graph: {
        title: "Pump signal → Decision",
        stages: [
          {slot: "Input", label: "PLC 수집"},
          {slot: "Inference", label: "고장 추론"},
        ],
        targets: [
          {slot: "Device1", label: "현장 Jetson", description: "local"},
        ],
      },
      observability: {adapter: "sensor-anomaly-v1"},
    },
  }, {getElementById: (id) => elements[id]});

  assert.equal(elements.serviceDemoTitle.textContent, "펌프 감시");
  assert.equal(elements.serviceOperationsServiceId.textContent, "pump-monitor");
  assert.equal(elements.serviceDemoStepInputLabel.textContent, "PLC 수집");
  assert.equal(elements.serviceDemoStepInferenceLabel.textContent, "고장 추론");
  assert.equal(elements.serviceDagDevice1Label.textContent, "현장 Jetson");
});


test("renders service list status independently from equipment decision", () => {
  const elements = Object.fromEntries([
    "serviceCatalogName", "serviceCatalogStatus", "serviceCatalogAvailability",
    "serviceCatalogInput", "serviceCatalogNode", "serviceCatalogModel",
    "serviceCatalogDecision", "serviceCatalogRouting",
  ].map((id) => [id, {textContent: "", dataset: {}}]));
  const documentRef = {getElementById: (id) => elements[id]};

  renderServiceCatalog({
    status: "anomaly",
    input_state: "fresh",
    model_state: "ready",
    binding: {consumer: "sensor-anomaly-demo", node: "etri-dev0001-jetorn"},
    latest: {anomaly: true, model_version: "baseline-1.0.0"},
  }, documentRef);

  assert.equal(elements.serviceCatalogStatus.textContent, "실행 중");
  assert.equal(elements.serviceCatalogStatus.dataset.state, "running");
  assert.equal(elements.serviceCatalogAvailability.textContent, "1/1 실행 중");
  assert.equal(elements.serviceCatalogDecision.textContent, "이상 감지");
});


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
  assert.equal(view.copy, "진동·온도 복합 이상 점수 · edge-local inference");
  assert.equal(view.inferenceRouting, "로컬 추론 · edge-local · 승인 없음");
  assert.equal(view.decisionLabel, "이상 감지");
  assert.equal(view.pipeline.map((step) => step.state).join(","), "ready,ready,active,anomaly,anomaly");
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
  assert.equal(Number.isFinite(view.scoreMax), true);
  assert.equal(Number.isFinite(view.scoreValue), true);
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
  assert.equal(view.copy, "3축 진동 이상 점수 · edge-local inference");
});


test("shows approved server1 routing and rollback evidence independently", () => {
  const remote = buildServiceDemoView({
    status: "normal",
    inference_routing: {
      state: "remote",
      effective_target: "server1",
      approval_id: "approval-001",
      consecutive_failures: 0,
    },
  });
  const rollback = buildServiceDemoView({
    status: "normal",
    inference_routing: {
      state: "rolled-back",
      effective_target: "edge-local",
      approval_id: "approval-001",
      consecutive_failures: 3,
      rollback_remaining_seconds: 840,
    },
  });

  assert.equal(remote.inferenceRouting, "승인 원격 추론 · server1 · approval-001");
  assert.equal(remote.inferenceRoutingTone, "remote");
  assert.equal(rollback.inferenceRouting, "로컬 rollback · edge-local · approval-001 · 연속 실패 3 · 복귀까지 840초");
  assert.equal(rollback.inferenceRoutingTone, "rollback");
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


test("builds an oldest-to-newest recent decision rail from persisted results", () => {
  const view = buildServiceDemoResultsView({
    mode: "live",
    results: [
      {score: 0.8, anomaly: false, observed_at: "2026-08-13T10:00:01Z"},
      {score: 5.2, anomaly: true, observed_at: "2026-08-13T10:00:02Z"},
    ],
  });
  assert.equal(view.summary, "최근 2건 · 이상 1건");
  assert.deepEqual(view.results.map((result) => result.anomaly), [false, true]);
  assert.deepEqual(view.results.map((result) => result.score), ["0.80", "5.20"]);
});


test("refreshes the recent decision rail from the result endpoint", async () => {
  let request = null;
  const elements = {
    serviceDemoHistorySummary: {textContent: ""},
    serviceDemoHistoryRail: null,
  };
  const documentRef = {
    getElementById: (id) => elements[id],
  };
  await refreshServiceDemoResults(async (url, options) => {
    request = {url, options};
    return {
      ok: true,
      json: async () => ({mode: "live", count: 0, results: []}),
    };
  }, documentRef);
  assert.deepEqual(request, {
    url: "/state/service-demo/results?limit=12",
    options: {cache: "no-store"},
  });
  assert.equal(elements.serviceDemoHistorySummary.textContent, "아직 저장된 판정 결과가 없습니다.");
});


test("builds a resource recommendation without mixing the equipment anomaly score", () => {
  const view = buildServiceAugmentationView({
    state: "RECOMMENDED",
    recommendation: "scale-up",
    apply_state: "observed-only",
    reason_codes: ["sustained_resource_and_service_pressure"],
    anomaly_signal_used: false,
    metrics: {
      cpu_percent: 91,
      memory_percent: 72,
      gpu_percent: 55,
      processing_latency_p95_ms: 740,
      backlog: 8,
      throughput_per_second: 0.8,
    },
    dwell: {
      resource_pressure_seconds: 300,
      resource_pressure_required_seconds: 300,
      service_pressure_seconds: 180,
      service_pressure_required_seconds: 180,
    },
    gates: [{id: "input", label: "센서 입력", passed: true, reason: "input_ready"}],
  });

  assert.equal(view.state, "RECOMMENDED");
  assert.equal(view.label, "증강 권고");
  assert.equal(view.metrics, "CPU 91.0% · Memory 72.0% · GPU 55.0% · p95 740 ms · backlog 8 · 0.80 fps");
  assert.equal(view.resourceDwell.value, 300);
  assert.equal(view.serviceDwell.value, 180);
  assert.equal(view.anomalyNote, "설비 anomaly 점수 미사용");
  assert.equal(view.gates[0].passed, true);
});


test("formats only observed augmentation snapshots for before and after comparison", () => {
  const view = buildServiceAugmentationView({
    state: "AUGMENTED",
    metrics: {processing_latency_p95_ms: 320, backlog: 0, throughput_per_second: 2.4},
    performance_comparison: {
      before: {processing_latency_p95_ms: 700, backlog: 8, throughput_per_second: 0.8},
      after: {processing_latency_p95_ms: 320, backlog: 0, throughput_per_second: 2.4},
    },
  });

  assert.equal(view.event.label, "자원 증강 실행");
  assert.equal(view.comparison.before, "p95 700 ms · backlog 8 · 0.80 fps");
  assert.equal(view.comparison.after, "p95 320 ms · backlog 0 · 2.40 fps");
  assert.equal(view.comparison.available, true);
});


test("renders blocked augmentation gates and polls the observed-only endpoint", async () => {
  const elements = {
    serviceAugmentationState: {textContent: "", dataset: {}},
    serviceAugmentationSummary: {textContent: ""},
    serviceAugmentationMetrics: {textContent: ""},
    serviceAugmentationResourceDwellLabel: {textContent: ""},
    serviceAugmentationServiceDwellLabel: {textContent: ""},
    serviceAugmentationResourceDwell: {value: 0, max: 0},
    serviceAugmentationServiceDwell: {value: 0, max: 0},
    serviceAugmentationGateList: null,
  };
  const documentRef = {getElementById: (id) => elements[id]};
  let request = null;
  await refreshServiceAugmentation(async (url, options) => {
    request = {url, options};
    return {
      ok: true,
      json: async () => ({
        state: "BLOCKED",
        reason_codes: ["sensor_stale"],
        metrics: {},
        dwell: {},
        gates: [],
        anomaly_signal_used: false,
      }),
    };
  }, documentRef);

  assert.deepEqual(request, {
    url: "/state/service-demo/augmentation",
    options: {cache: "no-store"},
  });
  assert.equal(elements.serviceAugmentationState.textContent, "차단");
  assert.equal(elements.serviceAugmentationState.dataset.state, "BLOCKED");
  assert.match(elements.serviceAugmentationSummary.textContent, /센서 입력이 오래됨/);
});


test("dashboard ships a responsive accessible live demo panel", () => {
  const root = path.resolve(__dirname, "..");
  const html = fs.readFileSync(path.join(root, "app/static/index.html"), "utf8");
  const css = fs.readFileSync(path.join(root, "app/static/service-demo.css"), "utf8");
  const javascript = fs.readFileSync(path.join(root, "app/static/service-demo.js"), "utf8");

  assert.match(html, /aria-labelledby="serviceDemoTitle"/);
  assert.match(html, /data-dashboard-page="services"/);
  assert.match(html, /data-page="services"/);
  assert.match(html, /id="serviceCatalogList"/);
  assert.match(html, /data-service-catalog="descriptor-driven"/);
  assert.doesNotMatch(html, /id="serviceCatalogRow"/);
  assert.doesNotMatch(html, /service-demo-panel[^>]+data-page="overview"/);
  for (const id of [
    "serviceDemoState", "serviceDemoFlow", "serviceDemoPhysicalSource",
    "serviceDemoDeviceService", "serviceDemoConsumer", "serviceDemoNode",
    "serviceDemoDevices", "serviceDemoValues", "serviceDemoMagnitude",
    "serviceDemoVibrationScore", "serviceDemoTemperatureScore", "serviceDemoScore",
    "serviceDemoTemperatureContext", "serviceDemoModel", "serviceDemoOrigin", "serviceDemoError",
    "serviceDemoInputAge",
    "serviceDemoAlertCount", "serviceDemoAlertLatest",
    "serviceDemoDecisionLabel", "serviceDemoDecisionSummary", "serviceDemoScoreMeter",
    "serviceDemoStepInput", "serviceDemoStepAlignment", "serviceDemoStepFeatures",
    "serviceDemoStepInference", "serviceDemoStepResult", "serviceDemoHistoryRail",
    "serviceDemoHistorySummary", "serviceDemoFrames",
    "serviceAugmentationState", "serviceAugmentationSummary",
    "serviceAugmentationEquipmentState", "serviceAugmentationMetrics",
    "serviceAugmentationResourceDwell", "serviceAugmentationServiceDwell",
    "serviceAugmentationResourceDwellLabel", "serviceAugmentationServiceDwellLabel",
    "serviceAugmentationGateList", "serviceAugmentationStateRail",
    "serviceOperationsDag", "serviceOperationsTimeline", "serviceOperationsTimelineList",
    "serviceDagAugmentationEvent", "serviceDeviceRatio", "serviceServerRatio",
    "serviceMetricCpu", "serviceMetricLatency", "serviceMetricBacklog",
    "serviceMetricThroughput", "servicePerformanceBefore", "servicePerformanceAfter",
  ]) {
    assert.match(html, new RegExp(`id="${id}"`));
  }
  assert.match(html, /service-demo\.css\?v=service-catalog-v1-20260813/);
  assert.match(html, /service-demo\.js\?v=service-catalog-v1-20260813/);
  assert.match(html, /aria-labelledby="serviceDemoTitle" open/);
  assert.match(css, /\[data-state="anomaly"\]/);
  assert.match(css, /grid-template-columns: repeat\(5, minmax\(0, 1fr\)\);/);
  assert.match(css, /@media \(max-width: 760px\)/);
  assert.match(css, /\.service-demo-alert-summary/);
  assert.match(css, /\.service-augmentation-dual-rail/);
  assert.match(css, /\.service-catalog-row/);
  assert.match(css, /\.service-operations-cockpit/);
  assert.match(css, /\.service-dag-node\[data-current="true"\]/);
  assert.match(css, /\.service-demo-route > div > span,/);
  assert.doesNotMatch(css, /\.service-demo-route span,/);
  assert.doesNotMatch(javascript, /\.innerHTML\s*=/);
});
