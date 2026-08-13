function serviceDemoText(value, fallback = "관측 불가") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}


function serviceDemoNumber(value, digits, suffix = "") {
  const number = Number(value);
  if (!Number.isFinite(number)) return "관측 불가";
  return `${number.toFixed(digits)}${suffix}`;
}


function serviceDemoAge(observedAt, nowMs) {
  const observedMs = Date.parse(observedAt);
  if (!Number.isFinite(observedMs) || !Number.isFinite(nowMs)) return "관측 불가";
  return `${(Math.max(0, nowMs - observedMs) / 1_000).toFixed(1)} s`;
}


function serviceDemoDecision(status) {
  return {
    normal: {label: "정상", summary: "현재 입력 window에서 이상 징후가 임계값보다 낮습니다."},
    anomaly: {label: "이상 감지", summary: "이상 상태를 유지하며 정상 복귀 조건을 평가하고 있습니다."},
    warming_up: {label: "기준선 학습 중", summary: "판정에 필요한 초기 sample을 수집하고 있습니다."},
    starting: {label: "입력 대기", summary: "첫 번째 정렬 입력 window를 기다리고 있습니다."},
    degraded: {label: "확인 필요", summary: "입력 또는 모델 관측이 불완전해 판정을 확정할 수 없습니다."},
  }[status] || {label: "확인 필요", summary: "서비스 상태를 확인할 수 없습니다."};
}


function serviceDemoPipeline(data, latest, model) {
  const inputState = data.input_state || "unknown";
  const counters = data.counters || {};
  const vibration = latest?.vibration_features || null;
  const temperature = latest?.temperature_features || null;
  const inputStateTone = inputState === "fresh" ? "ready"
    : ["stale", "error"].includes(inputState) ? "warn"
      : inputState === "waiting" ? "active" : "pending";
  const aligned = Boolean(latest && temperature);
  const featuresReady = Boolean(vibration && temperature);
  const modelReady = data.model_state === "ready";
  const inferenceTarget = latest?.inference_target === "server1" ? "server1" : "edge-local";
  const frames = Number(counters.frames_processed);
  return [
    {
      id: "Input",
      state: inputStateTone,
      evidence: inputState === "fresh" ? "X/Y/Z·온도 fresh" : `입력 ${serviceDemoText(inputState, "미확인")}`,
    },
    {
      id: "Alignment",
      state: aligned ? "ready" : latest ? "warn" : "pending",
      evidence: aligned ? `정렬 ${serviceDemoNumber(temperature.alignment_lag_ms, 1, " ms")}` : "온도 context 대기",
    },
    {
      id: "Features",
      state: featuresReady ? "ready" : latest ? "active" : "pending",
      evidence: featuresReady
        ? `RMS ${serviceDemoNumber(vibration.rms, 2)} · peak ${serviceDemoNumber(vibration.peak, 2)}`
        : "feature window 대기",
    },
    {
      id: "Inference",
      state: modelReady && latest ? latest.anomaly ? "anomaly" : "ready" : data.model_state === "warming_up" ? "active" : "pending",
      evidence: modelReady && latest
        ? `${latest.anomaly ? "이상" : "정상"} · ${serviceDemoText(latest.model_version || model?.version)} · ${inferenceTarget}`
        : `모델 ${serviceDemoText(data.model_state, "미확인")}`,
    },
    {
      id: "Result",
      state: latest ? latest.anomaly ? "anomaly" : "ready" : "pending",
      evidence: latest && Number.isFinite(frames) ? `${frames} frames 처리` : "저장 결과 대기",
    },
  ];
}


