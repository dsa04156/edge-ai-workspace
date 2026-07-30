function targetMatchesFilter(target) {
  if (workflowState.selectedFilter === "all") return true;
  if (workflowState.selectedFilter === "telemetry") return target.kind === "device";
  if (workflowState.selectedFilter === "fresh") return target.kind === "device" && target.eventFresh;
  if (workflowState.selectedFilter === "stale") return target.kind === "device" && !target.eventFresh;
  if (workflowState.selectedFilter === "sensehat") return isSenseHatTarget(target);
  if (workflowState.selectedFilter === "aihat") return target.id === `resource:${AI_HAT_NODE}:ai-hat`;
  return true;
}

function sortedWorkflowTargets() {
  const node = selectedWorkflowNode();
  return [...workflowState.targets].filter(targetMatchesFilter).sort((left, right) => {
    const recommended = Number(nodeAcceptsTarget(node, right)) - Number(nodeAcceptsTarget(node, left));
    if (recommended !== 0) return recommended;
    const fresh = Number(right.eventFresh) - Number(left.eventFresh);
    if (fresh !== 0) return fresh;
    return left.displayName.localeCompare(right.displayName);
  });
}

function buildValidation() {
  const workflow = currentWorkflow();
  const results = [];
  const devices = workflowState.targets.filter((target) => target.kind === "device");
  const boundNodes = workflow.nodes.filter((node) => node.targetId);
  results.push(devices.length ? { level: "PASS", rule: "device-pool", message: `${devices.length}개 EdgeX Core Metadata device를 조회했습니다.` } : { level: "FAIL", rule: "device-pool", message: "EdgeX Core Metadata device를 조회하지 못했습니다." });
  results.push(workflow.nodes.length ? { level: "PASS", rule: "nodes", message: `${workflow.name} node ${workflow.nodes.length}개가 있습니다.` } : { level: "FAIL", rule: "nodes", message: "workflow node가 없습니다." });
  results.push(workflow.edges.length ? { level: "PASS", rule: "connections", message: `node 연결 ${workflow.edges.length}개가 정의되어 있습니다.` } : { level: "FAIL", rule: "connections", message: "node 간 연결이 없습니다." });
  for (const node of workflow.nodes) {
    const target = targetById(node.targetId);
    if (node.type !== "device_source" && !incomingEdges(workflow, node.id).length) results.push({ level: "FAIL", rule: "incoming", message: `${node.label} 입력 연결이 없습니다.` });
    if (node.type !== "dashboard_event" && !outgoingEdges(workflow, node.id).length) results.push({ level: "WARN", rule: "outgoing", message: `${node.label} 출력 연결이 없습니다.` });
    if ((node.type === "device_source" || node.type === "ai_inference") && !target) results.push({ level: "FAIL", rule: "binding", message: `${node.label} node에 대상이 없습니다.` });
    if (!target) continue;
    if (!nodeAcceptsTarget(node, target)) results.push({ level: "FAIL", rule: "capability", message: `${node.label}와 ${target.displayName} 역할이 맞지 않습니다.` });
    if (node.type === "device_source" && !resolvedWorkflowResource(node, target)) results.push({ level: "FAIL", rule: "resource", message: `${node.label}에 읽을 Device Profile resource가 없습니다.` });
    if (node.type === "device_source" && !sourceReadModesForTarget(target).includes(node.config.readMode || "history")) results.push({ level: "FAIL", rule: "read-mode", message: `${target.displayName}에서 ${DEVICE_SOURCE_MODE_LABELS[node.config.readMode] || node.config.readMode} 방식을 사용할 수 없습니다.` });
    if (node.type === "device_source" && !target.eventFresh) results.push({ level: "WARN", rule: "freshness", message: `${target.displayName} 최신 Core Data event가 ${target.eventFreshness} 상태입니다.` });
    if (target.kind === "device" && target.connectionState !== "connected") results.push({ level: target.connectionState === "disconnected" ? "FAIL" : "WARN", rule: "connection", message: `${target.displayName} EdgeX connection state가 ${target.connectionState}입니다.` });
    if (target.kind === "device" && (!target.profileName || !target.serviceName)) results.push({ level: "FAIL", rule: "edgex-identity", message: `${target.displayName} EdgeX profile 또는 Device Service identity가 없습니다.` });
  }
  results.push(boundNodes.length ? { level: "PASS", rule: "binding-count", message: `${boundNodes.length}/${workflow.nodes.length} node가 source/resource를 참조합니다.` } : { level: "WARN", rule: "binding-count", message: "아직 binding된 node가 없습니다." });
  const status = results.some((item) => item.level === "FAIL") ? "FAIL" : results.some((item) => item.level === "WARN") ? "WARN" : "PASS";
  return { status, results };
}

