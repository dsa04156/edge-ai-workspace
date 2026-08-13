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


function buildServiceRoutingView(data = {}) {
  const results = (Array.isArray(data.results) ? data.results : []).filter((item) => (
    item?.inference_target === "edge-local" || item?.inference_target === "server1"
  ));
  const deviceCount = results.filter((item) => item.inference_target === "edge-local").length;
  const serverCount = results.filter((item) => item.inference_target === "server1").length;
  const total = deviceCount + serverCount;
  return {
    deviceCount,
    serverCount,
    deviceRatio: total ? Math.round((deviceCount / total) * 100) : null,
    serverRatio: total ? 100 - Math.round((deviceCount / total) * 100) : null,
    summary: total ? `최근 ${total}건 기준` : "처리 표본 대기",
  };
}


function buildServiceOperationsTimelineView(augmentation = {}, alertData = {}) {
  const transitions = (Array.isArray(augmentation.transitions) ? augmentation.transitions : []).map((item) => {
    const title = item?.to_state === "AUGMENTED" ? "자원 증강 실행"
      : item?.to_state === "RECOMMENDED" ? "자원 증강 권고"
        : item?.to_state === "BLOCKED" ? "자원 증강 차단"
          : item?.to_state === "OBSERVING" ? "자원 압박 관찰"
            : item?.to_state === "COOLDOWN" ? "증강 쿨다운"
              : "자원 상태 정상";
    return {
      kind: "augmentation",
      tone: item?.to_state === "AUGMENTED" ? "executed"
        : item?.to_state === "BLOCKED" ? "blocked"
          : item?.to_state === "RECOMMENDED" ? "recommended" : "observing",
      title,
      detail: `${serviceDemoText(item?.from_state, "-")} → ${serviceDemoText(item?.to_state, "-")} · ${serviceAugmentationReason(item?.reason)}`,
      occurredAt: serviceDemoText(item?.occurred_at, ""),
    };
  });
  const alerts = (Array.isArray(alertData.alerts) ? alertData.alerts : []).map((item) => ({
    kind: "equipment",
    tone: item?.transition === "opened" ? "blocked" : "normal",
    title: item?.transition === "opened" ? "설비 이상 발생" : "설비 정상 복귀",
    detail: `anomaly score ${serviceDemoNumber(item?.score, 2)} · 자원 증강 판단과 독립`,
    occurredAt: serviceDemoText(item?.observed_at, ""),
  }));
  const events = [...transitions, ...alerts]
    .sort((left, right) => (Date.parse(right.occurredAt) || 0) - (Date.parse(left.occurredAt) || 0))
    .slice(0, 10);
  return {events};
}


const serviceOperationsObservations = {augmentation: {}, alerts: {}};
const serviceInventoryById = new Map();
const serviceOperationsEndpoints = {
  state: "/state/service-demo",
  results: "/state/service-demo/results?limit=12",
  alerts: "/state/service-demo/alerts?limit=10",
  augmentation: "/state/service-demo/augmentation",
};


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


function buildServiceCatalogView(data = {}) {
  const binding = data.binding || {};
  const latest = data.latest || {};
  const model = data.model || {};
  const running = data.mode !== "unavailable"
    && data.input_state === "fresh"
    && data.model_state === "ready";
  const routing = latest.inference_target
    || data.inference_routing?.effective_target
    || "edge-local";
  return {
    name: serviceDemoText(binding.consumer, "sensor-anomaly-demo"),
    operatingState: running ? "running" : "attention",
    operatingLabel: running ? "실행 중" : "확인 필요",
    availability: running ? "1/1 실행 중" : "0/1 확인 필요",
    input: serviceDemoText(data.input_state, "미확인"),
    node: serviceDemoText(binding.node, "etri-dev0001-jetorn"),
    model: serviceDemoText(latest.model_version || model.version, data.model_state || "미확인"),
    decision: serviceDemoDecision(data.status).label,
    routing: routing === "server1" ? "server1" : "edge-local",
  };
}