function buildServiceDemoView(data = {}, nowMs = Date.now()) {
  const binding = data.binding || {};
  const latest = data.latest || null;
  const model = data.model || null;
  const componentScores = latest?.component_scores || null;
  const temperatureFeatures = latest?.temperature_features || null;
  const allowedTones = new Set(["starting", "warming_up", "normal", "anomaly", "degraded"]);
  const status = allowedTones.has(data.status) ? data.status : "degraded";
  const physicalSource = serviceDemoText(binding.physical_source);
  const deviceService = serviceDemoText(binding.device_service);
  const consumer = serviceDemoText(binding.consumer, "sensor-anomaly-demo");
  const node = serviceDemoText(binding.node, "etri-dev0001-jetorn");
  const hasFlow = binding.physical_source && binding.device_service && binding.consumer;
  const values = latest?.values;
  const sampleCount = Number(model?.sample_count);
  const score = Number(latest?.score);
  const threshold = Number(model?.threshold);
  const scoreValue = Number.isFinite(score) ? score : 0;
  const decision = serviceDemoDecision(status);
  const routing = data.inference_routing || {};
  const inferenceTarget = routing.effective_target === "server1" ? "server1" : "edge-local";
  const routingState = routing.state === "remote" ? "승인 원격 추론"
    : routing.state === "rolled-back" ? "로컬 rollback"
      : "로컬 추론";
  const approval = serviceDemoText(routing.approval_id, "승인 없음");
  const failures = Number(routing.consecutive_failures);
  const rollback = Number(routing.rollback_remaining_seconds);

  return {
    badge: status.toUpperCase(),
    tone: status,
    inputState: serviceDemoText(data.input_state, "unknown"),
    physicalSource,
    deviceService,
    consumer,
    node,
    devices: Array.isArray(binding.devices) && binding.devices.length
      ? binding.devices.join(" · ")
      : "관측 불가",
    flow: hasFlow
      ? `${physicalSource} → ${deviceService} → ${consumer}`
      : "source binding 관측 불가",
    values: values
      ? `X ${serviceDemoText(values.x)} · Y ${serviceDemoText(values.y)} · Z ${serviceDemoText(values.z)}`
      : "관측 불가",
    magnitude: latest ? serviceDemoNumber(latest.magnitude, 3, " raw") : "관측 불가",
    vibrationScore: latest
      ? serviceDemoNumber(componentScores?.vibration ?? latest.score, 2)
      : "관측 불가",
    temperatureScore: componentScores
      ? serviceDemoNumber(componentScores.temperature, 2)
      : "관측 불가",
    score: latest && model
      ? `${serviceDemoNumber(latest.score, 2)} / ${serviceDemoNumber(model.threshold, 2)}`
      : "관측 불가",
    temperatureContext: temperatureFeatures
      ? `raw ${serviceDemoText(temperatureFeatures.raw)} · 정렬 ${serviceDemoNumber(temperatureFeatures.alignment_lag_ms, 1, " ms")}`
      : "관측 불가",
    model: model
      ? `${serviceDemoText(model.algorithm)} · ${Number.isFinite(sampleCount) ? sampleCount : "관측 불가"} samples · ${serviceDemoText(data.model_state, "unknown")}`
      : "model 관측 불가",
    origin: latest ? serviceDemoText(latest.origin) : "관측 불가",
    inputAge: latest ? serviceDemoAge(latest.observed_at, nowMs) : "관측 불가",
    frames: serviceDemoText(data.counters?.frames_processed),
    inferenceRouting: `${routingState} · ${inferenceTarget} · ${approval}${Number.isFinite(failures) && failures > 0 ? ` · 연속 실패 ${failures}` : ""}${Number.isFinite(rollback) && rollback > 0 ? ` · 복귀까지 ${rollback}초` : ""}`,
    inferenceRoutingTone: routing.state === "remote" ? "remote"
      : routing.state === "rolled-back" ? "rollback" : "local",
    decisionLabel: decision.label,
    decisionSummary: decision.summary,
    scoreValue,
    scoreMax: Number.isFinite(threshold) && threshold > 0
      ? Math.max(threshold * 1.5, scoreValue)
      : Math.max(scoreValue, 1),
    pipeline: serviceDemoPipeline(data, latest, model),
    copy: componentScores && temperatureFeatures
      ? `진동·온도 복합 이상 점수 · ${inferenceTarget} inference`
      : `3축 진동 이상 점수 · ${inferenceTarget} inference`,
    error: serviceDemoText(data.observation_error || data.last_error, ""),
  };
}


