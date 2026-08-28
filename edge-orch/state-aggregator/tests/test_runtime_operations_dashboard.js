const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  DASHBOARD_PAGES,
} = require("../app/static/navigation.js");
const {
  buildRuntimeOperationsView,
  calculateExecutionDurations,
  dryRunRuntimePlan,
  loadRuntimeOperationsData,
  mergeExecutionSteps,
  renderInferenceOffloading,
  renderOwnership,
  renderRuntimeCandidates,
  renderRuntimeHistory,
  renderRuntimePlan,
  renderSchedulingResourceDetails,
  runtimeDuration,
  runtimeOperationsState,
  runtimeSecureExecutionContext,
  runtimeTimeline,
  scheduleRuntimePolling,
} = require("../app/static/runtime-operations.js");

const staticDir = path.join(__dirname, "../app/static");
const indexHtml = fs.readFileSync(path.join(staticDir, "index.html"), "utf8");
const runtimeJavascript = fs.readFileSync(path.join(staticDir, "runtime-operations.js"), "utf8");

function decisionFixture() {
  return {
    serviceId: "sensor-anomaly-demo",
    namespace: "edgex-edge",
    workloadKind: "Deployment",
    workloadName: "sensor-anomaly-demo",
    currentNodes: ["etri-dev0001-jetorn"],
    state: "REPLACE_RECOMMENDED",
    previousState: "OBSERVING",
    reasonCodes: ["sustained_cpu_pressure", "latency_slo_violated"],
    metrics: {
      cpuRatio: 0.86,
      memoryRatio: 0.58,
      latencyP95Ms: 183,
      backlog: 4,
      throughputPerSecond: 1.25,
      desiredReplicas: 1,
      readyReplicas: 1,
    },
    dwell: {
      resourcePressureSeconds: 320,
      runtimeFailureSeconds: 320,
    },
    cooldownRemainingSeconds: 0,
    recommendation: {
      action: "replace",
      selectedNode: "etri-ser0002-cgnmsb",
      selectedScore: 91.03,
    },
    placement: {
      status: "selected",
      selectedNode: "etri-ser0002-cgnmsb",
      selectedScore: 91.03,
      reasonCodes: ["eligible_node_selected"],
      candidates: [
        {
          node: "etri-ser0002-cgnmsb",
          eligible: true,
          score: 91.03,
          reasonCodes: ["filter_passed", "selected_highest_score"],
          health: "healthy",
          architecture: "amd64",
          accelerator: "RTX5060Ti",
          availableBefore: {cpuCores: 16, memoryBytes: 80 * 1024 ** 3},
          availableAfter: {cpuCores: 14, memoryBytes: 76 * 1024 ** 3},
        },
        {
          node: "etri-ser0001-cg0msb",
          eligible: true,
          score: 87.21,
          reasonCodes: ["filter_passed", "eligible_lower_score"],
          health: "healthy",
          architecture: "amd64",
          accelerator: "NVIDIA",
          availableBefore: {cpuCores: 12, memoryBytes: 64 * 1024 ** 3},
        },
        {
          node: "etri-dev0003-raspi5",
          eligible: false,
          score: null,
          reasonCodes: ["architecture_mismatch"],
          health: "healthy",
          architecture: "arm64",
          accelerator: null,
          availableBefore: {cpuCores: 2, memoryBytes: 8 * 1024 ** 3},
        },
      ],
    },
    observationSource: "container-cadvisor",
    observationScope: "container",
    observedAt: "2026-08-25T08:00:00Z",
  };
}