function buildServiceInventoryView(data = {}) {
  const services = Array.isArray(data.services) ? data.services : [];
  const rows = services.map((service, index) => {
    const running = service.mode !== "unavailable"
      && service.input_state === "fresh"
      && service.model_state === "ready";
    return {
      index: String(index + 1).padStart(2, "0"),
      serviceId: serviceDemoText(service.service_id, "unknown-service"),
      displayName: serviceDemoText(service.display_name, "이름 미등록"),
      description: serviceDemoText(service.description, "설명 미등록"),
      input: serviceDemoText(service.input_state, "미확인"),
      node: serviceDemoText(service.node, "미확인"),
      model: serviceDemoText(service.model_version, service.model_state || "미확인"),
      routing: service.inference_target === "server1" ? "server1" : "edge-local",
      decision: serviceDemoDecision(service.status).label,
      operatingState: running ? "running" : "attention",
      operatingLabel: running ? "실행 중" : "확인 필요",
      descriptor: service.descriptor || null,
      definitionSource: serviceDemoText(service.definition_source, "미등록"),
      catalogVersion: serviceDemoText(service.catalog_version, "미등록"),
      adapter: service.descriptor?.observability?.adapter || "unsupported",
      raw: service,
    };
  });
  const runningCount = rows.filter((row) => row.operatingState === "running").length;
  return {
    rows,
    countLabel: `${rows.length}개 서비스`,
    availability: `${runningCount}/${rows.length} 실행 중`,
    availabilityState: rows.length > 0 && runningCount === rows.length ? "running" : "attention",
    definitionSource: rows[0]
      ? `${rows[0].definitionSource} · ${rows[0].catalogVersion}`
      : "등록된 서비스 없음",
  };
}


function appendCatalogFact(documentRef, button, label, values, ids = []) {
  const wrapper = documentRef.createElement("span");
  wrapper.className = "service-catalog-fact";
  const caption = documentRef.createElement("small");
  caption.textContent = label;
  const value = documentRef.createElement("strong");
  values.forEach((item, index) => {
    if (index > 0) value.append(documentRef.createTextNode(" · "));
    const part = documentRef.createElement("span");
    if (ids[index]) part.id = ids[index];
    part.textContent = item;
    value.append(part);
  });
  wrapper.append(caption, value);
  button.append(wrapper);
}


function applyServiceDescriptor(service, documentRef = document) {
  const descriptor = service?.descriptor || {};
  const graph = descriptor.graph || {};
  const text = (id, value) => {
    const element = documentRef.getElementById(id);
    if (element && value) element.textContent = value;
  };
  text("serviceDemoTitle", service?.display_name);
  text("serviceOperationsServiceId", service?.service_id);
  text("serviceOperationsDagTitle", graph.title);
  (Array.isArray(graph.stages) ? graph.stages : []).forEach((stage) => {
    text(`serviceDemoStep${stage.slot}Label`, stage.label);
  });
  (Array.isArray(graph.targets) ? graph.targets : []).forEach((target) => {
    text(`serviceDag${target.slot}Label`, target.label);
    text(`serviceDag${target.slot}Description`, target.description);
  });
  const observability = descriptor.observability || {};
  if (observability.adapter === "sensor-anomaly-v1") {
    serviceOperationsEndpoints.state = observability.state_path || serviceOperationsEndpoints.state;
    serviceOperationsEndpoints.results = observability.results_path || serviceOperationsEndpoints.results;
    serviceOperationsEndpoints.alerts = observability.alerts_path || serviceOperationsEndpoints.alerts;
    serviceOperationsEndpoints.augmentation = observability.augmentation_path || serviceOperationsEndpoints.augmentation;
  }
}