function renderServiceDemo(data, documentRef = document) {
  const view = buildServiceDemoView(data);
  const text = (id, value) => {
    const element = documentRef.getElementById(id);
    if (element) element.textContent = value;
    return element;
  };

  const badge = text("serviceDemoState", view.badge);
  if (badge) badge.dataset.state = view.tone;
  const decisionCard = text("serviceDemoDecisionLabel", view.decisionLabel)?.parentElement;
  if (decisionCard) decisionCard.dataset.state = view.tone;
  text("serviceDemoDecisionSummary", view.decisionSummary);
  text("serviceAugmentationEquipmentState", view.decisionLabel);
  text("serviceDemoInputState", view.inputState);
  text("serviceDemoFlow", view.flow);
  text("serviceDemoPhysicalSource", view.physicalSource);
  text("serviceDemoDeviceService", view.deviceService);
  text("serviceDemoConsumer", view.consumer);
  text("serviceDemoNode", view.node);
  text("serviceDemoDevices", view.devices);
  text("serviceDemoValues", view.values);
  text("serviceDemoMagnitude", view.magnitude);
  text("serviceDemoVibrationScore", view.vibrationScore);
  text("serviceDemoTemperatureScore", view.temperatureScore);
  text("serviceDemoScore", view.score);
  text("serviceDemoTemperatureContext", view.temperatureContext);
  text("serviceDemoModel", `${view.model} · ${view.copy}`);
  text("serviceDemoOrigin", view.origin);
  text("serviceDemoInputAge", view.inputAge);
  text("serviceDemoFrames", view.frames);
  const routing = text("serviceDemoInferenceRouting", view.inferenceRouting);
  if (routing) routing.dataset.state = view.inferenceRoutingTone;
  const scoreMeter = documentRef.getElementById("serviceDemoScoreMeter");
  if (scoreMeter) {
    scoreMeter.max = view.scoreMax;
    scoreMeter.value = view.scoreValue;
  }
  view.pipeline.forEach((step) => {
    const stage = documentRef.getElementById(`serviceDemoStep${step.id}`);
    if (stage) stage.dataset.state = step.state;
    text(`serviceDemoStep${step.id}Evidence`, step.evidence);
  });
  const error = text("serviceDemoError", view.error);
  if (error) error.hidden = !view.error;
}


function serviceAugmentationReason(reason) {
  return {
    sensor_disconnected: "센서 연결이 확인되지 않아 증강 판단을 차단했습니다.",
    sensor_stale: "센서 입력이 오래됨 상태라 증강 판단을 차단했습니다.",
    required_input_missing: "필수 X/Y/Z/온도 입력이 부족합니다.",
    input_schema_invalid: "입력 schema 계약이 일치하지 않습니다.",
    model_not_ready: "현재 모델이 준비되지 않았습니다.",
    metrics_invalid_or_stale: "자원 또는 서비스 메트릭이 부족하거나 오래되었습니다.",
    server1_pod_not_ready: "server1 inference Pod가 준비되지 않았습니다.",
    server1_endpoint_not_ready: "server1 inference endpoint가 준비되지 않았습니다.",
    server1_model_not_ready: "server1 모델이 준비되지 않았습니다.",
    server1_resource_insufficient: "server1의 사용 가능한 자원이 부족합니다.",
    sustained_resource_and_service_pressure: "자원 압박 5분과 서비스 압박 3분이 함께 지속되었습니다.",
    resource_pressure_observing: "자원 압박 지속시간을 관찰하고 있습니다.",
    service_pressure_observing: "서비스 성능 저하 지속시간을 관찰하고 있습니다.",
    within_operating_envelope: "현재 자원과 서비스 성능이 정상 범위입니다.",
    augmentation_active: "승인된 증강 상태의 축소 조건을 관찰하고 있습니다.",
    scale_down_recommended: "저부하 조건이 15분 지속되어 축소를 권고합니다.",
    cooldown_active: "마지막 변경 이후 cooldown을 적용하고 있습니다.",
  }[reason] || serviceDemoText(reason, "판단 근거 관측 대기");
}


function buildServiceAugmentationView(data = {}) {
  const labels = {
    NORMAL: "정상",
    OBSERVING: "관찰 중",
    RECOMMENDED: "증강 권고",
    AUGMENTED: "증강됨",
    COOLDOWN: "쿨다운",
    BLOCKED: "차단",
  };
  const allowed = new Set(Object.keys(labels));
  const state = allowed.has(data.state) ? data.state : "BLOCKED";
  const reasons = Array.isArray(data.reason_codes) ? data.reason_codes : [];
  const reasonTexts = reasons.map(serviceAugmentationReason);
  const metrics = data.metrics || {};
  const dwell = data.dwell || {};
  const number = (value, digits = 0) => Number.isFinite(Number(value))
    ? Number(value).toFixed(digits) : "관측 불가";
  const dwellView = (value, required) => {
    const maximum = Number.isFinite(Number(required)) && Number(required) > 0 ? Number(required) : 1;
    const current = Number.isFinite(Number(value)) ? Math.max(0, Number(value)) : 0;
    return {value: Math.min(current, maximum), max: maximum, label: `${Math.round(current)} / ${Math.round(maximum)}초`};
  };
  return {
    state,
    label: labels[state],
    summary: reasonTexts.length > 1
      ? `${reasonTexts[0]} 외 ${reasonTexts.length - 1}개 gate 차단`
      : reasonTexts[0] || "판단 근거 관측 대기",
    metrics: `CPU ${number(metrics.cpu_percent, 1)}% · Memory ${number(metrics.memory_percent, 1)}% · ${Number.isFinite(Number(metrics.gpu_percent)) ? `GPU ${number(metrics.gpu_percent, 1)}%` : "GPU 미관측"} · p95 ${number(metrics.processing_latency_p95_ms)} ms · backlog ${number(metrics.backlog)} · ${number(metrics.throughput_per_second, 2)} fps`,
    resourceDwell: dwellView(dwell.resource_pressure_seconds, dwell.resource_pressure_required_seconds),
    serviceDwell: dwellView(dwell.service_pressure_seconds, dwell.service_pressure_required_seconds),
    gates: (Array.isArray(data.gates) ? data.gates : []).map((gate) => ({
      id: serviceDemoText(gate?.id, "gate"),
      label: serviceDemoText(gate?.label, "확인 항목"),
      passed: Boolean(gate?.passed),
      reason: serviceAugmentationReason(gate?.reason),
    })),
    anomalyNote: data.anomaly_signal_used === false ? "설비 anomaly 점수 미사용" : "판단 계약 확인 필요",
  };
}


