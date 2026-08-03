function serviceDemoText(value, fallback = "관측 불가") {
  if (value === null || value === undefined || value === "") return fallback;
  return String(value);
}


function serviceDemoNumber(value, digits, suffix = "") {
  const number = Number(value);
  if (!Number.isFinite(number)) return "관측 불가";
  return `${number.toFixed(digits)}${suffix}`;
}


function serviceDemoAge(observedAt, nowMs) {
  const observedMs = Date.parse(observedAt);
  if (!Number.isFinite(observedMs) || !Number.isFinite(nowMs)) return "관측 불가";
  return `${(Math.max(0, nowMs - observedMs) / 1_000).toFixed(1)} s`;
}


function buildServiceDemoView(data = {}, nowMs = Date.now()) {
  const binding = data.binding || {};
  const latest = data.latest || null;
  const model = data.model || null;
  const componentScores = latest?.component_scores || null;
  const temperatureFeatures = latest?.temperature_features || null;
  const allowedTones = new Set(["starting", "warming_up", "normal", "anomaly", "degraded"]);
  const status = allowedTones.has(data.status) ? data.status : "degraded";
  const physicalSource = serviceDemoText(binding.physical_source);
  const deviceService = serviceDemoText(binding.device_service);
  const consumer = serviceDemoText(binding.consumer, "sensor-anomaly-demo");
  const node = serviceDemoText(binding.node, "etri-dev0001-jetorn");
  const hasFlow = binding.physical_source && binding.device_service && binding.consumer;
  const values = latest?.values;
  const sampleCount = Number(model?.sample_count);

  return {
    badge: status.toUpperCase(),
    tone: status,
    inputState: serviceDemoText(data.input_state, "unknown"),
    physicalSource,
    deviceService,
    consumer,
    node,
    devices: Array.isArray(binding.devices) && binding.devices.length
      ? binding.devices.join(" · ")
      : "관측 불가",
    flow: hasFlow
      ? `${physicalSource} → ${deviceService} → ${consumer}`
      : "source binding 관측 불가",
    values: values
      ? `X ${serviceDemoText(values.x)} · Y ${serviceDemoText(values.y)} · Z ${serviceDemoText(values.z)}`
      : "관측 불가",
    magnitude: latest ? serviceDemoNumber(latest.magnitude, 3, " raw") : "관측 불가",
    vibrationScore: latest
      ? serviceDemoNumber(componentScores?.vibration ?? latest.score, 2)
      : "관측 불가",
    temperatureScore: componentScores
      ? serviceDemoNumber(componentScores.temperature, 2)
      : "관측 불가",
    score: latest && model
      ? `${serviceDemoNumber(latest.score, 2)} / ${serviceDemoNumber(model.threshold, 2)}`
      : "관측 불가",
    temperatureContext: temperatureFeatures
      ? `raw ${serviceDemoText(temperatureFeatures.raw)} · 정렬 ${serviceDemoNumber(temperatureFeatures.alignment_lag_ms, 1, " ms")}`
      : "관측 불가",
    model: model
      ? `${serviceDemoText(model.algorithm)} · ${Number.isFinite(sampleCount) ? sampleCount : "관측 불가"} samples · ${serviceDemoText(data.model_state, "unknown")}`
      : "model 관측 불가",
    origin: latest ? serviceDemoText(latest.origin) : "관측 불가",
    inputAge: latest ? serviceDemoAge(latest.observed_at, nowMs) : "관측 불가",
    frames: serviceDemoText(data.counters?.frames_processed),
    copy: componentScores && temperatureFeatures
      ? "진동·온도 복합 이상 점수 · Jetson local inference"
      : "3축 진동 이상 점수 · Jetson local inference",
    error: serviceDemoText(data.observation_error || data.last_error, ""),
  };
}