function planFixture() {
  const target = {
    node: "etri-ser0002-cgnmsb",
    workload: {
      namespace: "edge-ai-workloads",
      kind: "Deployment",
      name: "sensor-anomaly-demo-replace-abcd",
      role: "candidate",
    },
  };
  const condition = {code: "candidate_ready", description: "candidate is Ready"};
  const steps = [
    ["create-candidate", "create_candidate", "always"],
    ["verify-ready", "verify_ready", "always"],
    ["validate-candidate-pre-activation", "validate_candidate_pre_activation", "always"],
    ["handoff-execution-ownership", "handoff_execution_ownership", "always"],
    ["verify-active-candidate", "verify_active_candidate", "always"],
    ["switch-traffic", "switch_traffic", "always"],
    ["verify-switched-traffic", "verify_switched_traffic", "always"],
    ["terminate-current", "terminate_current", "always"],
    ["rollback-traffic", "rollback_traffic", "on_failure"],
    ["rollback-execution-ownership", "rollback_execution_ownership", "on_failure"],
  ].map(([stepId, action, executionMode], index) => ({
    stepId,
    sequence: index + 1,
    action,
    executionMode,
    targets: [target],
    prerequisites: [condition],
    failureConditions: [condition],
  }));
  return {
    planId: "runtime-plan-abcd",
    serviceId: "sensor-anomaly-demo",
    status: "planned",
    mode: "read_only",
    reasonCodes: ["execution_plan_generated"],
    steps,
  };
}

function executionFixture() {
  const plan = planFixture();
  const startedAt = "2026-08-26T07:18:02.681Z";
  const step = (stepId, action, status, start, end, reasonCodes = []) => ({
    stepId, action, status, reasonCodes, startedAt: start, completedAt: end,
  });
  return {
    planId: plan.planId,
    serviceId: plan.serviceId,
    status: "FAILED",
    approvedBy: "operator",
    approvedAt: startedAt,
    candidateCreated: true,
    candidateReady: true,
    candidateWorkload: {
      namespace: "edge-ai-workloads",
      name: "sensor-anomaly-demo-replace-abcd",
      targetNode: "etri-dev0002-raspi5",
    },
    validation: {
      status: "SUCCEEDED",
      observedAt: "2026-08-26T07:18:50.309Z",
      consecutiveSuccesses: 7,
      requiredConsecutiveSuccesses: 6,
      minimumStableSeconds: 30,
      checks: [
        {name: "pod_ready", status: "SUCCEEDED", reasonCodes: [], measurements: {pod: "candidate-pod"}},
        {name: "execution_shadow", status: "SUCCEEDED", reasonCodes: [], measurements: {executionMode: "SHADOW"}},
      ],
      source: {node: "etri-dev0001-jetorn", pod: "source-pod", inputState: "fresh", modelState: "ready"},
      candidate: {node: "etri-dev0002-raspi5", pod: "candidate-pod", inputState: "fresh", modelState: "ready", framesProcessed: 35,
        dbWriteCount: 0, resultObservedAt: "2026-08-26T07:18:50.100Z"},
    },
    activeCandidateValidation: {
      status: "FAILED",
      observedAt: "2026-08-26T07:20:50.309Z",
      checks: [{name: "pod_ready", status: "BLOCKED", reasonCodes: ["candidate_not_ready"]}],
      source: {node: "etri-dev0001-jetorn", pod: "source-pod"},
      candidate: {node: "etri-dev0002-raspi5", pod: null},
    },
    executionOwnership: {
      leaseName: "sensor-anomaly-demo-execution",
      activeOwner: "source",
      rollbackAvailable: true,
      handedOffAt: "2026-08-26T07:18:50.337Z",
      rolledBackAt: "2026-08-26T07:20:50.400Z",
      before: {holderIdentity: "sensor-anomaly-demo", resourceVersion: "41"},
      after: {holderIdentity: "sensor-anomaly-demo", resourceVersion: "43"},
    },
    routing: null,
    plan,
    steps: [
      step("create-candidate", "create_candidate", "SUCCEEDED", "2026-08-26T07:18:02.700Z", "2026-08-26T07:18:02.800Z"),
      step("verify-ready", "verify_ready", "SUCCEEDED", "2026-08-26T07:18:02.800Z", "2026-08-26T07:18:19.481Z"),
      step("validate-candidate-pre-activation", "validate_candidate_pre_activation", "SUCCEEDED", "2026-08-26T07:18:19.485Z", "2026-08-26T07:18:50.309Z"),
      step("handoff-execution-ownership", "handoff_execution_ownership", "SUCCEEDED", "2026-08-26T07:18:50.314Z", "2026-08-26T07:18:50.368Z"),
      step("verify-active-candidate", "verify_active_candidate", "FAILED", "2026-08-26T07:18:50.374Z", "2026-08-26T07:20:50.309Z", ["candidate_not_ready"]),
      step("switch-traffic", "switch_traffic", "BLOCKED", null, "2026-08-26T07:20:50.309Z", ["previous_step_blocked"]),
      step("rollback-execution-ownership", "rollback_execution_ownership", "SUCCEEDED", "2026-08-26T07:20:50.309Z", "2026-08-26T07:20:50.432Z", ["execution_ownership_rollback_succeeded"]),
    ],
    updatedAt: "2026-08-26T07:20:50.432Z",
  };
}