function renderServiceInventory(data, documentRef = document) {
  const view = buildServiceInventoryView(data);
  const list = documentRef.getElementById("serviceCatalogList");
  if (!list || typeof documentRef.createElement !== "function") return view;
  serviceInventoryById.clear();
  const nodes = view.rows.map((row, index) => {
    serviceInventoryById.set(row.serviceId, row.raw);
    const item = documentRef.createElement("li");
    const button = documentRef.createElement("button");
    button.className = "service-catalog-row";
    button.type = "button";
    button.dataset.serviceId = row.serviceId;
    if (row.adapter === "sensor-anomaly-v1") {
      button.dataset.serviceDetailTarget = "serviceDemoPanel";
      button.setAttribute("aria-controls", "serviceDemoPanel");
      button.setAttribute("aria-expanded", String(index === 0));
    }
    const identity = documentRef.createElement("span");
    identity.className = "service-catalog-identity";
    const sequence = documentRef.createElement("span");
    sequence.className = "service-catalog-index";
    sequence.setAttribute("aria-hidden", "true");
    sequence.textContent = row.index;
    const identityBody = documentRef.createElement("span");
    const name = documentRef.createElement("strong");
    if (index === 0) name.id = "serviceCatalogName";
    name.textContent = row.serviceId;
    const description = documentRef.createElement("small");
    description.textContent = row.displayName;
    identityBody.append(name, description);
    identity.append(sequence, identityBody);
    button.append(identity);
    appendCatalogFact(documentRef, button, "입력", [row.input], index === 0 ? ["serviceCatalogInput"] : []);
    appendCatalogFact(documentRef, button, "실행 위치", [row.node], index === 0 ? ["serviceCatalogNode"] : []);
    appendCatalogFact(documentRef, button, "모델 · 추론", [row.model, row.routing], index === 0 ? ["serviceCatalogModel", "serviceCatalogRouting"] : []);
    appendCatalogFact(documentRef, button, "설비 판정 · 자원 증강", [row.decision, "관측 대기"], index === 0 ? ["serviceCatalogDecision", "serviceCatalogAugmentation"] : []);
    const status = documentRef.createElement("span");
    if (index === 0) status.id = "serviceCatalogStatus";
    status.className = "service-catalog-status";
    status.dataset.state = row.operatingState;
    status.textContent = row.operatingLabel;
    const open = documentRef.createElement("span");
    open.className = "service-catalog-open";
    open.textContent = row.adapter === "sensor-anomaly-v1" ? "상세 보기 →" : "목록 관측";
    button.append(status, open);
    item.append(button);
    return item;
  });
  if (nodes.length) {
    list.replaceChildren(...nodes);
    applyServiceDescriptor(view.rows[0].raw, documentRef);
  } else {
    const empty = documentRef.createElement("li");
    empty.className = "service-catalog-loading";
    empty.textContent = "등록된 서비스가 없습니다.";
    list.replaceChildren(empty);
  }
  const count = documentRef.getElementById("serviceCatalogCount");
  if (count) count.textContent = view.countLabel;
  const source = documentRef.getElementById("serviceCatalogDefinitionSource");
  if (source) source.textContent = view.definitionSource;
  const availability = documentRef.getElementById("serviceCatalogAvailability");
  if (availability) {
    availability.textContent = view.availability;
    availability.dataset.state = view.availabilityState;
  }
  return view;
}


