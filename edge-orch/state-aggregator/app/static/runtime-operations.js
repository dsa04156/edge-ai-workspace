const RUNTIME_ENDPOINTS = Object.freeze({
  recommendations: "/api/runtime-recommendations",
  resources: "/api/resources",
  services: "/state/services",
  serviceDemo: "/state/service-demo",
});

const RUNTIME_STATES = new Set([
  "NORMAL", "OBSERVING", "AUGMENT_RECOMMENDED", "OFFLOAD_RECOMMENDED", "REPLACE_RECOMMENDED", "BLOCKED",
]);
const EXECUTION_STATUSES = new Set(["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "BLOCKED"]);
const OWNERSHIP_ACTIONS = new Set([
  "create_candidate", "verify_ready", "validate_candidate_pre_activation",
  "handoff_execution_ownership", "verify_active_candidate", "rollback_execution_ownership",
]);
const TRAFFIC_ACTIONS = new Set([
  "switch_traffic", "verify_switched_traffic", "rollback_traffic", "distribute_traffic",
]);

const runtimeOperationsState = {
  recommendations: [], resources: [], services: [], serviceDemo: null,
  selectedServiceId: null, decision: null, history: null, plan: null,
  executions: [], selectedExecutionPlanId: null, executionRecord: null, audit: null,
  dryRun: null, actionMessage: null, errors: {}, loading: false,
  mutationPending: false, loadedAt: null, pollTimer: null,
};

function runtimeEscape(value) {
  return String(value ?? "").replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
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
  return Number.isFinite(parsed) ? new Date(parsed).toLocaleString("ko-KR") : "N/A";
}
function runtimeAge(value, now = Date.now()) {
  const parsed = Date.parse(value);
  if (!Number.isFinite(parsed)) return "age N/A";
  const seconds = Math.max(0, (now - parsed) / 1000);
  if (seconds < 60) return `${seconds.toFixed(0)}초 전`;
  if (seconds < 3600) return `${(seconds / 60).toFixed(1)}분 전`;
  if (seconds < 86400) return `${(seconds / 3600).toFixed(1)}시간 전`;
  return `${(seconds / 86400).toFixed(1)}일 전`;
}
function runtimeDuration(start, end) {
  const from = Date.parse(start);
  const to = Date.parse(end);
  if (!Number.isFinite(from) || !Number.isFinite(to) || to < from) return "N/A";
  const ms = to - from;
  if (ms < 1000) return `${ms.toFixed(0)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(ms < 10000 ? 2 : 1)}s`;
  return `${(ms / 60000).toFixed(1)}min`;
}
function runtimeList(value) { return Array.isArray(value) ? value : []; }
function runtimeField(source, camel, snake = camel) {
  return source && typeof source === "object" ? source[camel] ?? source[snake] : undefined;
}
function runtimeStateTone(state) {
  return {NORMAL: "normal", OBSERVING: "observing", AUGMENT_RECOMMENDED: "augment",
    OFFLOAD_RECOMMENDED: "offload", REPLACE_RECOMMENDED: "replace", BLOCKED: "blocked"}[state] || "unknown";
}
function runtimeExecutionTone(status) {
  return {PENDING: "pending", RUNNING: "running", SUCCEEDED: "succeeded", FAILED: "failed",
    BLOCKED: "blocked", ACTIVE: "active", STANDBY: "standby", SHADOW: "shadow"}[status] || "unknown";
}
function runtimeActionLabel(action) {
  return {augment: "AUGMENT", offload: "OFFLOAD", replace: "REPLACE", none: "NO CHANGE"}[action] || "N/A";
}
function executionPlane(action) {
  if (OWNERSHIP_ACTIONS.has(action)) return "ownership";
  if (TRAFFIC_ACTIONS.has(action)) return "traffic";
  return "lifecycle";
}
function executionPlaneLabel(action) {
  return {ownership: "Execution Ownership", traffic: "Traffic Routing",
    lifecycle: "Workload Lifecycle"}[executionPlane(action)];
}
function observedDurationSeconds(decision = {}) {
  const dwell = decision.dwell || {};
  const values = decision.state === "REPLACE_RECOMMENDED" ? [dwell.runtimeFailureSeconds]
    : ["AUGMENT_RECOMMENDED", "OFFLOAD_RECOMMENDED"].includes(decision.state)
      ? [dwell.resourcePressureSeconds, dwell.servicePressureSeconds]
      : [dwell.resourcePressureSeconds, dwell.servicePressureSeconds,
          dwell.runtimeFailureSeconds, dwell.recoverySeconds];
  const observed = values.map(runtimeNumber).filter((value) => value !== null);
  return observed.length ? Math.max(...observed) : null;
}
function serviceRuntimeStatus(decision = {}) {
  const desired = runtimeNumber(decision.metrics?.desiredReplicas);
  const ready = runtimeNumber(decision.metrics?.readyReplicas);
  if (desired === null || ready === null) return "N/A";
  if (desired > 0 && ready >= desired) return "RUNNING";
  return desired > 0 ? "DEGRADED" : "N/A";
}
function serviceObservationFor(serviceId, services = []) {
  return runtimeList(services).find((item) => runtimeField(item, "serviceId", "service_id") === serviceId) || null;
}
function findSchedulingResource(nodeName, resources = runtimeOperationsState.resources) {
  return nodeName ? runtimeList(resources).find((item) => item?.node === nodeName) || null : null;
}
function candidateView(candidate = {}, selectedNode = null) {
  const selected = candidate.eligible === true && candidate.node === selectedNode;
  return {node: runtimeValue(candidate.node), result: selected ? "SELECTED" : candidate.eligible === true ? "ELIGIBLE" : "REJECTED",
    score: runtimeNumber(candidate.score), reasonCodes: runtimeList(candidate.reasonCodes),
    availableBefore: candidate.availableBefore || null, availableAfter: candidate.availableAfter || null,
    utilization: candidate.utilization || null, health: runtimeValue(candidate.health),
    architecture: runtimeValue(candidate.architecture), accelerator: runtimeValue(candidate.accelerator)};
}
function validationCheck(validation, name) {
  return runtimeList(validation?.checks).find((check) => check?.name === name) || null;
}
function latestValidation(record) {
  return [record?.validation, record?.activeCandidateValidation, record?.postSwitchValidation]
    .filter(Boolean).sort((a, b) => Date.parse(b.observedAt || b.completedAt || 0) - Date.parse(a.observedAt || a.completedAt || 0))[0] || null;
}
function candidateExecutionMode(record) {
  if (!record?.candidateCreated) return "N/A";
  if (record.executionOwnership?.activeOwner === "candidate" && !record.executionOwnership?.rolledBackAt) return "ACTIVE";
  if (record.executionOwnership?.rolledBackAt) return "STANDBY";
  const shadow = validationCheck(record.validation, "execution_shadow");
  return shadow?.measurements?.executionMode === "SHADOW" || record.validation?.status === "RUNNING" ? "SHADOW" : "STANDBY";
}
function sourceExecutionMode(serviceDemo, record) {
  const live = runtimeField(serviceDemo, "executionOwnership", "execution_ownership");
  const effective = runtimeField(live, "effectiveMode", "effective_mode");
  if (["ACTIVE", "STANDBY", "SHADOW"].includes(effective)) return effective;
  return record?.executionOwnership?.activeOwner === "candidate" ? "STANDBY" : "ACTIVE";
}
function candidatePodReady(record) {
  const check = validationCheck(latestValidation(record), "pod_ready");
  if (check?.status === "SUCCEEDED") return "READY";
  if (["FAILED", "BLOCKED"].includes(check?.status)) return "NOT READY";
  return record?.candidateReady ? "READY (이전 단계)" : record?.candidateCreated ? "관측 불가" : "N/A";
}
function currentLeaseView(serviceDemo, record) {
  const live = runtimeField(serviceDemo, "executionOwnership", "execution_ownership");
  const ownership = record?.executionOwnership;
  const persisted = ownership?.after || ownership?.before || null;
  return {
    leaseName: runtimeValue(runtimeField(live, "leaseName", "lease_name") ?? ownership?.leaseName),
    leaseNamespace: runtimeValue(runtimeField(live, "leaseNamespace", "lease_namespace") ?? ownership?.leaseNamespace),
    holderIdentity: runtimeValue(runtimeField(live, "holderIdentity", "holder_identity") ?? persisted?.holderIdentity),
    ownershipEpoch: "N/A", acquiredAt: persisted?.acquireTime || null,
    resourceVersion: runtimeValue(runtimeField(live, "resourceVersion", "resource_version") ?? persisted?.resourceVersion),
    observedAt: runtimeField(live, "observedAt", "observed_at") ?? persisted?.observedAt ?? null,
    leaseValid: runtimeField(live, "leaseValid", "lease_valid"), rollbackAvailable: ownership?.rollbackAvailable === true,
    before: ownership?.before || null, after: ownership?.after || null,
    handedOffAt: ownership?.handedOffAt || null, rolledBackAt: ownership?.rolledBackAt || null,
  };
}
function inferenceOffloadingView(serviceDemo, decision = {}) {
  const routing = runtimeField(serviceDemo, "inferenceRouting", "inference_routing") || {};
  const latest = serviceDemo?.latest || {};
  const offloading = decision.offloading || {};
  const mode = runtimeValue(
    runtimeField(routing, "inferenceMode", "inference_mode")
      ?? runtimeField(latest, "executionMode", "execution_mode")?.toUpperCase(),
  );
  const latency = (camel, snake = camel) => {
    const value = runtimeNumber(runtimeField(routing, camel, snake) ?? runtimeField(latest, camel, snake));
    return value === null ? "N/A" : `${value.toFixed(2)} ms`;
  };
  return {
    mode,
    state: runtimeValue(offloading.state),
    remoteTarget: runtimeValue(
      offloading.targetNode
        ?? runtimeField(routing, "remoteNode", "remote_node")
        ?? runtimeField(latest, "remoteNode", "remote_node"),
    ),
    targetWorkload: runtimeValue(offloading.targetWorkload),
    remoteReady: runtimeField(routing, "remoteReady", "remote_ready") ?? offloading.targetReady,
    localLatency: latency("localLatencyMs", "local_latency_ms"),
    networkLatency: latency("networkLatencyMs", "network_latency_ms"),
    remoteProcessing: latency("remoteProcessingMs", "remote_processing_ms"),
    totalLatency: latency("totalLatencyMs", "total_latency_ms"),
    successRate: runtimeRatio(runtimeField(routing, "offloadSuccessRate", "offload_success_rate")),
    fallbackCount: runtimeNumber(runtimeField(routing, "fallbackCount", "fallback_count")),
    reasonCode: runtimeValue(
      runtimeField(routing, "lastReasonCode", "last_reason_code")
        ?? runtimeField(latest, "reasonCode", "reason_code")
        ?? runtimeList(offloading.reasonCodes)[0],
    ),
    observedAt: runtimeField(routing, "observedAt", "observed_at") ?? serviceDemo?.generated_at,
  };
}
function workloadObservation(record, role, serviceDemo, status) {
  const validations = [record?.postSwitchValidation, record?.activeCandidateValidation, record?.validation]
    .filter(Boolean).sort((a, b) => Date.parse(b.observedAt || 0) - Date.parse(a.observedAt || 0));
  const observations = validations.map((validation) => role === "source" ? validation?.source : validation?.candidate).filter(Boolean);
  const observed = observations[0];
  const observedMetric = (field) => observations.find((item) => item?.[field] !== null && item?.[field] !== undefined)?.[field];
  const liveOwnership = runtimeField(serviceDemo, "executionOwnership", "execution_ownership");
  const mode = role === "source" ? sourceExecutionMode(serviceDemo, record) : candidateExecutionMode(record);
  const source = role === "source";
  const node = source ? observed?.node || serviceDemo?.binding?.node || record?.plan?.currentNodes?.[0]
    : observed?.node || record?.candidateWorkload?.targetNode || record?.plan?.selectedNode;
  const currentName = runtimeList(record?.plan?.steps).flatMap((step) => runtimeList(step.targets))
    .find((target) => target.workload?.role === "current")?.workload?.name;
  const observedAt = source ? runtimeField(liveOwnership, "observedAt", "observed_at") || serviceDemo?.generated_at || observed?.observedAt
    : observed?.observedAt || validations[0]?.observedAt || record?.updatedAt;
  const latestInferenceAt = source ? runtimeField(serviceDemo?.latest, "observedAt", "observed_at")
    : observedMetric("resultObservedAt");
  const rolledBack = Boolean(record?.executionOwnership?.rolledBackAt);
  return {role, title: source ? "Source" : "Candidate", node: runtimeValue(node),
    workload: runtimeValue(source ? currentName || "sensor-anomaly-demo" : record?.candidateWorkload?.name),
    pod: runtimeValue(observed?.pod), podReady: source ? (status === "RUNNING" ? "READY" : status === "DEGRADED" ? "NOT READY" : "N/A") : candidatePodReady(record),
    mode, lease: mode === "ACTIVE" ? "Lease Holder" : "-",
    inputState: runtimeValue(source ? serviceDemo?.input_state ?? observed?.inputState : observed?.inputState),
    modelState: runtimeValue(source ? serviceDemo?.model_state ?? observed?.modelState : observed?.modelState),
    latency: runtimeNumber(source ? runtimeField(serviceDemo?.performance, "processingLatencyP95Ms", "processing_latency_p95_ms") ?? observedMetric("latencyMs") : observedMetric("latencyMs")),
    framesProcessed: runtimeNumber(source ? runtimeField(serviceDemo?.counters, "framesProcessed", "frames_processed") ?? observedMetric("framesProcessed") : observedMetric("framesProcessed")),
    dbWriteCount: runtimeNumber(source ? runtimeField(serviceDemo?.storage, "resultCount", "result_count") ?? observedMetric("dbWriteCount") : observedMetric("dbWriteCount")),
    latestInferenceAt,
    observedAt, exists: source || record?.candidateCreated === true,
    shadowNote: mode === "SHADOW" ? "검증 중 / production 결과 미반영" : null,
    preservedNote: !source && rolledBack ? "rollback 후 workload 보존 · 삭제되지 않음" : null};
}
function mergeExecutionSteps(plan, record) {
  const states = new Map(runtimeList(record?.steps).map((step) => [step.stepId, step]));
  return runtimeList(plan?.steps).map((step) => {
    const state = states.get(step.stepId) || runtimeList(record?.steps).find((item) => item.action === step.action);
    return {...step, status: EXECUTION_STATUSES.has(state?.status) ? state.status : "PENDING",
      stateReasonCodes: runtimeList(state?.reasonCodes), startedAt: state?.startedAt || null,
      completedAt: state?.completedAt || null, plane: executionPlane(step.action), planeLabel: executionPlaneLabel(step.action)};
  });
}
function firstActiveInferenceAt(audit = []) {
  for (const event of runtimeList(audit)) {
    if (event.eventType === "active_candidate_validation_observed"
      && validationCheck(event.details?.validation, "processing_counter_increased")?.status === "SUCCEEDED") return event.recordedAt;
  }
  return null;
}
function calculateExecutionDurations(record, audit = []) {
  const step = (action) => runtimeList(record?.steps).find((item) => item.action === action) || {};
  const auditAt = (eventType) => runtimeList(audit).find((event) => event.eventType === eventType)?.recordedAt;
  return [
    {label: "승인 → Candidate Ready", value: runtimeDuration(record?.approvedAt, step("verify_ready").completedAt)},
    {label: "Pre-validation", value: runtimeDuration(step("validate_candidate_pre_activation").startedAt, step("validate_candidate_pre_activation").completedAt)},
    {label: "Lease handoff", value: runtimeDuration(step("handoff_execution_ownership").startedAt, step("handoff_execution_ownership").completedAt)},
    {label: "Candidate inference 재개", value: runtimeDuration(record?.executionOwnership?.handedOffAt, firstActiveInferenceAt(audit))},
    {label: "Lease rollback", value: runtimeDuration(step("rollback_execution_ownership").startedAt, step("rollback_execution_ownership").completedAt)},
    {label: "Source ACTIVE 복구", value: runtimeDuration(step("rollback_execution_ownership").startedAt, auditAt("execution_ownership_restored_to_source"))},
    {label: "Traffic rollback", value: runtimeDuration(step("rollback_traffic").startedAt, step("rollback_traffic").completedAt)},
  ];
}
function runtimeTimeline(history = [], audit = [], record = null) {
  const decisions = runtimeList(history).map((entry) => ({kind: "decision", at: entry.recordedAt,
    label: entry.state === "REPLACE_RECOMMENDED" ? "REPLACE_RECOMMENDED" : entry.state === "OBSERVING" ? "문제 감지" : runtimeValue(entry.state), status: entry.state,
    trigger: `${runtimeValue(entry.previousState)} → ${runtimeValue(entry.state)}`,
    reasonCodes: runtimeList(entry.decision?.reasonCodes), sourceNode: runtimeList(entry.decision?.currentNodes).join(", ") || "N/A",
    candidateNode: runtimeValue(entry.decision?.recommendation?.selectedNode)}));
  const labels = {approval_received: "승인", execution_ownership_handed_off: "Lease handoff",
    execution_ownership_rollback_started: "rollback 시작", execution_ownership_restored_to_source: "Source ACTIVE 복구",
    execution_ownership_rollback_succeeded: "rollback 완료", traffic_switched: "Traffic 전환",
    traffic_rollback_started: "Traffic rollback 시작", traffic_rollback_succeeded: "Traffic rollback 완료",
    traffic_rollback_failed: "Traffic rollback 실패"};
  const firstInference = firstActiveInferenceAt(audit);
  const executions = runtimeList(audit).filter((event) => labels[event.eventType] || event.recordedAt === firstInference)
    .map((event) => ({kind: "execution", at: event.recordedAt,
      label: event.recordedAt === firstInference ? "Candidate ACTIVE" : labels[event.eventType],
      status: event.status, trigger: event.stepId || event.eventType, reasonCodes: runtimeList(event.reasonCodes), actor: event.actor,
      sourceNode: runtimeValue(event.details?.validation?.source?.node), candidateNode: runtimeValue(event.details?.validation?.candidate?.node)}));
  const auditTypes = new Set(runtimeList(audit).map((event) => event.eventType));
  const steps = runtimeList(record?.steps);
  const milestone = (action, label, status = "SUCCEEDED") => {
    const step = steps.find((item) => item.action === action);
    if (!step || step.status !== status || !step.completedAt) return null;
    return {kind: "execution", at: step.completedAt, label, status: step.status, trigger: step.stepId,
      reasonCodes: runtimeList(step.reasonCodes), sourceNode: "N/A", candidateNode: runtimeValue(record?.candidateWorkload?.targetNode)};
  };
  const derived = [milestone("verify_ready", "Candidate Ready"),
    milestone("validate_candidate_pre_activation", "Pre-validation 완료"),
    !auditTypes.has("execution_ownership_handed_off") ? milestone("handoff_execution_ownership", "Lease handoff") : null,
    milestone("verify_active_candidate", "Candidate 장애", "FAILED")].filter(Boolean);
  const sorted = [...decisions, ...executions, ...derived].filter((event) => Number.isFinite(Date.parse(event.at)))
    .sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  return sorted.map((event, index) => ({...event, durationFromPrevious: index ? runtimeDuration(sorted[index - 1].at, event.at) : "N/A"}));
}

function buildRuntimeOperationsView({decision, history, plan, resources, services, serviceDemo,
  executions, executionRecord, audit, dryRun, actionMessage, errors = {}} = {}) {
  if (!decision) {
    return {available: false, serviceId: runtimeValue(runtimeOperationsState.selectedServiceId), state: "N/A", tone: "unknown",
      status: "N/A", statusTone: "unknown", currentNodes: [], currentNode: "N/A", activeNode: "N/A",
      inputState: "N/A", modelState: "N/A", reasonCodes: [], observedDuration: null,
      metrics: {cpu: "N/A", memory: "N/A", gpu: "N/A", latency: "N/A", backlog: "N/A"},
      currentScheduling: {cpu: "N/A", memory: "N/A", accelerator: "N/A"}, action: "N/A", selectedNode: "N/A",
      selectedScore: null, candidates: [], plan: null, currentPlan: null, planSteps: [], history: [],
      offloading: inferenceOffloadingView(null),
      executions: runtimeList(executions), executionRecord: executionRecord || null, audit: runtimeList(audit?.items || audit),
      timeline: runtimeTimeline([], audit?.items || audit, executionRecord), dryRun: dryRun || null, actionMessage, errors};
  }
  const serviceId = runtimeValue(decision.serviceId);
  const service = serviceObservationFor(serviceId, services);
  const currentNodes = runtimeList(decision.currentNodes);
  const currentResource = findSchedulingResource(currentNodes[0], resources);
  const selectedNode = decision.recommendation?.selectedNode || decision.placement?.selectedNode || null;
  const status = serviceRuntimeStatus(decision);
  const demo = serviceId === "sensor-anomaly-demo" ? serviceDemo : null;
  const recordPlan = executionRecord?.plan || plan;
  const ownership = currentLeaseView(demo, executionRecord);
  const source = workloadObservation(executionRecord, "source", demo, status);
  const candidate = workloadObservation(executionRecord, "candidate", demo, status);
  const rollbackStep = runtimeList(executionRecord?.steps).find((step) => step.action === "rollback_execution_ownership");
  const rollback = {failureDetected: executionRecord?.activeCandidateValidation?.status === "FAILED",
    started: Boolean(rollbackStep?.startedAt), succeeded: rollbackStep?.status === "SUCCEEDED",
    sourceRestored: Boolean(executionRecord?.executionOwnership?.rolledBackAt) && source.mode === "ACTIVE"};
  const activeNode = source.mode === "ACTIVE" ? source.node : candidate.mode === "ACTIVE" ? candidate.node : currentNodes[0] || "N/A";
  return {available: true, serviceId, workload: `${runtimeValue(decision.namespace)}/${runtimeValue(decision.workloadName)}`,
    workloadKind: runtimeValue(decision.workloadKind), state: RUNTIME_STATES.has(decision.state) ? decision.state : "N/A",
    tone: runtimeStateTone(decision.state), status, statusTone: status === "RUNNING" ? "running" : status === "DEGRADED" ? "degraded" : "unknown",
    currentNodes, currentNode: currentNodes.join(", ") || "N/A", activeNode, currentHealth: runtimeValue(currentResource?.health),
    inputState: runtimeValue(runtimeField(service, "inputState", "input_state") ?? demo?.input_state),
    modelState: runtimeValue(runtimeField(service, "modelState", "model_state") ?? demo?.model_state),
    reasonCodes: runtimeList(decision.reasonCodes), observedDuration: observedDurationSeconds(decision),
    cooldownRemainingSeconds: runtimeNumber(decision.cooldownRemainingSeconds),
    metrics: {cpu: runtimeRatio(decision.metrics?.cpuRatio), memory: runtimeRatio(decision.metrics?.memoryRatio),
      gpu: runtimeRatio(currentResource?.utilization?.gpuRatio),
      latency: runtimeNumber(decision.metrics?.latencyP95Ms) === null ? "N/A" : `${Number(decision.metrics.latencyP95Ms).toFixed(0)} ms`,
      backlog: runtimeNumber(decision.metrics?.backlog) === null ? "N/A" : `${Number(decision.metrics.backlog)}건`,
      throughput: runtimeNumber(decision.metrics?.throughputPerSecond) === null ? "N/A" : `${Number(decision.metrics.throughputPerSecond).toFixed(2)} /s`},
    currentScheduling: {cpu: runtimeNumber(currentResource?.available?.cpuCores) === null ? "N/A" : `${Number(currentResource.available.cpuCores).toFixed(2)} cores available`,
      memory: runtimeBytesToGb(currentResource?.available?.memoryBytes), accelerator: runtimeValue(currentResource?.accelerator)},
    action: runtimeActionLabel(decision.recommendation?.action), selectedNode: runtimeValue(selectedNode),
    selectedScore: runtimeNumber(decision.recommendation?.selectedScore ?? decision.placement?.selectedScore),
    candidates: runtimeList(decision.placement?.candidates).map((item) => candidateView(item, selectedNode)),
    placementStatus: runtimeValue(decision.placement?.status), placementReasons: runtimeList(decision.placement?.reasonCodes),
    plan: recordPlan || null, currentPlan: plan || null, planSteps: mergeExecutionSteps(recordPlan, executionRecord),
    history: runtimeList(history?.items), executions: runtimeList(executions), executionRecord: executionRecord || null,
    executionStatus: runtimeValue(executionRecord?.status, "실행 기록 없음"), audit: runtimeList(audit?.items || audit),
    timeline: runtimeTimeline(history?.items, audit?.items || audit, executionRecord), durations: calculateExecutionDurations(executionRecord, audit?.items || audit),
    ownership, source, candidate, validation: executionRecord?.validation || null,
    offloading: inferenceOffloadingView(demo, decision),
    activeValidation: executionRecord?.activeCandidateValidation || null,
    postSwitchValidation: executionRecord?.postSwitchValidation || null, routing: executionRecord?.routing || null,
    candidateExists: executionRecord?.candidateCreated === true, rollback,
    executionInProgress: ["PENDING", "RUNNING"].includes(executionRecord?.status), dryRun: dryRun || null, actionMessage,
    observedAt: decision.observedAt, observationSource: runtimeValue(decision.observationSource),
    observationScope: runtimeValue(decision.observationScope), errors};
}

function renderReasonCodes(codes = [], emptyText = "판단 근거 데이터 없음") {
  return codes.length ? codes.map((code) => `<li><code>${runtimeEscape(code)}</code></li>`).join("")
    : `<li class="runtime-empty-reason">${runtimeEscape(emptyText)}</li>`;
}
function renderInferenceOffloading(view) {
  const offload = view.offloading || inferenceOffloadingView(null);
  const ready = offload.remoteReady === true ? "READY" : offload.remoteReady === false ? "NOT READY" : "N/A";
  return `<section class="runtime-offload-summary" data-mode="${runtimeEscape(offload.mode.toLowerCase())}">
    <div class="runtime-offload-head"><div><span>Inference Execution</span><h4>부분 오프로딩 경로</h4></div><strong>${runtimeEscape(offload.mode)}</strong></div>
    <p>Lease는 ACTIVE workload를, Offload는 그 workload 내부의 inference 실행 위치를 결정합니다. 원본 Pod와 production DB 기록 권한은 ACTIVE 쪽에 유지됩니다.</p>
    <dl><div><dt>Remote Target</dt><dd>${runtimeEscape(offload.remoteTarget)}</dd></div><div><dt>Remote Service</dt><dd>${runtimeEscape(offload.targetWorkload)}</dd></div>
    <div><dt>Remote Ready</dt><dd>${runtimeEscape(ready)}</dd></div><div><dt>Policy State</dt><dd>${runtimeEscape(offload.state)}</dd></div>
    <div><dt>Local latency</dt><dd>${runtimeEscape(offload.localLatency)}</dd></div><div><dt>Network latency</dt><dd>${runtimeEscape(offload.networkLatency)}</dd></div>
    <div><dt>Remote processing</dt><dd>${runtimeEscape(offload.remoteProcessing)}</dd></div><div><dt>Total latency</dt><dd>${runtimeEscape(offload.totalLatency)}</dd></div>
    <div><dt>Offload 성공률</dt><dd>${runtimeEscape(offload.successRate)}</dd></div><div><dt>Fallback 횟수</dt><dd>${offload.fallbackCount === null ? "N/A" : runtimeEscape(offload.fallbackCount)}</dd></div>
    <div><dt>최근 reason</dt><dd><code>${runtimeEscape(offload.reasonCode)}</code></dd></div><div><dt>관측</dt><dd>${runtimeEscape(runtimeDate(offload.observedAt))} · ${runtimeEscape(runtimeAge(offload.observedAt))}</dd></div></dl>
    ${offload.mode === "LOCAL_FALLBACK" ? `<p class="runtime-offload-warning">Remote 실패 후 ACTIVE workload가 Local inference로 production 처리를 계속하고 있습니다.</p>` : ""}</section>`;
}
function renderRuntimeCandidates(view) {
  if (!view.candidates.length) return `<div class="runtime-section-empty">배치 후보 데이터 없음</div>`;
  const rows = view.candidates.map((candidate) => {
    const available = candidate.availableAfter || candidate.availableBefore;
    const cpu = runtimeNumber(available?.cpuCores);
    const memory = runtimeNumber(available?.memoryBytes);
    return `<tr data-result="${runtimeEscape(candidate.result.toLowerCase())}">
      <td><strong>${runtimeEscape(candidate.node)}</strong><small>${runtimeEscape(candidate.health)}</small></td>
      <td>${runtimeEscape(candidate.architecture)}</td>
      <td>${cpu === null ? "N/A" : `${runtimeEscape(cpu.toFixed(2))} cores`}</td>
      <td>${memory === null ? "N/A" : runtimeBytesToGb(memory)}</td>
      <td>CPU ${runtimeEscape(runtimeRatio(candidate.utilization?.cpuRatio))}<small>Memory ${runtimeEscape(runtimeRatio(candidate.utilization?.memoryRatio))}</small></td>
      <td>${runtimeEscape(candidate.accelerator)}</td><td>${candidate.score === null ? "-" : runtimeEscape(candidate.score.toFixed(2))}</td>
      <td><span class="runtime-result-badge" data-result="${runtimeEscape(candidate.result.toLowerCase())}">${runtimeEscape(candidate.result)}</span></td>
      <td><code>${runtimeEscape(candidate.reasonCodes.join(", ") || "데이터 없음")}</code></td></tr>`;
  }).join("");
  return `<div class="runtime-table-wrap" role="region" aria-label="배치 후보 비교" tabindex="0"><table class="runtime-candidate-table">
    <thead><tr><th>Node</th><th>Architecture</th><th>Scheduling CPU</th><th>Scheduling Memory</th><th>Utilization</th><th>Accelerator</th><th>Score</th><th>Eligible</th><th>Reason</th></tr></thead><tbody>${rows}</tbody></table></div>`;
}
function renderConditionList(conditions = []) {
  return runtimeList(conditions).length ? runtimeList(conditions).map((condition) =>
    `<li><code>${runtimeEscape(condition.code)}</code><span>${runtimeEscape(condition.description)}</span></li>`).join("") : "<li>N/A</li>";
}
function renderRuntimePlan(plan, stepsOverride = null) {
  if (!plan) return `<div class="runtime-section-empty">Execution Plan 데이터 없음</div>`;
  const steps = runtimeList(stepsOverride || plan.steps);
  if (!steps.length) return `<div class="runtime-section-empty"><strong>${runtimeEscape(runtimeValue(plan.status, "계획 없음"))}</strong><span>${runtimeEscape(runtimeList(plan.reasonCodes).join(", ") || "실행 단계 데이터 없음")}</span></div>`;
  return `<ol class="runtime-plan-steps">${steps.map((step) => {
    const targets = runtimeList(step.targets).map((target) => `${runtimeValue(target.node)} · ${runtimeValue(target.workload?.namespace)}/${runtimeValue(target.workload?.name)} (${runtimeValue(target.workload?.role)})`).join(" / ") || "N/A";
    const status = EXECUTION_STATUSES.has(step.status) ? step.status : "PENDING";
    return `<li data-mode="${runtimeEscape(runtimeValue(step.executionMode))}" data-action="${runtimeEscape(runtimeValue(step.action))}" data-plane="${runtimeEscape(executionPlane(step.action))}">
      <span class="runtime-plan-index">${runtimeEscape(runtimeValue(step.sequence))}</span><div class="runtime-plan-step-body">
      <div class="runtime-plan-step-title"><div><small>${runtimeEscape(step.planeLabel || executionPlaneLabel(step.action))}${step.action === "switch_traffic" ? " · 필요 시" : ""}</small><strong>${runtimeEscape(runtimeValue(step.action))}</strong></div>
      <span class="runtime-step-status" data-status="${runtimeEscape(runtimeExecutionTone(status))}">${runtimeEscape(status)}</span></div>
      ${step.executionMode === "on_failure" ? `<span class="runtime-compensation-label">실패 시 보상 단계</span>` : ""}
      <p>${runtimeEscape(targets)}</p>${runtimeList(step.stateReasonCodes).length ? `<p class="runtime-step-reasons"><code>${runtimeEscape(step.stateReasonCodes.join(", "))}</code></p>` : ""}
      <p class="runtime-step-time">${runtimeEscape(runtimeDate(step.startedAt))} → ${runtimeEscape(runtimeDate(step.completedAt))} · ${runtimeEscape(runtimeDuration(step.startedAt, step.completedAt))}</p>
      <details><summary>선행조건·실패조건</summary><div class="runtime-plan-conditions"><section><strong>선행조건</strong><ul>${renderConditionList(step.prerequisites)}</ul></section>
      <section><strong>실패조건</strong><ul>${renderConditionList(step.failureConditions)}</ul></section></div></details></div></li>`;
  }).join("")}</ol>`;
}
function renderWorkloadCard(workload) {
  if (!workload?.exists) return `<article class="runtime-workload-card"><div class="runtime-section-empty"><strong>Candidate 없음</strong><span>승인된 execution에서 생성된 candidate 기록이 없습니다.</span></div></article>`;
  return `<article class="runtime-workload-card" data-role="${runtimeEscape(workload.role)}" data-mode="${runtimeEscape(runtimeExecutionTone(workload.mode))}">
    <header><div><span>${runtimeEscape(workload.title)}</span><strong>${runtimeEscape(workload.node)}</strong></div><span class="runtime-state-badge" data-state="${runtimeEscape(runtimeExecutionTone(workload.mode))}">${runtimeEscape(workload.mode)}</span></header>
    <dl><div><dt>Workload</dt><dd>${runtimeEscape(workload.workload)}</dd></div><div><dt>Pod</dt><dd>${runtimeEscape(workload.pod)}</dd></div>
    <div><dt>Pod Ready</dt><dd>${runtimeEscape(workload.podReady)}</dd></div><div><dt>Lease</dt><dd>${runtimeEscape(workload.lease)}</dd></div>
    <div><dt>Input / Model</dt><dd>${runtimeEscape(workload.inputState)} / ${runtimeEscape(workload.modelState)}</dd></div>
    <div><dt>Latency</dt><dd>${workload.latency === null ? "N/A" : `${runtimeEscape(workload.latency.toFixed(1))} ms`}</dd></div>
    <div><dt>framesProcessed</dt><dd>${workload.framesProcessed === null ? "N/A" : runtimeEscape(workload.framesProcessed)}</dd></div>
    <div><dt>DB write count</dt><dd>${workload.dbWriteCount === null ? "N/A" : runtimeEscape(workload.dbWriteCount)}</dd></div>
    <div><dt>최근 inference</dt><dd>${runtimeEscape(runtimeDate(workload.latestInferenceAt))}<small>${runtimeEscape(runtimeAge(workload.latestInferenceAt))}</small></dd></div>
    <div><dt>상태 관측</dt><dd>${runtimeEscape(runtimeDate(workload.observedAt))}<small>${runtimeEscape(runtimeAge(workload.observedAt))}</small></dd></div></dl>
    ${workload.shadowNote ? `<p class="runtime-shadow-note">${runtimeEscape(workload.shadowNote)}</p>` : ""}
    ${workload.preservedNote ? `<p class="runtime-preserved-note">${runtimeEscape(workload.preservedNote)}</p>` : ""}</article>`;
}
function renderOwnership(view) {
  const lease = view.ownership || {};
  const holderWorkload = view.source?.mode === "ACTIVE" ? view.source : view.candidate?.mode === "ACTIVE" ? view.candidate : null;
  const holderObserved = lease.holderIdentity && lease.holderIdentity !== "N/A";
  const rollback = view.rollback || {};
  const rollbackFlow = (rollback.started || rollback.failureDetected) ? `<div class="runtime-rollback-flow" aria-label="Candidate 장애와 Lease rollback 흐름">
    <span data-state="${view.candidate?.mode === "ACTIVE" ? "current" : "complete"}">Candidate ACTIVE</span><i>→</i>
    <span data-state="${rollback.failureDetected ? "failed" : "pending"}">failure detected</span><i>→</i>
    <span data-state="${rollback.succeeded ? "complete" : rollback.started ? "current" : "pending"}">Lease rollback</span><i>→</i>
    <span data-state="${rollback.sourceRestored ? "complete" : "pending"}">Source ACTIVE</span></div>` : "";
  return `<section class="runtime-lease-holder-hero" data-state="${runtimeEscape(holderObserved ? runtimeExecutionTone(holderWorkload?.mode) : "unknown")}">
    <span>CURRENT LEASE HOLDER</span><strong>${runtimeEscape(lease.holderIdentity)}</strong>
    <small>${runtimeEscape(holderWorkload?.node || "소유 workload 관측 불가")} · ${runtimeEscape(holderWorkload?.title || "N/A")} ${runtimeEscape(holderWorkload?.mode || "N/A")}</small></section>
    <div class="runtime-execution-route"><div class="runtime-sensor-node"><span>INPUT</span><strong>Sensor</strong><small>${runtimeEscape(view.inputState)} · production frame</small></div><i class="runtime-route-arrow" aria-hidden="true">→</i>
    ${renderWorkloadCard(view.source)}
    <div class="runtime-ownership-arrow"><span>Lease Handoff</span><strong>${runtimeEscape(view.source?.mode)} → ${runtimeEscape(view.candidate?.mode)}</strong><small>${runtimeEscape(lease.holderIdentity)}</small></div>
    ${renderWorkloadCard(view.candidate)}</div>${rollbackFlow}
    <section class="runtime-lease"><div><span>Execution Ownership</span><h4>Kubernetes Lease</h4><p>누가 실제 polling·inference·production 결과 처리를 수행하는지 결정합니다.</p></div>
    <dl><div><dt>leaseName</dt><dd>${runtimeEscape(lease.leaseName)}</dd></div><div><dt>holderIdentity</dt><dd>${runtimeEscape(lease.holderIdentity)}</dd></div>
    <div><dt>ownershipEpoch</dt><dd>${runtimeEscape(lease.ownershipEpoch)} <small>API 필드 없음</small></dd></div><div><dt>acquiredAt</dt><dd>${runtimeEscape(runtimeDate(lease.acquiredAt))}</dd></div>
    <div><dt>resourceVersion</dt><dd>${runtimeEscape(lease.resourceVersion)}</dd></div><div><dt>Lease valid</dt><dd>${lease.leaseValid === true ? "true" : lease.leaseValid === false ? "false" : "N/A"}</dd></div>
    <div><dt>rollback 가능</dt><dd>${lease.rollbackAvailable ? "가능" : "N/A"}</dd></div><div><dt>관측</dt><dd>${runtimeEscape(runtimeDate(lease.observedAt))} · ${runtimeEscape(runtimeAge(lease.observedAt))}</dd></div></dl>
    ${(lease.before || lease.after) ? `<p class="runtime-handoff-summary">Before <strong>${runtimeEscape(runtimeValue(lease.before?.holderIdentity))}</strong> → After <strong>${runtimeEscape(runtimeValue(lease.after?.holderIdentity))}</strong>${lease.rolledBackAt ? ` · rollback ${runtimeEscape(runtimeDate(lease.rolledBackAt))}` : ""}</p>` : ""}</section>`;
}

function renderValidationBlock(title, validation) {
  if (!validation) return `<section class="runtime-validation-block"><header><strong>${runtimeEscape(title)}</strong><span>N/A</span></header><div class="runtime-section-empty">검증 기록 없음</div></section>`;
  return `<section class="runtime-validation-block"><header><strong>${runtimeEscape(title)}</strong><span class="runtime-step-status" data-status="${runtimeEscape(runtimeExecutionTone(validation.status))}">${runtimeEscape(runtimeValue(validation.status))}</span></header>
    <p>${runtimeEscape(runtimeDate(validation.observedAt))} · 안정 ${runtimeEscape(runtimeValue(validation.minimumStableSeconds))}s · 연속 ${runtimeEscape(runtimeValue(validation.consecutiveSuccesses))}/${runtimeEscape(runtimeValue(validation.requiredConsecutiveSuccesses))}</p>
    <ul>${runtimeList(validation.checks).map((check) => `<li><span>${runtimeEscape(check.name)}</span><strong data-status="${runtimeEscape(runtimeExecutionTone(check.status))}">${runtimeEscape(check.status)}</strong><code>${runtimeEscape(runtimeList(check.reasonCodes).join(", ") || "-")}</code></li>`).join("")}</ul></section>`;
}
function renderTraffic(view) {
  const routing = view.routing;
  return `<section class="runtime-traffic-summary"><div><span>Traffic Routing</span><h4>요청 전달 경로</h4><p>Lease와 별개입니다. polling workload는 Lease handoff만으로 실행 권한 전환이 완료될 수 있습니다.</p></div>
    <dl class="runtime-routing-support"><div data-support="verified"><dt>runtime-endpoints</dt><dd>VERIFIED</dd><small>EdgeMesh source → candidate → source 실클러스터 검증</small></div>
    <div data-support="blocked"><dt>runtime-endpointslice</dt><dd>BLOCKED</dd><small>EdgeMesh 호환성 미검증 · routing_mode_unsupported</small></div></dl>
    <dl class="runtime-routing-record"><div><dt>실행 기록 mode</dt><dd>${runtimeEscape(runtimeValue(routing?.mode))}</dd></div><div><dt>activeTarget</dt><dd>${runtimeEscape(runtimeValue(routing?.activeTarget))}</dd></div>
    <div><dt>switchedAt</dt><dd>${runtimeEscape(runtimeDate(routing?.switchedAt))}</dd></div><div><dt>rolledBackAt</dt><dd>${runtimeEscape(runtimeDate(routing?.rolledBackAt))}</dd></div></dl></section>`;
}
function renderExecutionSelector(view) {
  if (!view.executions?.length) return `<span>실행 기록 없음</span>`;
  return `<label class="runtime-execution-selector">실행 기록<select id="runtimeExecutionSelect" aria-label="Runtime execution 기록 선택">
    ${view.executions.map((record) => `<option value="${runtimeEscape(record.planId)}"${record.planId === view.executionRecord?.planId ? " selected" : ""}>${runtimeEscape(record.status)} · ${runtimeEscape(runtimeDate(record.updatedAt))} · ${runtimeEscape(record.planId)}</option>`).join("")}</select></label>`;
}
function renderDryRun(dryRun) {
  if (!dryRun) return `<div class="runtime-section-empty">Dry Run을 실행하면 template·storage·node preflight와 지원 단계가 표시됩니다.</div>`;
  return `<div class="runtime-dry-run-result" data-status="${runtimeEscape(dryRun.status)}"><header><strong>Preflight ${runtimeEscape(String(dryRun.status).toUpperCase())}</strong><span>${runtimeEscape(runtimeDate(dryRun.generatedAt))}</span></header>
    <p><code>${runtimeEscape(runtimeList(dryRun.reasonCodes).join(", ") || "preflight_passed")}</code></p><ul>${runtimeList(dryRun.steps).map((step) =>
      `<li><span>${runtimeEscape(step.action)}</span><strong>${step.supported ? "SUPPORTED" : "UNSUPPORTED"}</strong><code>${runtimeEscape(runtimeList(step.reasonCodes).join(", ") || "-")}</code></li>`).join("")}</ul></div>`;
}
function runtimeSecureExecutionContext(root = globalThis) {
  return root?.isSecureContext === true && root?.location?.protocol === "https:";
}
function renderExecutionControls(view, secureContext = runtimeSecureExecutionContext()) {
  const plan = view.currentPlan;
  const actionable = plan?.status === "planned";
  const preflightAllowed = view.dryRun?.planId === plan?.planId && view.dryRun?.status !== "blocked";
  return `<form class="runtime-execution-controls" data-plan-id="${runtimeEscape(runtimeValue(plan?.planId, ""))}" novalidate>
    <div class="runtime-execution-control-head"><div><span>Explicit approval</span><h4>Dry Run → 승인 → Execute</h4></div><span>${secureContext ? "HTTPS" : "READ-ONLY / insecure context"}</span></div>
    <p>추천만으로 자동 실행하지 않습니다. 공유 토큰은 입력 즉시 요청에만 사용하고 JS 코드·브라우저 저장소에 저장하지 않습니다.</p>
    <button type="button" class="runtime-control-button" data-runtime-dry-run${actionable ? "" : " disabled"}>Dry Run</button>${renderDryRun(view.dryRun)}
    <fieldset${preflightAllowed && secureContext ? "" : " disabled"}><legend>명시적 승인</legend>
    <label>승인자<input id="runtimeExecutionApprovedBy" name="approvedBy" autocomplete="name" maxlength="128" placeholder="operator identity" /></label>
    <label>일회성 Execution Token<input id="runtimeExecutionToken" name="executionToken" type="password" autocomplete="off" spellcheck="false" /></label>
    <label class="runtime-approval-check"><input id="runtimeExecutionApproved" type="checkbox" /> <span><code>${runtimeEscape(runtimeValue(plan?.planId))}</code> 실행을 명시적으로 승인합니다.</span></label>
    <button type="button" class="runtime-control-button runtime-control-button-primary" data-runtime-execute disabled>Execute</button></fieldset>
    ${!secureContext ? `<p class="runtime-control-warning">현재 origin은 신뢰 가능한 HTTPS가 아니므로 토큰 입력과 Execute를 차단했습니다. Dry Run과 상태 조회만 가능합니다.</p>` : ""}
    ${view.actionMessage ? `<p class="runtime-action-message" data-state="${runtimeEscape(view.actionMessage.state)}">${runtimeEscape(view.actionMessage.text)}</p>` : ""}</form>`;
}
function renderRuntimeHistory(items = []) {
  if (!items.length) return `<div class="runtime-section-empty">Runtime History 데이터 없음</div>`;
  return `<ol class="runtime-history-list">${items.map((entry) => { const decision = entry.decision || {}; const state = runtimeValue(entry.state);
    return `<li data-state="${runtimeEscape(runtimeStateTone(state))}"><span class="runtime-history-marker"></span><div><header><strong>${runtimeEscape(state)}</strong><time>${runtimeEscape(runtimeDate(entry.recordedAt))}</time></header>
    <dl><div><dt>trigger</dt><dd>${runtimeEscape(runtimeValue(entry.previousState))} → ${runtimeEscape(state)}</dd></div><div><dt>reason</dt><dd><code>${runtimeEscape(runtimeList(decision.reasonCodes).join(", ") || "데이터 없음")}</code></dd></div>
    <div><dt>기존 노드</dt><dd>${runtimeEscape(runtimeList(decision.currentNodes).join(", ") || "N/A")}</dd></div><div><dt>추천 노드</dt><dd>${runtimeEscape(runtimeValue(decision.recommendation?.selectedNode))}</dd></div></dl></div></li>`;
  }).join("")}</ol>`;
}
function renderAuditTimeline(view) {
  if (!view.timeline?.length) return `<div class="runtime-section-empty">Execution / Audit Timeline 데이터 없음</div>`;
  return `<ol class="runtime-audit-timeline">${view.timeline.map((event) => `<li data-status="${runtimeEscape(runtimeExecutionTone(event.status))}"><span class="runtime-history-marker"></span><div>
    <header><strong>${runtimeEscape(event.label)}</strong><time>${runtimeEscape(runtimeDate(event.at))}</time></header><p>${runtimeEscape(event.trigger)} · 이전 이벤트부터 <strong>${runtimeEscape(event.durationFromPrevious)}</strong></p>
    <dl><div><dt>reason</dt><dd><code>${runtimeEscape(event.reasonCodes.join(", ") || "-")}</code></dd></div><div><dt>source</dt><dd>${runtimeEscape(event.sourceNode || "N/A")}</dd></div><div><dt>candidate</dt><dd>${runtimeEscape(event.candidateNode || "N/A")}</dd></div></dl></div></li>`).join("")}</ol>`;
}

function renderRuntimeOperations(view, documentRef = document) {
  const content = documentRef.getElementById("runtimeOperationsContent");
  const notice = documentRef.getElementById("runtimeOperationsAvailability");
  if (!content || !notice) return view;
  notice.dataset.state = view.available ? view.tone : "unknown";
  notice.textContent = view.available ? `${view.serviceId} · ${view.state} · ACTIVE ${view.activeNode} · ${runtimeDate(view.observedAt)}`
    : `Runtime Recommendation 관측 불가${view.errors?.decision ? ` · ${view.errors.decision}` : ""}`;
  content.innerHTML = `
    <section class="panel runtime-service-panel"><div class="runtime-section-head"><div><span>Service Runtime</span><h3>${runtimeEscape(view.serviceId)}</h3></div><span class="runtime-state-badge" data-state="${runtimeEscape(view.statusTone)}">${runtimeEscape(view.status)}</span></div>
    <div class="runtime-service-grid"><dl class="runtime-fact-list"><div><dt>현재 ACTIVE 노드</dt><dd>${runtimeEscape(view.activeNode)}</dd></div><div><dt>Source 노드</dt><dd>${runtimeEscape(view.currentNode)}</dd></div><div><dt>Node Health</dt><dd>${runtimeEscape(runtimeValue(view.currentHealth))}</dd></div>
    <div><dt>Input 상태</dt><dd>${runtimeEscape(view.inputState)}</dd></div><div><dt>Model 상태</dt><dd>${runtimeEscape(view.modelState)}</dd></div><div><dt>Workload</dt><dd>${runtimeEscape(runtimeValue(view.workload))}</dd></div></dl>
    <dl class="runtime-metric-strip"><div><dt>CPU</dt><dd>${runtimeEscape(view.metrics.cpu)}</dd></div><div><dt>Memory</dt><dd>${runtimeEscape(view.metrics.memory)}</dd></div><div><dt>GPU</dt><dd>${runtimeEscape(view.metrics.gpu)}</dd></div>
    <div><dt>Latency p95</dt><dd>${runtimeEscape(view.metrics.latency)}</dd></div><div><dt>Backlog</dt><dd>${runtimeEscape(view.metrics.backlog)}</dd></div><div><dt>Throughput</dt><dd>${runtimeEscape(runtimeValue(view.metrics.throughput))}</dd></div></dl></div>
    <dl class="runtime-current-scheduling"><div><dt>Scheduling CPU</dt><dd>${runtimeEscape(view.currentScheduling.cpu)}</dd></div><div><dt>Scheduling Memory</dt><dd>${runtimeEscape(view.currentScheduling.memory)}</dd></div><div><dt>Accelerator</dt><dd>${runtimeEscape(view.currentScheduling.accelerator)}</dd></div><div><dt>근거</dt><dd>Kubernetes allocatable − Pod requests</dd></div></dl>
    <section class="runtime-decision" data-state="${runtimeEscape(view.tone)}"><div><span>Runtime Recommendation</span><strong>${runtimeEscape(view.state)}</strong></div><ul>${renderReasonCodes(view.reasonCodes)}</ul>
    <p>observed duration: <strong>${view.observedDuration === null ? "N/A" : `${runtimeEscape(view.observedDuration)}s`}</strong> · cooldown: <strong>${view.cooldownRemainingSeconds === null ? "N/A" : `${runtimeEscape(view.cooldownRemainingSeconds)}s`}</strong></p></section></section>

    <section class="panel runtime-offload-panel"><div class="runtime-section-head"><div><span>Runtime Offloading</span><h3>Local / Remote Inference</h3></div><span>${runtimeEscape(view.offloading?.state || "N/A")}</span></div>${renderInferenceOffloading(view)}</section>

    <section class="panel runtime-ownership-panel"><div class="runtime-section-head"><div><span>Runtime Orchestration</span><h3>Live Execution Demo</h3></div><span>2–5초 live polling</span></div>${renderOwnership(view)}</section>

    <section class="panel runtime-placement-panel"><div class="runtime-section-head"><div><span>Placement Evidence</span><h3>배치 추천</h3></div><span>${runtimeEscape(view.placementStatus)}</span></div>
    <div class="runtime-decision-rail"><div><span>Current</span><strong>${runtimeEscape(view.currentNode)}</strong></div><div class="runtime-decision-arrow"><span>↓</span><strong>${runtimeEscape(view.action)}</strong></div>
    <div><span>Recommended</span><strong>${runtimeEscape(view.selectedNode)}</strong><small>Score ${view.selectedScore === null ? "N/A" : runtimeEscape(view.selectedScore.toFixed(2))}</small></div></div>
    <p class="runtime-capacity-note">Scheduling capacity(allocatable − requests)와 Prometheus utilization은 별도 열입니다.</p>${renderRuntimeCandidates(view)}</section>

    <section class="panel runtime-plan-panel"><div class="runtime-section-head"><div><span>Execution Plan</span><h3>승인 기반 실행 계획</h3></div>${renderExecutionSelector(view)}</div>
    <div class="runtime-control-plane-legend"><span data-plane="ownership">Execution Ownership · 실제 AI 처리 권한</span><span data-plane="traffic">Traffic Routing · 요청 전달 대상</span><span data-plane="lifecycle">Lifecycle · workload 보존/종료</span></div>
    ${renderRuntimePlan(view.plan, view.planSteps)}${renderExecutionControls(view)}</section>

    <section class="panel runtime-validation-panel"><div class="runtime-section-head"><div><span>Validation / Routing</span><h3>검증·전환·롤백 결과</h3></div><span>${runtimeEscape(view.executionStatus)}</span></div>
    <div class="runtime-validation-grid">${renderValidationBlock("Pre-activation / SHADOW", view.validation)}${renderValidationBlock("ACTIVE Candidate", view.activeValidation)}${renderValidationBlock("Post-switch", view.postSwitchValidation)}</div>${renderTraffic(view)}</section>

    <section class="panel runtime-history-panel"><div class="runtime-section-head"><div><span>Decision Timeline</span><h3>Runtime History / Audit</h3></div><span>${runtimeEscape(view.timeline?.length || 0)} events</span></div>
    <dl class="runtime-duration-strip">${runtimeList(view.durations).map((item) => `<div><dt>${runtimeEscape(item.label)}</dt><dd>${runtimeEscape(item.value)}</dd></div>`).join("") || "<div><dt>측정</dt><dd>N/A</dd></div>"}</dl>
    ${renderAuditTimeline(view)}<details class="runtime-decision-history"><summary>Runtime Recommendation 판단 이력만 보기</summary>${renderRuntimeHistory(view.history)}</details></section>
    <p class="runtime-observation-source">관측 ${runtimeEscape(runtimeValue(view.observationSource))} · ${runtimeEscape(runtimeValue(view.observationScope))} · candidate/Lease는 persisted execution 및 service-demo API 기준 · 각 시각의 age를 확인하세요.</p>`;
  return view;
}

function renderRuntimeOverview(view, documentRef = document) {
  const set = (id, value) => { const element = documentRef.getElementById(id); if (element) element.textContent = value; return element; };
  const title = set("runtimeOverviewTitle", view.state);
  if (title) title.dataset.state = view.tone;
  set("runtimeOverviewReasons", view.reasonCodes.join(", ") || "판단 근거 데이터 없음");
  set("runtimeOverviewCurrentNode", view.activeNode || view.currentNode);
  set("runtimeOverviewCpu", view.metrics.cpu); set("runtimeOverviewMemory", view.metrics.memory);
  set("runtimeOverviewLatency", view.metrics.latency); set("runtimeOverviewSelectedNode", view.selectedNode);
  set("runtimeOverviewScore", view.selectedScore === null ? "N/A" : view.selectedScore.toFixed(2));
  set("runtimeOverviewCandidate", view.candidateExists ? `${view.candidate?.node || "N/A"} · ${view.candidate?.mode || "N/A"}` : "없음");
  set("runtimeOverviewExecution", view.executionInProgress ? `진행 중 · ${view.executionStatus}` : view.executionStatus || "실행 기록 없음");
  return view;
}
function renderSchedulingResourceDetails(resource, fallbackUsage = {}) {
  const usage = resource?.utilization || fallbackUsage || {};
  const rows = [["CPU", "cpuCores", (v) => v === null ? "N/A" : `${v.toFixed(2)} cores`], ["Memory", "memoryBytes", runtimeBytesToGb]];
  const scheduling = resource ? rows.map(([label, key, format]) => `<tr><th>${label}</th><td>${format(runtimeNumber(resource.allocatable?.[key]))}</td><td>${format(runtimeNumber(resource.requested?.[key]))}</td><td>${format(runtimeNumber(resource.available?.[key]))}</td></tr>`).join("")
    : `<tr><th>CPU</th><td>N/A</td><td>N/A</td><td>N/A</td></tr><tr><th>Memory</th><td>N/A</td><td>N/A</td><td>N/A</td></tr>`;
  const acceleratorKeys = resource ? [...new Set([...Object.keys(resource.allocatable?.acceleratorUnits || {}), ...Object.keys(resource.requested?.acceleratorUnits || {}), ...Object.keys(resource.available?.acceleratorUnits || {})])] : [];
  const gpuRows = acceleratorKeys.length ? acceleratorKeys.map((key) => `<tr><th>GPU · ${runtimeEscape(key)}</th><td>${runtimeEscape(runtimeValue(resource.allocatable?.acceleratorUnits?.[key]))}</td><td>${runtimeEscape(runtimeValue(resource.requested?.acceleratorUnits?.[key]))}</td><td>${runtimeEscape(runtimeValue(resource.available?.acceleratorUnits?.[key]))}</td></tr>`).join("")
    : `<tr><th>GPU</th><td>N/A</td><td>N/A</td><td>N/A</td></tr>`;
  return `<section class="node-resource-evidence"><div class="node-resource-usage"><strong>실사용</strong><span>Prometheus</span><dl>
    <div><dt>CPU Usage</dt><dd>${runtimeRatio(usage.cpuRatio ?? usage.cpu_utilization)}</dd></div><div><dt>Memory Usage</dt><dd>${runtimeRatio(usage.memoryRatio ?? usage.memory_usage_ratio)}</dd></div><div><dt>GPU Usage</dt><dd>${runtimeRatio(usage.gpuRatio ?? usage.gpu_utilization)}</dd></div></dl></div>
    <div class="node-scheduling-resource"><div><strong>Scheduling Resource</strong><span>Kubernetes allocatable − Pod requests</span></div><div class="node-scheduling-table-wrap"><table><thead><tr><th>Resource</th><th>Allocatable</th><th>Requested</th><th>Available</th></tr></thead><tbody>${scheduling}${gpuRows}</tbody></table></div>
    <p>${resource ? `${runtimeEscape(runtimeValue(resource.health))} · ${runtimeEscape(runtimeList(resource.reasonCodes).join(", ") || "reason 없음")}` : "Scheduling Resource 관측 불가 · /api/resources 데이터 없음"}</p></div></section>`;
}

async function runtimeFetchJson(url, fetchFn = fetch, options = {}) {
  const response = await fetchFn(url, {cache: "no-store", ...options});
  if (!response.ok) {
    let code = `HTTP ${response.status}`;
    try { const payload = await response.json(); code = payload?.detail?.code || payload?.code || code; } catch (_error) { /* status is sufficient */ }
    throw new Error(code);
  }
  return response.json();
}
function runtimeErrorMessage(error) { return error instanceof Error ? error.message : "관측 불가"; }
async function loadRuntimeOperationsData(fetchFn = fetch) {
  runtimeOperationsState.loading = true;
  const [recommendationsResult, resourcesResult, servicesResult, serviceDemoResult] = await Promise.allSettled([
    runtimeFetchJson(RUNTIME_ENDPOINTS.recommendations, fetchFn), runtimeFetchJson(RUNTIME_ENDPOINTS.resources, fetchFn),
    runtimeFetchJson(RUNTIME_ENDPOINTS.services, fetchFn), runtimeFetchJson(RUNTIME_ENDPOINTS.serviceDemo, fetchFn),
  ]);
  runtimeOperationsState.errors = {};
  runtimeOperationsState.recommendations = recommendationsResult.status === "fulfilled" ? runtimeList(recommendationsResult.value?.items) : [];
  if (recommendationsResult.status === "rejected") runtimeOperationsState.errors.recommendations = runtimeErrorMessage(recommendationsResult.reason);
  runtimeOperationsState.resources = resourcesResult.status === "fulfilled" && Array.isArray(resourcesResult.value) ? resourcesResult.value : [];
  if (resourcesResult.status === "rejected") runtimeOperationsState.errors.resources = runtimeErrorMessage(resourcesResult.reason);
  runtimeOperationsState.services = servicesResult.status === "fulfilled" ? runtimeList(servicesResult.value?.services) : [];
  if (servicesResult.status === "rejected") runtimeOperationsState.errors.services = runtimeErrorMessage(servicesResult.reason);
  runtimeOperationsState.serviceDemo = serviceDemoResult.status === "fulfilled" ? serviceDemoResult.value : null;
  const serviceIds = runtimeOperationsState.recommendations.map((item) => item?.serviceId).filter(Boolean);
  if (!serviceIds.includes(runtimeOperationsState.selectedServiceId)) runtimeOperationsState.selectedServiceId = serviceIds[0] || null;
  const serviceId = runtimeOperationsState.selectedServiceId;
  runtimeOperationsState.decision = null; runtimeOperationsState.history = null; runtimeOperationsState.plan = null;
  runtimeOperationsState.executions = []; runtimeOperationsState.executionRecord = null; runtimeOperationsState.audit = null;
  if (serviceId) {
    const encoded = encodeURIComponent(serviceId);
    const [decisionResult, historyResult, planResult, executionsResult] = await Promise.allSettled([
      runtimeFetchJson(`/api/runtime-recommendations/${encoded}`, fetchFn),
      runtimeFetchJson(`/api/runtime-recommendations/${encoded}/history?limit=50`, fetchFn),
      runtimeFetchJson(`/api/runtime-recommendations/${encoded}/execution-plan`, fetchFn),
      runtimeFetchJson(`/api/executions?serviceId=${encoded}&limit=20`, fetchFn),
    ]);
    if (decisionResult.status === "fulfilled") runtimeOperationsState.decision = decisionResult.value;
    else runtimeOperationsState.errors.decision = runtimeErrorMessage(decisionResult.reason);
    if (historyResult.status === "fulfilled") runtimeOperationsState.history = historyResult.value;
    else runtimeOperationsState.errors.history = runtimeErrorMessage(historyResult.reason);
    if (planResult.status === "fulfilled") runtimeOperationsState.plan = planResult.value;
    else runtimeOperationsState.errors.plan = runtimeErrorMessage(planResult.reason);
    if (executionsResult.status === "fulfilled") runtimeOperationsState.executions = runtimeList(executionsResult.value?.items);
    else runtimeOperationsState.errors.executions = runtimeErrorMessage(executionsResult.reason);
    const ids = runtimeOperationsState.executions.map((item) => item.planId);
    if (!ids.includes(runtimeOperationsState.selectedExecutionPlanId)) runtimeOperationsState.selectedExecutionPlanId = ids[0] || null;
    if (runtimeOperationsState.selectedExecutionPlanId) {
      const planId = encodeURIComponent(runtimeOperationsState.selectedExecutionPlanId);
      const [recordResult, auditResult] = await Promise.allSettled([
        runtimeFetchJson(`/api/execution-plans/${planId}`, fetchFn), runtimeFetchJson(`/api/execution-plans/${planId}/audit?limit=500`, fetchFn),
      ]);
      if (recordResult.status === "fulfilled") runtimeOperationsState.executionRecord = recordResult.value;
      else runtimeOperationsState.errors.executionRecord = runtimeErrorMessage(recordResult.reason);
      if (auditResult.status === "fulfilled") runtimeOperationsState.audit = auditResult.value;
      else runtimeOperationsState.errors.audit = runtimeErrorMessage(auditResult.reason);
    }
  }
  runtimeOperationsState.loading = false;
  runtimeOperationsState.loadedAt = new Date().toISOString();
  return runtimeOperationsState;
}
function renderRuntimeServiceOptions(documentRef = document) {
  const select = documentRef.getElementById("runtimeOperationsServiceSelect");
  if (!select) return;
  const ids = runtimeOperationsState.recommendations.map((item) => item?.serviceId).filter(Boolean);
  select.innerHTML = ids.length ? ids.map((id) => `<option value="${runtimeEscape(id)}">${runtimeEscape(id)}</option>`).join("") : `<option value="">서비스 데이터 없음</option>`;
  select.value = runtimeOperationsState.selectedServiceId || "";
}
function runtimeApprovalFormHasFocus(documentRef = document) {
  return Boolean(documentRef.activeElement?.closest?.(".runtime-execution-controls"));
}
async function refreshRuntimeOperations(fetchFn = fetch, documentRef = document, {background = false} = {}) {
  if (background && runtimeApprovalFormHasFocus(documentRef)) return buildRuntimeOperationsView(runtimeOperationsState);
  const notice = documentRef.getElementById("runtimeOperationsAvailability");
  if (notice && !background) { notice.dataset.state = "observing"; notice.textContent = "Runtime Recommendation을 갱신하고 있습니다."; }
  await loadRuntimeOperationsData(fetchFn);
  renderRuntimeServiceOptions(documentRef);
  const view = buildRuntimeOperationsView(runtimeOperationsState);
  renderRuntimeOperations(view, documentRef); renderRuntimeOverview(view, documentRef);
  if (typeof documentRef.dispatchEvent === "function" && typeof CustomEvent !== "undefined") documentRef.dispatchEvent(new CustomEvent("runtime-resources-updated"));
  return view;
}
async function selectRuntimeService(serviceId, fetchFn = fetch, documentRef = document) {
  runtimeOperationsState.selectedServiceId = serviceId || null; runtimeOperationsState.selectedExecutionPlanId = null;
  runtimeOperationsState.dryRun = null; return refreshRuntimeOperations(fetchFn, documentRef);
}
async function selectRuntimeExecution(planId, fetchFn = fetch, documentRef = document) {
  runtimeOperationsState.selectedExecutionPlanId = planId || null; return refreshRuntimeOperations(fetchFn, documentRef);
}

async function dryRunRuntimePlan(fetchFn = fetch, documentRef = document) {
  const plan = runtimeOperationsState.plan;
  const serviceId = runtimeOperationsState.selectedServiceId;
  if (!plan?.planId || !serviceId) return null;
  runtimeOperationsState.mutationPending = true;
  runtimeOperationsState.actionMessage = {state: "running", text: "Dry Run preflight를 실행하고 있습니다."};
  try {
    const result = await runtimeFetchJson(`/api/runtime-recommendations/${encodeURIComponent(serviceId)}/execution-plan/dry-run`, fetchFn, {
      method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({planId: plan.planId}),
    });
    runtimeOperationsState.dryRun = result;
    runtimeOperationsState.actionMessage = {state: result.status === "blocked" ? "failed" : "succeeded",
      text: `Dry Run ${String(result.status).toUpperCase()} · ${runtimeList(result.reasonCodes).join(", ") || "preflight_passed"}`};
    return result;
  } catch (error) {
    runtimeOperationsState.actionMessage = {state: "failed", text: `Dry Run 실패 · ${runtimeErrorMessage(error)}`};
    throw error;
  } finally {
    runtimeOperationsState.mutationPending = false;
    const view = buildRuntimeOperationsView(runtimeOperationsState);
    renderRuntimeOperations(view, documentRef); renderRuntimeOverview(view, documentRef);
  }
}
async function executeRuntimePlan({approvedBy, token}, fetchFn = fetch, documentRef = document, root = globalThis) {
  const plan = runtimeOperationsState.plan;
  const serviceId = runtimeOperationsState.selectedServiceId;
  if (!runtimeSecureExecutionContext(root)) throw new Error("secure_context_required");
  if (!plan?.planId || !serviceId || runtimeOperationsState.dryRun?.planId !== plan.planId) throw new Error("dry_run_required");
  runtimeOperationsState.mutationPending = true;
  runtimeOperationsState.actionMessage = {state: "running", text: "명시 승인된 plan을 실행 요청했습니다."};
  try {
    const record = await runtimeFetchJson(`/api/runtime-recommendations/${encodeURIComponent(serviceId)}/execution-plan/execute`, fetchFn, {
      method: "POST", headers: {"Content-Type": "application/json", "X-Execution-Token": token},
      body: JSON.stringify({planId: plan.planId, approved: true, approvedBy}),
    });
    runtimeOperationsState.selectedExecutionPlanId = record.planId;
    runtimeOperationsState.executionRecord = record;
    runtimeOperationsState.actionMessage = {state: "succeeded", text: `Execution ${record.status} · ${record.planId}`};
    await refreshRuntimeOperations(fetchFn, documentRef);
    return record;
  } catch (error) {
    runtimeOperationsState.actionMessage = {state: "failed", text: `Execute 실패 · ${runtimeErrorMessage(error)}`};
    throw error;
  } finally {
    runtimeOperationsState.mutationPending = false;
    const view = buildRuntimeOperationsView(runtimeOperationsState);
    renderRuntimeOperations(view, documentRef); renderRuntimeOverview(view, documentRef);
  }
}
function updateExecuteButton(documentRef = document) {
  const controls = documentRef.querySelector?.(".runtime-execution-controls");
  const button = controls?.querySelector?.("[data-runtime-execute]");
  if (!button) return;
  const approvedBy = controls.querySelector("#runtimeExecutionApprovedBy")?.value?.trim();
  const token = controls.querySelector("#runtimeExecutionToken")?.value;
  const checked = controls.querySelector("#runtimeExecutionApproved")?.checked === true;
  button.disabled = !(approvedBy && token && checked && !runtimeOperationsState.mutationPending);
}
function scheduleRuntimePolling(fetchFn = fetch, documentRef = document, root = globalThis) {
  if (runtimeOperationsState.pollTimer) root.clearTimeout?.(runtimeOperationsState.pollTimer);
  const delay = ["PENDING", "RUNNING"].includes(runtimeOperationsState.executionRecord?.status) ? 2000 : 5000;
  runtimeOperationsState.pollTimer = root.setTimeout?.(async () => {
    const page = documentRef.querySelector?.('[data-page="operations"]');
    if (page?.classList?.contains("active")) {
      try { await refreshRuntimeOperations(fetchFn, documentRef, {background: true}); } catch (_error) { /* next poll retries */ }
    }
    scheduleRuntimePolling(fetchFn, documentRef, root);
  }, delay);
  return delay;
}
function openRuntimeOperations(documentRef = document) {
  if (typeof globalThis.showDashboardPage === "function") globalThis.showDashboardPage("operations");
  if (globalThis.location && globalThis.location.hash !== "#operations") globalThis.location.hash = "operations";
  documentRef.getElementById("runtimeOperationsTitle")?.scrollIntoView?.({block: "start"});
}

if (typeof document !== "undefined") {
  document.getElementById("runtimeOperationsServiceSelect")?.addEventListener("change", (event) => void selectRuntimeService(event.currentTarget.value));
  document.addEventListener("change", (event) => {
    if (event.target?.id === "runtimeExecutionSelect") void selectRuntimeExecution(event.target.value);
    if (event.target?.closest?.(".runtime-execution-controls")) updateExecuteButton();
  });
  document.addEventListener("input", (event) => { if (event.target?.closest?.(".runtime-execution-controls")) updateExecuteButton(); });
  document.addEventListener("click", async (event) => {
    if (event.target.closest?.("[data-runtime-operations-link]")) openRuntimeOperations();
    if (event.target.closest?.("[data-runtime-dry-run]")) {
      try { await dryRunRuntimePlan(); } catch (_error) { /* rendered */ }
    }
    if (event.target.closest?.("[data-runtime-execute]")) {
      const controls = event.target.closest(".runtime-execution-controls");
      const approvedBy = controls.querySelector("#runtimeExecutionApprovedBy")?.value?.trim();
      const tokenInput = controls.querySelector("#runtimeExecutionToken");
      const token = tokenInput?.value || "";
      if (tokenInput) tokenInput.value = "";
      try { await executeRuntimePlan({approvedBy, token}); } catch (_error) { /* rendered */ }
    }
  });
  void refreshRuntimeOperations().finally(() => scheduleRuntimePolling());
}
if (typeof globalThis !== "undefined") {
  globalThis.runtimeOperations = {state: runtimeOperationsState, findSchedulingResource,
    refresh: refreshRuntimeOperations, renderSchedulingResourceDetails};
  globalThis.refreshRuntimeOperations = refreshRuntimeOperations;
  globalThis.onRuntimeOperationsVisible = () => refreshRuntimeOperations();
}
if (typeof module !== "undefined") {
  module.exports = {RUNTIME_ENDPOINTS, buildRuntimeOperationsView, calculateExecutionDurations,
    candidateExecutionMode, candidateView, dryRunRuntimePlan, executeRuntimePlan,
    findSchedulingResource, loadRuntimeOperationsData, mergeExecutionSteps, observedDurationSeconds,
    refreshRuntimeOperations, renderAuditTimeline, renderRuntimeCandidates, renderRuntimeHistory,
    renderInferenceOffloading, renderOwnership, renderRuntimeOperations, renderRuntimeOverview, renderRuntimePlan, renderSchedulingResourceDetails,
    runtimeDuration, runtimeOperationsState, runtimeSecureExecutionContext, runtimeTimeline,
    scheduleRuntimePolling, selectRuntimeExecution, selectRuntimeService, serviceRuntimeStatus};
}