test("registers service operations between overview and the four existing pages", () => {
  assert.deepEqual(DASHBOARD_PAGES, [
    "overview", "operations", "inventory", "management", "designer",
  ]);
  const menuLabels = [...indexHtml.matchAll(/data-dashboard-page="([^"]+)"[^>]*>([^<]+)<\/button>/g)]
    .map((match) => [match[1], match[2].trim()]);
  assert.deepEqual(menuLabels, [
    ["overview", "운영 현황"],
    ["operations", "서비스 운영"],
    ["inventory", "디바이스"],
    ["management", "장비 관리"],
    ["designer", "서비스 설계"],
  ]);
  assert.match(indexHtml, /data-page="operations"/);
  assert.match(indexHtml, /runtime-operations\.js/);
  assert.match(indexHtml, /runtime-operations\.css/);
});

test("renders recommendation reasons, duration, and all placement outcomes", () => {
  const view = buildRuntimeOperationsView({
    decision: decisionFixture(),
    history: {items: []},
    plan: planFixture(),
    resources: [{
      node: "etri-dev0001-jetorn",
      health: "healthy",
      utilization: {gpuRatio: 0},
      available: {cpuCores: 3, memoryBytes: 4 * 1024 ** 3},
      accelerator: "JetsonGPU",
    }],
    services: [{
      service_id: "sensor-anomaly-demo",
      input_state: "fresh",
      model_state: "ready",
    }],
  });

  assert.equal(view.status, "RUNNING");
  assert.equal(view.statusTone, "running");
  assert.equal(view.state, "REPLACE_RECOMMENDED");
  assert.equal(view.observedDuration, 320);
  assert.equal(view.inputState, "fresh");
  assert.equal(view.modelState, "ready");
  assert.equal(view.currentScheduling.cpu, "3.00 cores available");
  assert.equal(view.currentScheduling.memory, "4.00 GB");
  assert.equal(view.currentScheduling.accelerator, "JetsonGPU");
  assert.deepEqual(view.reasonCodes, ["sustained_cpu_pressure", "latency_slo_violated"]);
  assert.deepEqual(view.candidates.map((candidate) => candidate.result), [
    "SELECTED", "ELIGIBLE", "REJECTED",
  ]);

  const candidates = renderRuntimeCandidates(view);
  assert.match(candidates, /SELECTED/);
  assert.match(candidates, /ELIGIBLE/);
  assert.match(candidates, /REJECTED/);
  assert.match(candidates, /architecture_mismatch/);
  assert.match(candidates, /91\.03/);
});

