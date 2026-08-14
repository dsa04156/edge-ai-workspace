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


function buildServiceAugmentationView(augmentation = {}) {
  const state = ["NORMAL", "OBSERVING", "RECOMMENDED", "BLOCKED"].includes(augmentation.state)
    ? augmentation.state : "BLOCKED";
  const labels = {
    NORMAL: "정상",
    OBSERVING: "관찰",
    RECOMMENDED: "증강 권고",
    BLOCKED: "차단",
  };
  const reasons = {
    within_operating_envelope: "현재 자원 사용량과 서비스 처리 지표가 운영 범위 안에 있습니다.",
    resource_pressure_observing: "자원 압력이 감지되어 지속 시간을 관찰하고 있습니다.",
    service_pressure_observing: "지연·백로그·처리량 압력이 감지되어 지속 시간을 관찰하고 있습니다.",
    sustained_resource_and_service_pressure: "자원과 서비스 압력이 기준 시간 이상 지속되어 증강을 권고합니다.",
    augmentation_candidate_not_ready: "증강 조건은 충족했지만 server1 후보가 준비되지 않아 실행 판단을 차단합니다.",
    resource_observation_unavailable: "실제 자원 사용량을 확인할 수 없어 증강 판단을 차단합니다.",
    performance_observation_unavailable: "서비스 처리 지표를 확인할 수 없어 증강 판단을 차단합니다.",
    input_invalid_or_stale: "입력이 없거나 오래되어 증강 판단을 차단합니다.",
    model_not_ready: "모델이 준비되지 않아 증강 판단을 차단합니다.",
  };
  const metrics = augmentation.metrics || {};
  const dwell = augmentation.dwell || {};
  const reasonCodes = Array.isArray(augmentation.reason_codes) ? augmentation.reason_codes : [];
  const reason = reasonCodes.map((code) => reasons[code]).filter(Boolean).join(" ")
    || "판단 근거를 확인할 수 없습니다.";
  const number = (value, digits, suffix) => value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value))
    ? `${Number(value).toFixed(digits)}${suffix}` : "관측 불가";
  const backlog = Number(metrics.backlog);
  const resourceSeconds = Number(dwell.resource_pressure_seconds);
  const resourceRequired = Number(dwell.resource_pressure_required_seconds);
  const observation = augmentation.observation || {};
  return {
    state,
    label: labels[state],
    reason,
    cpu: number(metrics.cpu_percent, 1, "%"),
    memory: number(metrics.memory_percent, 1, "%"),
    latency: number(metrics.processing_latency_p95_ms, 0, " ms"),
    backlog: metrics.backlog !== null && metrics.backlog !== undefined && Number.isFinite(backlog)
      ? `${Math.max(0, Math.trunc(backlog))}건` : "관측 불가",
    throughput: number(metrics.throughput_per_second, 2, " /s"),
    observation: observation.source === "container-cadvisor" ? "컨테이너 · cAdvisor"
      : observation.source === "process-self" ? "메인 프로세스 · 자체 관측"
        : "관측 불가",
    candidate: augmentation.candidate?.ready === true ? "server1 GPU 준비됨"
      : augmentation.candidate?.ready === false ? "준비 안됨" : "관측 불가",
    dwell: Number.isFinite(resourceSeconds) && Number.isFinite(resourceRequired)
      ? `${Math.max(0, Math.trunc(resourceSeconds))} / ${Math.max(0, Math.trunc(resourceRequired))}초`
      : "관측 불가",
    boundary: "판단만 제공하며 자동 배포·라우팅·마이그레이션은 수행하지 않습니다.",
  };
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


function buildServiceOperationsTimelineView(alertData = {}) {
  const alerts = (Array.isArray(alertData.alerts) ? alertData.alerts : []).map((item) => ({
    kind: "equipment",
    tone: item?.transition === "opened" ? "blocked" : "normal",
    title: item?.transition === "opened" ? "설비 이상 발생" : "설비 정상 복귀",
    detail: `anomaly score ${serviceDemoNumber(item?.score, 2)}`,
    occurredAt: serviceDemoText(item?.observed_at, ""),
  }));
  const events = alerts
    .sort((left, right) => (Date.parse(right.occurredAt) || 0) - (Date.parse(left.occurredAt) || 0))
    .slice(0, 10);
  return {events};
}


