(function virtualDeviceDashboard(global) {
  "use strict";

  const state = {
    payload: null,
    status: "",
    search: "",
    loading: false,
  };

  const STATUS_LABELS = {
    ready: "사용 가능",
    degraded: "점검 필요",
    unavailable: "사용 불가",
    configured: "구성됨",
  };

  const USAGE_ORDER = {
    "in-use": 0,
    degraded: 1,
    unavailable: 2,
    available: 3,
    configured: 4,
    unknown: 5,
  };

  function escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function statusLabel(status) {
    return STATUS_LABELS[status] || "상태 미확인";
  }

  function resourceUsage(item = {}) {
    const bindingIds = Array.isArray(item.current_bindings) ? item.current_bindings : [];
    if (item.category === "data" && bindingIds.length) {
      return {state: "in-use", label: "사용 중", bindingIds};
    }
    if (item.category === "data" && item.status === "ready") {
      return {state: "available", label: "사용 가능", bindingIds};
    }
    return {
      state: item.status || "unknown",
      label: statusLabel(item.status),
      bindingIds,
    };
  }

  function filterResources(resources, filters = {}) {
    const category = String(filters.category || "");
    const status = String(filters.status || "");
    const search = String(filters.search || "").trim().toLocaleLowerCase("ko");
    return (Array.isArray(resources) ? resources : []).filter((item) => {
      if (category && item.category !== category) return false;
      if (status && resourceUsage(item).state !== status) return false;
      if (!search) return true;
      const metadata = item.metadata || {};
      const haystack = [
        item.id,
        item.name,
        item.node,
        metadata.physical_device_id,
        ...(Array.isArray(metadata.resource_names) ? metadata.resource_names : []),
        ...(Array.isArray(item.capabilities) ? item.capabilities : []),
        ...(Array.isArray(item.current_bindings) ? item.current_bindings : []),
      ].join(" ").toLocaleLowerCase("ko");
      return haystack.includes(search);
    });
  }

  function sortVirtualDevices(resources) {
    return [...resources].sort((left, right) => {
      const usageDiff = (USAGE_ORDER[resourceUsage(left).state] ?? 9)
        - (USAGE_ORDER[resourceUsage(right).state] ?? 9);
      return usageDiff || String(left.name || "").localeCompare(String(right.name || ""), "ko");
    });
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function setText(id, value) {
    const element = byId(id);
    if (element) element.textContent = String(value ?? "");
  }

  function serviceName(serviceId) {
    const resource = state.payload?.resources?.find((item) => item.id === `service:${serviceId}`);
    return resource?.name || serviceId;
  }

  function renderSummary() {
    const summary = state.payload?.summary || {};
    setText("resourcePoolVirtualCount", summary.virtual_devices || 0);
    setText("resourcePoolInUseCount", summary.used_virtual_devices || 0);
    setText("resourcePoolAvailableCount", summary.available_virtual_devices || 0);
    setText("resourcePoolAttentionCount", summary.attention_virtual_devices || 0);
  }

  function renderNotice() {
    const notice = byId("resourcePoolError");
    if (!notice) return;
    const errors = state.payload?.observation_errors || [];
    notice.hidden = !errors.length;
    notice.textContent = errors.length
      ? "AI 서비스 상태를 확인할 수 없어 사용 여부가 일부 누락될 수 있습니다."
      : "";
  }

  function resourceRow(item) {
    const usage = resourceUsage(item);
    const metadata = item.metadata || {};
    const resources = Array.isArray(metadata.resource_names) && metadata.resource_names.length
      ? metadata.resource_names
      : item.capabilities || [];
    const services = usage.bindingIds.map(serviceName);
    const serviceMarkup = services.length
      ? services.map((name) => `<strong>${escapeHtml(name)}</strong>`).join("")
      : '<span class="resource-pool-none">—</span>';
    const resourceMarkup = resources.length
      ? resources.map((name) => `<code>${escapeHtml(name)}</code>`).join("")
      : '<span class="resource-pool-none">—</span>';

    return `
      <tr data-usage="${escapeHtml(usage.state)}">
        <td data-label="가상 디바이스"><strong>${escapeHtml(item.name)}</strong></td>
        <td data-label="원본 장비">
          <strong>${escapeHtml(metadata.physical_device_id || "미확인")}</strong>
          <small>${escapeHtml(item.node || "노드 미확인")}</small>
        </td>
        <td data-label="데이터"><span class="resource-pool-data">${resourceMarkup}</span></td>
        <td data-label="사용 서비스"><span class="resource-pool-service">${serviceMarkup}</span></td>
        <td data-label="상태"><span class="resource-pool-badge" data-status="${escapeHtml(usage.state)}">${escapeHtml(usage.label)}</span></td>
      </tr>
    `;
  }

  function renderDevices() {
    const container = byId("resourcePoolList");
    if (!container) return;
    const resources = sortVirtualDevices(filterResources(state.payload?.resources, {
      category: "data",
      status: state.status,
      search: state.search,
    }));
    setText("resourcePoolVisibleCount", `${resources.length}개`);
    container.innerHTML = resources.length
      ? resources.map(resourceRow).join("")
      : '<tr><td class="resource-pool-empty" colspan="5">조건에 맞는 가상 디바이스가 없습니다.</td></tr>';
  }

  function renderAll() {
    renderSummary();
    renderNotice();
    renderDevices();
  }

  async function loadResourcePool(fetchFn = global.fetch) {
    if (state.loading || typeof fetchFn !== "function") return null;
    state.loading = true;
    try {
      const response = await fetchFn("/state/resource-pool", {cache: "no-store"});
      if (!response.ok) throw new Error(`virtual devices ${response.status}`);
      state.payload = await response.json();
      renderAll();
      return state.payload;
    } catch (error) {
      const notice = byId("resourcePoolError");
      if (notice) {
        notice.hidden = false;
        notice.textContent = "가상 디바이스를 불러오지 못했습니다.";
      }
      throw error;
    } finally {
      state.loading = false;
    }
  }

  function bindControls() {
    byId("resourcePoolSearch")?.addEventListener("input", (event) => {
      state.search = event.target.value || "";
      renderDevices();
    });
    byId("resourcePoolStatusFilter")?.addEventListener("change", (event) => {
      state.status = event.target.value || "";
      renderDevices();
    });
    byId("refreshButton")?.addEventListener("click", () => {
      if (document.body.dataset.dashboardPage === "resource-pool") {
        loadResourcePool().catch(() => undefined);
      }
    });
  }

  function initialize() {
    if (!byId("resourcePoolList")) return;
    bindControls();
    loadResourcePool().catch(() => undefined);
  }

  global.onResourcePoolVisible = function onResourcePoolVisible() {
    if (!state.payload) loadResourcePool().catch(() => undefined);
  };
  global.EdgeResourcePool = {
    filterResources,
    resourceUsage,
    sortVirtualDevices,
    statusLabel,
    loadResourcePool,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {filterResources, resourceUsage, sortVirtualDevices, statusLabel};
  }
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initialize, {once: true});
    } else {
      initialize();
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : window);