test("renders API-backed partial offloading mode, target, latency, and fallback evidence", () => {
  const decision = decisionFixture();
  decision.state = "OFFLOAD_RECOMMENDED";
  decision.recommendation.action = "offload";
  decision.offloading = {
    state: "OFFLOAD_RECOMMENDED",
    targetWorkload: "edgex-edge/sensor-anomaly-inference-server1",
    targetNode: "etri-ser0002-cgnmsb",
    targetReady: true,
    networkLatencyMs: 12.5,
    maxNetworkLatencyMs: 250,
    candidateQualified: true,
    reasonCodes: ["remote_target_ready"],
  };
  const view = buildRuntimeOperationsView({
    decision,
    history: {items: []},
    resources: [],
    services: [],
    serviceDemo: {
      generated_at: "2026-08-26T08:00:00Z",
      inference_routing: {
        inference_mode: "LOCAL_FALLBACK",
        remote_node: "etri-ser0002-cgnmsb",
        remote_ready: false,
        local_latency_ms: 3.2,
        network_latency_ms: 18.4,
        remote_processing_ms: 6.1,
        total_latency_ms: 27.7,
        offload_success_rate: 0.875,
        fallback_count: 2,
        last_reason_code: "remote_timeout",
        observed_at: "2026-08-26T08:00:00Z",
      },
    },
  });

  assert.equal(view.state, "OFFLOAD_RECOMMENDED");
  assert.equal(view.action, "OFFLOAD");
  assert.equal(view.offloading.mode, "LOCAL_FALLBACK");
  assert.equal(view.offloading.remoteTarget, "etri-ser0002-cgnmsb");
  assert.equal(view.offloading.successRate, "87.5%");
  const rendered = renderInferenceOffloading(view);
  assert.match(rendered, /Inference Execution/);
  assert.match(rendered, /LOCAL_FALLBACK/);
  assert.match(rendered, /etri-ser0002-cgnmsb/);
  assert.match(rendered, /18\.40 ms/);
  assert.match(rendered, /remote_timeout/);
  assert.match(rendered, /production 처리를 계속/);
});

test("renders read-only execution steps and the rollback branch", () => {
  const rendered = renderRuntimePlan(planFixture());
  assert.match(rendered, /create_candidate/);
  assert.match(rendered, /verify_ready/);
  assert.match(rendered, /switch_traffic/);
  assert.match(rendered, /terminate_current/);
  assert.match(rendered, /rollback/);
  assert.match(rendered, /on_failure/);
  assert.match(rendered, /candidate_ready/);
});

test("renders runtime history transition, reasons, old node, and recommended node", () => {
  const decision = decisionFixture();
  const rendered = renderRuntimeHistory([{
    sequence: 3,
    recordedAt: "2026-08-25T08:00:00Z",
    previousState: "OBSERVING",
    state: "REPLACE_RECOMMENDED",
    decision,
  }]);
  assert.match(rendered, /OBSERVING/);
  assert.match(rendered, /REPLACE_RECOMMENDED/);
  assert.match(rendered, /sustained_cpu_pressure/);
  assert.match(rendered, /etri-dev0001-jetorn/);
  assert.match(rendered, /etri-ser0002-cgnmsb/);
});

test("keeps actual usage separate from scheduling allocatable requested available", () => {
  const rendered = renderSchedulingResourceDetails({
    node: "etri-ser0002-cgnmsb",
    health: "healthy",
    reasonCodes: ["ready"],
    utilization: {cpuRatio: 0.21, memoryRatio: 0.53, gpuRatio: 0},
    allocatable: {cpuCores: 24, memoryBytes: 125 * 1024 ** 3, acceleratorUnits: {"nvidia.com/gpu": 2}},
    requested: {cpuCores: 8, memoryBytes: 45 * 1024 ** 3, acceleratorUnits: {"nvidia.com/gpu": 1}},
    available: {cpuCores: 16, memoryBytes: 80 * 1024 ** 3, acceleratorUnits: {"nvidia.com/gpu": 1}},
  });
  assert.match(rendered, /실사용/);
  assert.match(rendered, /CPU Usage/);
  assert.match(rendered, /21\.0%/);
  assert.match(rendered, /Scheduling Resource/);
  assert.match(rendered, /Allocatable/);
  assert.match(rendered, /Requested/);
  assert.match(rendered, /Available/);
  assert.match(rendered, /24\.00 cores/);
  assert.match(rendered, /8\.00 cores/);
  assert.match(rendered, /16\.00 cores/);
  assert.match(rendered, /nvidia\.com\/gpu/);
});