const serviceOperationsObservations = {alerts: {}};
const serviceInventoryById = new Map();
let serviceOperationsDescriptor = null;
let serviceOperationsLastData = null;
const serviceOperationsEndpoints = {
  state: "/state/service-demo",
  results: "/state/service-demo/results?limit=12",
  alerts: "/state/service-demo/alerts?limit=10",
};


function buildServiceStagePlacementView(data = {}, descriptor = {}) {
  const graph = descriptor?.graph || {};
  const binding = data.binding || {};
  const targets = new Map((Array.isArray(graph.targets) ? graph.targets : []).map((target) => (
    [target.slot, target]
  )));
  if (!targets.has("Device1")) {
    targets.set("Device1", {
      slot: "Device1",
      label: "Device1",
      node: serviceDemoText(binding.node, "위치 미확인"),
    });
  }
  if (!targets.has("Server1")) {
    targets.set("Server1", {slot: "Server1", label: "Server GPU", node: "위치 미확인"});
  }
  const stages = new Map((Array.isArray(graph.stages) ? graph.stages : []).map((stage) => (
    [stage.slot, stage]
  )));
  const effectiveTarget = data.inference_routing?.effective_target === "server1"
    || data.latest?.inference_target === "server1" ? "Server1" : "Device1";
  const fallbackExecutors = {
    Input: serviceDemoText(binding.device_service, "EdgeX Device Service"),
    Alignment: serviceDemoText(binding.consumer, "service workload"),
    Features: serviceDemoText(binding.consumer, "service workload"),
    Inference: effectiveTarget === "Server1"
      ? "sensor-anomaly-inference-server1"
      : serviceDemoText(binding.consumer, "service workload"),
    Result: serviceDemoText(binding.consumer, "service workload"),
  };

  return Object.fromEntries(["Input", "Alignment", "Features", "Inference", "Result"].map((slot) => {
    const stage = stages.get(slot) || {};
    const executions = Array.isArray(stage.executions) ? stage.executions : [];
    const desiredTarget = slot === "Inference" ? effectiveTarget : "Device1";
    const execution = executions.find((item) => item.target_slot === desiredTarget)
      || executions[0]
      || {target_slot: desiredTarget, executor: fallbackExecutors[slot]};
    const target = targets.get(execution.target_slot) || targets.get(desiredTarget);
    return [slot, {
      targetSlot: execution.target_slot,
      location: `${serviceDemoText(target?.label, execution.target_slot)} · ${serviceDemoText(target?.node, "위치 미확인")}`,
      executor: serviceDemoText(execution.executor, fallbackExecutors[slot]),
    }];
  }));
}


