(function initServiceDesigner(root) {
  const model = root?.ServiceDesignerModel;
  const viewportModel = root?.ServiceDesignerViewport;
  const STORAGE_KEY = "edge-ai-service-design-v1";
  const state = {
    design: model ? model.createDefaultDesign() : null,
    inventory: {devices: [], profiles: [], nodes: []},
    selectedNodeId: null,
    pendingFromId: null,
    selectedEdgeId: null,
    lastValidation: null,
    initialized: false,
    loadedFromStorage: false,
    liveBindingSeeded: false,
    dirty: false,
    dragging: null,
    suppressNodeClickId: null,
    panning: null,
    viewport: viewportModel
      ? viewportModel.normalizeViewport()
      : {x: 0, y: 0, zoom: 1},
    viewportInitialized: false,
    paletteOpen: true,
    resizeFrame: null,
    resizeObserver: null,
  };

  function el(id, documentRef = document) {
    return documentRef.getElementById(id);
  }

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function loadStoredDesign(storage = root?.localStorage) {
    if (!model || !storage) return null;
    try {
      const raw = storage.getItem(STORAGE_KEY);
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (!parsed || parsed.version !== model.DESIGN_VERSION) return null;
      return model.normalizeDesign(parsed);
    } catch (_error) {
      return null;
    }
  }

  function saveStoredDesign(design, storage = root?.localStorage) {
    if (!storage) return false;
    const saved = {
      ...model.normalizeDesign(design),
      updatedAt: new Date().toISOString(),
    };
    storage.setItem(STORAGE_KEY, JSON.stringify(saved));
    state.design = saved;
    state.dirty = false;
    return true;
  }

  function nodeName(node = {}) {
    return node.hostname || node.name || node.node_name || "";
  }

  function nodeSummary(node, inventory = state.inventory) {
    if (!node) return "";
    if (node.type === "sensor") {
      const device = inventory.devices.find(
        (item) => item.name === node.config.deviceName,
      );
      const resource = model.sourceResource(node, inventory);
      if (!device) return "디바이스를 선택하세요";
      if (!resource) return `${device.name} · 리소스 선택 필요`;
      return `${device.name} · ${resource.name}`;
    }
    if (node.type === "preprocess") {
      const operation = model.PREPROCESS_OPERATIONS[node.config.operation];
      return `${operation?.label || "연산 미선택"} · ${node.config.targetNode || "노드 미선택"}`;
    }
    if (node.type === "inference") {
      const algorithm = model.INFERENCE_ALGORITHMS[node.config.algorithm];
      return `${algorithm?.label || "추론 미선택"} · ${node.config.targetNode || "노드 미선택"}`;
    }
    return "대시보드 결과";
  }

  function sourceBindingCandidate(inventory = {}) {
    const devices = [...(inventory.devices || [])].sort((left, right) => {
      const leftRank = left.overall_status === "available" ? 0 : 1;
      const rightRank = right.overall_status === "available" ? 0 : 1;
      return leftRank - rightRank || String(left.name).localeCompare(String(right.name));
    });
    const preferredNames = ["acceleration", "temperature", "humidity", "pressure"];
    for (const preferred of preferredNames) {
      for (const device of devices) {
        const resource = model.resourcesForDevice(
          device,
          inventory.profiles || [],
        ).find((item) => (
          item.name.toLowerCase().includes(preferred)
          && model.canonicalDataType(item.valueType) === "number"
        ));
        if (resource) return {device, resource};
      }
    }
    for (const device of devices) {
      const resource = model.resourcesForDevice(
        device,
        inventory.profiles || [],
      ).find((item) => model.canonicalDataType(item.valueType) === "number");
      if (resource) return {device, resource};
    }
    return null;
  }

  function serverNodeName(nodes = []) {
    const server = nodes.find((node) => (
      ["cloud_server", "server"].includes(String(node.node_type || "").toLowerCase())
    ));
    return nodeName(server) || nodeName(nodes[0]);
  }

  function maybeSeedLiveBinding() {
    if (
      !model
      || state.loadedFromStorage
      || state.liveBindingSeeded
      || !state.design
    ) {
      return false;
    }
    const sensor = state.design.nodes.find((node) => node.type === "sensor");
    if (!sensor || sensor.config.deviceName) return false;
    const candidate = sourceBindingCandidate(state.inventory);
    if (!candidate) return false;
    const sourceNode = candidate.device.node_name || "";
    const sourceMode = sourceNode ? "local_recent" : "core_history";
    let next = model.updateNode(state.design, sensor.id, {
      config: {
        deviceName: candidate.device.name,
        resourceName: candidate.resource.name,
        sourceMode,
      },
    });
    const preprocess = next.nodes.find((node) => node.type === "preprocess");
    if (preprocess) {
      next = model.updateNode(next, preprocess.id, {
        config: {
          targetNode: sourceNode || serverNodeName(state.inventory.nodes),
        },
      });
    }
    const inference = next.nodes.find((node) => node.type === "inference");
    if (inference) {
      next = model.updateNode(next, inference.id, {
        config: {
          targetNode: serverNodeName(state.inventory.nodes) || sourceNode,
        },
      });
    }
    state.design = next;
    state.liveBindingSeeded = true;
    state.dirty = true;
    setFeedback(
      `${candidate.device.name} / ${candidate.resource.name}을 현재 EdgeX 입력으로 연결했습니다.`,
      "success",
    );
    return true;
  }

  function setFeedback(message, feedbackState = "ready", documentRef = document) {
    const target = el("serviceDesignerFeedback", documentRef);
    if (!target) return;
    target.textContent = message;
    target.dataset.state = feedbackState;
  }

  function setDraftState(label, draftState = "draft", documentRef = document) {
    const target = el("serviceDesignerDraftState", documentRef);
    if (!target) return;
    target.textContent = label;
    target.dataset.state = draftState;
  }

  function markDirty(message = "설계가 변경되었습니다.", documentRef = document) {
    state.dirty = true;
    state.lastValidation = null;
    state.selectedEdgeId = null;
    setDraftState("초안", "draft", documentRef);
    setFeedback(message, "ready", documentRef);
  }

  function renderMiniMap(documentRef = document) {
    if (!viewportModel || !state.design) return;
    const map = el("serviceDesignerMiniMap", documentRef);
    const nodes = el("serviceDesignerMiniMapNodes", documentRef);
    const viewportRect = el("serviceDesignerMiniMapViewport", documentRef);
    const canvasViewport = el("serviceDesignerCanvasViewport", documentRef);
    if (!map || !nodes || !viewportRect || !canvasViewport) return;
    nodes.innerHTML = state.design.nodes.map((node) => `
      <rect
        class="service-designer-minimap-node${node.id === state.selectedNodeId ? " selected" : ""}"
        x="${Number(node.x)}"
        y="${Number(node.y)}"
        width="${viewportModel.NODE_WIDTH}"
        height="${viewportModel.NODE_HEIGHT}"
        rx="18"
      ></rect>
    `).join("");
    const visible = viewportModel.visibleWorldRect(
      state.viewport,
      canvasViewport.clientWidth,
      canvasViewport.clientHeight,
    );
    const left = Math.max(0, visible.x);
    const top = Math.max(0, visible.y);
    const right = Math.min(
      viewportModel.CANVAS_WIDTH,
      visible.x + visible.width,
    );
    const bottom = Math.min(
      viewportModel.CANVAS_HEIGHT,
      visible.y + visible.height,
    );
    viewportRect.setAttribute("x", String(left));
    viewportRect.setAttribute("y", String(top));
    viewportRect.setAttribute("width", String(Math.max(0, right - left)));
    viewportRect.setAttribute("height", String(Math.max(0, bottom - top)));
  }

  function applyCanvasViewport(documentRef = document) {
    if (!viewportModel) return;
    const canvas = el("serviceDesignerCanvas", documentRef);
    const viewport = el("serviceDesignerCanvasViewport", documentRef);
    const zoomLabel = el("serviceDesignerZoomLevel", documentRef);
    if (!canvas || !viewport) return;
    state.viewport = viewportModel.normalizeViewport(state.viewport);
    canvas.style.transform = `translate(${state.viewport.x}px, ${state.viewport.y}px) scale(${state.viewport.zoom})`;
    viewport.style.setProperty(
      "--canvas-grid-size",
      `${24 * state.viewport.zoom}px`,
    );
    viewport.style.setProperty("--canvas-grid-x", `${state.viewport.x}px`);
    viewport.style.setProperty("--canvas-grid-y", `${state.viewport.y}px`);
    if (zoomLabel) {
      zoomLabel.textContent = `${Math.round(state.viewport.zoom * 100)}%`;
    }
    renderMiniMap(documentRef);
  }

  function fitCanvas(documentRef = document) {
    if (!viewportModel || !state.design) return false;
    const viewport = el("serviceDesignerCanvasViewport", documentRef);
    if (!viewport || viewport.clientWidth < 80 || viewport.clientHeight < 80) {
      return false;
    }
    const inspector = el("serviceDesignerInspector", documentRef);
    const rightInset = inspector?.classList.contains("is-open")
      && viewport.clientWidth >= 720
      ? Math.min(350, viewport.clientWidth * 0.38)
      : 0;
    state.viewport = viewportModel.fitViewport(
      state.design.nodes,
      viewport.clientWidth,
      viewport.clientHeight,
      {
        padding: viewport.clientWidth < 520 ? 24 : 44,
        rightInset,
      },
    );
    state.viewportInitialized = true;
    applyCanvasViewport(documentRef);
    return true;
  }

  function scheduleCanvasFit(documentRef = document) {
    if (!root?.requestAnimationFrame) return;
    if (state.resizeFrame) root.cancelAnimationFrame?.(state.resizeFrame);
    state.resizeFrame = root.requestAnimationFrame(() => {
      state.resizeFrame = null;
      fitCanvas(documentRef);
    });
  }

  function revealCanvasNode(nodeId, documentRef = document) {
    if (!viewportModel || !state.design) return false;
    const node = state.design.nodes.find((item) => item.id === nodeId);
    const viewport = el("serviceDesignerCanvasViewport", documentRef);
    if (!node || !viewport) return false;
    const inspector = el("serviceDesignerInspector", documentRef);
    const rightInset = inspector?.classList.contains("is-open")
      && viewport.clientWidth >= 720
      ? Math.min(350, viewport.clientWidth * 0.38)
      : 0;
    state.viewport = viewportModel.ensureWorldRectVisible(
      state.viewport,
      {
        x: node.x,
        y: node.y,
        width: viewportModel.NODE_WIDTH,
        height: viewportModel.NODE_HEIGHT,
      },
      viewport.clientWidth,
      viewport.clientHeight,
      {
        padding: viewport.clientWidth < 520 ? 20 : 36,
        rightInset,
      },
    );
    applyCanvasViewport(documentRef);
    return true;
  }

  function setPaletteOpen(open, documentRef = document) {
    state.paletteOpen = Boolean(open);
    const workbench = el("serviceDesignerWorkbench", documentRef);
    const toggle = el("serviceDesignerPaletteToggle", documentRef);
    workbench?.classList.toggle("palette-open", state.paletteOpen);
    toggle?.setAttribute("aria-expanded", String(state.paletteOpen));
    scheduleCanvasFit(documentRef);
  }

  function zoomCanvasBy(delta, documentRef = document) {
    if (!viewportModel) return;
    const viewport = el("serviceDesignerCanvasViewport", documentRef);
    if (!viewport) return;
    const nextZoom = state.viewport.zoom * delta;
    state.viewport = viewportModel.zoomAtPoint(
      state.viewport,
      viewport.clientWidth / 2,
      viewport.clientHeight / 2,
      nextZoom,
    );
    state.viewportInitialized = true;
    applyCanvasViewport(documentRef);
  }

  function centerCanvasFromMiniMap(event, documentRef = document) {
    if (!viewportModel) return;
    const map = el("serviceDesignerMiniMap", documentRef);
    const viewport = el("serviceDesignerCanvasViewport", documentRef);
    if (!map || !viewport) return;
    const bounds = map.getBoundingClientRect();
    if (!bounds.width || !bounds.height) return;
    const worldX = (
      (event.clientX - bounds.left) / bounds.width
    ) * viewportModel.CANVAS_WIDTH;
    const worldY = (
      (event.clientY - bounds.top) / bounds.height
    ) * viewportModel.CANVAS_HEIGHT;
    state.viewport = viewportModel.centerOnWorldPoint(
      state.viewport,
      worldX,
      worldY,
      viewport.clientWidth,
      viewport.clientHeight,
    );
    state.viewportInitialized = true;
    applyCanvasViewport(documentRef);
  }

  function startCanvasPan(event, documentRef = document) {
    if (!viewportModel || ![0, 1].includes(event.button)) return;
    const viewport = el("serviceDesignerCanvasViewport", documentRef);
    if (!viewport || !event.target.closest?.("#serviceDesignerCanvasViewport")) {
      return;
    }
    const interactive = event.target.closest?.(
      "[data-designer-node], [data-designer-remove-edge], button, input, select, textarea",
    );
    if (event.button === 0 && interactive) return;
    state.panning = {
      startClientX: event.clientX,
      startClientY: event.clientY,
      startViewport: {...state.viewport},
    };
    viewport.classList.add("is-panning");
    event.preventDefault();
  }

  function moveCanvasPan(event, documentRef = document) {
    if (!state.panning || !viewportModel) return false;
    state.viewport = viewportModel.panViewport(
      state.panning.startViewport,
      event.clientX - state.panning.startClientX,
      event.clientY - state.panning.startClientY,
    );
    state.viewportInitialized = true;
    applyCanvasViewport(documentRef);
    event.preventDefault();
    return true;
  }

  function finishCanvasPan(documentRef = document) {
    if (!state.panning) return false;
    state.panning = null;
    el("serviceDesignerCanvasViewport", documentRef)?.classList.remove(
      "is-panning",
    );
    return true;
  }

  function handleCanvasWheel(event, documentRef = document) {
    if (!viewportModel) return;
    const viewport = el("serviceDesignerCanvasViewport", documentRef);
    if (!viewport) return;
    const bounds = viewport.getBoundingClientRect();
    const factor = Math.exp(-event.deltaY * 0.0014);
    state.viewport = viewportModel.zoomAtPoint(
      state.viewport,
      event.clientX - bounds.left,
      event.clientY - bounds.top,
      state.viewport.zoom * factor,
    );
    state.viewportInitialized = true;
    applyCanvasViewport(documentRef);
    event.preventDefault();
  }

  function optionMarkup(value, label, selectedValue, disabled = false) {
    return `<option value="${escapeHtml(value)}"${value === selectedValue ? " selected" : ""}${disabled ? " disabled" : ""}>${escapeHtml(label)}</option>`;
  }

  function renderNodes(documentRef = document) {
    const container = el("serviceDesignerNodes", documentRef);
    if (!container || !state.design) return;
    const errorNodeIds = new Set(
      (state.lastValidation?.errors || [])
        .map((issue) => issue.nodeId)
        .filter(Boolean),
    );
    container.innerHTML = state.design.nodes.map((node) => {
      const definition = model.nodeDefinition(node.type);
      const selected = state.selectedNodeId === node.id;
      const pending = state.pendingFromId === node.id;
      const outputType = model.nodeOutputType(node, state.inventory);
      const inputType = model.nodeInputType(node);
      return `
        <article
          class="service-designer-node${selected ? " selected" : ""}"
          data-designer-node="${escapeHtml(node.id)}"
          data-node-type="${escapeHtml(node.type)}"
          data-validity="${errorNodeIds.has(node.id) ? "error" : "ready"}"
          style="left:${Number(node.x)}px;top:${Number(node.y)}px"
          tabindex="0"
          aria-label="${escapeHtml(`${node.title}: ${nodeSummary(node)}`)}"
        >
          ${definition.acceptsInput ? `
            <button
              class="service-designer-port input"
              type="button"
              data-designer-input="${escapeHtml(node.id)}"
              aria-label="${escapeHtml(`${node.title} ${inputType} 입력 포트`)}"
              title="${escapeHtml(`${inputType} 입력`)}"
            ></button>
          ` : ""}
          <div class="service-designer-node-head" data-designer-drag="${escapeHtml(node.id)}">
            <div>
              <span>${escapeHtml(definition.shortLabel)}</span>
              <strong>${escapeHtml(node.title)}</strong>
            </div>
            <button
              class="service-designer-node-delete"
              type="button"
              data-designer-delete="${escapeHtml(node.id)}"
              aria-label="${escapeHtml(`${node.title} 단계 삭제`)}"
            >삭제</button>
          </div>
          <div class="service-designer-node-body">
            <p>${escapeHtml(nodeSummary(node))}</p>
            <small>${escapeHtml(definition.description)}</small>
          </div>
          ${definition.providesOutput ? `
            <button
              class="service-designer-port output${pending ? " pending" : ""}"
              type="button"
              data-designer-output="${escapeHtml(node.id)}"
              aria-label="${escapeHtml(`${node.title} ${outputType} 출력 포트`)}"
              aria-pressed="${pending ? "true" : "false"}"
              title="${escapeHtml(`${outputType} 출력`)}"
            ></button>
          ` : ""}
        </article>
      `;
    }).join("");
  }

  function edgePath(fromNode, toNode) {
    const x1 = Number(fromNode.x) + 218;
    const y1 = Number(fromNode.y) + 78;
    const x2 = Number(toNode.x);
    const y2 = Number(toNode.y) + 78;
    const bend = Math.max(70, Math.abs(x2 - x1) * 0.42);
    return {
      d: `M ${x1} ${y1} C ${x1 + bend} ${y1}, ${x2 - bend} ${y2}, ${x2} ${y2}`,
      labelX: (x1 + x2) / 2,
      labelY: (y1 + y2) / 2 - 9,
    };
  }

  function renderEdges(documentRef = document) {
    const container = el("serviceDesignerEdges", documentRef);
    if (!container || !state.design) return;
    const nodes = Object.fromEntries(
      state.design.nodes.map((node) => [node.id, node]),
    );
    container.innerHTML = `
      <defs>
        <marker id="serviceDesignerArrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
          <path d="M 0 0 L 10 5 L 0 10 z" fill="#64748b"></path>
        </marker>
      </defs>
      ${state.design.edges.map((edge) => {
        const from = nodes[edge.from];
        const to = nodes[edge.to];
        if (!from || !to) return "";
        const path = edgePath(from, to);
        const selected = state.selectedEdgeId === edge.id;
        return `
          <g class="service-designer-edge-group" data-designer-edge="${escapeHtml(edge.id)}">
            <path class="service-designer-edge-path${selected ? " selected" : ""}" d="${path.d}" marker-end="url(#serviceDesignerArrow)"></path>
            <path
              class="service-designer-edge-target"
              d="${path.d}"
              data-designer-remove-edge="${escapeHtml(edge.id)}"
              aria-label="연결 삭제"
            ></path>
            ${selected ? `<text class="service-designer-edge-label" x="${path.labelX}" y="${path.labelY}">클릭하여 삭제</text>` : ""}
          </g>
        `;
      }).join("")}
    `;
  }

  function renderSensorInspector(node) {
    const devices = [...state.inventory.devices].sort(
      (left, right) => String(left.name).localeCompare(String(right.name)),
    );
    const selectedDevice = devices.find(
      (device) => device.name === node.config.deviceName,
    );
    const resources = model.resourcesForDevice(
      selectedDevice,
      state.inventory.profiles,
    );
    const resource = resources.find(
      (item) => item.name === node.config.resourceName,
    );
    return `
      <label class="service-designer-field">
        <span>센서 디바이스</span>
        <select data-designer-config="deviceName">
          ${optionMarkup("", "선택", node.config.deviceName)}
          ${devices.map((device) => optionMarkup(
            device.name,
            `${device.name} · ${device.overall_status || "unknown"}`,
            node.config.deviceName,
          )).join("")}
        </select>
      </label>
      <label class="service-designer-field">
        <span>DeviceResource</span>
        <select data-designer-config="resourceName"${selectedDevice ? "" : " disabled"}>
          ${optionMarkup("", "선택", node.config.resourceName)}
          ${resources.map((item) => optionMarkup(
            item.name,
            `${item.name} · ${item.valueType}${item.units ? ` · ${item.units}` : ""}`,
            node.config.resourceName,
          )).join("")}
        </select>
      </label>
      <label class="service-designer-field">
        <span>데이터 접근</span>
        <select data-designer-config="sourceMode">
          ${Object.entries(model.SOURCE_MODES).map(([value, item]) => (
            optionMarkup(value, item.label, node.config.sourceMode)
          )).join("")}
        </select>
        <small>${escapeHtml(model.SOURCE_MODES[node.config.sourceMode]?.description || "")}</small>
      </label>
      <p class="service-designer-binding-status">
        <strong>${escapeHtml(selectedDevice?.name || "바인딩 없음")}</strong>
        <span>노드 ${escapeHtml(selectedDevice?.node_name || "미확인")}</span>
        <span>Profile ${escapeHtml(selectedDevice?.profile_name || "미확인")}</span>
        <span>출력 ${escapeHtml(model.canonicalDataType(resource?.valueType))}</span>
      </p>
    `;
  }

  function targetNodeOptions(selectedValue) {
    const nodes = [...state.inventory.nodes].sort(
      (left, right) => nodeName(left).localeCompare(nodeName(right)),
    );
    return [
      optionMarkup("", "선택", selectedValue),
      ...nodes.map((node) => {
        const name = nodeName(node);
        const health = node.node_health || "unknown";
        return optionMarkup(name, `${name} · ${health}`, selectedValue);
      }),
    ].join("");
  }

  function renderPreprocessInspector(node) {
    return `
      <label class="service-designer-field">
        <span>연산</span>
        <select data-designer-config="operation">
          ${Object.entries(model.PREPROCESS_OPERATIONS).map(([value, item]) => (
            optionMarkup(value, item.label, node.config.operation)
          )).join("")}
        </select>
      </label>
      <label class="service-designer-field">
        <span>실행 노드</span>
        <select data-designer-config="targetNode">
          ${targetNodeOptions(node.config.targetNode)}
        </select>
      </label>
      <label class="service-designer-field">
        <span>윈도우 크기</span>
        <input data-designer-config="windowSize" data-designer-number type="number" min="1" max="10000" value="${escapeHtml(node.config.windowSize || 30)}" />
      </label>
    `;
  }

  function renderInferenceInspector(node) {
    return `
      <label class="service-designer-field">
        <span>추론 방식</span>
        <select data-designer-config="algorithm">
          ${Object.entries(model.INFERENCE_ALGORITHMS).map(([value, item]) => (
            optionMarkup(value, item.label, node.config.algorithm)
          )).join("")}
        </select>
      </label>
      <label class="service-designer-field">
        <span>실행 노드</span>
        <select data-designer-config="targetNode">
          ${targetNodeOptions(node.config.targetNode)}
        </select>
      </label>
      <label class="service-designer-field">
        <span>임계값</span>
        <input data-designer-config="threshold" data-designer-number type="number" step="0.1" min="0" value="${escapeHtml(node.config.threshold ?? 4)}" />
      </label>
    `;
  }

  function renderInspector(documentRef = document) {
    const inspector = el("serviceDesignerInspector", documentRef);
    const title = el("serviceDesignerInspectorTitle", documentRef);
    const body = el("serviceDesignerInspectorBody", documentRef);
    if (!inspector || !title || !body || !state.design) return;
    const node = state.design.nodes.find(
      (item) => item.id === state.selectedNodeId,
    );
    inspector.classList.toggle("is-open", Boolean(node));
    inspector.setAttribute("aria-hidden", String(!node));
    if (!node) {
      title.textContent = "단계 선택";
      body.innerHTML = '<p class="service-designer-empty">캔버스에서 단계를 선택하세요.</p>';
      return;
    }
    title.textContent = node.title;
    const common = `
      <label class="service-designer-field">
        <span>표시 이름</span>
        <input data-designer-title type="text" maxlength="80" value="${escapeHtml(node.title)}" />
      </label>
    `;
    let fields = "";
    if (node.type === "sensor") fields = renderSensorInspector(node);
    if (node.type === "preprocess") fields = renderPreprocessInspector(node);
    if (node.type === "inference") fields = renderInferenceInspector(node);
    if (node.type === "output") {
      fields = `
        <label class="service-designer-field">
          <span>결과 대상</span>
          <select data-designer-config="destination" disabled>
            ${optionMarkup("dashboard", "대시보드", node.config.destination)}
          </select>
          <small>현재 PoC는 설계 결과 미리보기만 제공합니다.</small>
        </label>
      `;
    }
    body.innerHTML = `${common}${fields}`;
  }

  function renderValidation(documentRef = document) {
    const container = el("serviceDesignerValidation", documentRef);
    const summary = el("serviceDesignerValidationSummary", documentRef);
    if (!container || !summary) return;
    if (!state.lastValidation) {
      summary.textContent = state.dirty ? "재검증 필요" : "검증 전";
      container.innerHTML = '<p class="service-designer-empty">설계 검증을 누르면 연결과 배치를 확인합니다.</p>';
      return;
    }
    const {errors, warnings} = state.lastValidation;
    summary.textContent = errors.length
      ? `오류 ${errors.length} · 주의 ${warnings.length}`
      : warnings.length
        ? `통과 · 주의 ${warnings.length}`
        : "통과";
    if (!errors.length && !warnings.length) {
      container.innerHTML = `
        <div class="service-designer-issue" data-level="success">
          <strong>통과</strong>
          <span>입력, 연결, 타입과 실행 노드가 현재 관측 정보와 일치합니다.</span>
        </div>
      `;
      return;
    }
    container.innerHTML = [...errors.map((issue) => ({...issue, level: "error"})), ...warnings.map((issue) => ({...issue, level: "warning"}))]
      .map((issue) => `
        <button
          class="service-designer-issue"
          type="button"
          data-level="${issue.level}"
          ${issue.nodeId ? `data-designer-select-issue="${escapeHtml(issue.nodeId)}"` : ""}
        >
          <strong>${issue.level === "error" ? "오류" : "주의"}</strong>
          <span>${escapeHtml(issue.message)}</span>
        </button>
      `)
      .join("");
  }

  function renderPlan(documentRef = document) {
    const container = el("serviceDesignerPlan", documentRef);
    if (!container) return;
    if (!state.lastValidation) {
      container.innerHTML = '<li class="service-designer-empty">설계를 검증하면 단계 순서를 표시합니다.</li>';
      return;
    }
    const plan = model.buildExecutionPlan(state.design, state.inventory);
    container.innerHTML = plan.stages.map((stage) => `
      <li>
        <b>${stage.order}</b>
        <span>
          <strong>${escapeHtml(stage.label)}</strong>
          <small>${escapeHtml(stage.detail)}</small>
        </span>
        <small>${escapeHtml(stage.outputType === "none" ? "result" : stage.outputType)}</small>
      </li>
    `).join("");
  }

  function renderInventoryState(documentRef = document) {
    const target = el("serviceDesignerInventoryState", documentRef);
    if (!target) return;
    const profileSuffix = state.inventory.profiles.length
      ? ` · Profile ${state.inventory.profiles.length}개`
      : " · Profile 확인 중";
    target.textContent = `센서 ${state.inventory.devices.length}개 · 노드 ${state.inventory.nodes.length}개${profileSuffix}`;
  }

  function renderAll(documentRef = document) {
    if (!state.initialized || !state.design) return;
    const nameInput = el("serviceDesignerName", documentRef);
    if (nameInput && nameInput.value !== state.design.name) {
      nameInput.value = state.design.name;
    }
    renderInventoryState(documentRef);
    renderNodes(documentRef);
    renderEdges(documentRef);
    renderInspector(documentRef);
    renderValidation(documentRef);
    renderPlan(documentRef);
    if (state.viewportInitialized) {
      applyCanvasViewport(documentRef);
    } else {
      scheduleCanvasFit(documentRef);
    }
  }

  function selectNode(
    nodeId,
    documentRef = document,
    fitForInspector = true,
  ) {
    if (!state.design.nodes.some((node) => node.id === nodeId)) return;
    state.selectedNodeId = nodeId;
    state.selectedEdgeId = null;
    renderNodes(documentRef);
    renderEdges(documentRef);
    renderInspector(documentRef);
    renderMiniMap(documentRef);
    if (fitForInspector) revealCanvasNode(nodeId, documentRef);
  }

  function handleOutputPort(nodeId, documentRef = document) {
    state.pendingFromId = state.pendingFromId === nodeId ? null : nodeId;
    if (state.pendingFromId) {
      const node = state.design.nodes.find((item) => item.id === nodeId);
      setFeedback(
        `${node?.title || "단계"} 출력 선택됨 · 연결할 입력 포트를 누르세요.`,
        "connecting",
        documentRef,
      );
    } else {
      setFeedback("연결 선택을 취소했습니다.", "ready", documentRef);
    }
    renderNodes(documentRef);
  }

  function handleInputPort(nodeId, documentRef = document) {
    if (!state.pendingFromId) {
      setFeedback("먼저 연결할 출력 포트를 누르세요.", "error", documentRef);
      return;
    }
    const result = model.connectNodes(
      state.design,
      state.pendingFromId,
      nodeId,
      state.inventory,
    );
    if (result.error) {
      setFeedback(result.error, "error", documentRef);
      return;
    }
    state.design = result.design;
    state.pendingFromId = null;
    markDirty("단계를 연결했습니다.", documentRef);
    renderAll(documentRef);
  }

  function handleConfigChange(target, documentRef = document) {
    const node = state.design.nodes.find(
      (item) => item.id === state.selectedNodeId,
    );
    if (!node) return;
    if (target.matches("[data-designer-title]")) {
      state.design = model.updateNode(state.design, node.id, {
        title: target.value.trim() || model.nodeDefinition(node.type).label,
      });
      markDirty("단계 이름을 변경했습니다.", documentRef);
      renderNodes(documentRef);
      return;
    }
    const key = target.dataset.designerConfig;
    if (!key) return;
    let value = target.value;
    if (target.hasAttribute("data-designer-number")) {
      value = Number(value);
    }
    const config = {[key]: value};
    if (key === "deviceName") config.resourceName = "";
    state.design = model.updateNode(state.design, node.id, {config});
    markDirty("단계 설정을 변경했습니다.", documentRef);
    renderAll(documentRef);
  }

  function validateCurrentDesign(documentRef = document) {
    state.lastValidation = model.validateDesign(state.design, state.inventory);
    const reviewPanel = el("serviceDesignerReviewPanel", documentRef);
    if (reviewPanel) reviewPanel.open = true;
    const valid = state.lastValidation.valid;
    setDraftState(valid ? "검증됨" : "수정 필요", valid ? "valid" : "invalid", documentRef);
    setFeedback(
      valid
        ? state.lastValidation.warnings.length
          ? `검증을 통과했습니다. 주의 ${state.lastValidation.warnings.length}건을 확인하세요.`
          : "검증을 통과했습니다. 실행 계획은 미리보기이며 배포되지 않습니다."
        : `오류 ${state.lastValidation.errors.length}건을 수정하세요.`,
      valid ? "success" : "error",
      documentRef,
    );
    renderNodes(documentRef);
    renderValidation(documentRef);
    renderPlan(documentRef);
    return state.lastValidation;
  }

  function updateInventory(data = {}, documentRef = document) {
    state.inventory.devices = Array.isArray(data.devices) ? data.devices : [];
    state.inventory.nodes = Array.isArray(data.nodes) ? data.nodes : [];
    maybeSeedLiveBinding();
    renderAll(documentRef);
  }

  async function fetchDesignerProfiles(fetchFn = fetch) {
    const response = await fetchFn("/state/device-profiles", {cache: "no-store"});
    if (!response.ok) {
      throw new Error(`Device Profile API 오류 (${response.status})`);
    }
    const payload = await response.json();
    if (!Array.isArray(payload)) {
      throw new Error("Device Profile 응답 형식이 올바르지 않습니다.");
    }
    return payload;
  }

  async function refreshProfiles(
    fetchFn = fetch,
    documentRef = document,
  ) {
    try {
      state.inventory.profiles = await fetchDesignerProfiles(fetchFn);
      maybeSeedLiveBinding();
      renderAll(documentRef);
      return true;
    } catch (error) {
      renderInventoryState(documentRef);
      setFeedback(
        error instanceof Error ? error.message : "Device Profile을 조회하지 못했습니다.",
        "error",
        documentRef,
      );
      return false;
    }
  }

  async function refreshInventory(
    fetchFn = fetch,
    documentRef = document,
  ) {
    try {
      const response = await fetchFn("/state/dashboard", {cache: "no-store"});
      if (!response.ok) throw new Error(`Dashboard API 오류 (${response.status})`);
      const payload = await response.json();
      updateInventory(payload, documentRef);
      return true;
    } catch (error) {
      setFeedback(
        error instanceof Error ? error.message : "EdgeX 정보를 조회하지 못했습니다.",
        "error",
        documentRef,
      );
      return false;
    }
  }

  function renderDragGuides(guides = {}, documentRef = document) {
    const vertical = el("serviceDesignerGuideVertical", documentRef);
    const horizontal = el("serviceDesignerGuideHorizontal", documentRef);
    if (vertical) {
      const visible = Number.isFinite(guides.vertical);
      vertical.hidden = !visible;
      if (visible) vertical.style.left = `${guides.vertical}px`;
    }
    if (horizontal) {
      const visible = Number.isFinite(guides.horizontal);
      horizontal.hidden = !visible;
      if (visible) horizontal.style.top = `${guides.horizontal}px`;
    }
  }

  function selectNodeForDrag(nodeId, nodeElement, documentRef = document) {
    state.selectedNodeId = nodeId;
    state.selectedEdgeId = null;
    documentRef.querySelectorAll("[data-designer-node]").forEach((element) => {
      element.classList.toggle(
        "selected",
        element.dataset.designerNode === nodeId,
      );
    });
    renderEdges(documentRef);
    renderInspector(documentRef);
    renderMiniMap(documentRef);
    try {
      nodeElement.focus({preventScroll: true});
    } catch (_error) {
      nodeElement.focus?.();
    }
  }

  function startDrag(event, nodeId, documentRef = document) {
    if (event.button !== 0 || event.target.closest?.("button")) return;
    const node = state.design.nodes.find((item) => item.id === nodeId);
    const nodeElement = event.target.closest?.("[data-designer-node]");
    if (!node || !nodeElement) return;
    state.dragging = {
      nodeId,
      nodeElement,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: Number(node.x),
      startY: Number(node.y),
      x: Number(node.x),
      y: Number(node.y),
      pointerId: event.pointerId,
      moved: false,
    };
    selectNodeForDrag(nodeId, nodeElement, documentRef);
    try {
      nodeElement.setPointerCapture?.(event.pointerId);
    } catch (_error) {
      // Pointer capture is an enhancement; window listeners remain the fallback.
    }
    event.preventDefault();
  }

  function moveDrag(event, documentRef = document) {
    if (
      !state.dragging
      || (
        Number.isFinite(state.dragging.pointerId)
        && event.pointerId !== state.dragging.pointerId
      )
    ) {
      return false;
    }
    const deltaClientX = event.clientX - state.dragging.startClientX;
    const deltaClientY = event.clientY - state.dragging.startClientY;
    if (
      !state.dragging.moved
      && Math.hypot(deltaClientX, deltaClientY) < 5
    ) {
      return false;
    }
    if (!state.dragging.moved) {
      state.dragging.moved = true;
      state.dragging.nodeElement.classList.add("is-dragging");
      el("serviceDesignerCanvasViewport", documentRef)?.classList.add(
        "is-node-dragging",
      );
    }
    const zoom = Math.max(0.01, Number(state.viewport.zoom) || 1);
    const constrained = viewportModel.constrainNodePosition(
      {x: state.dragging.startX, y: state.dragging.startY},
      {
        x: state.dragging.startX + deltaClientX / zoom,
        y: state.dragging.startY + deltaClientY / zoom,
      },
      event.shiftKey,
    );
    const placement = viewportModel.snapNodePosition(
      constrained,
      state.design.nodes,
      state.dragging.nodeId,
      {
        snap: !event.altKey,
        tolerance: viewportModel.SNAP_TOLERANCE / zoom,
        lockX: constrained.lockedAxis === "vertical",
        lockY: constrained.lockedAxis === "horizontal",
      },
    );
    const {x, y} = placement;
    state.dragging.x = x;
    state.dragging.y = y;
    state.dragging.nodeElement.style.left = `${x}px`;
    state.dragging.nodeElement.style.top = `${y}px`;
    renderDragGuides(placement.guides, documentRef);
    const node = state.design.nodes.find((item) => item.id === state.dragging.nodeId);
    if (node) {
      const previousX = node.x;
      const previousY = node.y;
      node.x = x;
      node.y = y;
      renderEdges(documentRef);
      renderMiniMap(documentRef);
      node.x = previousX;
      node.y = previousY;
    }
    event.preventDefault();
    return true;
  }

  function finishDrag(
    event,
    documentRef = document,
    cancelled = false,
  ) {
    if (!state.dragging) return false;
    const drag = state.dragging;
    if (
      Number.isFinite(drag.pointerId)
      && Number.isFinite(event?.pointerId)
      && event.pointerId !== drag.pointerId
    ) {
      return false;
    }
    state.dragging = null;
    drag.nodeElement.classList.remove("is-dragging");
    el("serviceDesignerCanvasViewport", documentRef)?.classList.remove(
      "is-node-dragging",
    );
    renderDragGuides({}, documentRef);
    try {
      if (drag.nodeElement.hasPointerCapture?.(drag.pointerId)) {
        drag.nodeElement.releasePointerCapture(drag.pointerId);
      }
    } catch (_error) {
      // The browser may already have released capture on pointercancel.
    }
    if (!drag.moved || cancelled) {
      drag.nodeElement.style.left = `${drag.startX}px`;
      drag.nodeElement.style.top = `${drag.startY}px`;
      if (drag.moved) {
        renderEdges(documentRef);
        renderMiniMap(documentRef);
      }
      return false;
    }
    const x = Math.round(drag.x * 100) / 100;
    const y = Math.round(drag.y * 100) / 100;
    state.suppressNodeClickId = drag.nodeId;
    root.setTimeout?.(() => {
      if (state.suppressNodeClickId === drag.nodeId) {
        state.suppressNodeClickId = null;
      }
    }, 0);
    if (x === drag.startX && y === drag.startY) return true;
    state.design = model.updateNode(state.design, drag.nodeId, {x, y});
    markDirty("단계 위치를 변경했습니다.", documentRef);
    renderEdges(documentRef);
    renderMiniMap(documentRef);
    event?.preventDefault?.();
    return true;
  }

  function moveSelectedNodeByKeyboard(event, documentRef = document) {
    if (
      !["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown"].includes(event.key)
      || !state.selectedNodeId
      || event.target.matches?.("input, select, textarea, button")
      || event.target.isContentEditable
      || !event.target.closest?.(".service-designer-page")
    ) {
      return false;
    }
    const node = state.design.nodes.find(
      (item) => item.id === state.selectedNodeId,
    );
    if (!node) return false;
    const next = viewportModel.nudgeNodePosition(
      node,
      event.key,
      event.shiftKey,
    );
    event.preventDefault();
    if (next.x === node.x && next.y === node.y) return true;
    state.design = model.updateNode(state.design, node.id, next);
    const nodeElement = [...documentRef.querySelectorAll("[data-designer-node]")]
      .find((element) => element.dataset.designerNode === node.id);
    if (nodeElement) {
      nodeElement.style.left = `${next.x}px`;
      nodeElement.style.top = `${next.y}px`;
    }
    markDirty(
      event.shiftKey
        ? "단계를 그리드 한 칸 이동했습니다."
        : "단계를 미세 이동했습니다.",
      documentRef,
    );
    renderEdges(documentRef);
    renderMiniMap(documentRef);
    return true;
  }

  function bindEvents(documentRef = document) {
    documentRef.addEventListener("click", (event) => {
      const suppressedNode = event.target.closest?.("[data-designer-node]");
      if (
        suppressedNode
        && state.suppressNodeClickId === suppressedNode.dataset.designerNode
      ) {
        state.suppressNodeClickId = null;
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      const addButton = event.target.closest?.("[data-designer-add]");
      if (addButton) {
        state.design = model.addNode(state.design, addButton.dataset.designerAdd);
        const added = state.design.nodes[state.design.nodes.length - 1];
        state.selectedNodeId = added.id;
        markDirty(`${added.title} 단계를 추가했습니다.`, documentRef);
        renderAll(documentRef);
        if (root.matchMedia?.("(max-width: 860px)").matches) {
          setPaletteOpen(false, documentRef);
        }
        scheduleCanvasFit(documentRef);
        return;
      }
      const deleteButton = event.target.closest?.("[data-designer-delete]");
      if (deleteButton) {
        const nodeId = deleteButton.dataset.designerDelete;
        state.design = model.removeNode(state.design, nodeId);
        if (state.selectedNodeId === nodeId) state.selectedNodeId = null;
        if (state.pendingFromId === nodeId) state.pendingFromId = null;
        markDirty("단계를 삭제했습니다.", documentRef);
        renderAll(documentRef);
        scheduleCanvasFit(documentRef);
        return;
      }
      const outputPort = event.target.closest?.("[data-designer-output]");
      if (outputPort) {
        handleOutputPort(outputPort.dataset.designerOutput, documentRef);
        return;
      }
      const inputPort = event.target.closest?.("[data-designer-input]");
      if (inputPort) {
        handleInputPort(inputPort.dataset.designerInput, documentRef);
        return;
      }
      const edgeTarget = event.target.closest?.("[data-designer-remove-edge]");
      if (edgeTarget) {
        const edgeId = edgeTarget.dataset.designerRemoveEdge;
        if (state.selectedEdgeId !== edgeId) {
          state.selectedEdgeId = edgeId;
          setFeedback("연결을 다시 누르면 삭제합니다.", "ready", documentRef);
          renderEdges(documentRef);
          return;
        }
        state.design = model.removeEdge(state.design, edgeId);
        state.selectedEdgeId = null;
        markDirty("연결을 삭제했습니다.", documentRef);
        renderAll(documentRef);
        return;
      }
      const issue = event.target.closest?.("[data-designer-select-issue]");
      if (issue) {
        selectNode(issue.dataset.designerSelectIssue, documentRef);
        return;
      }
      const nodeTarget = event.target.closest?.("[data-designer-node]");
      if (nodeTarget) {
        selectNode(nodeTarget.dataset.designerNode, documentRef);
      }
    });

    documentRef.addEventListener("pointerdown", (event) => {
      const dragNode = event.target.closest?.("[data-designer-node]");
      if (dragNode) {
        startDrag(event, dragNode.dataset.designerNode, documentRef);
        return;
      }
      startCanvasPan(event, documentRef);
    });
    root.addEventListener("pointermove", (event) => {
      if (!moveCanvasPan(event, documentRef)) moveDrag(event, documentRef);
    });
    root.addEventListener("pointerup", (event) => {
      finishCanvasPan(documentRef);
      finishDrag(event, documentRef);
    });
    root.addEventListener("pointercancel", (event) => {
      finishCanvasPan(documentRef);
      finishDrag(event, documentRef, true);
    });

    el("serviceDesignerCanvasViewport", documentRef)?.addEventListener(
      "wheel",
      (event) => handleCanvasWheel(event, documentRef),
      {passive: false},
    );
    el("serviceDesignerPaletteToggle", documentRef)?.addEventListener(
      "click",
      () => setPaletteOpen(!state.paletteOpen, documentRef),
    );
    el("serviceDesignerPaletteClose", documentRef)?.addEventListener(
      "click",
      () => setPaletteOpen(false, documentRef),
    );
    el("serviceDesignerInspectorClose", documentRef)?.addEventListener(
      "click",
      () => {
        state.selectedNodeId = null;
        renderNodes(documentRef);
        renderInspector(documentRef);
        renderMiniMap(documentRef);
        scheduleCanvasFit(documentRef);
      },
    );
    el("serviceDesignerFitView", documentRef)?.addEventListener(
      "click",
      () => fitCanvas(documentRef),
    );
    el("serviceDesignerZoomReset", documentRef)?.addEventListener(
      "click",
      () => fitCanvas(documentRef),
    );
    el("serviceDesignerZoomIn", documentRef)?.addEventListener(
      "click",
      () => zoomCanvasBy(1.2, documentRef),
    );
    el("serviceDesignerZoomOut", documentRef)?.addEventListener(
      "click",
      () => zoomCanvasBy(1 / 1.2, documentRef),
    );
    el("serviceDesignerMiniMap", documentRef)?.addEventListener(
      "click",
      (event) => centerCanvasFromMiniMap(event, documentRef),
    );
    el("serviceDesignerMiniMap", documentRef)?.addEventListener(
      "keydown",
      (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          fitCanvas(documentRef);
        }
      },
    );

    el("serviceDesignerInspectorBody", documentRef)?.addEventListener(
      "change",
      (event) => handleConfigChange(event.target, documentRef),
    );
    el("serviceDesignerInspectorBody", documentRef)?.addEventListener(
      "input",
      (event) => {
        if (event.target.matches("[data-designer-title]")) {
          handleConfigChange(event.target, documentRef);
        }
      },
    );
    el("serviceDesignerName", documentRef)?.addEventListener("input", (event) => {
      state.design = {
        ...state.design,
        name: event.target.value,
      };
      markDirty("서비스 이름을 변경했습니다.", documentRef);
    });
    el("serviceDesignerPaletteSearch", documentRef)?.addEventListener(
      "input",
      (event) => {
        const query = event.target.value.trim().toLowerCase();
        documentRef.querySelectorAll("[data-designer-add]").forEach((button) => {
          button.hidden = Boolean(query) && !button.textContent.toLowerCase().includes(query);
        });
      },
    );
    el("serviceDesignerValidate", documentRef)?.addEventListener(
      "click",
      () => validateCurrentDesign(documentRef),
    );
    el("serviceDesignerSave", documentRef)?.addEventListener("click", () => {
      try {
        saveStoredDesign(state.design);
        setDraftState("저장됨", "saved", documentRef);
        setFeedback("현재 초안을 이 브라우저에 저장했습니다.", "success", documentRef);
      } catch (_error) {
        setFeedback("브라우저 저장소에 초안을 저장하지 못했습니다.", "error", documentRef);
      }
    });
    el("serviceDesignerReset", documentRef)?.addEventListener("click", () => {
      state.design = model.createDefaultDesign();
      state.selectedNodeId = null;
      state.pendingFromId = null;
      state.lastValidation = null;
      state.loadedFromStorage = false;
      state.liveBindingSeeded = false;
      maybeSeedLiveBinding();
      markDirty("현재 EdgeX 정보로 기본 설계를 다시 만들었습니다.", documentRef);
      state.viewportInitialized = false;
      renderAll(documentRef);
      scheduleCanvasFit(documentRef);
    });
    documentRef.addEventListener("keydown", (event) => {
      if (moveSelectedNodeByKeyboard(event, documentRef)) return;
      if (event.key === "Escape" && state.pendingFromId) {
        state.pendingFromId = null;
        setFeedback("연결 선택을 취소했습니다.", "ready", documentRef);
        renderNodes(documentRef);
      } else if (event.key === "Escape" && state.selectedNodeId) {
        state.selectedNodeId = null;
        renderNodes(documentRef);
        renderInspector(documentRef);
        renderMiniMap(documentRef);
        scheduleCanvasFit(documentRef);
      }
      if (
        (event.key === "Delete" || event.key === "Backspace")
        && state.selectedNodeId
        && !event.target.matches("input, select, textarea")
        && event.target.closest?.(".service-designer-page")
      ) {
        event.preventDefault();
        const nodeId = state.selectedNodeId;
        state.design = model.removeNode(state.design, nodeId);
        state.selectedNodeId = null;
        markDirty("단계를 삭제했습니다.", documentRef);
        renderAll(documentRef);
      }
    });
  }

  async function boot(documentRef = document) {
    if (!model || !viewportModel || state.initialized) return;
    const stored = loadStoredDesign();
    if (stored) {
      state.design = stored;
      state.loadedFromStorage = true;
      setDraftState("저장된 초안", "saved", documentRef);
    }
    state.initialized = true;
    bindEvents(documentRef);
    state.paletteOpen = !root.matchMedia?.("(max-width: 860px)").matches;
    setPaletteOpen(state.paletteOpen, documentRef);
    const canvasViewport = el("serviceDesignerCanvasViewport", documentRef);
    if (canvasViewport && root.ResizeObserver) {
      state.resizeObserver = new root.ResizeObserver(() => {
        if (documentRef.body?.dataset.dashboardPage === "designer") {
          scheduleCanvasFit(documentRef);
        }
      });
      state.resizeObserver.observe(canvasViewport);
    }
    if (root.edgeDashboardData) {
      updateInventory(root.edgeDashboardData, documentRef);
    }
    renderAll(documentRef);
    await Promise.all([
      refreshProfiles(root.fetch, documentRef),
      root.edgeDashboardData
        ? Promise.resolve(true)
        : refreshInventory(root.fetch, documentRef),
    ]);
  }

  root.updateServiceDesignerInventory = (data) => updateInventory(data);
  root.refreshServiceDesignerProfiles = () => refreshProfiles(root.fetch);
  root.onServiceDesignerVisible = () => {
    renderAll();
    root.requestAnimationFrame?.(() => {
      renderEdges();
      if (state.viewportInitialized) {
        applyCanvasViewport();
      } else {
        fitCanvas();
      }
    });
  };

  if (typeof document !== "undefined") {
    void boot();
  }

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {
      STORAGE_KEY,
      escapeHtml,
      fetchDesignerProfiles,
      loadStoredDesign,
      nodeSummary,
      saveStoredDesign,
      sourceBindingCandidate,
      state,
      updateInventory,
    };
  }
}(typeof globalThis !== "undefined" ? globalThis : this));
