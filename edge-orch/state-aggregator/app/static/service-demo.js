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
    score: latest && model
      ? `${serviceDemoNumber(latest.score, 2)} / ${serviceDemoNumber(model.threshold, 2)}`
      : "관측 불가",
    model: model
      ? `${serviceDemoText(model.algorithm)} · ${Number.isFinite(sampleCount) ? sampleCount : "관측 불가"} samples · ${serviceDemoText(data.model_state, "unknown")}`
      : "model 관측 불가",
    origin: latest ? serviceDemoText(latest.origin) : "관측 불가",
    inputAge: latest ? serviceDemoAge(latest.observed_at, nowMs) : "관측 불가",
    frames: serviceDemoText(data.counters?.frames_processed),
    copy: "실측 raw 변화 이상 탐지 · Jetson local inference",
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
  text("serviceDemoScore", view.score);
  text("serviceDemoModel", `${view.model} · ${view.copy}`);
  text("serviceDemoOrigin", view.origin);
  text("serviceDemoInputAge", view.inputAge);
  const error = text("serviceDemoError", view.error);
  if (error) error.hidden = !view.error;
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


if (typeof module !== "undefined") {
  module.exports = {buildServiceDemoView, refreshServiceDemo, renderServiceDemo};
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  window.addEventListener("DOMContentLoaded", () => {
    refreshServiceDemo();
    window.setInterval(refreshServiceDemo, 5_000);
    document.getElementById("refreshButton")?.addEventListener(
      "click",
      () => refreshServiceDemo(),
    );
  });
}
