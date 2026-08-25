const test = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

const {
  DASHBOARD_PAGES,
} = require("../app/static/navigation.js");
const {
  buildRuntimeOperationsView,
  loadRuntimeOperationsData,
  renderRuntimeCandidates,
  renderRuntimeHistory,
  renderRuntimePlan,
  renderSchedulingResourceDetails,
  runtimeOperationsState,
} = require("../app/static/runtime-operations.js");

const staticDir = path.join(__dirname, "../app/static");
const indexHtml = fs.readFileSync(path.join(staticDir, "index.html"), "utf8");

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
  return {
    planId: "runtime-plan-abcd",
    serviceId: "sensor-anomaly-demo",
    status: "planned",
    mode: "read_only",
    reasonCodes: ["execution_plan_generated"],
    steps: [
      {sequence: 1, action: "create_candidate", executionMode: "always", targets: [target], prerequisites: [condition], failureConditions: [condition]},
      {sequence: 2, action: "verify_ready", executionMode: "always", targets: [target], prerequisites: [condition], failureConditions: [condition]},
      {sequence: 3, action: "switch_traffic", executionMode: "always", targets: [target], prerequisites: [condition], failureConditions: [condition]},
      {sequence: 4, action: "terminate_current", executionMode: "always", targets: [target], prerequisites: [condition], failureConditions: [condition]},
      {sequence: 5, action: "rollback", executionMode: "on_failure", targets: [target], prerequisites: [condition], failureConditions: [condition]},
    ],
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
    ["/api/runtime-recommendations/sensor-anomaly-demo", decision],
    ["/api/runtime-recommendations/sensor-anomaly-demo/history?limit=50", {items: []}],
    ["/api/runtime-recommendations/sensor-anomaly-demo/execution-plan", planFixture()],
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

test("does not expose execution controls or revive removed orchestration UI", () => {
  const operationsSection = indexHtml.match(/<section\s+class="runtime-operations-page[\s\S]*?<section class="service-catalog/)[0];
  assert.doesNotMatch(operationsSection, /<button[^>]*>\s*(실행|적용|승인)\s*<\/button>/);
  assert.doesNotMatch(indexHtml, /id="serviceAugmentationPanel"/);
  assert.doesNotMatch(indexHtml, /AI Pipeline Builder/);
  assert.doesNotMatch(indexHtml, /Workflow Builder/);
  assert.doesNotMatch(indexHtml, /data-dashboard-page="resource-augmentation"/);
});