function renderServiceCatalog(data, documentRef = document) {
  const view = buildServiceCatalogView(data);
  const text = (id, value) => {
    const element = documentRef.getElementById(id);
    if (element) element.textContent = value;
    return element;
  };
  text("serviceCatalogName", view.name);
  text("serviceCatalogInput", view.input);
  text("serviceCatalogNode", view.node);
  text("serviceCatalogModel", view.model);
  text("serviceCatalogDecision", view.decision);
  text("serviceCatalogRouting", view.routing);
  const status = text("serviceCatalogStatus", view.operatingLabel);
  if (status) status.dataset.state = view.operatingState;
  const availability = text("serviceCatalogAvailability", view.availability);
  if (availability) availability.dataset.state = view.operatingState;
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
  text("serviceDagFreshness", view.inputAge);
  text("serviceOperationsRunState", view.inputState === "fresh" ? "STREAMING" : "ATTENTION");
  text("serviceDemoFrames", view.frames);
  const routing = text("serviceDemoInferenceRouting", view.inferenceRouting);
  if (routing) routing.dataset.state = view.inferenceRoutingTone;
  const scoreMeter = documentRef.getElementById("serviceDemoScoreMeter");
  if (scoreMeter) {
    scoreMeter.max = view.scoreMax;
    scoreMeter.value = view.scoreValue;
  }
  const currentStep = view.inputState === "fresh" ? "Inference"
    : view.pipeline.find((step) => ["active", "warn"].includes(step.state))?.id || "Input";
  view.pipeline.forEach((step) => {
    const stage = documentRef.getElementById(`serviceDemoStep${step.id}`);
    if (stage) {
      stage.dataset.state = step.state;
      stage.dataset.current = String(step.id === currentStep);
    }
    text(`serviceDemoStep${step.id}Evidence`, step.evidence);
  });
  const error = text("serviceDemoError", view.error);
  if (error) error.hidden = !view.error;
  renderServiceCatalog(data, documentRef);
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
    approved_augmentation_observed: "승인된 server1 증강 전환을 관측했습니다.",
    pressure_dwell_in_progress: "자원·서비스 압력 지속시간을 관찰하고 있습니다.",
    pressure_cleared: "자원·서비스 압력이 정상 범위로 복귀했습니다.",
    cooldown_complete: "증강 cooldown이 완료되었습니다.",
    scale_down_envelope_sustained: "저부하 축소 조건이 15분 지속되었습니다.",
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
  const comparison = data.performance_comparison || {};
  const comparisonText = (snapshot, fallback) => snapshot
    ? `p95 ${number(snapshot.processing_latency_p95_ms)} ms · backlog ${number(snapshot.backlog)} · ${number(snapshot.throughput_per_second, 2)} fps`
    : fallback;
  const event = state === "AUGMENTED"
    ? {hidden: false, tone: "executed", eyebrow: "APPROVED EVENT", label: "자원 증강 실행"}
    : state === "RECOMMENDED"
      ? {hidden: false, tone: "recommended", eyebrow: "OBSERVED ONLY", label: "자원 증강 권고"}
      : state === "OBSERVING"
        ? {hidden: false, tone: "observing", eyebrow: "DWELL GATE", label: "자원 압박 관찰 중"}
        : state === "BLOCKED"
          ? {hidden: false, tone: "blocked", eyebrow: "GATE BLOCKED", label: "자원 증강 차단"}
          : {hidden: true, tone: "normal", eyebrow: "NORMAL", label: "자원 증강 이벤트 없음"};
  return {
    state,
    label: labels[state],
    summary: reasonTexts.length > 1
      ? `${reasonTexts[0]} 외 ${reasonTexts.length - 1}개 gate 차단`
      : reasonTexts[0] || "판단 근거 관측 대기",
    metrics: `CPU ${number(metrics.cpu_percent, 1)}% · Memory ${number(metrics.memory_percent, 1)}% · ${Number.isFinite(Number(metrics.gpu_percent)) ? `GPU ${number(metrics.gpu_percent, 1)}%` : "GPU 미관측"} · p95 ${number(metrics.processing_latency_p95_ms)} ms · backlog ${number(metrics.backlog)} · ${number(metrics.throughput_per_second, 2)} fps`,
    metricValues: {
      cpu: Number.isFinite(Number(metrics.cpu_percent)) ? `${number(metrics.cpu_percent, 1)}%` : "—",
      latency: Number.isFinite(Number(metrics.processing_latency_p95_ms)) ? `${number(metrics.processing_latency_p95_ms)} ms` : "—",
      backlog: Number.isFinite(Number(metrics.backlog)) ? number(metrics.backlog) : "—",
      throughput: Number.isFinite(Number(metrics.throughput_per_second)) ? `${number(metrics.throughput_per_second, 2)} fps` : "—",
    },
    comparison: {
      before: comparisonText(comparison.before, "전환 전 스냅샷 대기"),
      after: comparisonText(comparison.after, state === "AUGMENTED" ? comparisonText(metrics, "관측 대기") : "증강 실행 후 수집"),
      available: Boolean(comparison.before && comparison.after),
    },
    event,
    transitions: Array.isArray(data.transitions) ? data.transitions : [],
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
  const catalogState = text("serviceCatalogAugmentation", view.label);
  if (catalogState) catalogState.dataset.state = view.state;
  text("serviceAugmentationSummary", `${view.summary} · ${view.anomalyNote}`);
  text("serviceAugmentationMetrics", view.metrics);
  text("serviceMetricCpu", view.metricValues.cpu);
  text("serviceMetricLatency", view.metricValues.latency);
  text("serviceMetricBacklog", view.metricValues.backlog);
  text("serviceMetricThroughput", view.metricValues.throughput);
  text("servicePerformanceBefore", view.comparison.before);
  text("servicePerformanceAfter", view.comparison.after);
  const comparisonState = text(
    "servicePerformanceComparisonState",
    view.comparison.available ? "전후 스냅샷 비교" : "스냅샷 수집 대기",
  );
  if (comparisonState) comparisonState.dataset.state = view.comparison.available ? "ready" : "waiting";
  const event = documentRef.getElementById("serviceDagAugmentationEvent");
  if (event) {
    event.hidden = view.event.hidden;
    event.dataset.state = view.event.tone;
  }
  text("serviceDagAugmentationEyebrow", view.event.eyebrow);
  text("serviceDagAugmentationLabel", view.event.label);
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
  serviceOperationsObservations.augmentation = {transitions: view.transitions};
  renderServiceOperationsTimeline(documentRef);
}


function openServiceCatalogDetail(target, documentRef = document) {
  const trigger = target?.closest?.("[data-service-detail-target]");
  if (!trigger) return false;
  const panel = documentRef.getElementById(trigger.dataset.serviceDetailTarget);
  if (!panel) return false;
  panel.open = true;
  trigger.setAttribute("aria-expanded", "true");
  panel.scrollIntoView?.({behavior: "smooth", block: "start"});
  panel.querySelector?.("summary")?.focus?.({preventScroll: true});
  return true;
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
  const routingView = buildServiceRoutingView(data);
  const summary = documentRef.getElementById("serviceDemoHistorySummary");
  const rail = documentRef.getElementById("serviceDemoHistoryRail");
  if (summary) summary.textContent = view.summary;
  const deviceRatio = documentRef.getElementById("serviceDeviceRatio");
  const serverRatio = documentRef.getElementById("serviceServerRatio");
  const routingSummary = documentRef.getElementById("serviceRoutingSampleSummary");
  if (deviceRatio) deviceRatio.textContent = routingView.deviceRatio === null ? "—" : `${routingView.deviceRatio}%`;
  if (serverRatio) serverRatio.textContent = routingView.serverRatio === null ? "—" : `${routingView.serverRatio}%`;
  if (routingSummary) routingSummary.textContent = routingView.summary;
  const split = documentRef.getElementById("serviceRoutingSplit");
  if (split) {
    split.dataset.empty = String(routingView.deviceRatio === null);
    split.style?.setProperty?.("--device-ratio", `${routingView.deviceRatio ?? 50}%`);
  }
  const deviceNode = documentRef.getElementById("serviceDagDevice1");
  const serverNode = documentRef.getElementById("serviceDagServer1");
  if (deviceNode) deviceNode.dataset.traffic = routingView.deviceCount > 0 ? "active" : "idle";
  if (serverNode) serverNode.dataset.traffic = routingView.serverCount > 0 ? "active" : "idle";
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
  serviceOperationsObservations.alerts = data;
  renderServiceOperationsTimeline(documentRef);
}


function renderServiceOperationsTimeline(documentRef = document) {
  const list = documentRef.getElementById("serviceOperationsTimelineList");
  if (!list || typeof documentRef.createElement !== "function") return;
  const view = buildServiceOperationsTimelineView(
    serviceOperationsObservations.augmentation,
    serviceOperationsObservations.alerts,
  );
  if (!view.events.length) {
    const empty = documentRef.createElement("li");
    empty.className = "service-timeline-empty";
    empty.textContent = "관측된 운영 이벤트가 없습니다.";
    list.replaceChildren(empty);
    return;
  }
  const nodes = view.events.map((entry) => {
    const item = documentRef.createElement("li");
    item.dataset.kind = entry.kind;
    item.dataset.state = entry.tone;
    const marker = documentRef.createElement("span");
    marker.className = "service-timeline-marker";
    marker.setAttribute("aria-hidden", "true");
    const body = documentRef.createElement("div");
    const title = documentRef.createElement("strong");
    title.textContent = entry.title;
    const detail = documentRef.createElement("p");
    detail.textContent = entry.detail;
    const time = documentRef.createElement("time");
    time.dateTime = entry.occurredAt;
    const parsed = Date.parse(entry.occurredAt);
    time.textContent = Number.isFinite(parsed) ? new Date(parsed).toLocaleString("ko-KR") : "시각 미확인";
    body.append(title, detail, time);
    item.append(marker, body);
    return item;
  });
  list.replaceChildren(...nodes);
}


async function refreshServiceDemo(fetchFn = fetch, documentRef = document) {
  try {
    const response = await fetchFn(serviceOperationsEndpoints.state, {cache: "no-store"});
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
    const response = await fetchFn(serviceOperationsEndpoints.alerts, {cache: "no-store"});
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
    const response = await fetchFn(serviceOperationsEndpoints.results, {cache: "no-store"});
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
    const response = await fetchFn(serviceOperationsEndpoints.augmentation, {cache: "no-store"});
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


async function refreshServiceInventory(fetchFn = fetch, documentRef = document) {
  try {
    const response = await fetchFn("/state/services", {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return renderServiceInventory(await response.json(), documentRef);
  } catch (error) {
    return renderServiceInventory({services: []}, documentRef);
  }
}


if (typeof module !== "undefined") {
  module.exports = {
    buildServiceAugmentationView,
    buildServiceCatalogView,
    buildServiceInventoryView,
    buildServiceDemoAlertView,
    buildServiceDemoResultsView,
    buildServiceDemoView,
    buildServiceOperationsTimelineView,
    buildServiceRoutingView,
    refreshServiceDemo,
    refreshServiceDemoAlerts,
    refreshServiceDemoResults,
    refreshServiceAugmentation,
    refreshServiceInventory,
    renderServiceDemo,
    renderServiceCatalog,
    renderServiceInventory,
    applyServiceDescriptor,
    renderServiceDemoAlerts,
    renderServiceDemoResults,
    renderServiceOperationsTimeline,
    renderServiceAugmentation,
    openServiceCatalogDetail,
  };
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  window.addEventListener("DOMContentLoaded", () => {
    document.getElementById("serviceCatalogList")?.addEventListener("click", (event) => {
      const trigger = event.target?.closest?.("[data-service-id]");
      const selected = trigger ? serviceInventoryById.get(trigger.dataset.serviceId) : null;
      if (selected) applyServiceDescriptor(selected);
      openServiceCatalogDetail(event.target);
    });
    refreshServiceInventory();
    refreshServiceDemo();
    refreshServiceDemoAlerts();
    refreshServiceDemoResults();
    refreshServiceAugmentation();
    window.setInterval(refreshServiceDemo, 5_000);
    window.setInterval(refreshServiceDemoAlerts, 5_000);
    window.setInterval(refreshServiceDemoResults, 5_000);
    window.setInterval(refreshServiceAugmentation, 5_000);
    window.setInterval(refreshServiceInventory, 5_000);
  });
}