function renderServiceDemo(data, documentRef = document) {
  const view = buildServiceDemoView(data);
  const text = (id, value) => {
    const element = documentRef.getElementById(id);
    if (element) element.textContent = value;
    return element;
  };

  const badge = text("serviceDemoState", view.badge);
  if (badge) badge.dataset.state = view.tone;
  text("serviceDemoInputState", view.inputState);
  text("serviceDemoFlow", view.flow);
  text("serviceDemoPhysicalSource", view.physicalSource);
  text("serviceDemoDeviceService", view.deviceService);
  text("serviceDemoConsumer", view.consumer);
  text("serviceDemoNode", view.node);
  text("serviceDemoDevices", view.devices);
  text("serviceDemoValues", view.values);
  text("serviceDemoMagnitude", view.magnitude);
  text("serviceDemoVibrationScore", view.vibrationScore);
  text("serviceDemoTemperatureScore", view.temperatureScore);
  text("serviceDemoScore", view.score);
  text("serviceDemoTemperatureContext", view.temperatureContext);
  text("serviceDemoModel", `${view.model} · ${view.copy}`);
  text("serviceDemoOrigin", view.origin);
  text("serviceDemoInputAge", view.inputAge);
  const error = text("serviceDemoError", view.error);
  if (error) error.hidden = !view.error;
}


function buildServiceDemoAlertView(data = {}) {
  const alerts = Array.isArray(data.alerts) ? data.alerts : [];
  const latest = alerts[0] || null;
  const count = Number(data.count);
  const observedAt = latest?.observed_at ? Date.parse(latest.observed_at) : NaN;
  const transition = latest?.transition === "opened" ? "이상 발생"
    : latest?.transition === "cleared" ? "정상 복귀" : "관측 대기";
  return {
    count: Number.isFinite(count) ? `${count}건` : "관측 불가",
    latest: latest
      ? `${transition} · 점수 ${serviceDemoNumber(latest.score, 2)}${Number.isFinite(observedAt) ? ` · ${new Date(observedAt).toLocaleString("ko-KR")}` : ""}`
      : data.mode === "live" ? "알림 없음" : "관측 불가",
    error: serviceDemoText(data.observation_error, ""),
  };
}


function renderServiceDemoAlerts(data, documentRef = document) {
  const view = buildServiceDemoAlertView(data);
  const count = documentRef.getElementById("serviceDemoAlertCount");
  const latest = documentRef.getElementById("serviceDemoAlertLatest");
  if (count) count.textContent = view.count;
  if (latest) latest.textContent = view.error || view.latest;
}


async function refreshServiceDemo(fetchFn = fetch, documentRef = document) {
  try {
    const response = await fetchFn("/state/service-demo", {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderServiceDemo(await response.json(), documentRef);
  } catch (error) {
    renderServiceDemo({
      mode: "unavailable",
      status: "degraded",
      input_state: "error",
      model_state: "unavailable",
      binding: {
        consumer: "sensor-anomaly-demo",
        node: "etri-dev0001-jetorn",
        devices: [],
      },
      latest: null,
      model: null,
      observation_error: `dashboard fetch failed: ${error?.name || "Error"}`,
    }, documentRef);
  }
}


async function refreshServiceDemoAlerts(fetchFn = fetch, documentRef = document) {
  try {
    const response = await fetchFn("/state/service-demo/alerts?limit=10", {cache: "no-store"});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    renderServiceDemoAlerts(await response.json(), documentRef);
  } catch (error) {
    renderServiceDemoAlerts({
      mode: "unavailable",
      count: 0,
      alerts: [],
      observation_error: `alert fetch failed: ${error?.name || "Error"}`,
    }, documentRef);
  }
}


if (typeof module !== "undefined") {
  module.exports = {
    buildServiceDemoAlertView,
    buildServiceDemoView,
    refreshServiceDemo,
    refreshServiceDemoAlerts,
    renderServiceDemo,
    renderServiceDemoAlerts,
  };
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  window.addEventListener("DOMContentLoaded", () => {
    refreshServiceDemo();
    refreshServiceDemoAlerts();
    window.setInterval(refreshServiceDemo, 5_000);
    window.setInterval(refreshServiceDemoAlerts, 5_000);
  });
}