test("shows N/A and data absence when recommendation APIs fail", () => {
  const view = buildRuntimeOperationsView({
    decision: null,
    history: null,
    plan: null,
    resources: [],
    services: [],
    errors: {decision: "HTTP 503"},
  });
  assert.equal(view.available, false);
  assert.equal(view.state, "N/A");
  assert.equal(view.metrics.cpu, "N/A");
  assert.equal(view.selectedNode, "N/A");
  assert.match(renderRuntimeCandidates(view), /배치 후보 데이터 없음/);
  assert.match(renderRuntimePlan(view.plan), /Execution Plan 데이터 없음/);
  assert.match(renderRuntimeHistory(view.history), /Runtime History 데이터 없음/);
});

test("refresh reads only GET projections and never calls placement selection", async () => {
  runtimeOperationsState.selectedServiceId = null;
  const calls = [];
  const decision = decisionFixture();
  const responseByUrl = new Map([
    ["/api/runtime-recommendations", {items: [decision]}],
    ["/api/resources", []],
    ["/state/services", {services: []}],
    ["/state/service-demo", {input_state: "fresh", model_state: "ready"}],
    ["/api/runtime-recommendations/sensor-anomaly-demo", decision],
    ["/api/runtime-recommendations/sensor-anomaly-demo/history?limit=50", {items: []}],
    ["/api/runtime-recommendations/sensor-anomaly-demo/execution-plan", planFixture()],
    ["/api/executions?serviceId=sensor-anomaly-demo&limit=20", {items: []}],
  ]);
  const fetchFn = async (url, options = {}) => {
    calls.push([url, options]);
    return {
      ok: responseByUrl.has(url),
      status: responseByUrl.has(url) ? 200 : 404,
      json: async () => responseByUrl.get(url),
    };
  };

  await loadRuntimeOperationsData(fetchFn);

  assert.equal(calls.every(([, options]) => options.method === undefined || options.method === "GET"), true);
  assert.equal(calls.some(([url]) => url.includes("/api/placements/select")), false);
  assert.equal(runtimeOperationsState.decision.state, "REPLACE_RECOMMENDED");
});

test("adds explicit execution controls without reviving removed orchestration UI", () => {
  const operationsSection = indexHtml.match(/<section\s+class="runtime-operations-page[\s\S]*?<section class="service-catalog/)[0];
  assert.match(runtimeJavascript, /Dry Run → 승인 → Execute/);
  assert.match(runtimeJavascript, /type="password" autocomplete="off"/);
  assert.match(runtimeJavascript, /data-runtime-execute disabled/);
  assert.doesNotMatch(runtimeJavascript, /localStorage|sessionStorage/);
  assert.doesNotMatch(runtimeJavascript, /api\/v1\/inference-routing/);
  assert.doesNotMatch(indexHtml, /id="serviceAugmentationPanel"/);
  assert.doesNotMatch(indexHtml, /AI Pipeline Builder/);
  assert.doesNotMatch(indexHtml, /Workflow Builder/);
  assert.doesNotMatch(indexHtml, /data-dashboard-page="resource-augmentation"/);
});