function buildExecutionPlan() {
  const workflow = currentWorkflow();
  return {
    workflow_id: workflow.id,
    workflow_name: workflow.name,
    mode: "dry-run",
    mutation: "none",
    source_api: ["/state/devices", "/state/device-source-bindings/sample"],
    graph: {
      nodes: workflow.nodes.map((node) => {
        const target = targetById(node.targetId);
        return {
          id: node.id,
          type: node.type,
          label: node.label,
          position: { x: node.x, y: node.y },
          config: { ...node.config },
          bound_target_type: target?.kind || null,
          edgex_device: target?.kind === "device" ? target.name : null,
          edgex_source: target?.kind === "device" ? target.source : null,
          edgex_profile: target?.kind === "device" ? target.profileName : null,
          edgex_device_service: target?.kind === "device" ? target.serviceName : null,
          edgex_protocols: target?.kind === "device" ? target.protocolNames : null,
          source_names: target?.kind === "device" ? target.sourceNames : null,
          resource_name: target?.kind === "device" ? resolvedWorkflowResource(node, target) || null : null,
          read_mode: target?.kind === "device" ? node.config.readMode || "history" : null,
          read_path: target?.kind !== "device"
            ? null
            : (node.config.readMode || "history").startsWith("local_")
              ? "same-node Device Service Local Data API"
              : "central EdgeX Core Data",
          sample_preview_api: target?.kind === "device" ? "/state/device-source-bindings/sample" : null,
          node_placement: target?.nodeName || null,
          admin_state: target?.kind === "device" ? target.adminState : null,
          operating_state: target?.kind === "device" ? target.operatingState : null,
          device_service_available: target?.kind === "device" ? target.deviceServiceAvailable : null,
          connection_state: target?.kind === "device" ? target.connectionState : null,
          latest_event_timestamp: target?.kind === "device" ? target.latestEventTimestamp : null,
          event_freshness: target?.kind === "device" ? target.eventFreshness : null,
          output_data: nodeTemplate(node.type)?.data || "custom",
        };
      }),
      edges: workflow.edges.map((edge) => ({ ...edge })),
    },
    validation: buildValidation().status,
  };
}

function renderWorkflowSelector() {
  const selector = workflowEl("workflowSelector");
  selector.innerHTML = workflowState.workflows.map((workflow) => `<option value="${workflowEscape(workflow.id)}">${workflowEscape(workflow.name)}</option>`).join("");
  selector.value = currentWorkflow().id;
}

function renderWorkflowSummary() {
  const workflow = currentWorkflow();
  const devices = workflowState.targets.filter((target) => target.kind === "device");
  workflowEl("workflowDeviceTotalCount").textContent = String(devices.length);
  workflowEl("workflowDeviceAvailableCount").textContent = String(devices.filter((target) => target.overallStatus === "healthy" || target.overallStatus === "available").length);
  workflowEl("workflowFreshTelemetryCount").textContent = String(devices.filter((target) => target.eventFresh).length);
  workflowEl("workflowAiHatCount").textContent = String(workflowState.targets.filter((target) => target.id === `resource:${AI_HAT_NODE}:ai-hat`).length);
  workflowEl("workflowBoundCount").textContent = `${workflow.nodes.filter((node) => node.targetId).length}/${workflow.nodes.length}`;
  workflowEl("workflowValidationSummary").textContent = buildValidation().status;
}

function renderNodePalette() {
  workflowEl("workflowNodePalette").innerHTML = NODE_TEMPLATES.map((template) => `<button class="workflow-template" type="button" data-node-template="${workflowEscape(template.type)}"><span>${workflowEscape(template.label)}</span><em>${workflowEscape(template.caption)}</em></button>`).join("");
}
