(function deviceTwinsDashboard(global) {
  "use strict";

  const state = {
    payload: null,
    binding: "",
    search: "",
    loading: false,
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
    setText("deviceTwinsPhysicalCount", summary.physical_devices || 0);
    setText("deviceTwinsTotalCount", summary.device_twins || 0);
    setText("deviceTwinsBoundCount", summary.service_bound_twins || 0);
    setText("deviceTwinsAttentionCount", summary.attention_twins || 0);
  }

  function renderNotice() {
    const notice = byId("deviceTwinsError");
    if (!notice) return;
    const errors = state.payload?.observation_errors || [];
    notice.hidden = !errors.length;
    notice.textContent = errors.length
      ? "EdgeX 또는 AI 서비스 상태를 확인할 수 없어 일부 트윈 정보가 누락될 수 있습니다."
      : "";
  }

  function serviceMarkup(bindings) {
    if (!bindings.length) return '<span class="device-twins-unbound">미연결</span>';
    return bindings.map((binding) => `
      <span class="device-twins-service" data-status="${escapeHtml(binding.status)}">
        <strong>${escapeHtml(binding.service_name)}</strong>
        ${binding.status === "active" ? "" : "<small>서비스 상태 확인 필요</small>"}
      </span>
    `).join("");
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
        <td data-label="사용 서비스">${serviceMarkup(connection.bindings)}</td>
        <td data-label="상태"><span class="device-twins-badge" data-status="${escapeHtml(twin.health)}">${escapeHtml(HEALTH_LABELS[twin.health] || "상태 미확인")}</span></td>
      </tr>
    `;
  }

  function renderTwins() {
    const container = byId("deviceTwinsList");
    if (!container) return;
    const twins = sortTwins(filterTwins(state.payload?.twins, {
      binding: state.binding,
      search: state.search,
    }));
    setText("deviceTwinsVisibleCount", `${twins.length}개`);
    container.innerHTML = twins.length
      ? twins.map(twinRow).join("")
      : '<tr><td class="device-twins-empty" colspan="4">조건에 맞는 디바이스 트윈이 없습니다.</td></tr>';
  }

  function renderAll() {
    renderSummary();
    renderNotice();
    renderTwins();
  }

  async function loadDeviceTwins(fetchFn = global.fetch) {
    if (state.loading || typeof fetchFn !== "function") return null;
    state.loading = true;
    try {
      const response = await fetchFn("/state/device-twins", {cache: "no-store"});
      if (!response.ok) throw new Error(`device twins ${response.status}`);
      state.payload = await response.json();
      renderAll();
      return state.payload;
    } catch (error) {
      const notice = byId("deviceTwinsError");
      if (notice) {
        notice.hidden = false;
        notice.textContent = "디바이스 트윈을 불러오지 못했습니다.";
      }
      throw error;
    } finally {
      state.loading = false;
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
    byId("refreshButton")?.addEventListener("click", () => {
      if (document.body.dataset.dashboardPage === "device-twins") {
        loadDeviceTwins().catch(() => undefined);
      }
    });
  }

  function initialize() {
    if (!byId("deviceTwinsList")) return;
    bindControls();
    loadDeviceTwins().catch(() => undefined);
  }

  global.onDeviceTwinsVisible = function onDeviceTwinsVisible() {
    if (!state.payload) loadDeviceTwins().catch(() => undefined);
  };
  global.EdgeDeviceTwins = {filterTwins, loadDeviceTwins, sortTwins, twinConnection};

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {filterTwins, sortTwins, twinConnection};
  }
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initialize, {once: true});
    } else {
      initialize();
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : window);