test("shows Pod readiness separately from ACTIVE ownership and persisted rollback", () => {
  const record = executionFixture();
  const view = buildRuntimeOperationsView({
    decision: decisionFixture(),
    history: {items: []},
    plan: planFixture(),
    executionRecord: record,
    executions: [record],
    audit: {items: []},
    resources: [],
    services: [],
    serviceDemo: {
      input_state: "fresh",
      model_state: "ready",
      binding: {node: "etri-dev0001-jetorn"},
      counters: {frames_processed: 81},
      storage: {result_count: 80},
      latest: {observed_at: "2026-08-26T07:20:59.900Z"},
      execution_ownership: {
        effective_mode: "ACTIVE",
        lease_name: "sensor-anomaly-demo-execution",
        holder_identity: "sensor-anomaly-demo",
        lease_valid: true,
        resource_version: "44",
        observed_at: "2026-08-26T07:21:00Z",
      },
    },
  });

  assert.equal(view.source.podReady, "READY");
  assert.equal(view.source.mode, "ACTIVE");
  assert.equal(view.candidate.podReady, "NOT READY");
  assert.equal(view.candidate.mode, "STANDBY");
  assert.equal(view.ownership.holderIdentity, "sensor-anomaly-demo");
  assert.equal(view.ownership.rollbackAvailable, true);
  assert.equal(view.activeNode, "etri-dev0001-jetorn");
  assert.equal(view.source.framesProcessed, 81);
  assert.equal(view.source.dbWriteCount, 80);
  assert.equal(view.candidate.framesProcessed, 35);
  assert.equal(view.candidate.dbWriteCount, 0);
  assert.equal(view.candidate.preservedNote, "rollback 후 workload 보존 · 삭제되지 않음");
  const liveDemo = renderOwnership(view);
  assert.match(liveDemo, /CURRENT LEASE HOLDER/);
  assert.match(liveDemo, /DB write count/);
  assert.match(liveDemo, /최근 inference/);
  assert.match(liveDemo, /failure detected/);
  assert.match(liveDemo, /workload 보존/);
});

test("merges persisted step state and keeps ownership and traffic planes distinct", () => {
  const merged = mergeExecutionSteps(planFixture(), executionFixture());
  assert.equal(merged.find((step) => step.action === "handoff_execution_ownership").status, "SUCCEEDED");
  assert.equal(merged.find((step) => step.action === "handoff_execution_ownership").plane, "ownership");
  assert.equal(merged.find((step) => step.action === "switch_traffic").status, "BLOCKED");
  assert.equal(merged.find((step) => step.action === "switch_traffic").plane, "traffic");
  assert.equal(merged.find((step) => step.action === "terminate_current").plane, "lifecycle");

  const rendered = renderRuntimePlan(planFixture(), merged);
  assert.match(rendered, /Execution Ownership/);
  assert.match(rendered, /Traffic Routing · 필요 시/);
  assert.match(rendered, /previous_step_blocked/);
});

test("calculates handoff, validation, inference resume, and rollback durations from audit timestamps", () => {
  const record = executionFixture();
  const audit = [{
    eventType: "active_candidate_validation_observed",
    recordedAt: "2026-08-26T07:18:55.427Z",
    details: {validation: {checks: [{name: "processing_counter_increased", status: "SUCCEEDED"}]}},
  }];
  const durations = Object.fromEntries(calculateExecutionDurations(record, audit).map((item) => [item.label, item.value]));
  assert.equal(durations["Pre-validation"], "30.8s");
  assert.equal(durations["Lease handoff"], "54ms");
  assert.equal(durations["Candidate inference 재개"], "5.09s");
  assert.equal(durations["Lease rollback"], "123ms");
  assert.equal(runtimeDuration("2026-08-26T00:00:00.000Z", "2026-08-26T00:00:00.054Z"), "54ms");
});

test("builds a chronological recommendation and audit timeline with elapsed durations", () => {
  const timeline = runtimeTimeline([{
    recordedAt: "2026-08-26T07:17:00Z",
    previousState: "OBSERVING",
    state: "REPLACE_RECOMMENDED",
    decision: decisionFixture(),
  }], [{
    eventType: "approval_received",
    status: "PENDING",
    recordedAt: "2026-08-26T07:17:10Z",
    reasonCodes: [],
  }]);
  assert.equal(timeline[0].label, "REPLACE_RECOMMENDED");
  assert.equal(timeline[1].label, "승인");
  assert.equal(timeline[1].durationFromPrevious, "10.0s");
});

