(function initServiceDesignerModel(root, factory) {
  const api = factory();
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
  if (root) {
    root.ServiceDesignerModel = api;
  }
}(typeof globalThis !== "undefined" ? globalThis : this, () => {
  const DESIGN_VERSION = 1;
  const SOURCE_MODES = {
    local_recent: {
      label: "엣지 최근 데이터",
      description: "같은 물리 노드의 Device Service Local Data API를 사용하는 설계",
    },
    core_history: {
      label: "중앙 저장 데이터",
      description: "EdgeX Core Data의 저장 Event/Reading을 사용하는 설계",
    },
  };
  const NODE_DEFINITIONS = {
    sensor: {
      label: "센서 입력",
      shortLabel: "입력",
      description: "EdgeX Device와 DeviceResource를 선택합니다.",
      acceptsInput: false,
      providesOutput: true,
      defaultConfig: {
        deviceName: "",
        resourceName: "",
        sourceMode: "local_recent",
      },
    },
    preprocess: {
      label: "전처리",
      shortLabel: "처리",
      description: "고정된 전처리 연산을 선택합니다.",
      acceptsInput: true,
      providesOutput: true,
      defaultConfig: {
        operation: "standardize",
        targetNode: "",
        windowSize: 30,
      },
    },
    inference: {
      label: "추론",
      shortLabel: "AI",
      description: "검증할 추론 방식과 실행 노드를 지정합니다.",
      acceptsInput: true,
      providesOutput: true,
      defaultConfig: {
        algorithm: "online-gaussian-baseline-v1",
        targetNode: "",
        threshold: 4,
      },
    },
    output: {
      label: "결과",
      shortLabel: "출력",
      description: "분석 결과를 대시보드에 노출하는 단계입니다.",
      acceptsInput: true,
      providesOutput: false,
      defaultConfig: {
        destination: "dashboard",
      },
    },
  };
  const PREPROCESS_OPERATIONS = {
    passthrough: {
      label: "그대로 전달",
      inputType: "any",
      outputType: "same",
      maxInputs: 1,
    },
    standardize: {
      label: "표준화",
      inputType: "number",
      outputType: "number",
      maxInputs: 1,
    },
    rolling_mean: {
      label: "이동 평균",
      inputType: "number",
      outputType: "number",
      maxInputs: 1,
    },
    vector_magnitude: {
      label: "벡터 크기",
      inputType: "number",
      outputType: "number",
      maxInputs: 3,
    },
  };
  const INFERENCE_ALGORITHMS = {
    "online-gaussian-baseline-v1": {
      label: "온라인 이상 점수",
      inputType: "number",
      outputType: "number",
    },
    "threshold-rule-v1": {
      label: "임계값 판정",
      inputType: "number",
      outputType: "boolean",
    },
  };
  const SERVICE_CATEGORIES = [
    {id: "input", label: "데이터 입력"},
    {id: "preprocess", label: "전처리"},
    {id: "inference", label: "AI 추론"},
    {id: "output", label: "결과"},
  ];
  const SERVICE_TEMPLATES = [
    {
      id: "edgex-local-recent",
      category: "input",
      type: "sensor",
      label: "엣지 최근 데이터",
      description: "Device Service Local Data API",
      config: {sourceMode: "local_recent"},
      inputKind: "local",
    },
    {
      id: "edgex-core-history",
      category: "input",
      type: "sensor",
      label: "중앙 저장 데이터",
      description: "EdgeX Core Data Event / Reading",
      config: {sourceMode: "core_history"},
      inputKind: "history",
    },
    {
      id: "preprocess-passthrough",
      category: "preprocess",
      type: "preprocess",
      label: "그대로 전달",
      description: "입력값 변경 없이 전달",
      config: {operation: "passthrough"},
    },
    {
      id: "preprocess-standardize",
      category: "preprocess",
      type: "preprocess",
      label: "표준화",
      description: "수치 입력 정규화",
      config: {operation: "standardize"},
    },
    {
      id: "preprocess-rolling-mean",
      category: "preprocess",
      type: "preprocess",
      label: "이동 평균",
      description: "최근 구간 평균 계산",
      config: {operation: "rolling_mean"},
    },
    {
      id: "preprocess-vector-magnitude",
      category: "preprocess",
      type: "preprocess",
      label: "벡터 크기",
      description: "3축 수치 입력 결합",
      config: {operation: "vector_magnitude"},
    },
    {
      id: "inference-online-gaussian",
      category: "inference",
      type: "inference",
      label: "온라인 이상 점수",
      description: "Gaussian baseline v1",
      config: {algorithm: "online-gaussian-baseline-v1"},
    },
    {
      id: "inference-threshold",
      category: "inference",
      type: "inference",
      label: "임계값 판정",
      description: "Threshold rule v1",
      config: {algorithm: "threshold-rule-v1"},
    },
    {
      id: "dashboard-output",
      category: "output",
      type: "output",
      label: "대시보드 결과",
      description: "분석 결과 표시",
      config: {destination: "dashboard"},
    },
  ];

  function clone(value) {
    return JSON.parse(JSON.stringify(value));
  }

  function boundedNumber(value, fallback, minimum, maximum) {
    const parsed = Number(value);
    if (!Number.isFinite(parsed)) return fallback;
    return Math.max(minimum, Math.min(maximum, parsed));
  }

  function nodeDefinition(type) {
    return NODE_DEFINITIONS[type] || null;
  }

  function serviceDefinition(serviceId) {
    return SERVICE_TEMPLATES.find((service) => service.id === serviceId) || null;
  }

  function makeNode(type, id, x, y) {
    const definition = nodeDefinition(type);
    if (!definition) throw new Error(`지원하지 않는 단계 유형입니다: ${type}`);
    return {
      id,
      type,
      title: definition.label,
      x,
      y,
      config: clone(definition.defaultConfig),
    };
  }

  function createDefaultDesign() {
    return {
      version: DESIGN_VERSION,
      id: "sensor-anomaly-service-draft",
      name: "센서 이상 탐지 서비스",
      description: "EdgeX 센서 입력을 전처리·추론·결과 단계에 연결하는 설계 초안",
      nodes: [
        makeNode("sensor", "sensor-1", 48, 128),
        makeNode("preprocess", "preprocess-1", 330, 128),
        makeNode("inference", "inference-1", 612, 128),
        makeNode("output", "output-1", 894, 128),
      ],
      edges: [
        {id: "edge-1", from: "sensor-1", to: "preprocess-1"},
        {id: "edge-2", from: "preprocess-1", to: "inference-1"},
        {id: "edge-3", from: "inference-1", to: "output-1"},
      ],
      updatedAt: null,
    };
  }

  function normalizeNode(rawNode, index) {
    const type = String(rawNode?.type || "");
    const definition = nodeDefinition(type);
    if (!definition) return null;
    const fallback = makeNode(type, `${type}-${index + 1}`, 48 + (index % 4) * 282, 128);
    const rawConfig = rawNode?.config && typeof rawNode.config === "object"
      ? rawNode.config
      : {};
    return {
      ...fallback,
      id: String(rawNode?.id || fallback.id).slice(0, 80),
      title: String(rawNode?.title || definition.label).slice(0, 80),
      x: boundedNumber(rawNode?.x, fallback.x, 16, 1050),
      y: boundedNumber(rawNode?.y, fallback.y, 16, 650),
      config: {
        ...fallback.config,
        ...rawConfig,
      },
    };
  }

  function normalizeDesign(rawDesign) {
    const fallback = createDefaultDesign();
    if (!rawDesign || typeof rawDesign !== "object") return fallback;
    const nodes = Array.isArray(rawDesign.nodes)
      ? rawDesign.nodes.map(normalizeNode).filter(Boolean)
      : fallback.nodes;
    const nodeIds = new Set(nodes.map((node) => node.id));
    const edges = Array.isArray(rawDesign.edges)
      ? rawDesign.edges
        .filter((edge) => (
          edge
          && nodeIds.has(String(edge.from || ""))
          && nodeIds.has(String(edge.to || ""))
          && String(edge.from || "") !== String(edge.to || "")
        ))
        .map((edge, index) => ({
          id: String(edge.id || `edge-${index + 1}`).slice(0, 80),
          from: String(edge.from),
          to: String(edge.to),
        }))
      : fallback.edges;
    return {
      version: DESIGN_VERSION,
      id: String(rawDesign.id || fallback.id).slice(0, 120),
      name: String(rawDesign.name || fallback.name).slice(0, 120),
      description: String(rawDesign.description || fallback.description).slice(0, 500),
      nodes,
      edges,
      updatedAt: rawDesign.updatedAt || null,
    };
  }

  function nextNodeId(design, type) {
    const used = new Set((design.nodes || []).map((node) => node.id));
    let suffix = 1;
    while (used.has(`${type}-${suffix}`)) suffix += 1;
    return `${type}-${suffix}`;
  }

  function nextEdgeId(design) {
    const used = new Set((design.edges || []).map((edge) => edge.id));
    let suffix = 1;
    while (used.has(`edge-${suffix}`)) suffix += 1;
    return `edge-${suffix}`;
  }

  function addNode(design, type) {
    const next = normalizeDesign(design);
    const id = nextNodeId(next, type);
    const count = next.nodes.length;
    next.nodes.push(makeNode(
      type,
      id,
      48 + (count % 4) * 250,
      128 + Math.floor(count / 4) * 190,
    ));
    return next;
  }

  function addServiceNode(design, serviceId) {
    const service = serviceDefinition(serviceId);
    if (!service) throw new Error(`지원하지 않는 서비스입니다: ${serviceId}`);
    const next = addNode(design, service.type);
    const added = next.nodes[next.nodes.length - 1];
    return updateNode(next, added.id, {
      title: service.label,
      config: clone(service.config),
    });
  }

  function removeNode(design, nodeId) {
    const next = normalizeDesign(design);
    next.nodes = next.nodes.filter((node) => node.id !== nodeId);
    next.edges = next.edges.filter((edge) => edge.from !== nodeId && edge.to !== nodeId);
    return next;
  }

  function updateNode(design, nodeId, patch) {
    const next = normalizeDesign(design);
    next.nodes = next.nodes.map((node) => {
      if (node.id !== nodeId) return node;
      return {
        ...node,
        ...(patch || {}),
        config: {
          ...node.config,
          ...(patch?.config || {}),
        },
      };
    });
    return next;
  }

  function canonicalDataType(valueType) {
    const normalized = String(valueType || "").toLowerCase();
    if (
      normalized.includes("float")
      || normalized.includes("int")
      || normalized.includes("uint")
      || normalized.includes("decimal")
    ) {
      return "number";
    }
    if (normalized.includes("bool")) return "boolean";
    if (normalized.includes("string") || normalized.includes("char")) return "string";
    if (normalized.includes("object") || normalized.includes("binary")) return "object";
    return "any";
  }

  function resourcesForDevice(device, profiles = []) {
    if (!device) return [];
    const profile = profiles.find((item) => item.name === device.profile_name);
    const byName = new Map();
    (profile?.resources || []).forEach((resource) => {
      byName.set(resource.name, {
        name: resource.name,
        valueType: resource.value_type || resource.valueType || "Unknown",
        units: resource.units || null,
        source: "profile",
      });
    });
    (device.latest_readings || []).forEach((reading) => {
      const name = reading.resource_name || reading.source_name;
      if (!name) return;
      const current = byName.get(name) || {};
      byName.set(name, {
        name,
        valueType: reading.value_type || current.valueType || "Unknown",
        units: reading.units || current.units || null,
        source: current.source || "latest-event",
      });
    });
    return [...byName.values()].sort((left, right) => left.name.localeCompare(right.name));
  }

  function buildServiceCatalog(inventory = {}) {
    const devices = Array.isArray(inventory.devices) ? inventory.devices : [];
    const profiles = Array.isArray(inventory.profiles) ? inventory.profiles : [];
    const devicesWithResources = devices.filter(
      (device) => resourcesForDevice(device, profiles).length > 0,
    );
    const localDevices = devicesWithResources.filter(
      (device) => Boolean(device.node_name),
    );
    return SERVICE_TEMPLATES.map((service) => {
      if (service.category !== "input") {
        return {
          ...clone(service),
          enabled: true,
          availability: "design",
          badge: "설계용",
          eligibleCount: null,
        };
      }
      const eligibleCount = service.inputKind === "local"
        ? localDevices.length
        : devicesWithResources.length;
      return {
        ...clone(service),
        enabled: eligibleCount > 0,
        availability: eligibleCount > 0 ? "available" : "unavailable",
        badge: eligibleCount > 0 ? `입력 ${eligibleCount}` : "입력 없음",
        eligibleCount,
      };
    });
  }

  function sourceResource(node, inventory = {}) {
    if (node?.type !== "sensor") return null;
    const device = (inventory.devices || [])
      .find((item) => item.name === node.config.deviceName);
    return resourcesForDevice(device, inventory.profiles || [])
      .find((resource) => resource.name === node.config.resourceName) || null;
  }

  function nodeOutputType(node, inventory = {}) {
    if (!node) return "any";
    if (node.type === "sensor") {
      return canonicalDataType(sourceResource(node, inventory)?.valueType);
    }
    if (node.type === "preprocess") {
      const operation = PREPROCESS_OPERATIONS[node.config.operation]
        || PREPROCESS_OPERATIONS.passthrough;
      return operation.outputType === "same" ? "any" : operation.outputType;
    }
    if (node.type === "inference") {
      return (
        INFERENCE_ALGORITHMS[node.config.algorithm]
        || INFERENCE_ALGORITHMS["online-gaussian-baseline-v1"]
      ).outputType;
    }
    return "none";
  }

  function nodeInputType(node) {
    if (!node) return "any";
    if (node.type === "preprocess") {
      return (
        PREPROCESS_OPERATIONS[node.config.operation]
        || PREPROCESS_OPERATIONS.passthrough
      ).inputType;
    }
    if (node.type === "inference") {
      return (
        INFERENCE_ALGORITHMS[node.config.algorithm]
        || INFERENCE_ALGORITHMS["online-gaussian-baseline-v1"]
      ).inputType;
    }
    if (node.type === "output") return "any";
    return "none";
  }

  function compatibleTypes(outputType, inputType) {
    if (outputType === "none" || inputType === "none") return false;
    return outputType === "any" || inputType === "any" || outputType === inputType;
  }

  function outgoingIds(design, nodeId) {
    return (design.edges || [])
      .filter((edge) => edge.from === nodeId)
      .map((edge) => edge.to);
  }

  function incomingEdges(design, nodeId) {
    return (design.edges || []).filter((edge) => edge.to === nodeId);
  }

  function wouldCreateCycle(design, fromId, toId) {
    if (fromId === toId) return true;
    const pending = [toId];
    const visited = new Set();
    while (pending.length) {
      const current = pending.pop();
      if (current === fromId) return true;
      if (visited.has(current)) continue;
      visited.add(current);
      pending.push(...outgoingIds(design, current));
    }
    return false;
  }

  function maxInputsForNode(node) {
    if (node.type === "preprocess") {
      return (
        PREPROCESS_OPERATIONS[node.config.operation]
        || PREPROCESS_OPERATIONS.passthrough
      ).maxInputs;
    }
    return nodeDefinition(node.type)?.acceptsInput ? 1 : 0;
  }

  function connectNodes(design, fromId, toId, inventory = {}) {
    const next = normalizeDesign(design);
    const from = next.nodes.find((node) => node.id === fromId);
    const to = next.nodes.find((node) => node.id === toId);
    if (!from || !to) return {design: next, error: "연결할 단계를 찾을 수 없습니다."};
    if (!nodeDefinition(from.type)?.providesOutput || !nodeDefinition(to.type)?.acceptsInput) {
      return {design: next, error: "출력 포트에서 입력 포트로만 연결할 수 있습니다."};
    }
    if (next.edges.some((edge) => edge.from === fromId && edge.to === toId)) {
      return {design: next, error: "이미 연결된 단계입니다."};
    }
    if (wouldCreateCycle(next, fromId, toId)) {
      return {design: next, error: "순환 연결은 만들 수 없습니다."};
    }
    if (incomingEdges(next, toId).length >= maxInputsForNode(to)) {
      return {design: next, error: `${to.title} 입력 포트가 이미 사용 중입니다.`};
    }
    const outputType = nodeOutputType(from, inventory);
    const inputType = nodeInputType(to);
    if (!compatibleTypes(outputType, inputType)) {
      return {
        design: next,
        error: `${outputType} 출력을 ${inputType} 입력에 연결할 수 없습니다.`,
      };
    }
    next.edges.push({id: nextEdgeId(next), from: fromId, to: toId});
    return {design: next, error: null};
  }

  function removeEdge(design, edgeId) {
    const next = normalizeDesign(design);
    next.edges = next.edges.filter((edge) => edge.id !== edgeId);
    return next;
  }

  function topologicalOrder(design) {
    const nodes = design.nodes || [];
    const indegree = Object.fromEntries(nodes.map((node) => [node.id, 0]));
    (design.edges || []).forEach((edge) => {
      if (Object.prototype.hasOwnProperty.call(indegree, edge.to)) {
        indegree[edge.to] += 1;
      }
    });
    const queue = nodes
      .filter((node) => indegree[node.id] === 0)
      .map((node) => node.id);
    const ordered = [];
    while (queue.length) {
      const id = queue.shift();
      ordered.push(id);
      outgoingIds(design, id).forEach((targetId) => {
        indegree[targetId] -= 1;
        if (indegree[targetId] === 0) queue.push(targetId);
      });
    }
    return ordered;
  }

  function reachableNodeIds(design, startId) {
    const visited = new Set();
    const pending = [startId];
    while (pending.length) {
      const id = pending.pop();
      if (visited.has(id)) continue;
      visited.add(id);
      pending.push(...outgoingIds(design, id));
    }
    return visited;
  }

  function validateDesign(rawDesign, inventory = {}) {
    const design = normalizeDesign(rawDesign);
    const errors = [];
    const warnings = [];
    const addError = (code, message, nodeId = null) => errors.push({code, message, nodeId});
    const addWarning = (code, message, nodeId = null) => warnings.push({code, message, nodeId});
    const byType = (type) => design.nodes.filter((node) => node.type === type);
    if (!design.name.trim()) addError("service_name_required", "서비스 이름을 입력하세요.");
    if (!byType("sensor").length) addError("sensor_required", "센서 입력 단계를 하나 이상 추가하세요.");
    if (!byType("inference").length) addError("inference_required", "추론 단계를 하나 이상 추가하세요.");
    if (!byType("output").length) addError("output_required", "결과 단계를 하나 이상 추가하세요.");
    if (topologicalOrder(design).length !== design.nodes.length) {
      addError("cycle_detected", "순환 연결을 제거하세요.");
    }

    design.nodes.forEach((node) => {
      const incoming = incomingEdges(design, node.id);
      const outgoing = (design.edges || []).filter((edge) => edge.from === node.id);
      if (nodeDefinition(node.type)?.acceptsInput && incoming.length === 0) {
        addError("input_missing", `${node.title} 단계의 입력이 연결되지 않았습니다.`, node.id);
      }
      if (nodeDefinition(node.type)?.providesOutput && outgoing.length === 0) {
        addError("output_missing", `${node.title} 단계의 출력이 연결되지 않았습니다.`, node.id);
      }
      if (incoming.length > maxInputsForNode(node)) {
        addError("too_many_inputs", `${node.title} 단계의 입력 수가 허용 범위를 넘었습니다.`, node.id);
      }
      if (node.type === "sensor") {
        const device = (inventory.devices || [])
          .find((item) => item.name === node.config.deviceName);
        if (!node.config.deviceName) {
          addError("device_required", "센서 입력에서 EdgeX 디바이스를 선택하세요.", node.id);
        } else if (!device) {
          addError("device_missing", `등록된 EdgeX 디바이스 ${node.config.deviceName}을 찾을 수 없습니다.`, node.id);
        }
        if (!node.config.resourceName) {
          addError("resource_required", "센서 입력에서 DeviceResource를 선택하세요.", node.id);
        } else if (device && !sourceResource(node, inventory)) {
          addError("resource_missing", `${node.config.resourceName} 리소스를 Profile에서 찾을 수 없습니다.`, node.id);
        }
        if (!SOURCE_MODES[node.config.sourceMode]) {
          addError("source_mode_invalid", "지원되는 데이터 접근 방식을 선택하세요.", node.id);
        }
        if (device?.overall_status !== "available") {
          addWarning(
            "device_not_available",
            `${device?.name || node.config.deviceName} 상태가 Available이 아닙니다.`,
            node.id,
          );
        }
        if (device?.telemetry_freshness !== "fresh") {
          addWarning(
            "telemetry_not_fresh",
            `${device?.name || node.config.deviceName}의 최신 Event가 fresh가 아닙니다.`,
            node.id,
          );
        }
        if (node.config.sourceMode === "local_recent") {
          if (!device?.node_name) {
            addError(
              "source_node_missing",
              "엣지 최근 데이터는 디바이스의 물리 노드 정보가 필요합니다.",
              node.id,
            );
          } else {
            outgoing.forEach((edge) => {
              const target = design.nodes.find((item) => item.id === edge.to);
              if (
                target
                && ["preprocess", "inference"].includes(target.type)
                && target.config.targetNode !== device.node_name
              ) {
                addError(
                  "local_node_mismatch",
                  `엣지 최근 데이터의 첫 처리 단계는 ${device.node_name}에 배치해야 합니다.`,
                  target.id,
                );
              }
            });
          }
        }
      }
      if (["preprocess", "inference"].includes(node.type)) {
        if (!node.config.targetNode) {
          addError("target_node_required", `${node.title} 실행 노드를 선택하세요.`, node.id);
        } else if (
          (inventory.nodes || []).length
          && !(inventory.nodes || []).some((item) => (
            item.hostname === node.config.targetNode
            || item.name === node.config.targetNode
            || item.node_name === node.config.targetNode
          ))
        ) {
          addError("target_node_missing", `${node.config.targetNode} 노드를 찾을 수 없습니다.`, node.id);
        }
      }
    });

    (design.edges || []).forEach((edge) => {
      const from = design.nodes.find((node) => node.id === edge.from);
      const to = design.nodes.find((node) => node.id === edge.to);
      if (!from || !to) return;
      if (!compatibleTypes(nodeOutputType(from, inventory), nodeInputType(to))) {
        addError(
          "type_mismatch",
          `${from.title}의 ${nodeOutputType(from, inventory)} 출력과 ${to.title}의 ${nodeInputType(to)} 입력이 맞지 않습니다.`,
          to.id,
        );
      }
    });

    const outputIds = new Set(byType("output").map((node) => node.id));
    byType("sensor").forEach((source) => {
      const reachable = reachableNodeIds(design, source.id);
      if (![...outputIds].some((outputId) => reachable.has(outputId))) {
        addError(
          "result_unreachable",
          `${source.title} 입력이 결과 단계까지 이어지지 않습니다.`,
          source.id,
        );
      }
    });
    return {
      valid: errors.length === 0,
      errors,
      warnings,
    };
  }

  function stageDetail(node, inventory = {}) {
    if (node.type === "sensor") {
      const sourceMode = SOURCE_MODES[node.config.sourceMode]?.label || "데이터 방식 미선택";
      return `${node.config.deviceName || "디바이스 미선택"} / ${node.config.resourceName || "리소스 미선택"} · ${sourceMode}`;
    }
    if (node.type === "preprocess") {
      return `${PREPROCESS_OPERATIONS[node.config.operation]?.label || node.config.operation} · ${node.config.targetNode || "노드 미선택"}`;
    }
    if (node.type === "inference") {
      return `${INFERENCE_ALGORITHMS[node.config.algorithm]?.label || node.config.algorithm} · ${node.config.targetNode || "노드 미선택"}`;
    }
    if (node.type === "output") return "대시보드 결과";
    return "";
  }

  function buildExecutionPlan(rawDesign, inventory = {}) {
    const design = normalizeDesign(rawDesign);
    const order = topologicalOrder(design);
    const validation = validateDesign(design, inventory);
    return {
      serviceName: design.name,
      mode: "dry-run",
      valid: validation.valid,
      stages: order.map((id, index) => {
        const node = design.nodes.find((item) => item.id === id);
        return {
          order: index + 1,
          id: node.id,
          type: node.type,
          label: node.title,
          detail: stageDetail(node, inventory),
          inputType: nodeInputType(node),
          outputType: nodeOutputType(node, inventory),
        };
      }),
      errors: validation.errors,
      warnings: validation.warnings,
    };
  }

  return {
    DESIGN_VERSION,
    INFERENCE_ALGORITHMS,
    NODE_DEFINITIONS,
    PREPROCESS_OPERATIONS,
    SERVICE_CATEGORIES,
    SERVICE_TEMPLATES,
    SOURCE_MODES,
    addNode,
    addServiceNode,
    buildServiceCatalog,
    buildExecutionPlan,
    canonicalDataType,
    compatibleTypes,
    connectNodes,
    createDefaultDesign,
    nodeDefinition,
    nodeInputType,
    nodeOutputType,
    normalizeDesign,
    removeEdge,
    removeNode,
    resourcesForDevice,
    serviceDefinition,
    sourceResource,
    topologicalOrder,
    updateNode,
    validateDesign,
    wouldCreateCycle,
  };
}));
