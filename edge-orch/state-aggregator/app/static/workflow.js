function graphPoint(event) {
  const canvas = workflowEl("workflowGraphCanvas").getBoundingClientRect();
  const scale = workflowState.renderedCanvasScale || workflowState.canvasScale || 1;
  return { x: (event.clientX - canvas.left + workflowEl("workflowGraphCanvas").scrollLeft) / scale, y: (event.clientY - canvas.top + workflowEl("workflowGraphCanvas").scrollTop) / scale };
}

function bindWorkflowEvents() {
  workflowEl("workflowRefresh")?.addEventListener("click", () => loadWorkflowDevices().catch(showWorkflowError));
  workflowEl("createWorkflow")?.addEventListener("click", createWorkflow);
  workflowEl("workflowSelector")?.addEventListener("change", (event) => {
    workflowState.selectedWorkflowId = event.target.value;
    workflowState.selectedNodeId = currentWorkflow().nodes[0]?.id || "";
    workflowState.linkFromNodeId = "";
    renderWorkflow();
    setWorkflowStatus(`${currentWorkflow().name} 초안을 열었습니다.`, "success");
  });
  workflowEl("startWorkflowLink")?.addEventListener("click", () => {
    workflowState.linkFromNodeId = selectedWorkflowNode()?.id || "";
    workflowEl("workflowLinkHint").textContent = workflowState.linkFromNodeId ? "연결할 target node를 클릭하세요." : "먼저 node를 선택하세요.";
    renderGraph();
    setWorkflowStatus(
      workflowState.linkFromNodeId
        ? "연결할 대상 단계를 클릭하세요."
        : "연결을 시작할 단계를 먼저 선택하세요.",
      workflowState.linkFromNodeId ? "waiting" : "warning",
    );
  });
  workflowEl("removeWorkflowLink")?.addEventListener("click", removeSelectedLink);
  workflowEl("removeWorkflowNode")?.addEventListener("click", removeSelectedNode);
  workflowEl("bindWorkflowDevice")?.addEventListener("click", bindSelectedTargetToNode);
  workflowEl("releaseWorkflowDevice")?.addEventListener("click", releaseSelectedTargetFromNode);
  workflowEl("readLatestWorkflowDevice")?.addEventListener("click", () => readLatestWorkflowDevice().catch(showWorkflowError));
  workflowEl("workflowAutoLayout")?.addEventListener("click", autoLayoutWorkflow);
  workflowEl("workflowZoomOut")?.addEventListener("click", () => setWorkflowScale(workflowState.canvasScale - 0.1));
  workflowEl("workflowZoomReset")?.addEventListener("click", () => setWorkflowScale(1));
  workflowEl("workflowZoomIn")?.addEventListener("click", () => setWorkflowScale(workflowState.canvasScale + 0.1));
  workflowEl("workflowNodePalette")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-node-template]");
    if (button) addWorkflowNode(button.getAttribute("data-node-template") || "transform");
  });
  workflowEl("workflowBindingInspector")?.addEventListener("change", (event) => {
    if (!(event.target instanceof HTMLElement)) return;
    const field = event.target.getAttribute("data-config-field");
    if (field) updateSelectedNodeConfig(field, event.target.value);
  });
  workflowEl("workflowBindingInspector")?.addEventListener("input", (event) => {
    if (!(event.target instanceof HTMLElement) || event.target.tagName === "SELECT") return;
    const field = event.target.getAttribute("data-config-field");
    if (field) updateSelectedNodeConfig(field, event.target.value);
  });
  document.querySelectorAll("[data-device-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      workflowState.selectedFilter = button.getAttribute("data-device-filter") || "all";
      document.querySelectorAll("[data-device-filter]").forEach((item) => item.classList.toggle("active", item === button));
      renderTargetPool();
      setWorkflowStatus(`${button.textContent.trim()} 필터를 적용했습니다.`, "success");
    });
  });
  bindGraphEvents();
  workflowEl("deviceSourcePool")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-target-id]");
    if (!button) return;
    workflowState.selectedTargetId = button.getAttribute("data-target-id") || "";
    renderTargetPool();
    renderInspector();
    const target = selectedWorkflowTarget();
    setWorkflowStatus(`${target?.displayName || "대상"}을(를) 선택했습니다.`, "success");
  });
}

function bindGraphEvents() {
  workflowEl("workflowGraphNodes")?.addEventListener("click", (event) => {
    const button = event.target.closest("[data-node-id]");
    if (!button || workflowState.drag?.moved) return;
    handleNodeClick(button.getAttribute("data-node-id") || "");
  });
  workflowEl("workflowGraphNodes")?.addEventListener("pointerdown", (event) => {
    const button = event.target.closest("[data-node-id]");
    if (!button) return;
    const node = currentWorkflow().nodes.find((item) => item.id === button.getAttribute("data-node-id"));
    if (!node) return;
    const point = graphPoint(event);
    workflowState.drag = { nodeId: node.id, dx: point.x - node.x, dy: point.y - node.y, moved: false };
    button.setPointerCapture(event.pointerId);
  });
  workflowEl("workflowGraphNodes")?.addEventListener("pointermove", (event) => {
    if (!workflowState.drag) return;
    const node = currentWorkflow().nodes.find((item) => item.id === workflowState.drag.nodeId);
    if (!node) return;
    const point = graphPoint(event);
    node.x = Math.max(12, Math.round(point.x - workflowState.drag.dx));
    node.y = Math.max(12, Math.round(point.y - workflowState.drag.dy));
    workflowState.drag.moved = true;
    renderGraph();
    workflowEl("workflowExecutionPlan").textContent = JSON.stringify(buildExecutionPlan(), null, 2);
  });
  workflowEl("workflowGraphNodes")?.addEventListener("pointerup", () => {
    window.setTimeout(() => {
      workflowState.drag = null;
    }, 0);
  });
}

function showWorkflowError(error) {
  setWorkflowStatus(
    error instanceof Error ? error.message : "워크플로우 API 요청에 실패했습니다.",
    "error",
  );
  renderWorkflow();
}

bindWorkflowEvents();
window.addEventListener("resize", () => {
  if (workflowEl("workflowGraphCanvas")) renderGraph();
});
loadWorkflowDevices().catch(showWorkflowError);