function renderServiceAugmentation(data, documentRef = document) {
  const view = buildServiceAugmentationView(data);
  const text = (id, value) => {
    const element = documentRef.getElementById(id);
    if (element) element.textContent = value;
    return element;
  };
  const state = text("serviceAugmentationState", view.label);
  if (state) state.dataset.state = view.state;
  text("serviceAugmentationSummary", `${view.summary} · ${view.anomalyNote}`);
  text("serviceAugmentationMetrics", view.metrics);
  const updateDwell = (id, labelId, dwell) => {
    const progress = documentRef.getElementById(id);
    if (progress) {
      progress.max = dwell.max;
      progress.value = dwell.value;
    }
    text(labelId, dwell.label);
  };
  updateDwell("serviceAugmentationResourceDwell", "serviceAugmentationResourceDwellLabel", view.resourceDwell);
  updateDwell("serviceAugmentationServiceDwell", "serviceAugmentationServiceDwellLabel", view.serviceDwell);

  const gates = documentRef.getElementById("serviceAugmentationGateList");
  if (gates && typeof documentRef.createElement === "function") {
    const nodes = view.gates.map((gate) => {
      const item = documentRef.createElement("li");
      item.dataset.state = gate.passed ? "pass" : "blocked";
      const marker = documentRef.createElement("span");
      marker.textContent = gate.passed ? "통과" : "차단";
      const label = documentRef.createElement("strong");
      label.textContent = gate.label;
      const reason = documentRef.createElement("small");
      reason.textContent = gate.reason;
      item.append(marker, label, reason);
      return item;
    });
    gates.replaceChildren(...nodes);
  }
  const rail = documentRef.getElementById("serviceAugmentationStateRail");
  if (rail && typeof rail.querySelectorAll === "function") {
    rail.querySelectorAll("[data-augmentation-state]").forEach((item) => {
      item.dataset.active = String(item.dataset.augmentationState === view.state);
    });
  }
}


function buildServiceDemoResultsView(data = {}) {
  const results = (Array.isArray(data.results) ? data.results : []).slice(-12);
  const anomalyCount = results.filter((item) => item?.anomaly).length;
  return {
    count: results.length,
    summary: data.observation_error
      ? "최근 결과를 불러오지 못했습니다."
      : results.length
        ? `최근 ${results.length}건 · 이상 ${anomalyCount}건`
        : data.mode === "live" ? "아직 저장된 판정 결과가 없습니다." : "결과 관측 대기",
    results: results.map((item) => ({
      anomaly: Boolean(item?.anomaly),
      score: serviceDemoNumber(item?.score, 2),
      observedAt: serviceDemoText(item?.observed_at, "시각 미확인"),
    })),
  };
}


function renderServiceDemoResults(data, documentRef = document) {
  const view = buildServiceDemoResultsView(data);
  const summary = documentRef.getElementById("serviceDemoHistorySummary");
  const rail = documentRef.getElementById("serviceDemoHistoryRail");
  if (summary) summary.textContent = view.summary;
  if (!rail || typeof documentRef.createElement !== "function") return;
  const nodes = view.results.map((result, index) => {
    const item = documentRef.createElement("li");
    item.dataset.state = result.anomaly ? "anomaly" : "normal";
    const marker = documentRef.createElement("span");
    marker.setAttribute("aria-hidden", "true");
    const label = documentRef.createElement("strong");
    label.textContent = result.anomaly ? "이상" : "정상";
    const score = documentRef.createElement("small");
    score.textContent = `점수 ${result.score}`;
    item.setAttribute("aria-label", `${index + 1}번째 최근 판정 ${label.textContent}, ${score.textContent}`);
    item.title = result.observedAt;
    item.append(marker, label, score);
    return item;
  });
  rail.replaceChildren(...nodes);
}


