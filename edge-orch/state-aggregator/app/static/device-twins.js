(function deviceTwinsDashboard(global) {
  "use strict";

  const state = {
    payload: null,
    binding: "",
    search: "",
    loading: false,
    health: "",
    error: null,
  };

  const HEALTH_LABELS = {
    ready: "정상",
    degraded: "점검 필요",
    unavailable: "사용 불가",
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function twinConnection(twin = {}) {
    const bindings = Array.isArray(twin.service_bindings) ? twin.service_bindings : [];
    return {state: bindings.length ? "bound" : "unbound", bindings};
  }

  function filterTwins(twins, filters = {}) {
    const binding = String(filters.binding || "");
    const search = String(filters.search || "").trim().toLocaleLowerCase("ko");
    return (Array.isArray(twins) ? twins : []).filter((twin) => {
      if (binding && twinConnection(twin).state !== binding) return false;
      if (filters.health === "attention" && twin.health === "ready") return false;
      if (filters.health === "ready" && twin.health !== "ready") return false;
      if (!search) return true;
      const haystack = [
        twin.id,
        twin.name,
        twin.physical_device_id,
        twin.node,
        twin.profile_name,
        ...(Array.isArray(twin.observed_resources) ? twin.observed_resources : []),
        ...(Array.isArray(twin.service_bindings)
          ? twin.service_bindings.flatMap((item) => [item.service_id, item.service_name])
          : []),
      ].join(" ").toLocaleLowerCase("ko");
      return haystack.includes(search);
    });
  }

  function sortTwins(twins) {
    return [...twins].sort((left, right) => {
      const connectionDiff = Number(twinConnection(right).state === "bound")
        - Number(twinConnection(left).state === "bound");
      return connectionDiff
        || String(left.physical_device_id || "").localeCompare(
          String(right.physical_device_id || ""),
          "ko",
        )
        || String(left.name || "").localeCompare(String(right.name || ""), "ko");
    });
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function setText(id, value) {
    const element = byId(id);
    if (element) element.textContent = String(value ?? "");
  }

  function renderSummary() {
    const summary = state.payload?.summary || {};
    const errors = state.payload?.observation_errors || [];
    const inventoryKnown = Boolean(state.payload && !state.error && !errors.some((error) => /EdgeX/i.test(error)));
    const bindingsKnown = inventoryKnown && !errors.length;
    setText("deviceTwinsPhysicalCount", inventoryKnown ? summary.physical_devices ?? 0 : "—");
    setText("deviceTwinsTotalCount", inventoryKnown ? summary.device_twins ?? 0 : "—");
    setText(
      "deviceTwinsBoundCount",
      bindingsKnown ? summary.service_connections ?? summary.service_bound_twins ?? 0 : "—",
    );
    setText("deviceTwinsAttentionCount", inventoryKnown ? summary.attention_twins ?? 0 : "—");
  }

  function renderNotice() {
    const notice = byId("deviceTwinsError");
    if (!notice) return;
    const errors = state.payload?.observation_errors || [];
    notice.hidden = !errors.length && !state.error;
    notice.textContent = state.error
      ? `연결 관측 실패 · ${state.error}${state.payload ? ` · 이전 관측 (${eventTime(state.payload.generated_at)})을 참고용으로 표시합니다.` : ""}`
      : errors.length
      ? "EdgeX 또는 AI 서비스 관측이 불완전합니다. 연결 없음·0개로 판단하지 마세요."
      : "";
  }

  function serviceMarkup(bindings, {bindingsKnown = true} = {}) {
    if (!bindingsKnown) return '<span class="device-twins-unbound">서비스 연결 관측 불가</span>';
    if (!bindings.length) return '<span class="device-twins-unbound">미연결</span>';
    return `<span class="device-twins-services">${bindings.map((binding) => `
        <span class="device-twins-service" data-status="${escapeHtml(binding.status)}">
          <strong>${escapeHtml(binding.service_name)}</strong>
          ${binding.status === "active" ? "" : "<small>서비스 상태 확인 필요</small>"}
          ${binding.service_id ? `<button type="button" class="workspace-text-button" data-workspace-service="${escapeHtml(binding.service_id)}">서비스 보기 ↗</button>` : ""}
        </span>
      `).join("")}</span>`;
  }

  function eventTime(value) {
    const date = new Date(value);
    return value && Number.isFinite(date.getTime()) ? date.toLocaleString("ko-KR") : "이벤트 없음";
  }

  function freshnessMarkup(twin) {
    const label = {fresh: "최신 입력", stale: "입력 지연", no_events: "이벤트 없음"}[twin.telemetry_freshness] || "최신성 미확인";
    return `<small class="connection-freshness">${escapeHtml(label)} · ${escapeHtml(eventTime(twin.latest_event_timestamp))}</small>`;
  }

  function connectionCards(twins, options = {}) {
    return (Array.isArray(twins) ? twins : []).map((twin) => `<article class="workspace-connection-row">
      <div><span class="workspace-source-mark" aria-hidden="true"></span><small class="workspace-column-label">물리 source</small><strong>${escapeHtml(twin.physical_device_id || "source 미확인")}</strong><small>${escapeHtml(twin.device_service_name || "수집 서비스 미확인")}</small><button type="button" class="workspace-text-button" data-workspace-device="${escapeHtml(twin.name)}" aria-label="${escapeHtml(twin.name)} 관측 근거 보기">관측 근거 ↗</button></div>
      <span class="workspace-arrow" aria-hidden="true">→</span>
      <div><small class="workspace-column-label">EdgeX 관측 트윈</small><strong>${escapeHtml((twin.observed_resources || []).join(", ") || twin.profile_name || "관측값 없음")}</strong>${freshnessMarkup(twin)}<span class="device-twins-badge" data-status="${escapeHtml(twin.health)}">${escapeHtml(HEALTH_LABELS[twin.health] || "미확인")}</span></div>
      <span class="workspace-arrow" aria-hidden="true">→</span>
      <div><small class="workspace-column-label">AI 서비스</small>${serviceMarkup(twinConnection(twin).bindings, options)}</div>
    </article>`).join("");
  }

  function twinRow(twin) {
    const connection = twinConnection(twin);
    const resources = Array.isArray(twin.observed_resources) ? twin.observed_resources : [];
    const resourceMarkup = resources.length
      ? resources.map((name) => `<code>${escapeHtml(name)}</code>`).join("")
      : '<span class="device-twins-unbound">관측값 없음</span>';
    return `
      <tr data-connection="${escapeHtml(connection.state)}">
        <td data-label="물리 디바이스">
          <strong>${escapeHtml(twin.physical_device_id)}</strong>
          <small>${escapeHtml(twin.node || "노드 미확인")}</small>
        </td>
        <td data-label="관측 트윈"><span class="device-twins-data">${resourceMarkup}</span></td>
        <td data-label="사용 서비스">${serviceMarkup(connection.bindings, {bindingsKnown: !state.error && !(state.payload?.observation_errors || []).length})}</td>
        <td data-label="상태"><span class="device-twins-badge" data-status="${escapeHtml(twin.health)}">${escapeHtml(HEALTH_LABELS[twin.health] || "상태 미확인")}</span>${freshnessMarkup(twin)}<button type="button" class="workspace-text-button" data-workspace-device="${escapeHtml(twin.name)}" aria-label="${escapeHtml(twin.name)} 상세 관측 근거 보기">근거 ↗</button></td>
      </tr>
    `;
  }

  function renderTwins() {
    const container = byId("deviceTwinsList");
    if (!container) return;
    const twins = sortTwins(filterTwins(state.payload?.twins, {
      binding: state.binding,
      search: state.search,
      health: state.health,
    }));
    setText("deviceTwinsVisibleCount", `${twins.length}개`);
    container.innerHTML = twins.length
      ? twins.map(twinRow).join("")
      : `<tr><td class="device-twins-empty" colspan="4">${state.error || state.payload?.observation_errors?.length ? "관측이 불완전해 목록을 확인할 수 없습니다." : !state.payload ? "관측 트윈을 확인하고 있습니다." : "조건에 맞는 관측 트윈이 없습니다."}</td></tr>`;
  }

  function renderAll() {
    renderSummary();
    renderNotice();
    renderTwins();
    global.EdgeOperationsOverview?.updateTwins(state.payload, state.error);
  }

  let pendingLoad = null;

  function loadDeviceTwins(fetchFn = global.fetch) {
    if (typeof fetchFn !== "function") return Promise.resolve(null);
    if (pendingLoad) return pendingLoad;
    pendingLoad = readDeviceTwins(fetchFn).finally(() => { pendingLoad = null; });
    return pendingLoad;
  }

  async function readDeviceTwins(fetchFn) {
    state.loading = true;
    const controller = new AbortController();
    const timeout = global.setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetchFn("/state/device-twins", {cache: "no-store", signal: controller.signal});
      if (!response.ok) throw new Error(`device twins ${response.status}`);
      const payload = await response.json();
      if (!Array.isArray(payload.twins) || !payload.summary) throw new Error("관측 트윈 응답 형식 오류");
      state.payload = payload;
      state.error = null;
      renderAll();
      return state.payload;
    } catch (error) {
      state.error = error.name === "AbortError" ? "응답 시간 초과" : error.message;
      renderAll();
      throw error;
    } finally {
      state.loading = false;
      global.clearTimeout(timeout);
    }
  }

  function bindControls() {
    byId("deviceTwinsSearch")?.addEventListener("input", (event) => {
      state.search = event.target.value || "";
      renderTwins();
    });
    byId("deviceTwinsBindingFilter")?.addEventListener("change", (event) => {
      state.binding = event.target.value || "";
      renderTwins();
    });
    byId("deviceTwinsHealthFilter")?.addEventListener("change", (event) => {
      state.health = event.target.value || "";
      renderTwins();
    });
  }

  function initialize() {
    if (!byId("deviceTwinsList")) return;
    bindControls();
    loadDeviceTwins().catch(() => undefined);
    global.setInterval(() => {
      if (!document.hidden && ["overview", "connections"].includes(document.body.dataset.dashboardPage)) {
        loadDeviceTwins().catch(() => undefined);
      }
    }, 5000);
  }

  global.onDeviceTwinsVisible = function onDeviceTwinsVisible() {
    loadDeviceTwins().catch(() => undefined);
  };
  global.EdgeDeviceTwins = {
    filterTwins,
    loadDeviceTwins,
    serviceMarkup,
    sortTwins,
    twinConnection,
    connectionCards,
    setHealthFilter(value) {
      state.health = value;
      if (byId("deviceTwinsHealthFilter")) byId("deviceTwinsHealthFilter").value = value;
      renderTwins();
    },
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {filterTwins, serviceMarkup, sortTwins, twinConnection, connectionCards};
  }
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initialize, {once: true});
    } else {
      initialize();
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : window);
