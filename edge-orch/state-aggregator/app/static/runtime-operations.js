const RUNTIME_ENDPOINTS = Object.freeze({
  recommendations: "/api/runtime-recommendations",
  resources: "/api/resources",
  services: "/state/services",
});

const RUNTIME_STATES = new Set([
  "NORMAL",
  "OBSERVING",
  "AUGMENT_RECOMMENDED",
  "REPLACE_RECOMMENDED",
  "BLOCKED",
]);

const runtimeOperationsState = {
  recommendations: [],
  resources: [],
  services: [],
  selectedServiceId: null,
  decision: null,
  history: null,
  plan: null,
  errors: {},
  loading: false,
  loadedAt: null,
};

function runtimeEscape(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function runtimeValue(value, fallback = "N/A") {
  return value === null || value === undefined || value === "" ? fallback : String(value);
}

function runtimeNumber(value) {
  if (value === null || value === undefined || value === "") return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function runtimeRatio(value) {
  const number = runtimeNumber(value);
  return number === null ? "N/A" : `${(number * 100).toFixed(1)}%`;
}

function runtimeBytesToGb(value) {
  const number = runtimeNumber(value);
  return number === null ? "N/A" : `${(number / (1024 ** 3)).toFixed(2)} GB`;
}

function runtimeDate(value) {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return "N/A";
  return new Date(parsed).toLocaleString("ko-KR");
}

function runtimeList(value) {
  return Array.isArray(value) ? value : [];
}

function runtimeField(source, camel, snake = camel) {
  if (!source || typeof source !== "object") return undefined;
  return source[camel] ?? source[snake];
}

function runtimeStateTone(state) {
  return {
    NORMAL: "normal",
    OBSERVING: "observing",
    AUGMENT_RECOMMENDED: "augment",
    REPLACE_RECOMMENDED: "replace",
    BLOCKED: "blocked",
  }[state] || "unknown";
}

function runtimeActionLabel(action) {
  return {
    augment: "AUGMENT",
    replace: "REPLACE",
    none: "NO CHANGE",
  }[action] || "N/A";
}

function observedDurationSeconds(decision = {}) {
  const dwell = decision.dwell || {};
  const values = decision.state === "REPLACE_RECOMMENDED"
    ? [dwell.runtimeFailureSeconds]
    : decision.state === "AUGMENT_RECOMMENDED"
      ? [dwell.resourcePressureSeconds, dwell.servicePressureSeconds]
      : [
          dwell.resourcePressureSeconds,
          dwell.servicePressureSeconds,
          dwell.runtimeFailureSeconds,
          dwell.recoverySeconds,
        ];
  const observed = values.map(runtimeNumber).filter((value) => value !== null);
  return observed.length ? Math.max(...observed) : null;
}

function serviceRuntimeStatus(decision = {}) {
  const desired = runtimeNumber(decision.metrics?.desiredReplicas);
  const ready = runtimeNumber(decision.metrics?.readyReplicas);
  if (desired === null || ready === null) return "N/A";
  if (desired > 0 && ready >= desired) return "RUNNING";
  if (desired > 0) return "DEGRADED";
  return "N/A";
}

function serviceObservationFor(serviceId, services = []) {
  return runtimeList(services).find((item) => (
    runtimeField(item, "serviceId", "service_id") === serviceId
  )) || null;
}

function findSchedulingResource(nodeName, resources = runtimeOperationsState.resources) {
  if (!nodeName) return null;
  return runtimeList(resources).find((item) => item?.node === nodeName) || null;
}

function candidateView(candidate = {}, selectedNode = null) {
  const selected = candidate.eligible === true && candidate.node === selectedNode;
  return {
    node: runtimeValue(candidate.node),
    result: selected ? "SELECTED" : candidate.eligible === true ? "ELIGIBLE" : "REJECTED",
    score: runtimeNumber(candidate.score),
    reasonCodes: runtimeList(candidate.reasonCodes),
    availableBefore: candidate.availableBefore || null,
    availableAfter: candidate.availableAfter || null,
    utilization: candidate.utilization || null,
    health: runtimeValue(candidate.health),
    architecture: runtimeValue(candidate.architecture),
    accelerator: runtimeValue(candidate.accelerator),
  };
}

function buildRuntimeOperationsView({decision, history, plan, resources, services, errors = {}} = {}) {
  if (!decision) {
    return {
      available: false,
      serviceId: runtimeValue(runtimeOperationsState.selectedServiceId),
      state: "N/A",
      tone: "unknown",
      status: "N/A",
      statusTone: "unknown",
      currentNodes: [],
      currentNode: "N/A",
      inputState: "N/A",
      modelState: "N/A",
      reasonCodes: [],
      observedDuration: null,
      metrics: {cpu: "N/A", memory: "N/A", gpu: "N/A", latency: "N/A", backlog: "N/A"},
      currentScheduling: {cpu: "N/A", memory: "N/A", accelerator: "N/A"},
      action: "N/A",
      selectedNode: "N/A",
      selectedScore: null,
      candidates: [],
      plan: null,
      history: [],
      errors,
    };
  }

  const serviceId = runtimeValue(decision.serviceId);
  const service = serviceObservationFor(serviceId, services);
  const currentNodes = runtimeList(decision.currentNodes);
  const currentResource = findSchedulingResource(currentNodes[0], resources);
  const gpuRatio = currentResource?.utilization?.gpuRatio;
  const selectedNode = decision.recommendation?.selectedNode || decision.placement?.selectedNode || null;
  return {
    available: true,
    serviceId,
    workload: `${runtimeValue(decision.namespace)}/${runtimeValue(decision.workloadName)}`,
    workloadKind: runtimeValue(decision.workloadKind),
    state: RUNTIME_STATES.has(decision.state) ? decision.state : "N/A",
    tone: runtimeStateTone(decision.state),
    status: serviceRuntimeStatus(decision),
    statusTone: serviceRuntimeStatus(decision) === "RUNNING" ? "running"
      : serviceRuntimeStatus(decision) === "DEGRADED" ? "degraded" : "unknown",
    currentNodes,
    currentNode: currentNodes.join(", ") || "N/A",
    currentHealth: runtimeValue(currentResource?.health),
    inputState: runtimeValue(runtimeField(service, "inputState", "input_state")),
    modelState: runtimeValue(runtimeField(service, "modelState", "model_state")),
    reasonCodes: runtimeList(decision.reasonCodes),
    observedDuration: observedDurationSeconds(decision),
    cooldownRemainingSeconds: runtimeNumber(decision.cooldownRemainingSeconds),
    metrics: {
      cpu: runtimeRatio(decision.metrics?.cpuRatio),
      memory: runtimeRatio(decision.metrics?.memoryRatio),
      gpu: runtimeRatio(gpuRatio),
      latency: runtimeNumber(decision.metrics?.latencyP95Ms) === null
        ? "N/A" : `${Number(decision.metrics.latencyP95Ms).toFixed(0)} ms`,
      backlog: runtimeNumber(decision.metrics?.backlog) === null
        ? "N/A" : `${Number(decision.metrics.backlog)}건`,
      throughput: runtimeNumber(decision.metrics?.throughputPerSecond) === null
        ? "N/A" : `${Number(decision.metrics.throughputPerSecond).toFixed(2)} /s`,
    },
    currentScheduling: {
      cpu: runtimeNumber(currentResource?.available?.cpuCores) === null
        ? "N/A" : `${Number(currentResource.available.cpuCores).toFixed(2)} cores available`,
      memory: runtimeBytesToGb(currentResource?.available?.memoryBytes),
      accelerator: runtimeValue(currentResource?.accelerator),
    },
    action: runtimeActionLabel(decision.recommendation?.action),
    selectedNode: runtimeValue(selectedNode),
    selectedScore: runtimeNumber(decision.recommendation?.selectedScore ?? decision.placement?.selectedScore),
    candidates: runtimeList(decision.placement?.candidates).map((candidate) => (
      candidateView(candidate, selectedNode)
    )),
    placementStatus: runtimeValue(decision.placement?.status),
    placementReasons: runtimeList(decision.placement?.reasonCodes),
    plan: plan || null,
    history: runtimeList(history?.items),
    observedAt: decision.observedAt,
    observationSource: runtimeValue(decision.observationSource),
    observationScope: runtimeValue(decision.observationScope),
    errors,
  };
}

function renderReasonCodes(codes = [], emptyText = "판단 근거 데이터 없음") {
  if (!codes.length) return `<li class="runtime-empty-reason">${runtimeEscape(emptyText)}</li>`;
  return codes.map((code) => `<li><code>${runtimeEscape(code)}</code></li>`).join("");
}

function renderRuntimeCandidates(view) {
  if (!view.candidates.length) {
    return `<div class="runtime-section-empty">배치 후보 데이터 없음</div>`;
  }
  const rows = view.candidates.map((candidate) => {
    const available = candidate.availableAfter || candidate.availableBefore;
    const cpu = runtimeNumber(available?.cpuCores);
    const memory = runtimeNumber(available?.memoryBytes);
    const reasons = candidate.reasonCodes.length ? candidate.reasonCodes.join(", ") : "데이터 없음";
    return `
      <tr data-result="${runtimeEscape(candidate.result.toLowerCase())}">
        <td data-label="Node"><strong>${runtimeEscape(candidate.node)}</strong><small>${runtimeEscape(candidate.health)} · ${runtimeEscape(candidate.architecture)} · ${runtimeEscape(candidate.accelerator)}</small></td>
        <td data-label="Result"><span class="runtime-result-badge" data-result="${runtimeEscape(candidate.result.toLowerCase())}">${runtimeEscape(candidate.result)}</span></td>
        <td data-label="Score">${candidate.score === null ? "-" : runtimeEscape(candidate.score.toFixed(2))}</td>
        <td data-label="Available">${cpu === null ? "CPU N/A" : `CPU ${runtimeEscape(cpu.toFixed(2))}`} · ${memory === null ? "Memory N/A" : runtimeBytesToGb(memory)}</td>
        <td data-label="Reason"><code>${runtimeEscape(reasons)}</code></td>
      </tr>
    `;
  }).join("");
  return `
    <div class="runtime-table-wrap" role="region" aria-label="배치 후보 비교" tabindex="0">
      <table class="runtime-candidate-table">
        <thead><tr><th scope="col">Node</th><th scope="col">Result</th><th scope="col">Score</th><th scope="col">Available</th><th scope="col">Reason</th></tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function renderConditionList(conditions = []) {
  if (!runtimeList(conditions).length) return "<li>N/A</li>";
  return runtimeList(conditions).map((condition) => `
    <li><code>${runtimeEscape(condition.code)}</code><span>${runtimeEscape(condition.description)}</span></li>
  `).join("");
}

function renderRuntimePlan(plan) {
  if (!plan) return `<div class="runtime-section-empty">Execution Plan 데이터 없음</div>`;
  const steps = runtimeList(plan.steps);
  if (!steps.length) {
    return `
      <div class="runtime-section-empty">
        <strong>${runtimeEscape(runtimeValue(plan.status, "계획 없음"))}</strong>
        <span>${runtimeEscape(runtimeList(plan.reasonCodes).join(", ") || "실행 단계 데이터 없음")}</span>
      </div>
    `;
  }
  return `
    <ol class="runtime-plan-steps">
      ${steps.map((step) => {
        const targets = runtimeList(step.targets).map((target) => (
          `${runtimeValue(target.node)} · ${runtimeValue(target.workload?.namespace)}/${runtimeValue(target.workload?.name)} (${runtimeValue(target.workload?.role)})`
        )).join(" / ") || "N/A";
        return `
          <li data-mode="${runtimeEscape(runtimeValue(step.executionMode))}" data-action="${runtimeEscape(runtimeValue(step.action))}">
            <span class="runtime-plan-index">${runtimeEscape(runtimeValue(step.sequence))}</span>
            <div class="runtime-plan-step-body">
              <div class="runtime-plan-step-title"><strong>${runtimeEscape(runtimeValue(step.action))}</strong><span>${runtimeEscape(runtimeValue(step.executionMode))}</span></div>
              <p>${runtimeEscape(targets)}</p>
              <details>
                <summary>선행조건·실패조건</summary>
                <div class="runtime-plan-conditions">
                  <section><strong>선행조건</strong><ul>${renderConditionList(step.prerequisites)}</ul></section>
                  <section><strong>실패조건</strong><ul>${renderConditionList(step.failureConditions)}</ul></section>
                </div>
              </details>
            </div>
          </li>
        `;
      }).join("")}
    </ol>
  `;
}

function renderRuntimeHistory(items = []) {
  if (!items.length) return `<div class="runtime-section-empty">Runtime History 데이터 없음</div>`;
  return `
    <ol class="runtime-history-list">
      ${items.map((entry) => {
        const decision = entry.decision || {};
        const previous = runtimeValue(entry.previousState, "N/A");
        const state = runtimeValue(entry.state);
        const selected = decision.recommendation?.selectedNode;
        return `
          <li data-state="${runtimeEscape(runtimeStateTone(state))}">
            <span class="runtime-history-marker" aria-hidden="true"></span>
            <div>
              <header><strong>${runtimeEscape(state)}</strong><time datetime="${runtimeEscape(runtimeValue(entry.recordedAt, ""))}">${runtimeEscape(runtimeDate(entry.recordedAt))}</time></header>
              <dl>
                <div><dt>trigger</dt><dd>${runtimeEscape(previous)} → ${runtimeEscape(state)}</dd></div>
                <div><dt>reason</dt><dd><code>${runtimeEscape(runtimeList(decision.reasonCodes).join(", ") || "데이터 없음")}</code></dd></div>
                <div><dt>기존 노드</dt><dd>${runtimeEscape(runtimeList(decision.currentNodes).join(", ") || "N/A")}</dd></div>
                <div><dt>추천 노드</dt><dd>${runtimeEscape(runtimeValue(selected))}</dd></div>
              </dl>
            </div>
          </li>
        `;
      }).join("")}
    </ol>
  `;
}

function renderRuntimeOperations(view, documentRef = document) {
  const content = documentRef.getElementById("runtimeOperationsContent");
  const notice = documentRef.getElementById("runtimeOperationsAvailability");
  if (!content || !notice) return view;
  notice.dataset.state = view.available ? view.tone : "unknown";
  notice.textContent = view.available
    ? `${view.serviceId} · ${view.state} · ${runtimeDate(view.observedAt)}`
    : `Runtime Recommendation 관측 불가${view.errors?.decision ? ` · ${view.errors.decision}` : ""}`;

  content.innerHTML = `
    <section class="panel runtime-service-panel" aria-labelledby="runtimeServiceStateTitle">
      <div class="runtime-section-head">
        <div><span>Service Runtime</span><h3 id="runtimeServiceStateTitle">${runtimeEscape(view.serviceId)}</h3></div>
        <span class="runtime-state-badge" data-state="${runtimeEscape(view.statusTone)}">${runtimeEscape(view.status)}</span>
      </div>
      <div class="runtime-service-grid">
        <dl class="runtime-fact-list">
          <div><dt>현재 노드</dt><dd>${runtimeEscape(view.currentNode)}</dd></div>
          <div><dt>Node Health</dt><dd>${runtimeEscape(runtimeValue(view.currentHealth))}</dd></div>
          <div><dt>Input 상태</dt><dd>${runtimeEscape(view.inputState)}</dd></div>
          <div><dt>Model 상태</dt><dd>${runtimeEscape(view.modelState)}</dd></div>
          <div><dt>Workload</dt><dd>${runtimeEscape(runtimeValue(view.workload))}</dd></div>
        </dl>
        <dl class="runtime-metric-strip" aria-label="서비스 자원과 처리 지표">
          <div><dt>CPU</dt><dd>${runtimeEscape(view.metrics.cpu)}</dd></div>
          <div><dt>Memory</dt><dd>${runtimeEscape(view.metrics.memory)}</dd></div>
          <div><dt>GPU</dt><dd>${runtimeEscape(view.metrics.gpu)}</dd></div>
          <div><dt>Latency p95</dt><dd>${runtimeEscape(view.metrics.latency)}</dd></div>
          <div><dt>Backlog</dt><dd>${runtimeEscape(view.metrics.backlog)}</dd></div>
          <div><dt>Throughput</dt><dd>${runtimeEscape(runtimeValue(view.metrics.throughput))}</dd></div>
        </dl>
      </div>
      <dl class="runtime-current-scheduling" aria-label="현재 노드 Scheduling Resource">
        <div><dt>Scheduling CPU</dt><dd>${runtimeEscape(view.currentScheduling.cpu)}</dd></div>
        <div><dt>Scheduling Memory</dt><dd>${runtimeEscape(view.currentScheduling.memory)}</dd></div>
        <div><dt>Accelerator</dt><dd>${runtimeEscape(view.currentScheduling.accelerator)}</dd></div>
        <div><dt>근거</dt><dd>Kubernetes allocatable − Pod requests</dd></div>
      </dl>
      <section class="runtime-decision" data-state="${runtimeEscape(view.tone)}" aria-labelledby="runtimeDecisionTitle">
        <div><span>Runtime Recommendation</span><strong id="runtimeDecisionTitle">${runtimeEscape(view.state)}</strong></div>
        <ul>${renderReasonCodes(view.reasonCodes)}</ul>
        <p>observed duration: <strong>${view.observedDuration === null ? "N/A" : `${runtimeEscape(view.observedDuration)}s`}</strong> · cooldown: <strong>${view.cooldownRemainingSeconds === null ? "N/A" : `${runtimeEscape(view.cooldownRemainingSeconds)}s`}</strong></p>
      </section>
    </section>

    <section class="panel runtime-placement-panel" aria-labelledby="runtimePlacementTitle">
      <div class="runtime-section-head"><div><span>Placement Evidence</span><h3 id="runtimePlacementTitle">배치 추천</h3></div><span>${runtimeEscape(view.placementStatus)}</span></div>
      <div class="runtime-decision-rail" data-action="${runtimeEscape(view.action.toLowerCase())}">
        <div><span>Current</span><strong>${runtimeEscape(view.currentNode)}</strong></div>
        <div class="runtime-decision-arrow"><span>↓</span><strong>${runtimeEscape(view.action)}</strong></div>
        <div><span>Recommended</span><strong>${runtimeEscape(view.selectedNode)}</strong><small>Score ${view.selectedScore === null ? "N/A" : runtimeEscape(view.selectedScore.toFixed(2))}</small></div>
      </div>
      ${renderRuntimeCandidates(view)}
    </section>

    <section class="panel runtime-plan-panel" aria-labelledby="runtimePlanTitle">
      <div class="runtime-section-head"><div><span>Execution Plan</span><h3 id="runtimePlanTitle">실행 계획 / Read-only</h3></div><span>${runtimeEscape(runtimeValue(view.plan?.status))}</span></div>
      <p class="runtime-readonly-boundary">조회용 계획입니다. 이 화면은 Kubernetes 변경, 트래픽 전환, 승인 또는 실행을 수행하지 않습니다.</p>
      ${renderRuntimePlan(view.plan)}
    </section>

    <section class="panel runtime-history-panel" aria-labelledby="runtimeHistoryTitle">
      <div class="runtime-section-head"><div><span>Decision Timeline</span><h3 id="runtimeHistoryTitle">Runtime History</h3></div><span>${runtimeEscape(view.history.length)} events</span></div>
      ${renderRuntimeHistory(view.history)}
    </section>

    <p class="runtime-observation-source">관측 ${runtimeEscape(runtimeValue(view.observationSource))} · ${runtimeEscape(runtimeValue(view.observationScope))} · 후보는 Runtime Recommendation 응답의 Placement 결과</p>
  `;
  return view;
}

function renderRuntimeOverview(view, documentRef = document) {
  const set = (id, value) => {
    const element = documentRef.getElementById(id);
    if (element) element.textContent = value;
    return element;
  };
  const title = set("runtimeOverviewTitle", view.state);
  if (title) title.dataset.state = view.tone;
  set("runtimeOverviewReasons", view.reasonCodes.join(", ") || "판단 근거 데이터 없음");
  set("runtimeOverviewCurrentNode", view.currentNode);
  set("runtimeOverviewCpu", view.metrics.cpu);
  set("runtimeOverviewMemory", view.metrics.memory);
  set("runtimeOverviewLatency", view.metrics.latency);
  set("runtimeOverviewSelectedNode", view.selectedNode);
  set("runtimeOverviewScore", view.selectedScore === null ? "N/A" : view.selectedScore.toFixed(2));
  return view;
}

function renderSchedulingResourceDetails(resource, fallbackUsage = {}) {
  const usage = resource?.utilization || fallbackUsage || {};
  const amountRows = [
    ["CPU", "cpuCores", (value) => value === null ? "N/A" : `${value.toFixed(2)} cores`],
    ["Memory", "memoryBytes", runtimeBytesToGb],
  ];
  const scheduling = resource ? amountRows.map(([label, key, formatter]) => {
    const allocatable = runtimeNumber(resource.allocatable?.[key]);
    const requested = runtimeNumber(resource.requested?.[key]);
    const available = runtimeNumber(resource.available?.[key]);
    return `
      <tr><th scope="row">${label}</th><td>${formatter(allocatable)}</td><td>${formatter(requested)}</td><td>${formatter(available)}</td></tr>
    `;
  }).join("") : `
    <tr><th scope="row">CPU</th><td>N/A</td><td>N/A</td><td>N/A</td></tr>
    <tr><th scope="row">Memory</th><td>N/A</td><td>N/A</td><td>N/A</td></tr>
  `;
  const acceleratorKeys = resource
    ? [...new Set([
        ...Object.keys(resource.allocatable?.acceleratorUnits || {}),
        ...Object.keys(resource.requested?.acceleratorUnits || {}),
        ...Object.keys(resource.available?.acceleratorUnits || {}),
      ])]
    : [];
  const gpuRows = acceleratorKeys.length ? acceleratorKeys.map((key) => `
    <tr><th scope="row">GPU · ${runtimeEscape(key)}</th><td>${runtimeEscape(runtimeValue(resource.allocatable?.acceleratorUnits?.[key]))}</td><td>${runtimeEscape(runtimeValue(resource.requested?.acceleratorUnits?.[key]))}</td><td>${runtimeEscape(runtimeValue(resource.available?.acceleratorUnits?.[key]))}</td></tr>
  `).join("") : `<tr><th scope="row">GPU</th><td>N/A</td><td>N/A</td><td>N/A</td></tr>`;
  return `
    <section class="node-resource-evidence" aria-label="노드 자원 상세">
      <div class="node-resource-usage">
        <strong>실사용</strong><span>Prometheus</span>
        <dl>
          <div><dt>CPU Usage</dt><dd>${runtimeRatio(usage.cpuRatio ?? usage.cpu_utilization)}</dd></div>
          <div><dt>Memory Usage</dt><dd>${runtimeRatio(usage.memoryRatio ?? usage.memory_usage_ratio)}</dd></div>
          <div><dt>GPU Usage</dt><dd>${runtimeRatio(usage.gpuRatio ?? usage.gpu_utilization)}</dd></div>
        </dl>
      </div>
      <div class="node-scheduling-resource">
        <div><strong>Scheduling Resource</strong><span>Kubernetes allocatable − Pod requests</span></div>
        <div class="node-scheduling-table-wrap">
          <table><thead><tr><th scope="col">Resource</th><th scope="col">Allocatable</th><th scope="col">Requested</th><th scope="col">Available</th></tr></thead><tbody>${scheduling}${gpuRows}</tbody></table>
        </div>
        <p>${resource ? `${runtimeEscape(runtimeValue(resource.health))} · ${runtimeEscape(runtimeList(resource.reasonCodes).join(", ") || "reason 없음")}` : "Scheduling Resource 관측 불가 · /api/resources 데이터 없음"}</p>
      </div>
    </section>
  `;
}

async function runtimeFetchJson(url, fetchFn = fetch) {
  const response = await fetchFn(url, {cache: "no-store"});
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function runtimeErrorMessage(error) {
  return error instanceof Error ? error.message : "관측 불가";
}

async function loadRuntimeOperationsData(fetchFn = fetch) {
  runtimeOperationsState.loading = true;
  const [recommendationsResult, resourcesResult, servicesResult] = await Promise.allSettled([
    runtimeFetchJson(RUNTIME_ENDPOINTS.recommendations, fetchFn),
    runtimeFetchJson(RUNTIME_ENDPOINTS.resources, fetchFn),
    runtimeFetchJson(RUNTIME_ENDPOINTS.services, fetchFn),
  ]);

  runtimeOperationsState.errors = {};
  if (recommendationsResult.status === "fulfilled") {
    runtimeOperationsState.recommendations = runtimeList(recommendationsResult.value?.items);
  } else {
    runtimeOperationsState.recommendations = [];
    runtimeOperationsState.errors.recommendations = runtimeErrorMessage(recommendationsResult.reason);
  }
  if (resourcesResult.status === "fulfilled" && Array.isArray(resourcesResult.value)) {
    runtimeOperationsState.resources = resourcesResult.value;
  } else {
    runtimeOperationsState.resources = [];
    runtimeOperationsState.errors.resources = resourcesResult.status === "rejected"
      ? runtimeErrorMessage(resourcesResult.reason) : "invalid resource response";
  }
  if (servicesResult.status === "fulfilled") {
    runtimeOperationsState.services = runtimeList(servicesResult.value?.services);
  } else {
    runtimeOperationsState.services = [];
    runtimeOperationsState.errors.services = runtimeErrorMessage(servicesResult.reason);
  }

  const serviceIds = runtimeOperationsState.recommendations
    .map((item) => item?.serviceId)
    .filter(Boolean);
  if (!serviceIds.includes(runtimeOperationsState.selectedServiceId)) {
    runtimeOperationsState.selectedServiceId = serviceIds[0] || null;
  }

  const serviceId = runtimeOperationsState.selectedServiceId;
  runtimeOperationsState.decision = null;
  runtimeOperationsState.history = null;
  runtimeOperationsState.plan = null;
  if (serviceId) {
    const encoded = encodeURIComponent(serviceId);
    const [decisionResult, historyResult, planResult] = await Promise.allSettled([
      runtimeFetchJson(`/api/runtime-recommendations/${encoded}`, fetchFn),
      runtimeFetchJson(`/api/runtime-recommendations/${encoded}/history?limit=50`, fetchFn),
      runtimeFetchJson(`/api/runtime-recommendations/${encoded}/execution-plan`, fetchFn),
    ]);
    if (decisionResult.status === "fulfilled") runtimeOperationsState.decision = decisionResult.value;
    else runtimeOperationsState.errors.decision = runtimeErrorMessage(decisionResult.reason);
    if (historyResult.status === "fulfilled") runtimeOperationsState.history = historyResult.value;
    else runtimeOperationsState.errors.history = runtimeErrorMessage(historyResult.reason);
    if (planResult.status === "fulfilled") runtimeOperationsState.plan = planResult.value;
    else runtimeOperationsState.errors.plan = runtimeErrorMessage(planResult.reason);
  }
  runtimeOperationsState.loading = false;
  runtimeOperationsState.loadedAt = new Date().toISOString();
  return runtimeOperationsState;
}

function renderRuntimeServiceOptions(documentRef = document) {
  const select = documentRef.getElementById("runtimeOperationsServiceSelect");
  if (!select) return;
  const ids = runtimeOperationsState.recommendations.map((item) => item?.serviceId).filter(Boolean);
  select.innerHTML = ids.length
    ? ids.map((id) => `<option value="${runtimeEscape(id)}">${runtimeEscape(id)}</option>`).join("")
    : `<option value="">서비스 데이터 없음</option>`;
  select.value = runtimeOperationsState.selectedServiceId || "";
}

async function refreshRuntimeOperations(fetchFn = fetch, documentRef = document) {
  const notice = documentRef.getElementById("runtimeOperationsAvailability");
  if (notice) {
    notice.dataset.state = "observing";
    notice.textContent = "Runtime Recommendation을 갱신하고 있습니다.";
  }
  await loadRuntimeOperationsData(fetchFn);
  renderRuntimeServiceOptions(documentRef);
  const view = buildRuntimeOperationsView(runtimeOperationsState);
  renderRuntimeOperations(view, documentRef);
  renderRuntimeOverview(view, documentRef);
  if (typeof documentRef.dispatchEvent === "function" && typeof CustomEvent !== "undefined") {
    documentRef.dispatchEvent(new CustomEvent("runtime-resources-updated"));
  }
  return view;
}

async function selectRuntimeService(serviceId, fetchFn = fetch, documentRef = document) {
  runtimeOperationsState.selectedServiceId = serviceId || null;
  return refreshRuntimeOperations(fetchFn, documentRef);
}

function openRuntimeOperations(documentRef = document) {
  if (typeof globalThis.showDashboardPage === "function") globalThis.showDashboardPage("operations");
  if (globalThis.location && globalThis.location.hash !== "#operations") {
    globalThis.location.hash = "operations";
  }
  documentRef.getElementById("runtimeOperationsTitle")?.scrollIntoView?.({block: "start"});
}

if (typeof document !== "undefined") {
  document.getElementById("runtimeOperationsServiceSelect")?.addEventListener("change", (event) => {
    void selectRuntimeService(event.currentTarget.value);
  });
  document.addEventListener("click", (event) => {
    if (event.target.closest?.("[data-runtime-operations-link]")) openRuntimeOperations();
  });
  void refreshRuntimeOperations();
}

if (typeof globalThis !== "undefined") {
  globalThis.runtimeOperations = {
    state: runtimeOperationsState,
    findSchedulingResource,
    refresh: refreshRuntimeOperations,
    renderSchedulingResourceDetails,
  };
  globalThis.refreshRuntimeOperations = refreshRuntimeOperations;
  globalThis.onRuntimeOperationsVisible = () => refreshRuntimeOperations();
}

if (typeof module !== "undefined") {
  module.exports = {
    RUNTIME_ENDPOINTS,
    buildRuntimeOperationsView,
    candidateView,
    findSchedulingResource,
    loadRuntimeOperationsData,
    observedDurationSeconds,
    refreshRuntimeOperations,
    renderRuntimeCandidates,
    renderRuntimeHistory,
    renderRuntimeOperations,
    renderRuntimeOverview,
    renderRuntimePlan,
    renderSchedulingResourceDetails,
    runtimeOperationsState,
    selectRuntimeService,
    serviceRuntimeStatus,
  };
}