function buildServiceDemoAlertView(data = {}) {
  const alerts = Array.isArray(data.alerts) ? data.alerts : [];
  const latest = alerts[0] || null;
  const count = Number(data.count);
  const observedAt = latest?.observed_at ? Date.parse(latest.observed_at) : NaN;
  const transition = latest?.transition === "opened" ? "이상 발생"
    : latest?.transition === "cleared" ? "정상 복귀" : "관측 대기";
  return {
    count: Number.isFinite(count) ? `${count}건` : "관측 불가",
    latest: latest
      ? `${transition} · 점수 ${serviceDemoNumber(latest.score, 2)}${Number.isFinite(observedAt) ? ` · ${new Date(observedAt).toLocaleString("ko-KR")}` : ""}`
      : data.mode === "live" ? "알림 없음" : "관측 불가",
    error: serviceDemoText(data.observation_error, ""),
  };
}


function renderServiceDemoAlerts(data, documentRef = document) {
  const view = buildServiceDemoAlertView(data);
  const count = documentRef.getElementById("serviceDemoAlertCount");
  const latest = documentRef.getElementById("serviceDemoAlertLatest");
  if (count) count.textContent = view.count;
  if (latest) latest.textContent = view.error || view.latest;
}


async function refreshServiceDemo(fetchFn = fetch, documentRef = document) {
  try {
    const response = await fetchFn("/state/service-demo", {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderServiceDemo(await response.json(), documentRef);
  } catch (error) {
    renderServiceDemo({
      mode: "unavailable",
      status: "degraded",
      input_state: "error",
      model_state: "unavailable",
      binding: {
        consumer: "sensor-anomaly-demo",
        node: "etri-dev0001-jetorn",
        devices: [],
      },
      latest: null,
      model: null,
      observation_error: `dashboard fetch failed: ${error?.name || "Error"}`,
    }, documentRef);
  }
}


async function refreshServiceDemoAlerts(fetchFn = fetch, documentRef = document) {
  try {
    const response = await fetchFn("/state/service-demo/alerts?limit=10", {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderServiceDemoAlerts(await response.json(), documentRef);
  } catch (error) {
    renderServiceDemoAlerts({
      mode: "unavailable",
      count: 0,
      alerts: [],
      observation_error: `alert fetch failed: ${error?.name || "Error"}`,
    }, documentRef);
  }
}


async function refreshServiceDemoResults(fetchFn = fetch, documentRef = document) {
  try {
    const response = await fetchFn("/state/service-demo/results?limit=12", {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderServiceDemoResults(await response.json(), documentRef);
  } catch (error) {
    renderServiceDemoResults({
      mode: "unavailable",
      results: [],
      observation_error: `result fetch failed: ${error?.name || "Error"}`,
    }, documentRef);
  }
}


async function refreshServiceAugmentation(fetchFn = fetch, documentRef = document) {
  try {
    const response = await fetchFn("/state/service-demo/augmentation", {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderServiceAugmentation(await response.json(), documentRef);
  } catch (error) {
    renderServiceAugmentation({
      state: "BLOCKED",
      reason_codes: [`evaluator unavailable: ${error?.name || "Error"}`],
      metrics: {},
      dwell: {},
      gates: [],
      anomaly_signal_used: false,
    }, documentRef);
  }
}


if (typeof module !== "undefined") {
  module.exports = {
    buildServiceAugmentationView,
    buildServiceDemoAlertView,
    buildServiceDemoResultsView,
    buildServiceDemoView,
    refreshServiceDemo,
    refreshServiceDemoAlerts,
    refreshServiceDemoResults,
    refreshServiceAugmentation,
    renderServiceDemo,
    renderServiceDemoAlerts,
    renderServiceDemoResults,
    renderServiceAugmentation,
  };
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  window.addEventListener("DOMContentLoaded", () => {
    refreshServiceDemo();
    refreshServiceDemoAlerts();
    refreshServiceDemoResults();
    refreshServiceAugmentation();
    window.setInterval(refreshServiceDemo, 5_000);
    window.setInterval(refreshServiceDemoAlerts, 5_000);
    window.setInterval(refreshServiceDemoResults, 5_000);
    window.setInterval(refreshServiceAugmentation, 5_000);
  });
}