test("connects read-only execution history, record, and audit APIs", async () => {
  runtimeOperationsState.selectedServiceId = null;
  runtimeOperationsState.selectedExecutionPlanId = null;
  const decision = decisionFixture();
  const record = executionFixture();
  const calls = [];
  const responses = new Map([
    ["/api/runtime-recommendations", {items: [decision]}],
    ["/api/resources", []],
    ["/state/services", {services: []}],
    ["/state/service-demo", {input_state: "fresh", model_state: "ready"}],
    ["/api/runtime-recommendations/sensor-anomaly-demo", decision],
    ["/api/runtime-recommendations/sensor-anomaly-demo/history?limit=50", {items: []}],
    ["/api/runtime-recommendations/sensor-anomaly-demo/execution-plan", planFixture()],
    ["/api/executions?serviceId=sensor-anomaly-demo&limit=20", {items: [record]}],
    ["/api/execution-plans/runtime-plan-abcd", record],
    ["/api/execution-plans/runtime-plan-abcd/audit?limit=500", {items: []}],
  ]);
  const fetchFn = async (url, options = {}) => {
    calls.push([url, options]);
    return {ok: responses.has(url), status: responses.has(url) ? 200 : 404, json: async () => responses.get(url)};
  };
  await loadRuntimeOperationsData(fetchFn);
  assert.equal(runtimeOperationsState.executionRecord.planId, "runtime-plan-abcd");
  assert.equal(calls.some(([url]) => url === "/api/execution-plans/runtime-plan-abcd"), true);
  assert.equal(calls.some(([url]) => url.endsWith("/audit?limit=500")), true);
  assert.equal(calls.every(([, options]) => !options.method || options.method === "GET"), true);
});

test("dry-run posts the current plan without an execution token or approval", async () => {
  runtimeOperationsState.selectedServiceId = "sensor-anomaly-demo";
  runtimeOperationsState.plan = planFixture();
  runtimeOperationsState.dryRun = null;
  const calls = [];
  const fetchFn = async (url, options) => {
    calls.push([url, options]);
    return {ok: true, status: 200, json: async () => ({
      planId: "runtime-plan-abcd", status: "partial", reasonCodes: ["unsupported_step"], steps: [], generatedAt: "2026-08-26T08:00:00Z",
    })};
  };
  const documentRef = {getElementById: () => null};
  await dryRunRuntimePlan(fetchFn, documentRef);
  const [, options] = calls[0];
  assert.equal(options.method, "POST");
  assert.deepEqual(JSON.parse(options.body), {planId: "runtime-plan-abcd"});
  assert.equal(Object.hasOwn(options.headers, "X-Execution-Token"), false);
});

test("execution token entry is blocked outside trusted HTTPS and polling uses 5s or 2s", () => {
  assert.equal(runtimeSecureExecutionContext({isSecureContext: false, location: {protocol: "http:"}}), false);
  assert.equal(runtimeSecureExecutionContext({isSecureContext: true, location: {protocol: "https:"}}), true);
  const root = {setTimeout: (_callback, delay) => delay, clearTimeout: () => {}};
  const documentRef = {querySelector: () => null};
  runtimeOperationsState.executionRecord = {status: "SUCCEEDED"};
  assert.equal(scheduleRuntimePolling(() => {}, documentRef, root), 5000);
  runtimeOperationsState.executionRecord = {status: "RUNNING"};
  assert.equal(scheduleRuntimePolling(() => {}, documentRef, root), 2000);
  runtimeOperationsState.pollTimer = null;
});

test("reports the verified Endpoints route and blocked EndpointSlice route exactly", () => {
  assert.match(runtimeJavascript, /runtime-endpoints<\/dt><dd>VERIFIED/);
  assert.match(runtimeJavascript, /runtime-endpointslice<\/dt><dd>BLOCKED/);
  assert.match(runtimeJavascript, /routing_mode_unsupported/);
  assert.match(runtimeJavascript, /polling workload는 Lease handoff만으로/);
});
