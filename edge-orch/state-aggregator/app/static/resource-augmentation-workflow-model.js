function normalizeWorkflowDemo(workflowDemo) {
  if (!workflowDemo || typeof workflowDemo !== "object") return null;
  const offloadPath = workflowDemo.offload_path || {};
  const progressPercent = Math.max(0, Math.min(100, Number(workflowDemo.progress_percent) || 0));
  return {
    name: workflowDemo.name || "-",
    status: workflowDemo.status || "unknown",
    automationTrigger: workflowDemo.automation_trigger || "runtime_metrics_observed",
    progressPercent,
    currentStepId: workflowDemo.current_step_id || "",
    operatorSummary: workflowDemo.operator_summary || "",
    autoPlay: workflowDemo.auto_play !== false,
    playbackIntervalMs: Math.max(500, Number(workflowDemo.playback_interval_ms) || 1600),
    scenarioTimeline: Array.isArray(workflowDemo.scenario_timeline)
      ? workflowDemo.scenario_timeline.map((phase) => ({
        id: phase.id || "",
        label: phase.label || phase.id || "",
        activeStepId: phase.active_step_id || "",
        progressPercent: Math.max(0, Math.min(100, Number(phase.progress_percent) || 0)),
        summary: phase.summary || "",
      }))
      : [],
    steps: Array.isArray(workflowDemo.steps) ? workflowDemo.steps : [],
    offloadPath: {
      source: offloadPath.source || "-",
      inference: offloadPath.inference || "-",
      cache: offloadPath.cache || "-",
      result: offloadPath.result || "-",
    },
  };
}

function workflowStepLabel(state) {
  return {
    completed: "done",
    active: "running",
    planned: "planned",
  }[state] || augText(state, "unknown");
}

function workflowAutomationLabel(value) {
  return {
    runtime_metrics_observed: "runtime metrics observed",
  }[value] || augText(value, "automatic decision");
}

function workflowRuntimeStatusLabel(state) {
  return {
    completed: "completed",
    current: "running",
    planned: "waiting",
  }[state] || augText(state, "waiting");
}

function workflowNodeStates(model, activeStepId) {
  const activeNodes = model.nodes.filter((node) => node.stepId === activeStepId);
  const activeOrderMin = activeNodes.length ? Math.min(...activeNodes.map((node) => node.order)) : -1;
  return Object.fromEntries(model.nodes.map((node) => {
    const state = node.stepId === activeStepId ? "current" : node.order < activeOrderMin ? "completed" : "planned";
    return [node.id, state];
  }));
}

function augmentationNodePayload(model, activeStepId, frame) {
  const states = workflowNodeStates(model, activeStepId);
  const activeNode = model.nodes.find((node) => node.stepId === activeStepId) || model.nodes[0];
  return {
    states,
    activeNode,
    phase: frame?.label || activeNode?.title || "workflow playback",
    summary: frame?.summary || activeNode?.meta || "runtime observation pending",
  };
}

function augmentationNodeCanvasModel(workflow) {
  const decision = augmentationState.decision || {};
  const selectedResources = decision.selectedResources || [];
  const inference = selectedResources.find((resource) => resource.role === "inference")?.name || "inference pending";
  const storage = selectedResources.find((resource) => resource.role === "storage")?.name || "cache pending";
  const result = decision.resultingAugmentedDevice?.name || "augmented device pending";
  const candidateCount = augmentationState.runtimeSummary.candidate_resource_total || augmentationState.candidateResources.length || 0;
  const pressure = decision.pressureReason?.join(" + ") || "pressure pending";
  return {
    nodes: [
      { id: "edge-device", stepId: "service-request", kind: "device", title: "Observe Edge Device", value: decision.targetDevice || "-", meta: "physical resource target", x: 14, y: 22, order: 0 },
      { id: "pressure", stepId: "pressure-detected", kind: "pressure", title: "Detect Resource Pressure", value: `${decision.pressureScore || 0}% pressure`, meta: pressure, x: 35, y: 22, order: 1 },
      { id: "candidates", stepId: "candidate-scan", kind: "pool", title: "Evaluate Candidate Pool", value: `${candidateCount} resources`, meta: `${augmentationState.runtimeSummary.available || 0} available · ${augmentationState.runtimeSummary.blocked || 0} blocked`, x: 56, y: 22, order: 2 },
      { id: "gpu-offload", stepId: "offload-plan", kind: "resource", title: "Select GPU Resource", value: inference, meta: "remote inference", x: 45, y: 70, order: 3 },
      { id: "cache-offload", stepId: "offload-plan", kind: "resource", title: "Select Cache Resource", value: storage, meta: "result window", x: 67, y: 70, order: 4 },
      { id: "augmented-device", stepId: "augmented-device-bind", kind: "result", title: "Plan Augmented Device Binding", value: result, meta: workflow?.status || "planned binding", x: 88, y: 46, order: 5 },
    ],
    edges: [
      ["edge-device", "pressure", "runtime metrics"],
      ["pressure", "candidates", "pressure signal"],
      ["candidates", "gpu-offload", "candidate scan"],
      ["candidates", "cache-offload", "candidate scan"],
      ["gpu-offload", "augmented-device", "select inference"],
      ["cache-offload", "augmented-device", "select cache"],
    ],
  };
}