function renderServiceStagePlacements(data, descriptor, documentRef = document) {
  const placements = buildServiceStagePlacementView(data, descriptor);
  Object.entries(placements).forEach(([slot, placement]) => {
    const location = documentRef.getElementById(`serviceDemoStep${slot}Location`);
    const executor = documentRef.getElementById(`serviceDemoStep${slot}Executor`);
    if (location) location.textContent = placement.location;
    if (executor) executor.textContent = placement.executor;
  });
  return placements;
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
  const frames = Number(data.counters?.frames_processed);
  const inputAge = latest ? serviceDemoAge(latest.observed_at, nowMs) : "관측 불가";
  const flowing = data.input_state === "fresh" && Boolean(latest);

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
    inputAge,
    frames: serviceDemoText(data.counters?.frames_processed),
    flowing,
    liveLabel: flowing ? "데이터 처리 중" : "데이터 확인 필요",
    liveAge: latest ? `입력 ${inputAge.replace(" s", "초")} 전` : "입력 확인 중",
    liveFrames: Number.isFinite(frames)
      ? `${Math.max(0, Math.trunc(frames)).toLocaleString("ko-KR")}건 처리`
      : "처리량 확인 중",
    inferenceTarget,
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
    augmentation: buildServiceAugmentationView(data.augmentation),
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
  serviceOperationsDescriptor = descriptor;
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
    text(`serviceDag${target.slot}Node`, target.node);
  });
  const observability = descriptor.observability || {};
  if (observability.adapter === "sensor-anomaly-v1") {
    serviceOperationsEndpoints.state = observability.state_path || serviceOperationsEndpoints.state;
    serviceOperationsEndpoints.results = observability.results_path || serviceOperationsEndpoints.results;
    serviceOperationsEndpoints.alerts = observability.alerts_path || serviceOperationsEndpoints.alerts;
  }
  if (serviceOperationsLastData) {
    renderServiceStagePlacements(serviceOperationsLastData, descriptor, documentRef);
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
    appendCatalogFact(documentRef, button, "설비 판정", [row.decision], index === 0 ? ["serviceCatalogDecision"] : []);
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
  serviceOperationsLastData = data;
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
  text("serviceOperationsRunState", view.liveLabel);
  text("serviceOperationsLiveAge", view.liveAge);
  text("serviceOperationsLiveFrames", view.liveFrames);
  const liveStatus = documentRef.getElementById("serviceOperationsLive");
  if (liveStatus) liveStatus.dataset.state = view.flowing ? "flowing" : "attention";
  text("serviceDemoFrames", view.frames);
  const augmentationPanel = documentRef.getElementById("serviceAugmentationPanel");
  if (augmentationPanel) augmentationPanel.dataset.state = view.augmentation.state;
  text("serviceAugmentationState", view.augmentation.label);
  text("serviceAugmentationReason", view.augmentation.reason);
  text("serviceAugmentationCpu", view.augmentation.cpu);
  text("serviceAugmentationMemory", view.augmentation.memory);
  text("serviceAugmentationLatency", view.augmentation.latency);
  text("serviceAugmentationBacklog", view.augmentation.backlog);
  text("serviceAugmentationThroughput", view.augmentation.throughput);
  text("serviceAugmentationObservation", view.augmentation.observation);
  text("serviceAugmentationCandidate", view.augmentation.candidate);
  text("serviceAugmentationDwell", view.augmentation.dwell);
  text("serviceAugmentationBoundary", view.augmentation.boundary);
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
      stage.dataset.live = String(view.flowing && step.state !== "pending");
    }
    text(`serviceDemoStep${step.id}Evidence`, step.evidence);
  });
  const dag = documentRef.getElementById("serviceOperationsDag");
  if (dag) {
    dag.dataset.flowing = String(view.flowing);
    dag.dataset.target = view.inferenceTarget === "server1" ? "server1" : "device1";
  }
  const deviceTarget = documentRef.getElementById("serviceDagDevice1");
  const serverTarget = documentRef.getElementById("serviceDagServer1");
  if (deviceTarget) deviceTarget.dataset.currentRoute = String(view.flowing && view.inferenceTarget !== "server1");
  if (serverTarget) serverTarget.dataset.currentRoute = String(view.flowing && view.inferenceTarget === "server1");
  renderServiceStagePlacements(data, serviceOperationsDescriptor || {}, documentRef);
  const error = text("serviceDemoError", view.error);
  if (error) error.hidden = !view.error;
  renderServiceCatalog(data, documentRef);
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
  const view = buildServiceOperationsTimelineView(serviceOperationsObservations.alerts);
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
    buildServiceCatalogView,
    buildServiceInventoryView,
    buildServiceDemoAlertView,
    buildServiceDemoResultsView,
    buildServiceDemoView,
    buildServiceOperationsTimelineView,
    buildServiceRoutingView,
    buildServiceStagePlacementView,
    refreshServiceDemo,
    refreshServiceDemoAlerts,
    refreshServiceDemoResults,
    refreshServiceInventory,
    renderServiceDemo,
    renderServiceCatalog,
    renderServiceInventory,
    applyServiceDescriptor,
    renderServiceDemoAlerts,
    renderServiceDemoResults,
    renderServiceOperationsTimeline,
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
    window.setInterval(refreshServiceDemo, 5_000);
    window.setInterval(refreshServiceDemoAlerts, 5_000);
    window.setInterval(refreshServiceDemoResults, 5_000);
    window.setInterval(refreshServiceInventory, 5_000);
  });
}
