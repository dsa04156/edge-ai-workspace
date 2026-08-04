(function initServiceDesigner(root) {
  const model = root?.ServiceDesignerModel;
  const viewportModel = root?.ServiceDesignerViewport;
  const STORAGE_KEY = "edge-ai-service-design-v1";
  const SERVICE_DRAFT_STORAGE_PREFIX = "edge-ai-service-draft-v1:";
  const DRAG_ACTIVATION_PX = 3;
  const DRAG_CLICK_SUPPRESSION_MS = 600;
  const INPUT_TELEMETRY_WINDOW = "-5m";
  const INPUT_TELEMETRY_LIMIT = 300;
  const INPUT_TELEMETRY_CACHE_MS = 15000;

  function createInputTelemetryPreview(overrides = {}) {
    return {
      key: "",
      nodeId: "",
      deviceName: "",
      resourceName: "",
      status: "idle",
      summary: null,
      error: "",
      loadedAt: 0,
      ...overrides,
    };
  }

  function createInputReadiness(overrides = {}) {
    return {
      status: "idle",
      rows: [],
      errors: [],
      warnings: [],
      readyCount: 0,
      maxSkewMs: null,
      telemetryByNodeId: {},
      checkedAt: 0,
      ...overrides,
    };
  }

  const state = {
    design: model
      ? model.createSensorAnomalyExampleDesign()
      : null,
    inventory: {devices: [], profiles: [], nodes: []},
    deployedServices: [],
    deployedServicesError: "",
    selectedDeployedServiceId: null,
    designMode: "draft",
    draftSnapshot: null,
    serviceDraftCache: {},
    selectedNodeId: null,
    inspectorOpen: false,
    pendingFromId: null,
    selectedEdgeId: null,
    lastValidation: null,
    initialized: false,
    loadedFromStorage: false,
    liveBindingSeeded: false,
    dirty: false,
    dragging: null,
    suppressNodeClickId: null,
    suppressNodeClickUntil: 0,
    panning: null,
    viewport: viewportModel
      ? viewportModel.normalizeViewport()
      : {x: 0, y: 0, zoom: 1},
    viewportInitialized: false,
    paletteOpen: true,
    resizeFrame: null,
    resizeObserver: null,
    edgeElements: new Map(),
    miniMapNodeElements: new Map(),
    miniMapBounds: null,
    pendingFullRender: false,
    inputTelemetryPreview: createInputTelemetryPreview(),
    inputTelemetryRequestId: 0,
    inputReadiness: createInputReadiness(),
    inputReadinessRequestId: 0,
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

  function designerTelemetryUrl(
    deviceName,
    windowValue = INPUT_TELEMETRY_WINDOW,
    limit = INPUT_TELEMETRY_LIMIT,
  ) {
    const safeLimit = Math.max(1, Math.min(1000, Number(limit) || INPUT_TELEMETRY_LIMIT));
    return `/state/devices/${encodeURIComponent(String(deviceName || ""))}/telemetry?window=${encodeURIComponent(windowValue)}&limit=${safeLimit}`;
  }

  async function fetchDesignerTelemetry(
    deviceName,
    windowValue = INPUT_TELEMETRY_WINDOW,
    fetchFn = root?.fetch,
    limit = INPUT_TELEMETRY_LIMIT,
  ) {
    if (!deviceName) throw new Error("센서 디바이스를 먼저 선택하세요.");
    if (typeof fetchFn !== "function") throw new Error("Telemetry 조회 기능을 사용할 수 없습니다.");
    const response = await fetchFn(
      designerTelemetryUrl(deviceName, windowValue, limit),
      {cache: "no-store"},
    );
    if (!response.ok) {
      throw new Error(`Telemetry API 오류 (${response.status})`);
    }
    const payload = await response.json();
    if (!Array.isArray(payload)) {
      throw new Error("Telemetry 응답 형식이 올바르지 않습니다.");
    }
    return payload;
  }

  function telemetryPointTimestampMs(point = {}) {
    const parsed = Date.parse(String(point.timestamp || ""));
    return Number.isFinite(parsed) ? parsed : null;
  }

  function summarizeDesignerTelemetry(points = [], resourceName = "") {
    const wanted = String(resourceName || "").trim().toLowerCase();
    const ordered = (Array.isArray(points) ? points : [])
      .filter((point) => {
        if (!wanted) return true;
        return [point?.resource_name, point?.source_name]
          .some((value) => String(value || "").trim().toLowerCase() === wanted);
      })
      .map((point) => ({point, timestampMs: telemetryPointTimestampMs(point)}))
      .filter((item) => Number.isFinite(item.timestampMs))
      .sort((left, right) => left.timestampMs - right.timestampMs);
    const intervals = ordered
      .slice(1)
      .map((item, index) => item.timestampMs - ordered[index].timestampMs)
      .filter((interval) => interval > 0)
      .sort((left, right) => left - right);
    let medianIntervalMs = null;
    if (intervals.length) {
      const middle = Math.floor(intervals.length / 2);
      medianIntervalMs = intervals.length % 2
        ? intervals[middle]
        : (intervals[middle - 1] + intervals[middle]) / 2;
    }
    const normalizedPoints = ordered.map((item) => item.point);
    return {
      points: normalizedPoints,
      sampleCount: normalizedPoints.length,
      firstTimestamp: normalizedPoints[0]?.timestamp || null,
      lastTimestamp: normalizedPoints.at(-1)?.timestamp || null,
      medianIntervalMs,
      latest: normalizedPoints.at(-1) || null,
      recent: normalizedPoints.slice(-5).reverse(),
    };
  }

  function inputLatestTimestamp(device = {}, resourceName = "", summary = null) {
    if (summary?.lastTimestamp) return summary.lastTimestamp;
    const wanted = String(resourceName || "").trim().toLowerCase();
    const matching = (device.latest_readings || [])
      .filter((reading) => (
        [reading?.resource_name, reading?.source_name]
          .some((value) => String(value || "").trim().toLowerCase() === wanted)
      ))
      .map((reading) => ({reading, timestamp: telemetryPointTimestampMs(reading)}))
      .filter((item) => Number.isFinite(item.timestamp))
      .sort((left, right) => right.timestamp - left.timestamp)[0];
    return matching?.reading?.timestamp || device.latest_event_timestamp || null;
  }

  function buildDesignInputReadiness(
    design,
    inventory = {},
    telemetryByNodeId = {},
  ) {
    const sensorNodes = (design?.nodes || []).filter((node) => node.type === "sensor");
    const errors = [];
    const warnings = [];
    const rows = sensorNodes.map((node) => {
      const device = (inventory.devices || [])
        .find((item) => item.name === node.config.deviceName);
      const resource = device ? model.sourceResource(node, inventory) : null;
      const telemetry = telemetryByNodeId[node.id] || {status: "idle"};
      const summary = telemetry.summary || null;
      const requiredSamples = Math.max(
        1,
        Number(model.sensorWindowRequirement?.(design, node.id)) || 1,
      );
      const sampleCount = Number(summary?.sampleCount) || 0;
      const freshness = String(device?.telemetry_freshness || "").toLowerCase();
      const latestTimestamp = inputLatestTimestamp(
        device,
        node.config.resourceName,
        summary,
      );
      let status = "pending";
      let statusLabel = "점검 전";
      let reason = "입력·설계 검증을 실행하세요.";

      if (!node.config.deviceName || !node.config.resourceName || !device || !resource) {
        status = "blocked";
        statusLabel = "바인딩 필요";
        reason = "EdgeX Device와 DeviceResource를 먼저 확인하세요.";
      } else if (telemetry.status === "error") {
        status = "blocked";
        statusLabel = "조회 실패";
        reason = telemetry.error || "최근 입력 데이터를 읽지 못했습니다.";
        errors.push({
          code: "input_history_unavailable",
          message: `${node.title}의 최근 입력 데이터를 확인하지 못했습니다: ${reason}`,
          nodeId: node.id,
        });
      } else if (telemetry.status === "ready") {
        if (freshness === "no_events") {
          status = "blocked";
          statusLabel = "데이터 없음";
          reason = "EdgeX Core Data에 저장된 Event가 없습니다.";
        } else if (freshness === "stale") {
          status = "blocked";
          statusLabel = "데이터 지연";
          reason = "최신 Event가 freshness 기준을 넘었습니다.";
        } else if (requiredSamples > INPUT_TELEMETRY_LIMIT) {
          status = "blocked";
          statusLabel = "검증 범위 초과";
          reason = `필요 ${requiredSamples}개가 현재 점검 한도 ${INPUT_TELEMETRY_LIMIT}개를 넘습니다.`;
          errors.push({
            code: "input_window_unverifiable",
            message: `${node.title}의 필요 표본 ${requiredSamples}개가 입력 점검 한도 ${INPUT_TELEMETRY_LIMIT}개를 넘습니다.`,
            nodeId: node.id,
          });
        } else if (sampleCount < requiredSamples) {
          status = "blocked";
          statusLabel = "표본 부족";
          reason = `최근 5분 표본 ${sampleCount}개 / 필요 ${requiredSamples}개`;
          errors.push({
            code: "input_sample_shortfall",
            message: `${node.title}의 최근 표본이 ${sampleCount}개로 필요 윈도우 ${requiredSamples}개보다 적습니다.`,
            nodeId: node.id,
          });
        } else if (freshness !== "fresh") {
          status = "warning";
          statusLabel = "최신성 확인 필요";
          reason = "표본은 충분하지만 freshness 상태를 확인해야 합니다.";
          warnings.push({
            code: "input_freshness_unverified",
            message: `${node.title}의 표본은 충분하지만 freshness 상태를 확인하지 못했습니다.`,
            nodeId: node.id,
          });
        } else {
          status = "ready";
          statusLabel = "준비";
          reason = `최근 5분 표본 ${sampleCount}개 / 필요 ${requiredSamples}개`;
        }
      }

      return {
        nodeId: node.id,
        title: node.title,
        deviceName: node.config.deviceName || "미선택",
        resourceName: node.config.resourceName || "미선택",
        sourceMode: node.config.sourceMode,
        nodeName: device?.node_name || "미확인",
        status,
        statusLabel,
        reason,
        sampleCount,
        requiredSamples,
        medianIntervalMs: summary?.medianIntervalMs ?? null,
        latestTimestamp,
        latest: summary?.latest || null,
        units: summary?.latest?.units || resource?.units || "",
        telemetryStatus: telemetry.status,
      };
    });

    let maxSkewMs = null;
    (design?.nodes || []).forEach((target) => {
      const sourceIds = (design?.edges || [])
        .filter((edge) => edge.to === target.id)
        .map((edge) => (design.nodes || []).find((node) => node.id === edge.from))
        .filter((node) => node?.type === "sensor" && node.config.sourceMode === "local_recent")
        .map((node) => node.id);
      if (sourceIds.length < 2) return;
      const sourceRows = sourceIds
        .map((nodeId) => rows.find((row) => row.nodeId === nodeId))
        .filter(Boolean);
      const timestamps = sourceRows
        .map((row) => Date.parse(String(row.latestTimestamp || "")))
        .filter(Number.isFinite);
      if (timestamps.length !== sourceRows.length) return;
      const skew = Math.max(...timestamps) - Math.min(...timestamps);
      maxSkewMs = Math.max(maxSkewMs || 0, skew);
      if (skew <= model.LIVE_INPUT_ALIGNMENT_TOLERANCE_MS) return;
      errors.push({
        code: "input_history_time_skew",
        message: `${target.title}의 최근 입력 시각 차이 ${Math.round(skew)}ms가 허용 범위 ${model.LIVE_INPUT_ALIGNMENT_TOLERANCE_MS}ms를 넘습니다.`,
        nodeId: target.id,
      });
      sourceRows.forEach((row) => {
        row.status = "blocked";
        row.statusLabel = "시각 불일치";
        row.reason = `묶인 입력의 최신 시각 차이 ${Math.round(skew)}ms`;
      });
    });

    const readyCount = rows.filter((row) => row.status === "ready").length;
    const status = !rows.length || rows.some((row) => row.status === "blocked")
      ? "blocked"
      : rows.some((row) => row.status !== "ready")
        ? "warning"
        : "ready";
    return {
      status,
      rows,
      errors,
      warnings,
      readyCount,
      maxSkewMs,
      telemetryByNodeId,
    };
  }

  function mergeValidationWithInputReadiness(validation, readiness) {
    const baseErrors = [...(validation?.errors || [])];
    const baseWarnings = [...(validation?.warnings || [])];
    const seen = new Set(
      [...baseErrors, ...baseWarnings]
        .map((issue) => `${issue.code}|${issue.nodeId || ""}`),
    );
    const append = (target, issues) => {
      (issues || []).forEach((issue) => {
        if (
          issue.code === "input_history_time_skew"
          && baseErrors.some((existing) => (
            existing.code === "multi_input_time_skew"
            && existing.nodeId === issue.nodeId
          ))
        ) return;
        const key = `${issue.code}|${issue.nodeId || ""}`;
        if (seen.has(key)) return;
        seen.add(key);
        target.push(issue);
      });
    };
    append(baseErrors, readiness?.errors);
    append(baseWarnings, readiness?.warnings);
    return {
      valid: baseErrors.length === 0,
      errors: baseErrors,
      warnings: baseWarnings,
    };
  }

  function isServiceDraftView() {
    return state.designMode === "service-draft";
  }

  function cloneDesign(design) {
    return JSON.parse(JSON.stringify(design));
  }

  function focusDeployedServiceAction(serviceId, documentRef = document) {
    const button = [...documentRef.querySelectorAll("[data-deployed-service-design]")]
      .find((item) => item.dataset.deployedServiceDesign === serviceId);
    try {
      button?.focus({preventScroll: true});
    } catch (_error) {
      button?.focus?.();
    }
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

  function serviceDraftStorageKey(serviceId) {
    return `${SERVICE_DRAFT_STORAGE_PREFIX}${encodeURIComponent(String(serviceId || ""))}`;
  }

  function loadStoredServiceDraft(service = {}, storage = root?.localStorage) {
    if (!model || !storage || !service.service_id) return null;
    try {
      const raw = storage.getItem(serviceDraftStorageKey(service.service_id));
      if (!raw) return null;
      const parsed = JSON.parse(raw);
      if (
        parsed?.version !== model.DESIGN_VERSION
        || parsed?.serviceId !== service.service_id
        || parsed?.contractId !== service.design_contract?.contract_id
      ) {
        return null;
      }
      return {
        ...parsed,
        design: model.normalizeDesign(parsed.design),
      };
    } catch (_error) {
      return null;
    }
  }

  function saveStoredServiceDraft(
    service,
    design,
    storage = root?.localStorage,
  ) {
    if (!storage || !service?.service_id) return false;
    const updatedAt = new Date().toISOString();
    const saved = {
      version: model.DESIGN_VERSION,
      serviceId: service.service_id,
      contractId: service.design_contract?.contract_id || "",
      updatedAt,
      design: {
        ...model.normalizeDesign(design),
        updatedAt,
      },
    };
    storage.setItem(serviceDraftStorageKey(service.service_id), JSON.stringify(saved));
    state.design = saved.design;
    state.dirty = false;
    return true;
  }

  function removeStoredServiceDraft(serviceId, storage = root?.localStorage) {
    if (!storage || !serviceId) return false;
    try {
      storage.removeItem(serviceDraftStorageKey(serviceId));
      return true;
    } catch (_error) {
      return false;
    }
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
      if (!device) {
        return node.config.deviceName
          ? `${node.config.deviceName} · ${node.config.resourceName || "리소스 확인 필요"} · 관측 확인 필요`
          : "디바이스를 선택하세요";
      }
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
    if (node.type === "fusion") {
      const method = model.FUSION_METHODS[node.config.method];
      return `${method?.label || "결합 방식 미선택"} · ${node.config.targetNode || "노드 미선택"}`;
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

  function normalizedIdentity(value) {
    return String(value || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  }

  function accelerationAxisBindingCandidates(inventory = {}) {
    const axes = ["x", "y", "z"];
    const profiles = inventory.profiles || [];
    const candidates = Object.fromEntries(axes.map((axis) => [axis, []]));
    (inventory.devices || []).forEach((device) => {
      if (!device.node_name) return;
      model.resourcesForDevice(device, profiles).forEach((resource) => {
        if (model.canonicalDataType(resource.valueType) !== "number") return;
        const deviceIdentity = normalizedIdentity(
          `${device.name} ${device.profile_name}`,
        );
        const resourceIdentity = normalizedIdentity(resource.name);
        axes.forEach((axis) => {
          const axisIdentity = `acceleration${axis}`;
          if (
            !resourceIdentity.includes(axisIdentity)
            && !deviceIdentity.includes(axisIdentity)
          ) {
            return;
          }
          let score = 0;
          if (resourceIdentity === `${axisIdentity}raw`) score += 100;
          else if (resourceIdentity.includes(axisIdentity)) score += 70;
          if (deviceIdentity.includes(`virtual${axisIdentity}`)) score += 40;
          else if (deviceIdentity.includes(axisIdentity)) score += 20;
          if (device.overall_status === "available") score += 10;
          if (device.telemetry_freshness === "fresh") score += 5;
          candidates[axis].push({axis, device, resource, score});
        });
      });
    });
    Object.values(candidates).forEach((items) => {
      items.sort((left, right) => (
        right.score - left.score
        || String(left.device.name).localeCompare(String(right.device.name))
        || String(left.resource.name).localeCompare(String(right.resource.name))
      ));
    });
    const commonNodes = [...new Set(candidates.x.map((item) => item.device.node_name))]
      .filter((node) => axes.every(
        (axis) => candidates[axis].some((item) => item.device.node_name === node),
      ));
    const preferredNode = commonNodes
      .map((node) => ({
        node,
        score: axes.reduce(
          (total, axis) => total + candidates[axis]
            .find((item) => item.device.node_name === node).score,
          0,
        ),
      }))
      .sort((left, right) => (
        right.score - left.score || left.node.localeCompare(right.node)
      ))[0]?.node;
    return Object.fromEntries(axes.map((axis) => [
      axis,
      candidates[axis].find(
        (item) => !preferredNode || item.device.node_name === preferredNode,
      ) || null,
    ]));
  }

  function contextSourceBindingCandidate(
    inventory = {},
    {preferredNode = "", excludedDeviceNames = []} = {},
  ) {
    const excluded = new Set(excludedDeviceNames);
    const preferredResources = [
      "temperature",
      "current",
      "pressure",
      "humidity",
      "rpm",
    ];
    const candidates = [];
    (inventory.devices || []).forEach((device) => {
      if (excluded.has(device.name)) return;
      if (preferredNode && device.node_name !== preferredNode) return;
      model.resourcesForDevice(device, inventory.profiles || []).forEach((resource) => {
        if (model.canonicalDataType(resource.valueType) !== "number") return;
        const identity = normalizedIdentity(
          `${device.name} ${device.profile_name} ${resource.name}`,
        );
        if (identity.includes("acceleration")) return;
        const preferredIndex = preferredResources.findIndex(
          (keyword) => identity.includes(keyword),
        );
        let score = preferredIndex >= 0 ? 100 - preferredIndex * 10 : 10;
        if (device.overall_status === "available") score += 5;
        if (device.telemetry_freshness === "fresh") score += 3;
        candidates.push({device, resource, score});
      });
    });
    return candidates.sort((left, right) => (
      right.score - left.score
      || String(left.device.name).localeCompare(String(right.device.name))
      || String(left.resource.name).localeCompare(String(right.resource.name))
    ))[0] || null;
  }

  function bindSensorAnomalyExample(design, inventory = {}) {
    const axisNodeIds = {
      x: "sensor-x",
      y: "sensor-y",
      z: "sensor-z",
    };
    const isExample = [
      ...Object.values(axisNodeIds),
      "vector-magnitude",
      "anomaly-inference",
    ].every((id) => design.nodes.some((node) => node.id === id));
    if (!isExample) {
      return {
        design,
        boundAxes: [],
        configuredAxes: [],
        sourceNode: "",
        isExample: false,
      };
    }
    const matches = accelerationAxisBindingCandidates(inventory);
    let next = design;
    const boundAxes = [];
    Object.entries(axisNodeIds).forEach(([axis, nodeId]) => {
      const node = next.nodes.find((item) => item.id === nodeId);
      const match = matches[axis];
      if (!node || node.config.deviceName || !match) return;
      next = model.updateNode(next, nodeId, {
        config: {
          deviceName: match.device.name,
          resourceName: match.resource.name,
          sourceMode: "local_recent",
        },
      });
      boundAxes.push(axis);
    });
    const sensors = Object.values(axisNodeIds)
      .map((id) => next.nodes.find((node) => node.id === id))
      .filter(Boolean);
    const sourceNodes = new Set(sensors.map((sensor) => (
      (inventory.devices || []).find(
        (device) => device.name === sensor.config.deviceName,
      )?.node_name || ""
    )).filter(Boolean));
    const allBound = sensors.length === 3 && sensors.every(
      (sensor) => sensor.config.deviceName && sensor.config.resourceName,
    );
    const configuredAxes = Object.entries(axisNodeIds)
      .filter(([, id]) => {
        const sensor = next.nodes.find((node) => node.id === id);
        return sensor?.config.deviceName && sensor?.config.resourceName;
      })
      .map(([axis]) => axis);
    const sourceNode = allBound && sourceNodes.size === 1
      ? [...sourceNodes][0]
      : "";
    if (sourceNode) {
      next = model.updateNode(next, "vector-magnitude", {
        config: {targetNode: sourceNode},
      });
      next = model.updateNode(next, "anomaly-inference", {
        config: {targetNode: sourceNode},
      });
    }
    return {
      design: next,
      boundAxes,
      configuredAxes,
      sourceNode,
      isExample: true,
    };
  }

  function bindMultiSensorScoreExample(design, inventory = {}) {
    const axisNodeIds = {
      x: "sensor-x",
      y: "sensor-y",
      z: "sensor-z",
    };
    const requiredIds = [
      ...Object.values(axisNodeIds),
      "sensor-context",
      "vibration-features",
      "context-features",
      "vibration-score",
      "context-score",
      "score-fusion",
    ];
    const isExample = requiredIds.every(
      (id) => design.nodes.some((node) => node.id === id),
    );
    if (!isExample) {
      return {
        design,
        boundInputs: [],
        configuredInputs: [],
        sourceNode: "",
        isExample: false,
      };
    }
    const matches = accelerationAxisBindingCandidates(inventory);
    let next = design;
    const boundInputs = [];
    Object.entries(axisNodeIds).forEach(([axis, nodeId]) => {
      const node = next.nodes.find((item) => item.id === nodeId);
      const match = matches[axis];
      if (!node || node.config.deviceName || !match) return;
      next = model.updateNode(next, nodeId, {
        config: {
          deviceName: match.device.name,
          resourceName: match.resource.name,
          sourceMode: "local_recent",
        },
      });
      boundInputs.push(axis);
    });
    const axisSensors = Object.values(axisNodeIds)
      .map((id) => next.nodes.find((node) => node.id === id))
      .filter(Boolean);
    const axisSourceNodes = new Set(axisSensors.map((sensor) => (
      (inventory.devices || []).find(
        (device) => device.name === sensor.config.deviceName,
      )?.node_name || ""
    )).filter(Boolean));
    const axesBound = axisSensors.length === 3 && axisSensors.every(
      (sensor) => sensor.config.deviceName && sensor.config.resourceName,
    );
    const preferredNode = axesBound && axisSourceNodes.size === 1
      ? [...axisSourceNodes][0]
      : "";
    const contextNode = next.nodes.find((node) => node.id === "sensor-context");
    if (contextNode && !contextNode.config.deviceName) {
      const contextMatch = contextSourceBindingCandidate(inventory, {
        preferredNode,
        excludedDeviceNames: axisSensors.map((sensor) => sensor.config.deviceName),
      });
      if (contextMatch) {
        next = model.updateNode(next, contextNode.id, {
          title: contextMatch.resource.name.toLowerCase().includes("temperature")
            ? "온도"
            : "보조 센서",
          config: {
            deviceName: contextMatch.device.name,
            resourceName: contextMatch.resource.name,
            sourceMode: contextMatch.device.node_name ? "local_recent" : "core_history",
          },
        });
        boundInputs.push("context");
      }
    }
    const sensorIds = [...Object.values(axisNodeIds), "sensor-context"];
    const sensors = sensorIds.map(
      (id) => next.nodes.find((node) => node.id === id),
    ).filter(Boolean);
    const configuredInputs = sensors
      .filter((sensor) => sensor.config.deviceName && sensor.config.resourceName)
      .map((sensor) => sensor.id);
    const sourceNodes = new Set(sensors.map((sensor) => (
      (inventory.devices || []).find(
        (device) => device.name === sensor.config.deviceName,
      )?.node_name || ""
    )).filter(Boolean));
    const sourceNode = configuredInputs.length === 4 && sourceNodes.size === 1
      ? [...sourceNodes][0]
      : "";
    if (sourceNode) {
      [
        "vibration-features",
        "context-features",
        "vibration-score",
        "context-score",
        "score-fusion",
      ].forEach((nodeId) => {
        next = model.updateNode(next, nodeId, {
          config: {targetNode: sourceNode},
        });
      });
    }
    return {
      design: next,
      boundInputs,
      configuredInputs,
      sourceNode,
      isExample: true,
    };
  }

  function bindDeployedServiceDesign(design, service = {}, inventory = {}) {
    const allowedDevices = new Set(
      Array.isArray(service.input_devices) ? service.input_devices : [],
    );
    const scopedInventory = allowedDevices.size
      ? {
        ...inventory,
        devices: (inventory.devices || []).filter(
          (device) => allowedDevices.has(device.name),
        ),
      }
      : inventory;
    return bindMultiSensorScoreExample(design, scopedInventory);
  }

  function buildServiceDraft(serviceId) {
    const service = state.deployedServices.find(
      (item) => item.service_id === serviceId,
    );
    const design = service && model.createDeployedServiceDesign?.(service);
    if (!service || !design) return null;
    return bindDeployedServiceDesign(
      design,
      service,
      state.inventory,
    ).design;
  }

  function cacheActiveServiceDraft() {
    if (!isServiceDraftView() || !state.selectedDeployedServiceId) return;
    state.serviceDraftCache[state.selectedDeployedServiceId] = {
      design: cloneDesign(state.design),
      dirty: state.dirty,
      lastValidation: state.lastValidation,
      inputReadiness: cloneDesign(state.inputReadiness),
      selectedNodeId: state.selectedNodeId,
      inspectorOpen: state.inspectorOpen,
    };
  }

  function resetActiveServiceDraft(documentRef = document) {
    if (!isServiceDraftView()) return false;
    const serviceId = state.selectedDeployedServiceId;
    const design = buildServiceDraft(serviceId);
    if (!design) {
      setFeedback("서비스 원본 설계 계약을 다시 불러오지 못했습니다.", "error", documentRef);
      return false;
    }
    state.design = design;
    state.selectedNodeId = null;
    state.inspectorOpen = false;
    state.pendingFromId = null;
    state.selectedEdgeId = null;
    state.lastValidation = null;
    resetInputReadiness();
    state.dirty = false;
    delete state.serviceDraftCache[serviceId];
    removeStoredServiceDraft(serviceId);
    state.viewportInitialized = false;
    renderAll(documentRef);
    setDraftState("서비스 초안", "service-draft", documentRef);
    setFeedback("현재 배포 설계를 편집 초안으로 다시 불러왔습니다.", "ready", documentRef);
    scheduleCanvasFit(documentRef);
    return true;
  }

  function editDeployedServiceDesign(serviceId, documentRef = document) {
    const service = state.deployedServices.find(
      (item) => item.service_id === serviceId,
    );
    const design = buildServiceDraft(serviceId);
    if (!service || !design) {
      setFeedback(
        "이 서비스는 편집할 수 있는 검증된 설계 계약이 없습니다.",
        "error",
        documentRef,
      );
      return false;
    }
    if (isServiceDraftView() && state.selectedDeployedServiceId === serviceId) {
      setFeedback("이 서비스 설계를 이미 편집하고 있습니다.", "ready", documentRef);
      focusDeployedServiceAction(serviceId, documentRef);
      return true;
    }
    if (!isServiceDraftView()) {
      const badge = el("serviceDesignerDraftState", documentRef);
      state.draftSnapshot = {
        design: cloneDesign(state.design),
        dirty: state.dirty,
        loadedFromStorage: state.loadedFromStorage,
        liveBindingSeeded: state.liveBindingSeeded,
        lastValidation: state.lastValidation,
        inputReadiness: cloneDesign(state.inputReadiness),
        selectedNodeId: state.selectedNodeId,
        inspectorOpen: state.inspectorOpen,
        badgeLabel: badge?.textContent || "초안",
        badgeState: badge?.dataset.state || "draft",
      };
    } else cacheActiveServiceDraft();
    state.inputReadinessRequestId += 1;
    const cached = state.serviceDraftCache[serviceId];
    const stored = cached ? null : loadStoredServiceDraft(service);
    state.designMode = "service-draft";
    state.selectedDeployedServiceId = serviceId;
    state.design = cached?.design
      ? cloneDesign(cached.design)
      : stored?.design
        ? cloneDesign(stored.design)
        : design;
    state.dirty = cached?.dirty ?? false;
    state.lastValidation = cached?.lastValidation ?? null;
    state.inputReadiness = cached?.inputReadiness
      ? cloneDesign(cached.inputReadiness)
      : createInputReadiness();
    state.selectedNodeId = cached?.selectedNodeId ?? null;
    state.inspectorOpen = cached?.inspectorOpen ?? false;
    state.pendingFromId = null;
    state.selectedEdgeId = null;
    state.viewportInitialized = false;
    state.paletteOpen = !root.matchMedia?.("(max-width: 860px)").matches;
    renderAll(documentRef);
    setDraftState("서비스 초안", "service-draft", documentRef);
    setFeedback(
      cached || stored
        ? `${service.display_name || service.service_id} 편집 초안을 이어서 엽니다.`
        : `${service.display_name || service.service_id} 원본을 편집 가능한 초안으로 불러왔습니다. 실제 배포에는 반영되지 않습니다.`,
      "success",
      documentRef,
    );
    focusDeployedServiceAction(serviceId, documentRef);
    scheduleCanvasFit(documentRef);
    return true;
  }

  function returnToPreviousDraft(documentRef = document) {
    if (!isServiceDraftView()) return false;
    cacheActiveServiceDraft();
    const snapshot = state.draftSnapshot;
    const previousServiceId = state.selectedDeployedServiceId;
    state.inputReadinessRequestId += 1;
    state.designMode = "draft";
    state.selectedDeployedServiceId = null;
    state.design = snapshot?.design
      ? cloneDesign(snapshot.design)
      : loadStoredDesign() || model.createSensorAnomalyExampleDesign();
    state.dirty = snapshot?.dirty ?? false;
    state.loadedFromStorage = snapshot?.loadedFromStorage ?? false;
    state.liveBindingSeeded = snapshot?.liveBindingSeeded ?? false;
    state.lastValidation = snapshot?.lastValidation ?? null;
    state.inputReadiness = snapshot?.inputReadiness
      ? cloneDesign(snapshot.inputReadiness)
      : createInputReadiness();
    state.selectedNodeId = snapshot?.selectedNodeId ?? null;
    state.inspectorOpen = snapshot?.inspectorOpen ?? false;
    state.pendingFromId = null;
    state.selectedEdgeId = null;
    state.viewportInitialized = false;
    state.paletteOpen = !root.matchMedia?.("(max-width: 860px)").matches;
    renderAll(documentRef);
    setDraftState(
      snapshot?.badgeLabel || (state.dirty ? "초안" : "저장됨"),
      snapshot?.badgeState || (state.dirty ? "draft" : "saved"),
      documentRef,
    );
    setFeedback("기존 브라우저 초안으로 돌아왔습니다. 서비스 편집 내용도 유지됩니다.", "ready", documentRef);
    focusDeployedServiceAction(previousServiceId, documentRef);
    scheduleCanvasFit(documentRef);
    return true;
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
    const multiSensorBinding = bindMultiSensorScoreExample(
      state.design,
      state.inventory,
    );
    if (multiSensorBinding.isExample) {
      state.design = multiSensorBinding.design;
      if (!multiSensorBinding.boundInputs.length && !multiSensorBinding.sourceNode) {
        return false;
      }
      state.liveBindingSeeded = Boolean(multiSensorBinding.sourceNode);
      state.dirty = true;
      setFeedback(
        state.liveBindingSeeded
          ? "가속도 X/Y/Z와 보조 센서를 같은 엣지 노드 입력에 연결했습니다."
          : `복합 점수 입력 ${multiSensorBinding.configuredInputs.length}/4개를 연결했습니다.`,
        state.liveBindingSeeded ? "success" : "ready",
      );
      return true;
    }
    const exampleBinding = bindSensorAnomalyExample(
      state.design,
      state.inventory,
    );
    if (exampleBinding.isExample) {
      state.design = exampleBinding.design;
      if (!exampleBinding.boundAxes.length && !exampleBinding.sourceNode) {
        return false;
      }
      state.liveBindingSeeded = Boolean(exampleBinding.sourceNode);
      state.dirty = true;
      setFeedback(
        state.liveBindingSeeded
          ? "가속도 X/Y/Z를 Jetson 실측 입력에 연결했습니다."
          : `가속도 입력 ${exampleBinding.configuredAxes.length}/3개를 연결했습니다.`,
        state.liveBindingSeeded ? "success" : "ready",
      );
      return true;
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

  function loadSensorAnomalyExample(documentRef = document) {
    if (isServiceDraftView()) return;
    resetInputTelemetryPreview();
    state.design = model.createSensorAnomalyExampleDesign();
    state.selectedNodeId = null;
    state.inspectorOpen = false;
    state.pendingFromId = null;
    state.lastValidation = null;
    state.loadedFromStorage = false;
    state.liveBindingSeeded = false;
    markDirty("가속도 이상 감지 예시 서비스를 불러왔습니다.", documentRef);
    maybeSeedLiveBinding();
    state.viewportInitialized = false;
    renderAll(documentRef);
    scheduleCanvasFit(documentRef);
  }

  function loadMultiSensorScoreExample(documentRef = document) {
    if (isServiceDraftView()) return;
    resetInputTelemetryPreview();
    state.design = model.createMultiSensorScoreExampleDesign();
    state.selectedNodeId = null;
    state.inspectorOpen = false;
    state.pendingFromId = null;
    state.lastValidation = null;
    state.loadedFromStorage = false;
    state.liveBindingSeeded = false;
    markDirty("복합 센서 점수 예시를 불러왔습니다.", documentRef);
    maybeSeedLiveBinding();
    state.viewportInitialized = false;
    renderAll(documentRef);
    scheduleCanvasFit(documentRef);
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
    resetInputReadiness();
    state.selectedEdgeId = null;
    setDraftState(
      isServiceDraftView() ? "서비스 초안 · 변경됨" : "초안",
      isServiceDraftView() ? "service-draft" : "draft",
      documentRef,
    );
    setFeedback(message, "ready", documentRef);
  }

  function renderMiniMap(documentRef = document) {
    if (!viewportModel || !state.design) return;
    const map = el("serviceDesignerMiniMap", documentRef);
    const nodes = el("serviceDesignerMiniMapNodes", documentRef);
    const viewportRect = el("serviceDesignerMiniMapViewport", documentRef);
    const canvasViewport = el("serviceDesignerCanvasViewport", documentRef);
    if (!map || !nodes || !viewportRect || !canvasViewport) return;
    const visible = viewportModel.visibleWorldRect(
      state.viewport,
      canvasViewport.clientWidth,
      canvasViewport.clientHeight,
    );
    const worldBounds = viewportModel.miniMapBounds(
      state.design.nodes,
      visible,
    );
    state.miniMapBounds = worldBounds;
    map.setAttribute(
      "viewBox",
      `${worldBounds.left} ${worldBounds.top} ${worldBounds.width} ${worldBounds.height}`,
    );
    map.setAttribute("preserveAspectRatio", "none");
    nodes.innerHTML = state.design.nodes.map((node) => `
      <rect
        class="service-designer-minimap-node${node.id === state.selectedNodeId ? " selected" : ""}"
        data-designer-minimap-node="${escapeHtml(node.id)}"
        x="${Number(node.x)}"
        y="${Number(node.y)}"
        width="${viewportModel.NODE_WIDTH}"
        height="${viewportModel.NODE_HEIGHT}"
        rx="18"
      ></rect>
    `).join("");
    state.miniMapNodeElements = new Map(
      [...nodes.querySelectorAll("[data-designer-minimap-node]")]
        .map((node) => [node.dataset.designerMinimapNode, node]),
    );
    viewportRect.setAttribute("x", String(visible.x));
    viewportRect.setAttribute("y", String(visible.y));
    viewportRect.setAttribute("width", String(visible.width));
    viewportRect.setAttribute("height", String(visible.height));
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
    const worldBounds = state.miniMapBounds || {
      left: 0,
      top: 0,
      width: viewportModel.CANVAS_WIDTH,
      height: viewportModel.CANVAS_HEIGHT,
    };
    const worldX = worldBounds.left + (
      (event.clientX - bounds.left) / bounds.width
    ) * worldBounds.width;
    const worldY = worldBounds.top + (
      (event.clientY - bounds.top) / bounds.height
    ) * worldBounds.height;
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
          aria-readonly="false"
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
          <g
            class="service-designer-edge-group"
            data-designer-edge="${escapeHtml(edge.id)}"
            data-designer-from="${escapeHtml(edge.from)}"
            data-designer-to="${escapeHtml(edge.to)}"
          >
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
    state.edgeElements = new Map(
      [...container.querySelectorAll("[data-designer-edge]")]
        .map((edge) => [edge.dataset.designerEdge, edge]),
    );
  }

  function inputTelemetryPreviewKey(node = {}) {
    return [node.id, node.config?.deviceName, node.config?.resourceName]
      .map((value) => String(value || ""))
      .join("|");
  }

  function resetInputTelemetryPreview() {
    state.inputTelemetryRequestId += 1;
    state.inputTelemetryPreview = createInputTelemetryPreview();
  }

  function resetInputReadiness() {
    state.inputReadinessRequestId += 1;
    state.inputReadiness = createInputReadiness();
  }

  function formatTelemetryValue(value, units = "") {
    let display = value;
    if (value && typeof value === "object") {
      try {
        display = JSON.stringify(value);
      } catch (_error) {
        display = String(value);
      }
    }
    const normalized = String(display ?? "-");
    const concise = normalized.length > 72
      ? `${normalized.slice(0, 69)}...`
      : normalized;
    return units ? `${concise} ${units}` : concise;
  }

  function formatTelemetryTimestamp(value) {
    const timestamp = Date.parse(String(value || ""));
    if (!Number.isFinite(timestamp)) return "시각 없음";
    return new Intl.DateTimeFormat("ko-KR", {
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false,
    }).format(new Date(timestamp));
  }

  function telemetryAgeLabel(value, now = Date.now()) {
    const timestamp = Date.parse(String(value || ""));
    if (!Number.isFinite(timestamp)) return "시각 없음";
    const elapsedMs = now - timestamp;
    if (elapsedMs < -5000) {
      return `현재보다 ${Math.round(Math.abs(elapsedMs) / 1000)}초 빠름`;
    }
    const seconds = Math.max(0, Math.floor(elapsedMs / 1000));
    if (seconds < 5) return "방금";
    if (seconds < 60) return `${seconds}초 전`;
    const minutes = Math.floor(seconds / 60);
    if (minutes < 60) return `${minutes}분 전`;
    const hours = Math.floor(minutes / 60);
    return hours < 24 ? `${hours}시간 전` : `${Math.floor(hours / 24)}일 전`;
  }

  function formatTelemetryInterval(value) {
    const milliseconds = Number(value);
    if (!Number.isFinite(milliseconds) || milliseconds <= 0) return "계산 불가";
    if (milliseconds < 1000) return `${Math.round(milliseconds)}ms`;
    if (milliseconds < 60000) {
      const seconds = milliseconds / 1000;
      return `${Number.isInteger(seconds) ? seconds : seconds.toFixed(1)}초`;
    }
    const minutes = milliseconds / 60000;
    return `${Number.isInteger(minutes) ? minutes : minutes.toFixed(1)}분`;
  }

  function telemetryFreshnessView(device = {}) {
    const freshness = String(device.telemetry_freshness || "").toLowerCase();
    if (freshness === "fresh") {
      return {state: "fresh", label: "데이터 최신", detail: "실행 입력으로 사용할 수 있습니다."};
    }
    if (freshness === "stale") {
      return {state: "stale", label: "데이터 지연", detail: "최신 Event가 오래되어 실행 계획을 차단합니다."};
    }
    if (freshness === "no_events") {
      return {state: "missing", label: "데이터 없음", detail: "저장된 Event가 없어 실행 계획을 차단합니다."};
    }
    return {state: "unknown", label: "상태 확인 필요", detail: "최신 Event 상태를 확인하지 못했습니다."};
  }

  function renderInputTelemetryPreview(
    node,
    selectedDevice,
    configuredResource,
    preview = state.inputTelemetryPreview,
  ) {
    const deviceName = node.config.deviceName || "";
    const resourceName = node.config.resourceName || "";
    const configured = Boolean(deviceName && resourceName);
    const key = inputTelemetryPreviewKey(node);
    const activePreview = preview.key === key
      ? preview
      : createInputTelemetryPreview();
    const immediate = summarizeDesignerTelemetry(
      selectedDevice?.latest_readings || [],
      resourceName,
    );
    const summary = activePreview.summary || immediate;
    const latest = summary.latest;
    const units = latest?.units || configuredResource?.units || "";
    const freshness = selectedDevice
      ? telemetryFreshnessView(selectedDevice)
      : {state: "unknown", label: "바인딩 필요", detail: "센서 디바이스와 리소스를 선택하세요."};
    let statusState = freshness.state;
    let statusLabel = freshness.label;
    let statusDetail = freshness.detail;
    if (configured && activePreview.status === "loading") {
      statusState = "loading";
      statusLabel = "최근 데이터 조회 중";
      statusDetail = "EdgeX Core Data에서 선택 리소스의 최근 5분을 읽고 있습니다.";
    } else if (configured && activePreview.status === "error") {
      statusState = "error";
      statusLabel = "조회 실패";
      statusDetail = activePreview.error;
    } else if (configured && activePreview.status === "ready" && !summary.sampleCount) {
      statusState = "missing";
      statusLabel = "최근 5분 데이터 없음";
      statusDetail = "선택 리소스와 일치하는 Reading이 없습니다.";
    }
    const latestTimestamp = latest?.timestamp || selectedDevice?.latest_event_timestamp;
    const recentMarkup = summary.recent.length
      ? summary.recent.map((point) => `
        <li>
          <strong>${escapeHtml(formatTelemetryValue(point.value, point.units || units))}</strong>
          <time datetime="${escapeHtml(point.timestamp)}">${escapeHtml(formatTelemetryTimestamp(point.timestamp))}</time>
        </li>
      `).join("")
      : '<li class="service-designer-input-empty">표시할 Reading이 없습니다.</li>';
    return `
      <section class="service-designer-input-preview" data-designer-telemetry-preview aria-label="실제 입력 데이터">
        <header class="service-designer-input-preview-head">
          <span>
            <small>실제 입력 데이터</small>
            <strong>최근 5분 · EdgeX Core Data</strong>
          </span>
          <button
            type="button"
            data-designer-telemetry-refresh
            ${configured && activePreview.status !== "loading" ? "" : "disabled"}
            aria-label="선택 센서의 실제 입력 데이터 새로고침"
          >새로고침</button>
        </header>
        <p class="service-designer-input-state" data-state="${escapeHtml(statusState)}" role="status" aria-live="polite">
          <strong>${escapeHtml(statusLabel)}</strong>
          <span>${escapeHtml(statusDetail)}</span>
        </p>
        <dl class="service-designer-input-summary">
          <div>
            <dt>최신값</dt>
            <dd>${escapeHtml(latest ? formatTelemetryValue(latest.value, units) : "-")}</dd>
          </div>
          <div>
            <dt>최신 시각</dt>
            <dd>${escapeHtml(latestTimestamp ? telemetryAgeLabel(latestTimestamp) : "-")}</dd>
          </div>
          <div>
            <dt>조회 표본</dt>
            <dd>${summary.sampleCount}개</dd>
          </div>
          <div>
            <dt>수집 간격 중앙값</dt>
            <dd>${escapeHtml(formatTelemetryInterval(summary.medianIntervalMs))}</dd>
          </div>
        </dl>
        <div class="service-designer-input-recent">
          <span>최근 Reading</span>
          <ol>${recentMarkup}</ol>
        </div>
        <small class="service-designer-input-note">읽기 전용 미리보기입니다. 이 화면에서 장비 명령이나 배포를 실행하지 않습니다.</small>
      </section>
    `;
  }

  async function loadInputTelemetryPreview(
    nodeId,
    fetchFn = root?.fetch,
    documentRef = document,
    {force = false} = {},
  ) {
    const node = state.design?.nodes.find((item) => item.id === nodeId);
    if (
      !node
      || node.type !== "sensor"
      || !node.config.deviceName
      || !node.config.resourceName
    ) {
      resetInputTelemetryPreview();
      renderInspector(documentRef);
      return null;
    }
    const key = inputTelemetryPreviewKey(node);
    const current = state.inputTelemetryPreview;
    const cacheFresh = Date.now() - current.loadedAt < INPUT_TELEMETRY_CACHE_MS;
    if (current.key === key && current.status === "loading") return current.summary;
    if (
      !force
      && current.key === key
      && ["ready", "error"].includes(current.status)
      && cacheFresh
    ) {
      return current.summary;
    }
    const requestId = state.inputTelemetryRequestId + 1;
    state.inputTelemetryRequestId = requestId;
    state.inputTelemetryPreview = createInputTelemetryPreview({
      key,
      nodeId,
      deviceName: node.config.deviceName,
      resourceName: node.config.resourceName,
      status: "loading",
      summary: current.key === key ? current.summary : null,
    });
    renderInspector(documentRef);
    try {
      const points = await fetchDesignerTelemetry(
        node.config.deviceName,
        INPUT_TELEMETRY_WINDOW,
        fetchFn,
        INPUT_TELEMETRY_LIMIT,
      );
      if (requestId !== state.inputTelemetryRequestId) return null;
      const selected = state.design?.nodes.find((item) => item.id === nodeId);
      if (!selected || inputTelemetryPreviewKey(selected) !== key) return null;
      const summary = summarizeDesignerTelemetry(points, node.config.resourceName);
      state.inputTelemetryPreview = createInputTelemetryPreview({
        key,
        nodeId,
        deviceName: node.config.deviceName,
        resourceName: node.config.resourceName,
        status: "ready",
        summary,
        loadedAt: Date.now(),
      });
      renderInspector(documentRef);
      return summary;
    } catch (error) {
      if (requestId !== state.inputTelemetryRequestId) return null;
      state.inputTelemetryPreview = createInputTelemetryPreview({
        key,
        nodeId,
        deviceName: node.config.deviceName,
        resourceName: node.config.resourceName,
        status: "error",
        summary: current.key === key ? current.summary : null,
        error: error instanceof Error ? error.message : "Telemetry를 조회하지 못했습니다.",
        loadedAt: Date.now(),
      });
      renderInspector(documentRef);
      return null;
    }
  }

  async function loadDesignInputReadiness(
    fetchFn = root?.fetch,
    documentRef = document,
  ) {
    const requestId = state.inputReadinessRequestId + 1;
    state.inputReadinessRequestId = requestId;
    const loading = buildDesignInputReadiness(state.design, state.inventory, {});
    state.inputReadiness = createInputReadiness({
      ...loading,
      status: "loading",
    });
    renderInputReadiness(documentRef);
    renderDesignModeControls(documentRef);

    const sensorNodes = (state.design?.nodes || [])
      .filter((node) => node.type === "sensor");
    const deviceNames = [...new Set(
      sensorNodes
        .filter((node) => node.config.deviceName && node.config.resourceName)
        .map((node) => node.config.deviceName),
    )];
    const byDevice = {};
    await Promise.all(deviceNames.map(async (deviceName) => {
      try {
        byDevice[deviceName] = {
          status: "ready",
          points: await fetchDesignerTelemetry(
            deviceName,
            INPUT_TELEMETRY_WINDOW,
            fetchFn,
            INPUT_TELEMETRY_LIMIT,
          ),
        };
      } catch (error) {
        byDevice[deviceName] = {
          status: "error",
          error: error instanceof Error
            ? error.message
            : "Telemetry를 조회하지 못했습니다.",
        };
      }
    }));
    if (requestId !== state.inputReadinessRequestId) return null;

    const telemetryByNodeId = Object.fromEntries(sensorNodes.map((node) => {
      if (!node.config.deviceName || !node.config.resourceName) {
        return [node.id, {status: "skipped"}];
      }
      const result = byDevice[node.config.deviceName] || {
        status: "error",
        error: "Telemetry 응답이 없습니다.",
      };
      if (result.status !== "ready") return [node.id, result];
      const {points: _points, ...summary} = summarizeDesignerTelemetry(
        result.points,
        node.config.resourceName,
      );
      return [node.id, {status: "ready", summary}];
    }));
    const readiness = buildDesignInputReadiness(
      state.design,
      state.inventory,
      telemetryByNodeId,
    );
    state.inputReadiness = createInputReadiness({
      ...readiness,
      checkedAt: Date.now(),
    });
    renderInputReadiness(documentRef);
    renderDesignModeControls(documentRef);
    return state.inputReadiness;
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
    const configuredResource = resource || (node.config.resourceName
      ? {name: node.config.resourceName, valueType: "Unknown", units: null}
      : null);
    return `
      <label class="service-designer-field">
        <span>센서 디바이스</span>
        <select data-designer-config="deviceName">
          ${optionMarkup("", "선택", node.config.deviceName)}
          ${node.config.deviceName && !selectedDevice
            ? optionMarkup(
              node.config.deviceName,
              `${node.config.deviceName} · 관측 확인 필요`,
              node.config.deviceName,
            )
            : ""}
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
          ${node.config.resourceName && !resource
            ? optionMarkup(
              node.config.resourceName,
              `${node.config.resourceName} · 계약`,
              node.config.resourceName,
            )
            : ""}
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
        <strong>${escapeHtml(selectedDevice?.name || node.config.deviceName || "바인딩 없음")}</strong>
        <span>노드 ${escapeHtml(selectedDevice?.node_name || "미확인")}</span>
        <span>Profile ${escapeHtml(selectedDevice?.profile_name || "미확인")}</span>
        <span>출력 ${escapeHtml(model.canonicalDataType(configuredResource?.valueType))}</span>
      </p>
      ${renderInputTelemetryPreview(node, selectedDevice, configuredResource)}
    `;
  }

  function targetNodeOptions(selectedValue) {
    const nodes = [...state.inventory.nodes].sort(
      (left, right) => nodeName(left).localeCompare(nodeName(right)),
    );
    const nodeNames = new Set(nodes.map((node) => nodeName(node)));
    return [
      optionMarkup("", "선택", selectedValue),
      ...(
        selectedValue && !nodeNames.has(selectedValue)
          ? [optionMarkup(selectedValue, `${selectedValue} · 배포 계약`, selectedValue)]
          : []
      ),
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
    const deployedDetails = node.config.warmupSamples ? `
      <label class="service-designer-field">
        <span>워밍업 표본</span>
        <input type="number" value="${escapeHtml(node.config.warmupSamples)}" />
      </label>
      <label class="service-designer-field">
        <span>모델 버전</span>
        <input type="text" value="${escapeHtml(node.config.modelVersion || "확인 필요")}" />
      </label>
    ` : "";
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
      ${deployedDetails}
    `;
  }

  function renderFusionInspector(node) {
    const incoming = state.design.edges
      .filter((edge) => edge.to === node.id)
      .map((edge) => ({
        ...edge,
        source: state.design.nodes.find((item) => item.id === edge.from),
      }));
    const weights = node.config.weights && typeof node.config.weights === "object"
      ? node.config.weights
      : {};
    const weightedInputs = node.config.method === "weighted_average"
      ? `
        <div class="service-designer-weight-list">
          <span>입력별 가중치</span>
          ${incoming.length ? incoming.map((edge) => `
            <label>
              <span>${escapeHtml(edge.source?.title || edge.from)}</span>
              <input
                data-designer-fusion-weight="${escapeHtml(edge.from)}"
                data-designer-number
                type="number"
                min="0"
                step="0.1"
                value="${escapeHtml(weights[edge.from] ?? 1)}"
              />
            </label>
          `).join("") : "<small>점수 출력을 연결하면 가중치를 설정할 수 있습니다.</small>"}
        </div>
      `
      : "";
    const pipeline = node.config.pipelineAlgorithm ? `
      <label class="service-designer-field">
        <span>파이프라인</span>
        <input type="text" value="${escapeHtml(node.config.pipelineAlgorithm)}" />
      </label>
    ` : "";
    return `
      <label class="service-designer-field">
        <span>결합 방식</span>
        <select data-designer-config="method">
          ${Object.entries(model.FUSION_METHODS).map(([value, item]) => (
            optionMarkup(value, item.label, node.config.method)
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
        <span>누락 점수 처리</span>
        <select data-designer-config="missingPolicy">
          ${Object.entries(model.FUSION_MISSING_POLICIES).map(([value, item]) => (
            optionMarkup(value, item.label, node.config.missingPolicy)
          )).join("")}
        </select>
        <small>${escapeHtml(model.FUSION_MISSING_POLICIES[node.config.missingPolicy]?.description || "")}</small>
      </label>
      ${pipeline}
      ${weightedInputs}
    `;
  }

  function renderInspector(documentRef = document) {
    const inspector = el("serviceDesignerInspector", documentRef);
    const title = el("serviceDesignerInspectorTitle", documentRef);
    const body = el("serviceDesignerInspectorBody", documentRef);
    if (!inspector || !title || !body || !state.design) return;
    const node = state.inspectorOpen
      ? state.design.nodes.find((item) => item.id === state.selectedNodeId)
      : null;
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
    if (node.type === "fusion") fields = renderFusionInspector(node);
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
    const sourceService = state.deployedServices.find(
      (service) => service.service_id === state.selectedDeployedServiceId,
    );
    body.innerHTML = `${isServiceDraftView() ? `
      <p class="service-designer-service-draft-note">
        <strong>${escapeHtml(sourceService?.display_name || sourceService?.service_id || "서비스")}</strong>
        원본에서 복사한 편집 초안입니다. 변경은 실제 배포에 반영되지 않습니다.
      </p>
    ` : ""}${common}${fields}`;
    body.dataset.mode = isServiceDraftView() ? "service-draft" : "draft";
  }

  function renderInputReadiness(documentRef = document) {
    const container = el("serviceDesignerInputReadiness", documentRef);
    const summaryTarget = el("serviceDesignerInputReadinessSummary", documentRef);
    if (!container || !summaryTarget) return;
    const readiness = state.inputReadiness;
    if (readiness.status === "idle") {
      summaryTarget.textContent = "점검 전";
      container.innerHTML = '<p class="service-designer-empty">입력·설계 검증을 누르면 모든 센서 입력의 최근 표본과 필요한 윈도우를 함께 확인합니다.</p>';
      return;
    }
    if (readiness.status === "loading") {
      summaryTarget.textContent = "점검 중";
      container.innerHTML = `
        <p class="service-designer-input-readiness-loading" role="status">
          <span aria-hidden="true"></span>
          EdgeX Core Data에서 서비스 입력 ${readiness.rows.length}개를 확인하고 있습니다.
        </p>
      `;
      return;
    }

    const total = readiness.rows.length;
    const blockedCount = readiness.rows.filter((row) => row.status === "blocked").length;
    const warningCount = readiness.rows.filter((row) => row.status === "warning").length;
    const stateLabel = readiness.status === "ready"
      ? "모든 입력 준비"
      : readiness.status === "blocked"
        ? "입력 준비 차단"
        : "입력 확인 필요";
    const stateCode = readiness.status === "ready"
      ? "READY"
      : readiness.status === "blocked"
        ? "BLOCKED"
        : "CHECK";
    summaryTarget.textContent = readiness.status === "ready"
      ? `${readiness.readyCount}/${total} 준비`
      : `${readiness.readyCount}/${total} 준비 · 차단 ${blockedCount}`;
    const checkedLabel = readiness.checkedAt
      ? telemetryAgeLabel(new Date(readiness.checkedAt).toISOString())
      : "시각 없음";
    const skewLabel = Number.isFinite(readiness.maxSkewMs)
      ? ` · 최대 입력 시각 차이 ${Math.round(readiness.maxSkewMs)}ms`
      : "";
    const rows = readiness.rows.map((row) => {
      const latestValue = row.latest
        ? formatTelemetryValue(row.latest.value, row.latest.units || row.units)
        : "-";
      return `
        <li class="service-designer-input-readiness-row" data-state="${escapeHtml(row.status)}">
          <div class="service-designer-input-readiness-identity">
            <strong>${escapeHtml(row.title)}</strong>
            <span>${escapeHtml(row.deviceName)} / ${escapeHtml(row.resourceName)}</span>
          </div>
          <div class="service-designer-input-readiness-cell">
            <small>물리 노드</small>
            <span>${escapeHtml(row.nodeName)}</span>
          </div>
          <div class="service-designer-input-readiness-cell">
            <small>최신값</small>
            <strong>${escapeHtml(latestValue)}</strong>
            <span>${escapeHtml(row.latestTimestamp ? telemetryAgeLabel(row.latestTimestamp) : "시각 없음")}</span>
          </div>
          <div class="service-designer-input-readiness-cell">
            <small>관측 증거</small>
            <strong>${row.sampleCount} / ${row.requiredSamples}개</strong>
            <span>${escapeHtml(formatTelemetryInterval(row.medianIntervalMs))}</span>
          </div>
          <div class="service-designer-input-readiness-result">
            <strong>${escapeHtml(row.statusLabel)}</strong>
            <span>${escapeHtml(row.reason)}</span>
          </div>
        </li>
      `;
    }).join("");
    container.innerHTML = `
      <div class="service-designer-input-readiness-gate" data-state="${escapeHtml(readiness.status)}">
        <span>
          <strong>${escapeHtml(stateLabel)}</strong>
          <small>${readiness.readyCount}/${total}개 준비 · 차단 ${blockedCount} · 확인 ${warningCount}${escapeHtml(skewLabel)}</small>
        </span>
        <b>${escapeHtml(stateCode)}</b>
      </div>
      <ol class="service-designer-input-readiness-list">${rows}</ol>
      <p class="service-designer-input-readiness-note">
        ${escapeHtml(checkedLabel)} 점검 · 최근 5분 Core Data를 읽은 실행 전 증거입니다. local_recent Runtime이나 Workflow를 실행하지 않습니다.
      </p>
    `;
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
    const effectiveErrors = state.lastValidation.errors || [];
    const planReady = plan.valid && state.lastValidation.valid;
    const gate = `
      <li class="service-designer-plan-gate" data-state="${planReady ? "ready" : "blocked"}">
        <b aria-hidden="true">${planReady ? "OK" : "!"}</b>
        <span>
          <strong>${planReady ? "Dry-run 준비" : "실행 계획 차단"}</strong>
          <small>${planReady
            ? "검증을 통과했습니다. 아래 순서는 읽기 전용 미리보기입니다."
            : `오류 ${effectiveErrors.length}건을 해결해야 실행 계획을 사용할 수 있습니다.`}</small>
        </span>
        <small>${planReady ? "PREVIEW" : "BLOCKED"}</small>
      </li>
    `;
    const blockers = planReady ? "" : effectiveErrors.slice(0, 5).map((issue) => `
      <li class="service-designer-plan-blocker">
        <b aria-hidden="true">!</b>
        <span>
          <strong>${escapeHtml(issue.code)}</strong>
          <small>${escapeHtml(issue.message)}</small>
        </span>
        <small>차단</small>
      </li>
    `).join("");
    const stages = plan.stages.map((stage) => `
      <li>
        <b>${stage.order}</b>
        <span>
          <strong>${escapeHtml(stage.label)}</strong>
          <small>${escapeHtml(stage.detail)}</small>
        </span>
        <small>${escapeHtml(stage.outputType === "none" ? "result" : stage.outputType)}</small>
      </li>
    `).join("");
    container.innerHTML = `${gate}${blockers}${stages}`;
  }

  function renderInventoryState(documentRef = document) {
    const target = el("serviceDesignerInventoryState", documentRef);
    if (!target) return;
    const profileSuffix = state.inventory.profiles.length
      ? ` · Profile ${state.inventory.profiles.length}개`
      : " · Profile 확인 중";
    target.textContent = `센서 ${state.inventory.devices.length}개 · 노드 ${state.inventory.nodes.length}개${profileSuffix}`;
  }

  const SERVICE_STATUS_LABELS = {
    starting: "시작 중",
    warming_up: "준비 중",
    normal: "정상",
    anomaly: "이상 감지",
    degraded: "점검 필요",
  };
  const SERVICE_INPUT_LABELS = {
    waiting: "입력 대기",
    fresh: "데이터 최신",
    stale: "데이터 지연",
    error: "입력 오류",
  };
  const SERVICE_MODEL_LABELS = {
    warming_up: "모델 준비 중",
    ready: "모델 준비",
    unavailable: "모델 확인 불가",
  };

  function conciseFlowTitle(value) {
    return String(value || "")
      .replace(/\s*\([^)]*\)\s*/g, " ")
      .replace(/\s+/g, " ")
      .trim();
  }

  function summarizeFlowTitles(nodes, fallback, limit = 3) {
    const titles = (Array.isArray(nodes) ? nodes : [])
      .map((node) => conciseFlowTitle(node?.title))
      .filter(Boolean);
    if (!titles.length) return fallback;
    if (titles.length <= limit) return titles.join(" · ");
    return `${titles.slice(0, limit).join(" · ")} 외 ${titles.length - limit}개`;
  }

  function summarizeSensorInputs(nodes, fallback) {
    const titles = (Array.isArray(nodes) ? nodes : [])
      .map((node) => conciseFlowTitle(node?.title))
      .filter(Boolean);
    const accelerationAxes = ["X", "Y", "Z"].filter((axis) =>
      titles.some((title) => title === `가속도 ${axis}`),
    );
    if (accelerationAxes.length !== 3) {
      return summarizeFlowTitles(nodes, fallback, 4);
    }
    const remaining = titles.filter((title) => !/^가속도 [XYZ]$/.test(title));
    return ["가속도 3축", ...remaining].join(" + ");
  }

  function deployedServiceFlow(service = {}) {
    const design = model.createDeployedServiceDesign?.(service);
    const nodes = Array.isArray(design?.nodes) ? design.nodes : [];
    const byType = (type) => nodes.filter((node) => node.type === type);
    const sources = byType("sensor");
    const preprocessors = byType("preprocess");
    const inference = byType("inference");
    const fusion = byType("fusion");
    const outputs = byType("output");
    const inputCount = Array.isArray(service.input_devices)
      ? service.input_devices.length
      : sources.length;
    const analysisStages = [...inference, ...fusion];
    const hasFusion = fusion.length > 0;

    return [
      {
        kind: "input",
        label: "입력",
        title: summarizeSensorInputs(sources, inputCount ? `센서 ${inputCount}개` : "입력 확인 필요"),
        detail: inputCount ? `${inputCount}개 센서` : "입력 없음",
      },
      {
        kind: "process",
        label: "전처리",
        title: summarizeFlowTitles(preprocessors, design ? "전처리 없음" : "설계 계약 확인 필요", 2),
        detail: preprocessors.length ? `${preprocessors.length}개 처리 단계` : "단계 미확인",
      },
      {
        kind: "analysis",
        label: "AI 분석",
        title: hasFusion
          ? "이상 점수 결합"
          : summarizeFlowTitles(analysisStages, "모델 확인 필요", 2),
        detail: service.model_version
          ? `모델 ${String(service.model_version)}`
          : `${analysisStages.length}개 분석 단계`,
      },
      {
        kind: "output",
        label: "결과",
        title: summarizeFlowTitles(outputs, "결과 확인 필요", 1),
        detail: outputs.length ? "운영 화면에 표시" : "출력 미확인",
      },
    ];
  }

  function deployedServiceView(service = {}) {
    const status = Object.hasOwn(SERVICE_STATUS_LABELS, service.status)
      ? service.status
      : "degraded";
    const inputDevices = Array.isArray(service.input_devices)
      ? service.input_devices
      : [];
    return {
      status,
      statusLabel: SERVICE_STATUS_LABELS[status],
      inputLabel: SERVICE_INPUT_LABELS[service.input_state] || "입력 확인 필요",
      modelLabel: SERVICE_MODEL_LABELS[service.model_state] || "모델 확인 필요",
      inputCount: inputDevices.length,
      node: String(service.node || "배치 확인 필요"),
      modelVersion: String(service.model_version || "버전 확인 필요"),
      description: String(service.description || "서비스 설명이 등록되지 않았습니다."),
      physicalSource: String(service.physical_source || "물리 소스 확인 필요"),
      deviceService: String(service.device_service || "Device Service 확인 필요"),
      flow: deployedServiceFlow(service),
      designAvailable: Boolean(model.createDeployedServiceDesign?.(service)),
    };
  }

  function renderDeployedServices(documentRef = document) {
    const container = el("serviceDesignerDeployedList", documentRef);
    const count = el("serviceDesignerDeployedCount", documentRef);
    if (!container || !count) return;
    if (state.deployedServicesError) {
      count.textContent = "조회 실패";
      container.innerHTML = `<p class="service-designer-empty">${escapeHtml(state.deployedServicesError)}</p>`;
      return;
    }
    count.textContent = `${state.deployedServices.length}개`;
    if (!state.deployedServices.length) {
      container.innerHTML = '<p class="service-designer-empty">현재 등록된 실행 서비스가 없습니다.</p>';
      return;
    }
    container.innerHTML = state.deployedServices.map((service) => {
      const view = deployedServiceView(service);
      const selected = isServiceDraftView()
        && state.selectedDeployedServiceId === service.service_id;
      const cached = Boolean(
        state.serviceDraftCache[service.service_id]
        || loadStoredServiceDraft(service),
      );
      return `
        <article
          class="service-designer-deployed-item${selected ? " selected" : ""}"
          data-service-status="${escapeHtml(view.status)}"
          data-selected="${selected ? "true" : "false"}"
          role="listitem"
        >
          <div class="service-designer-deployed-top">
            <div class="service-designer-deployed-identity">
              <div class="service-designer-deployed-title-line">
                <strong>${escapeHtml(service.display_name || service.service_id)}</strong>
                <span class="service-designer-service-status" data-status="${escapeHtml(view.status)}">
                  <i aria-hidden="true"></i>${escapeHtml(view.statusLabel)}
                </span>
              </div>
              <p>${escapeHtml(view.description)}</p>
              <span>${escapeHtml(service.service_id)}</span>
            </div>
            <button
              class="service-designer-deployed-action"
              type="button"
              data-deployed-service-design="${escapeHtml(service.service_id)}"
              aria-pressed="${selected ? "true" : "false"}"
              ${view.designAvailable ? "" : 'disabled aria-disabled="true" title="검증된 설계 계약이 없습니다."'}
            >${view.designAvailable ? (selected ? "편집 중" : cached ? "편집 계속" : "설계 편집") : "설계 없음"}</button>
          </div>
          <div class="service-designer-service-flow" role="list" aria-label="${escapeHtml(service.display_name || service.service_id)} 데이터 흐름">
            ${view.flow.map((stage, index) => `
              ${index ? '<span class="service-designer-flow-arrow" aria-hidden="true">→</span>' : ""}
              <div class="service-designer-flow-stage" data-stage="${escapeHtml(stage.kind)}" role="listitem">
                <span class="service-designer-flow-step" aria-hidden="true">${index + 1}</span>
                <div>
                  <small>${escapeHtml(stage.label)}</small>
                  <strong>${escapeHtml(stage.title)}</strong>
                  <span>${escapeHtml(stage.detail)}</span>
                </div>
              </div>
            `).join("")}
          </div>
          <div class="service-designer-deployed-meta" aria-label="서비스 실행 정보">
            <span><b>실행 위치</b>${escapeHtml(view.node)}</span>
            <span><b>수집 경로</b>${escapeHtml(view.physicalSource)} → ${escapeHtml(view.deviceService)}</span>
            <span><b>현재 상태</b>${escapeHtml(view.inputLabel)} · ${escapeHtml(view.modelLabel)}</span>
          </div>
        </article>
      `;
    }).join("");
  }

  function renderServiceCatalog(documentRef = document) {
    const container = el("serviceDesignerPaletteList", documentRef);
    const catalogState = el("serviceDesignerCatalogState", documentRef);
    if (!container || !model?.buildServiceCatalog) return;
    const query = (
      el("serviceDesignerPaletteSearch", documentRef)?.value || ""
    ).trim().toLowerCase();
    const catalog = model.buildServiceCatalog(state.inventory);
    const categoryLabels = new Map(
      (model.SERVICE_CATEGORIES || []).map((category) => [category.id, category.label]),
    );
    const matches = catalog.filter((service) => {
      const categoryLabel = categoryLabels.get(service.category) || "";
      return !query || `${service.label} ${service.description} ${categoryLabel}`
        .toLowerCase()
        .includes(query);
    });
    const sourceCount = Math.max(
      0,
      ...catalog
        .filter((service) => service.category === "input")
        .map((service) => service.eligibleCount || 0),
    );
    if (catalogState) {
      catalogState.textContent = query
        ? `${matches.length}/${catalog.length}개 블록`
        : `${catalog.length}개 블록 · EdgeX 입력 ${sourceCount}개`;
    }
    if (!matches.length) {
      container.innerHTML = '<p class="service-designer-empty">검색 결과가 없습니다.</p>';
      return;
    }
    container.innerHTML = (model.SERVICE_CATEGORIES || []).map((category) => {
      const services = matches.filter((service) => service.category === category.id);
      if (!services.length) return "";
      return `
        <section class="service-designer-service-group" aria-labelledby="serviceCatalog-${escapeHtml(category.id)}">
          <div class="service-designer-service-group-head">
            <h3 id="serviceCatalog-${escapeHtml(category.id)}">${escapeHtml(category.label)}</h3>
            <span>${services.length}</span>
          </div>
          <div class="service-designer-service-items">
            ${services.map((service) => `
              <button
                type="button"
                data-designer-service="${escapeHtml(service.id)}"
                data-service-state="${escapeHtml(service.availability)}"
                aria-label="${escapeHtml(service.label)} 서비스 추가"
                ${service.enabled ? "" : 'disabled aria-disabled="true" title="현재 선택 가능한 EdgeX 입력이 없습니다."'}
              >
                <span class="service-designer-service-title">
                  <strong>${escapeHtml(service.label)}</strong>
                  <small>${escapeHtml(service.badge)}</small>
                </span>
                <span>${escapeHtml(service.description)}</span>
              </button>
            `).join("")}
          </div>
        </section>
      `;
    }).join("");
  }

  function renderDesignModeControls(documentRef = document) {
    const serviceDraft = isServiceDraftView();
    const nameInput = el("serviceDesignerName", documentRef);
    const returnButton = el("serviceDesignerReturnDraft", documentRef);
    const reloadButton = el("serviceDesignerReloadService", documentRef);
    const exampleButtons = [
      el("serviceDesignerReset", documentRef),
      el("serviceDesignerMultiSensorExample", documentRef),
    ].filter(Boolean);
    const paletteToggle = el("serviceDesignerPaletteToggle", documentRef);
    const paletteClose = el("serviceDesignerPaletteClose", documentRef);
    const paletteSearch = el("serviceDesignerPaletteSearch", documentRef);
    const validateButton = el("serviceDesignerValidate", documentRef);
    const connectHint = el("serviceDesignerConnectHint", documentRef);
    const canvasStatus = el("serviceDesignerCanvasStatus", documentRef);
    const workbench = el("serviceDesignerWorkbench", documentRef);
    if (nameInput) {
      nameInput.readOnly = false;
      nameInput.setAttribute("aria-readonly", "false");
    }
    if (returnButton) returnButton.hidden = !serviceDraft;
    if (reloadButton) reloadButton.hidden = !serviceDraft;
    exampleButtons.forEach((button) => {
      button.hidden = serviceDraft;
      button.disabled = serviceDraft;
    });
    if (paletteToggle) paletteToggle.disabled = false;
    if (paletteClose) paletteClose.disabled = false;
    if (paletteSearch) paletteSearch.disabled = false;
    if (validateButton) {
      const checkingInputs = state.inputReadiness.status === "loading";
      validateButton.textContent = checkingInputs
        ? "입력 점검 중..."
        : "입력·설계 검증";
      validateButton.disabled = checkingInputs;
      validateButton.setAttribute("aria-busy", String(checkingInputs));
    }
    if (connectHint) {
      connectHint.textContent = "출력 포트 → 입력 포트";
    }
    if (canvasStatus) {
      canvasStatus.textContent = serviceDraft
        ? "서비스 원본 기반 편집 초안 · 실제 배포 미반영"
        : "자유 드래그 · 가장자리 자동 이동 · 놓을 때 정렬 · Alt 정렬 해제";
    }
    if (workbench) {
      workbench.dataset.designMode = serviceDraft ? "service-draft" : "draft";
      workbench.classList.toggle("palette-open", state.paletteOpen);
    }
    paletteToggle?.setAttribute("aria-expanded", String(state.paletteOpen));
  }

  function renderAll(documentRef = document) {
    if (!state.initialized || !state.design) return;
    if (state.dragging) {
      state.pendingFullRender = true;
      return;
    }
    state.pendingFullRender = false;
    const nameInput = el("serviceDesignerName", documentRef);
    if (nameInput && nameInput.value !== state.design.name) {
      nameInput.value = state.design.name;
    }
    renderDesignModeControls(documentRef);
    renderInventoryState(documentRef);
    renderDeployedServices(documentRef);
    renderServiceCatalog(documentRef);
    renderNodes(documentRef);
    renderEdges(documentRef);
    renderInspector(documentRef);
    renderInputReadiness(documentRef);
    renderValidation(documentRef);
    renderPlan(documentRef);
    const selected = state.inspectorOpen
      ? state.design.nodes.find((node) => node.id === state.selectedNodeId)
      : null;
    if (
      selected?.type === "sensor"
      && selected.config.deviceName
      && selected.config.resourceName
    ) {
      void loadInputTelemetryPreview(selected.id, root?.fetch, documentRef);
    }
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
    if (state.selectedNodeId !== nodeId) resetInputTelemetryPreview();
    state.selectedNodeId = nodeId;
    state.inspectorOpen = true;
    state.selectedEdgeId = null;
    renderNodes(documentRef);
    renderEdges(documentRef);
    renderInspector(documentRef);
    renderMiniMap(documentRef);
    const selected = state.design.nodes.find((node) => node.id === nodeId);
    if (
      selected?.type === "sensor"
      && selected.config.deviceName
      && selected.config.resourceName
    ) {
      void loadInputTelemetryPreview(nodeId, root?.fetch, documentRef);
    }
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
    const fusionWeightSource = target.dataset.designerFusionWeight;
    if (fusionWeightSource) {
      const weights = node.config.weights && typeof node.config.weights === "object"
        ? {...node.config.weights}
        : {};
      weights[fusionWeightSource] = Number(target.value);
      state.design = model.updateNode(state.design, node.id, {
        config: {weights},
      });
      markDirty("점수 가중치를 변경했습니다.", documentRef);
      renderAll(documentRef);
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
    if (key === "deviceName" || key === "resourceName") {
      resetInputTelemetryPreview();
    }
    markDirty("단계 설정을 변경했습니다.", documentRef);
    renderAll(documentRef);
  }

  async function validateCurrentDesign(documentRef = document) {
    const reviewPanel = el("serviceDesignerReviewPanel", documentRef);
    if (reviewPanel) reviewPanel.open = true;
    setFeedback(
      "모든 센서 입력의 최근 표본과 설계 계약을 확인하고 있습니다.",
      "ready",
      documentRef,
    );
    const readiness = await loadDesignInputReadiness(root?.fetch, documentRef);
    if (!readiness) return null;
    state.lastValidation = mergeValidationWithInputReadiness(
      model.validateDesign(state.design, state.inventory),
      readiness,
    );
    const valid = state.lastValidation.valid;
    setDraftState(
      isServiceDraftView() && valid
        ? "서비스 초안 · 검증됨"
        : valid
          ? "검증됨"
          : "수정 필요",
      valid ? "valid" : "invalid",
      documentRef,
    );
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

  function revalidateReviewedDesign(documentRef = document) {
    if (!state.lastValidation) return null;
    let readiness = state.inputReadiness;
    if (!["idle", "loading"].includes(readiness.status)) {
      const refreshed = buildDesignInputReadiness(
        state.design,
        state.inventory,
        readiness.telemetryByNodeId,
      );
      readiness = createInputReadiness({
        ...refreshed,
        checkedAt: state.inputReadiness.checkedAt,
      });
      state.inputReadiness = readiness;
    }
    state.lastValidation = mergeValidationWithInputReadiness(
      model.validateDesign(state.design, state.inventory),
      readiness,
    );
    const valid = state.lastValidation.valid;
    setDraftState(
      valid
        ? isServiceDraftView() ? "서비스 초안 · 검증됨" : "검증됨"
        : "입력 변경 · 수정 필요",
      valid ? "valid" : "invalid",
      documentRef,
    );
    return state.lastValidation;
  }

  function updateInventory(data = {}, documentRef = document) {
    state.inventory.devices = Array.isArray(data.devices) ? data.devices : [];
    state.inventory.nodes = Array.isArray(data.nodes) ? data.nodes : [];
    if (!isServiceDraftView()) maybeSeedLiveBinding();
    revalidateReviewedDesign(documentRef);
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

  async function fetchDesignerServices(fetchFn = fetch) {
    const response = await fetchFn("/state/services", {cache: "no-store"});
    if (!response.ok) {
      throw new Error(`실행 서비스 API 오류 (${response.status})`);
    }
    const payload = await response.json();
    if (!payload || !Array.isArray(payload.services)) {
      throw new Error("실행 서비스 응답 형식이 올바르지 않습니다.");
    }
    return payload.services;
  }

  async function refreshDeployedServices(fetchFn = fetch, documentRef = document) {
    try {
      state.deployedServices = await fetchDesignerServices(fetchFn);
      state.deployedServicesError = "";
      renderDeployedServices(documentRef);
      return true;
    } catch (error) {
      state.deployedServices = [];
      state.deployedServicesError = error instanceof Error
        ? error.message
        : "실행 서비스 목록을 조회하지 못했습니다.";
      renderDeployedServices(documentRef);
      return false;
    }
  }

  async function refreshProfiles(
    fetchFn = fetch,
    documentRef = document,
  ) {
    try {
      state.inventory.profiles = await fetchDesignerProfiles(fetchFn);
      if (!isServiceDraftView()) maybeSeedLiveBinding();
      revalidateReviewedDesign(documentRef);
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

  function updateDraggedEdges(drag) {
    if (!drag || !state.design) return;
    const nodes = Object.fromEntries(
      state.design.nodes.map((node) => [
        node.id,
        node.id === drag.nodeId
          ? {...node, x: drag.x, y: drag.y}
          : node,
      ]),
    );
    state.design.edges.forEach((edge) => {
      if (edge.from !== drag.nodeId && edge.to !== drag.nodeId) return;
      const group = state.edgeElements.get(edge.id);
      const from = nodes[edge.from];
      const to = nodes[edge.to];
      if (!group || !from || !to) return;
      const path = edgePath(from, to);
      group.querySelectorAll("path").forEach((element) => {
        element.setAttribute("d", path.d);
      });
      const label = group.querySelector(".service-designer-edge-label");
      label?.setAttribute("x", String(path.labelX));
      label?.setAttribute("y", String(path.labelY));
    });
  }

  function updateDraggedMiniMapNode(drag) {
    const node = drag && state.miniMapNodeElements.get(drag.nodeId);
    if (!node) return;
    node.setAttribute("x", String(drag.x));
    node.setAttribute("y", String(drag.y));
  }

  function scheduleDragAuxiliaryRender(documentRef = document) {
    const drag = state.dragging;
    if (!drag || drag.renderFrame !== null) return;
    const render = () => {
      drag.renderFrame = null;
      if (state.dragging !== drag) return;
      updateDraggedEdges(drag, documentRef);
      updateDraggedMiniMapNode(drag, documentRef);
    };
    if (root?.requestAnimationFrame) {
      drag.renderFrame = root.requestAnimationFrame(render);
      return;
    }
    render();
  }

  function cancelDragAuxiliaryRender(drag) {
    if (!drag || drag.renderFrame === null) return;
    root?.cancelAnimationFrame?.(drag.renderFrame);
    drag.renderFrame = null;
  }

  function flushPendingFullRender(documentRef = document) {
    if (!state.pendingFullRender) return false;
    state.pendingFullRender = false;
    renderAll(documentRef);
    return true;
  }

  function selectNodeForDrag(nodeId, nodeElement, documentRef = document) {
    state.selectedNodeId = nodeId;
    state.inspectorOpen = false;
    state.selectedEdgeId = null;
    documentRef.querySelectorAll("[data-designer-node]").forEach((element) => {
      element.classList.toggle(
        "selected",
        element.dataset.designerNode === nodeId,
      );
    });
    documentRef.querySelectorAll(".service-designer-edge-path.selected")
      .forEach((element) => element.classList.remove("selected"));
    documentRef.querySelectorAll(".service-designer-edge-label")
      .forEach((element) => element.remove());
    state.miniMapNodeElements.forEach((element, id) => {
      element.classList.toggle("selected", id === nodeId);
    });
    const inspector = el("serviceDesignerInspector", documentRef);
    inspector?.classList.remove("is-open");
    inspector?.setAttribute("aria-hidden", "true");
    try {
      nodeElement.focus({preventScroll: true});
    } catch (_error) {
      nodeElement.focus?.();
    }
  }

  function startDrag(event, nodeId, documentRef = document) {
    if (
      event.button !== 0
      || event.target.closest?.("button")
    ) return;
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
      dropX: Number(node.x),
      dropY: Number(node.y),
      nodeWidth: Math.max(1, nodeElement.offsetWidth || viewportModel.NODE_WIDTH),
      nodeHeight: Math.max(1, nodeElement.offsetHeight || viewportModel.NODE_HEIGHT),
      pointerId: event.pointerId,
      moved: false,
      renderFrame: null,
      autoPanFrame: null,
      startViewport: {...state.viewport},
      pointerClientX: event.clientX,
      pointerClientY: event.clientY,
      shiftKey: false,
      altKey: false,
    };
    try {
      nodeElement.setPointerCapture?.(event.pointerId);
    } catch (_error) {
      // Pointer capture is an enhancement; window listeners remain the fallback.
    }
    event.preventDefault();
  }

  function cancelDragAutoPan(drag) {
    if (!drag || drag.autoPanFrame === null) return;
    root?.cancelAnimationFrame?.(drag.autoPanFrame);
    drag.autoPanFrame = null;
  }

  function updateDragPlacement(
    clientX,
    clientY,
    shiftKey,
    altKey,
    documentRef = document,
    autoPan = true,
  ) {
    const drag = state.dragging;
    const canvasViewport = el("serviceDesignerCanvasViewport", documentRef);
    if (!drag || !canvasViewport) return {x: 0, y: 0};
    drag.pointerClientX = clientX;
    drag.pointerClientY = clientY;
    drag.shiftKey = Boolean(shiftKey);
    drag.altKey = Boolean(altKey);

    const canvasBounds = canvasViewport.getBoundingClientRect();
    const panDelta = autoPan
      ? viewportModel.dragAutoPanDelta(
          {x: clientX, y: clientY},
          canvasBounds,
        )
      : {x: 0, y: 0};
    if (panDelta.x || panDelta.y) {
      state.viewport = viewportModel.panViewport(
        state.viewport,
        panDelta.x,
        panDelta.y,
      );
      state.viewportInitialized = true;
      applyCanvasViewport(documentRef);
    }

    const freePosition = viewportModel.dragNodePosition(
      {x: drag.startX, y: drag.startY},
      {x: drag.startClientX, y: drag.startClientY},
      {x: clientX, y: clientY},
      drag.startViewport,
      state.viewport,
    );
    const constrained = viewportModel.constrainNodePosition(
      {x: drag.startX, y: drag.startY},
      freePosition,
      shiftKey,
    );
    const zoom = Math.max(0.01, Number(state.viewport.zoom) || 1);
    const dropPlacement = viewportModel.snapNodePosition(
      constrained,
      state.design.nodes,
      drag.nodeId,
      {
        snap: !altKey,
        // Pointer movement stays one-to-one with the node. Matching peer
        // anchors are applied only when the pointer is released.
        grid: false,
        tolerance: viewportModel.SNAP_TOLERANCE / zoom,
        lockX: constrained.lockedAxis === "vertical",
        lockY: constrained.lockedAxis === "horizontal",
        nodeWidth: drag.nodeWidth,
        nodeHeight: drag.nodeHeight,
      },
    );
    drag.x = constrained.x;
    drag.y = constrained.y;
    drag.dropX = dropPlacement.x;
    drag.dropY = dropPlacement.y;
    drag.nodeElement.style.transform = `translate3d(${drag.x - drag.startX}px, ${drag.y - drag.startY}px, 0)`;
    renderDragGuides(dropPlacement.guides, documentRef);
    scheduleDragAuxiliaryRender(documentRef);
    return panDelta;
  }

  function scheduleDragAutoPan(documentRef = document) {
    const drag = state.dragging;
    if (!drag || drag.autoPanFrame !== null || !root?.requestAnimationFrame) {
      return;
    }
    drag.autoPanFrame = root.requestAnimationFrame(() => {
      drag.autoPanFrame = null;
      if (state.dragging !== drag || !drag.moved) return;
      const panDelta = updateDragPlacement(
        drag.pointerClientX,
        drag.pointerClientY,
        drag.shiftKey,
        drag.altKey,
        documentRef,
        true,
      );
      if (panDelta.x || panDelta.y) scheduleDragAutoPan(documentRef);
    });
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
      && Math.hypot(deltaClientX, deltaClientY) < DRAG_ACTIVATION_PX
    ) {
      return false;
    }
    if (!state.dragging.moved) {
      state.dragging.moved = true;
      selectNodeForDrag(
        state.dragging.nodeId,
        state.dragging.nodeElement,
        documentRef,
      );
      state.dragging.nodeElement.classList.add("is-dragging");
      el("serviceDesignerCanvasViewport", documentRef)?.classList.add(
        "is-node-dragging",
      );
    }
    const panDelta = updateDragPlacement(
      event.clientX,
      event.clientY,
      event.shiftKey,
      event.altKey,
      documentRef,
      true,
    );
    if (panDelta.x || panDelta.y) scheduleDragAutoPan(documentRef);
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
    cancelDragAuxiliaryRender(drag);
    cancelDragAutoPan(drag);
    state.dragging = null;
    drag.nodeElement.classList.remove("is-dragging");
    drag.nodeElement.style.transform = "";
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
      if (!flushPendingFullRender(documentRef) && drag.moved) {
        renderEdges(documentRef);
        renderMiniMap(documentRef);
      }
      return false;
    }
    const x = Math.round(drag.dropX * 100) / 100;
    const y = Math.round(drag.dropY * 100) / 100;
    drag.nodeElement.style.left = `${x}px`;
    drag.nodeElement.style.top = `${y}px`;
    state.suppressNodeClickId = drag.nodeId;
    state.suppressNodeClickUntil = Date.now() + DRAG_CLICK_SUPPRESSION_MS;
    root.setTimeout?.(() => {
      if (
        state.suppressNodeClickId === drag.nodeId
        && Date.now() >= state.suppressNodeClickUntil
      ) {
        state.suppressNodeClickId = null;
        state.suppressNodeClickUntil = 0;
      }
    }, DRAG_CLICK_SUPPRESSION_MS);
    if (x === drag.startX && y === drag.startY) {
      if (!flushPendingFullRender(documentRef)) {
        renderEdges(documentRef);
        renderMiniMap(documentRef);
      }
      return true;
    }
    state.design = model.updateNode(state.design, drag.nodeId, {x, y});
    markDirty("단계 위치를 변경했습니다.", documentRef);
    if (!flushPendingFullRender(documentRef)) {
      renderEdges(documentRef);
      renderMiniMap(documentRef);
    }
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
    revealCanvasNode(node.id, documentRef);
    return true;
  }

  function bindEvents(documentRef = document) {
    documentRef.addEventListener("click", (event) => {
      const suppressedNode = event.target.closest?.("[data-designer-node]");
      if (
        suppressedNode
        && state.suppressNodeClickId === suppressedNode.dataset.designerNode
        && Date.now() <= state.suppressNodeClickUntil
      ) {
        state.suppressNodeClickId = null;
        state.suppressNodeClickUntil = 0;
        event.preventDefault();
        event.stopPropagation();
        return;
      }
      if (Date.now() > state.suppressNodeClickUntil) {
        state.suppressNodeClickId = null;
        state.suppressNodeClickUntil = 0;
      }
      const telemetryRefresh = event.target.closest?.(
        "[data-designer-telemetry-refresh]",
      );
      if (telemetryRefresh) {
        if (telemetryRefresh.disabled || !state.selectedNodeId) return;
        void loadInputTelemetryPreview(
          state.selectedNodeId,
          root?.fetch,
          documentRef,
          {force: true},
        );
        return;
      }
      const deployedDesignButton = event.target.closest?.(
        "[data-deployed-service-design]",
      );
      if (deployedDesignButton) {
        if (deployedDesignButton.disabled) return;
        editDeployedServiceDesign(
          deployedDesignButton.dataset.deployedServiceDesign,
          documentRef,
        );
        return;
      }
      const serviceButton = event.target.closest?.("[data-designer-service]");
      if (serviceButton) {
        if (serviceButton.disabled) return;
        const serviceId = serviceButton.dataset.designerService;
        state.design = model.addServiceNode(state.design, serviceId);
        const added = state.design.nodes[state.design.nodes.length - 1];
        if (added.type === "sensor") {
          const service = model.serviceDefinition(serviceId);
          const candidateInventory = service?.inputKind === "local"
            ? {
              ...state.inventory,
              devices: state.inventory.devices.filter((device) => device.node_name),
            }
            : state.inventory;
          const candidate = sourceBindingCandidate(candidateInventory);
          if (candidate) {
            state.design = model.updateNode(state.design, added.id, {
              config: {
                deviceName: candidate.device.name,
                resourceName: candidate.resource.name,
              },
            });
          }
        }
        state.selectedNodeId = added.id;
        state.inspectorOpen = true;
        markDirty(`${added.title} 서비스를 추가했습니다.`, documentRef);
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
        if (state.selectedNodeId === nodeId) {
          resetInputTelemetryPreview();
          state.selectedNodeId = null;
          state.inspectorOpen = false;
        }
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
        resetInputTelemetryPreview();
        state.selectedNodeId = null;
        state.inspectorOpen = false;
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
      () => renderServiceCatalog(documentRef),
    );
    el("serviceDesignerValidate", documentRef)?.addEventListener(
      "click",
      () => void validateCurrentDesign(documentRef),
    );
    el("serviceDesignerSave", documentRef)?.addEventListener("click", () => {
      try {
        if (isServiceDraftView()) {
          const service = state.deployedServices.find(
            (item) => item.service_id === state.selectedDeployedServiceId,
          );
          if (!saveStoredServiceDraft(service, state.design)) {
            throw new Error("service draft storage unavailable");
          }
        } else saveStoredDesign(state.design);
        setDraftState(
          isServiceDraftView() ? "서비스 초안 · 저장됨" : "저장됨",
          isServiceDraftView() ? "service-draft" : "saved",
          documentRef,
        );
        setFeedback(
          isServiceDraftView()
            ? "서비스 편집 초안을 이 브라우저에 저장했습니다. 실제 배포에는 반영되지 않습니다."
            : "현재 초안을 이 브라우저에 저장했습니다.",
          "success",
          documentRef,
        );
      } catch (_error) {
        setFeedback("브라우저 저장소에 초안을 저장하지 못했습니다.", "error", documentRef);
      }
    });
    el("serviceDesignerReset", documentRef)?.addEventListener("click", () => {
      loadSensorAnomalyExample(documentRef);
    });
    el("serviceDesignerMultiSensorExample", documentRef)?.addEventListener(
      "click",
      () => loadMultiSensorScoreExample(documentRef),
    );
    el("serviceDesignerReturnDraft", documentRef)?.addEventListener(
      "click",
      () => returnToPreviousDraft(documentRef),
    );
    el("serviceDesignerReloadService", documentRef)?.addEventListener(
      "click",
      () => resetActiveServiceDraft(documentRef),
    );
    documentRef.addEventListener("keydown", (event) => {
      if (moveSelectedNodeByKeyboard(event, documentRef)) return;
      if (event.key === "Escape" && state.pendingFromId) {
        state.pendingFromId = null;
        setFeedback("연결 선택을 취소했습니다.", "ready", documentRef);
        renderNodes(documentRef);
      } else if (event.key === "Escape" && state.selectedNodeId) {
        resetInputTelemetryPreview();
        state.selectedNodeId = null;
        state.inspectorOpen = false;
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
        resetInputTelemetryPreview();
        state.design = model.removeNode(state.design, nodeId);
        state.selectedNodeId = null;
        state.inspectorOpen = false;
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
      refreshDeployedServices(root.fetch, documentRef),
      root.edgeDashboardData
        ? Promise.resolve(true)
        : refreshInventory(root.fetch, documentRef),
    ]);
  }

  root.updateServiceDesignerInventory = (data) => updateInventory(data);
  root.refreshServiceDesignerProfiles = () => refreshProfiles(root.fetch);
  root.onServiceDesignerVisible = () => {
    renderAll();
    void refreshDeployedServices(root.fetch);
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
      INPUT_TELEMETRY_LIMIT,
      INPUT_TELEMETRY_WINDOW,
      SERVICE_DRAFT_STORAGE_PREFIX,
      STORAGE_KEY,
      escapeHtml,
      designerTelemetryUrl,
      fetchDesignerTelemetry,
      fetchDesignerProfiles,
      formatTelemetryInterval,
      formatTelemetryValue,
      accelerationAxisBindingCandidates,
      bindDeployedServiceDesign,
      bindMultiSensorScoreExample,
      bindSensorAnomalyExample,
      buildDesignInputReadiness,
      contextSourceBindingCandidate,
      createInputReadiness,
      deployedServiceFlow,
      deployedServiceView,
      fetchDesignerServices,
      loadStoredDesign,
      loadStoredServiceDraft,
      loadDesignInputReadiness,
      mergeValidationWithInputReadiness,
      nodeSummary,
      renderInputTelemetryPreview,
      saveStoredDesign,
      saveStoredServiceDraft,
      serviceDraftStorageKey,
      sourceBindingCandidate,
      state,
      summarizeDesignerTelemetry,
      telemetryAgeLabel,
      telemetryPointTimestampMs,
      updateInventory,
    };
  }
}(typeof globalThis !== "undefined" ? globalThis : this));
