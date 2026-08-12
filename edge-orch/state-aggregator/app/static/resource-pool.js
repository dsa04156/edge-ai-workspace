(function resourcePoolModule(global) {
  "use strict";

  const state = {
    payload: null,
    category: "",
    status: "",
    search: "",
    selectedServiceId: "",
    selectedDataId: "",
    selectedComputeId: "",
    plan: null,
    loading: false,
  };

  const STATUS_LABELS = {
    ready: "사용 가능",
    degraded: "확인 필요",
    unavailable: "사용 불가",
    configured: "구성됨",
  };

  const CATEGORY_LABELS = {
    data: "센서·데이터",
    compute: "컴퓨팅",
    service: "AI 서비스",
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

  function filterResources(resources, filters = {}) {
    const category = String(filters.category || "");
    const status = String(filters.status || "");
    const search = String(filters.search || "").trim().toLocaleLowerCase("ko");
    return (Array.isArray(resources) ? resources : []).filter((item) => {
      if (category && item.category !== category) return false;
      if (status && item.status !== status) return false;
      if (!search) return true;
      const haystack = [
        item.id,
        item.name,
        item.description,
        item.kind,
        item.node,
        ...(Array.isArray(item.capabilities) ? item.capabilities : []),
      ].join(" ").toLocaleLowerCase("ko");
      return haystack.includes(search);
    });
  }

  function byId(id) {
    return document.getElementById(id);
  }

  function resourceById(resourceId) {
    return state.payload?.resources?.find((item) => item.id === resourceId) || null;
  }

  function serviceIdFromResource(resourceId) {
    return String(resourceId || "").replace(/^service:/, "");
  }

  function setText(id, value) {
    const element = byId(id);
    if (element) element.textContent = String(value ?? "");
  }

  function renderSummary() {
    const summary = state.payload?.summary || {};
    setText("resourcePoolReadyCount", summary.ready_resources || 0);
    setText("resourcePoolDataCount", summary.data_resources || 0);
    setText("resourcePoolComputeCount", summary.compute_resources || 0);
    setText("resourcePoolServiceCount", summary.service_resources || 0);
    setText("resourcePoolBindingCount", summary.active_bindings || 0);
  }

  function renderNotice() {
    const notice = byId("resourcePoolError");
    if (!notice) return;
    const errors = state.payload?.observation_errors || [];
    if (!errors.length) {
      notice.hidden = true;
      notice.textContent = "";
      return;
    }
    notice.hidden = false;
    notice.textContent = `일부 권위 시스템 관측이 불완전합니다: ${errors.join(" · ")}`;
  }

  function renderServices() {
    const container = byId("resourcePoolServiceList");
    if (!container) return;
    const services = (state.payload?.resources || []).filter((item) => item.category === "service");
    setText("resourcePoolServiceStatus", services.length ? `${services.length}개 서비스` : "서비스 없음");
    if (!services.length) {
      container.innerHTML = '<p class="resource-pool-empty">현재 서비스 카탈로그가 비어 있습니다.</p>';
      return;
    }
    container.innerHTML = services.map((service) => {
      const selected = serviceIdFromResource(service.id) === state.selectedServiceId;
      return `
        <button
          class="resource-pool-service-option${selected ? " selected" : ""}"
          type="button"
          data-resource-pool-service="${escapeHtml(service.id)}"
          aria-pressed="${selected ? "true" : "false"}"
        >
          <strong>${escapeHtml(service.name)}</strong>
          <span>${escapeHtml(service.description)}</span>
        </button>
      `;
    }).join("");
    container.querySelectorAll("[data-resource-pool-service]").forEach((button) => {
      button.addEventListener("click", () => {
        state.selectedServiceId = serviceIdFromResource(button.dataset.resourcePoolService);
        state.plan = null;
        renderAll();
      });
    });
  }

  function resourceCard(item) {
    const selected = item.id === state.selectedDataId || item.id === state.selectedComputeId;
    const capabilities = (item.capabilities || []).slice(0, 4);
    const metadata = [CATEGORY_LABELS[item.category] || item.category, item.node, item.authority]
      .filter(Boolean);
    return `
      <button
        class="resource-pool-card${selected ? " selected" : ""}"
        type="button"
        data-resource-pool-item="${escapeHtml(item.id)}"
        data-category="${escapeHtml(item.category)}"
        aria-pressed="${selected ? "true" : "false"}"
        aria-disabled="${item.selectable ? "false" : "true"}"
      >
        <span class="resource-pool-card-head">
          <span>${escapeHtml(item.name)}</span>
          <span class="resource-pool-badge" data-status="${escapeHtml(item.status)}">${escapeHtml(statusLabel(item.status))}</span>
        </span>
        <span class="resource-pool-meta">${metadata.map((value) => `<span>${escapeHtml(value)}</span>`).join("")}</span>
        <p>${escapeHtml(item.description)}</p>
        <span class="resource-pool-capabilities">${capabilities.map((value) => `<span>${escapeHtml(value)}</span>`).join("")}</span>
      </button>
    `;
  }

  function renderCatalog() {
    const container = byId("resourcePoolList");
    if (!container) return;
    const resources = filterResources(state.payload?.resources, {
      category: state.category,
      status: state.status,
      search: state.search,
    });
    setText("resourcePoolVisibleCount", `${resources.length}개`);
    container.innerHTML = resources.length
      ? resources.map(resourceCard).join("")
      : '<p class="resource-pool-empty">조건에 맞는 자원이 없습니다. 검색어나 상태 필터를 바꿔보세요.</p>';
    container.querySelectorAll("[data-resource-pool-item]").forEach((button) => {
      button.addEventListener("click", () => {
        const item = resourceById(button.dataset.resourcePoolItem);
        if (!item || !item.selectable) return;
        if (item.category === "service") {
          state.selectedServiceId = serviceIdFromResource(item.id);
        } else if (item.category === "data") {
          state.selectedDataId = state.selectedDataId === item.id ? "" : item.id;
        } else if (item.category === "compute") {
          state.selectedComputeId = state.selectedComputeId === item.id ? "" : item.id;
        }
        state.plan = null;
        renderAll();
      });
    });
  }

  function renderSelection() {
    const service = resourceById(`service:${state.selectedServiceId}`);
    const data = resourceById(state.selectedDataId);
    const compute = resourceById(state.selectedComputeId);
    setText("resourcePoolSelectedService", service?.name || "선택 안 됨");
    setText("resourcePoolSelectedData", data?.name || "추천 자원 자동 선택");
    setText("resourcePoolSelectedCompute", compute?.name || "고정 Deployment 확인");
    const button = byId("resourcePoolPlanButton");
    if (button) button.disabled = !state.selectedServiceId || state.loading;
  }

  function renderFlow() {
    document.querySelectorAll(".resource-pool-flow [data-step]").forEach((item) => {
      item.classList.remove("complete", "active");
    });
    const serviceStep = document.querySelector('.resource-pool-flow [data-step="service"]');
    const resourceStep = document.querySelector('.resource-pool-flow [data-step="resource"]');
    const planStep = document.querySelector('.resource-pool-flow [data-step="plan"]');
    if (state.selectedServiceId) serviceStep?.classList.add("complete");
    if (state.selectedDataId || state.selectedComputeId || state.plan) {
      resourceStep?.classList.add("complete");
    } else if (state.selectedServiceId) {
      resourceStep?.classList.add("active");
    }
    if (state.plan) planStep?.classList.add(state.plan.compatible ? "complete" : "active");
  }

  function renderPlan() {
    const container = byId("resourcePoolPlanResult");
    const badge = byId("resourcePoolPlanState");
    if (!container || !badge) return;
    if (!state.plan) {
      badge.dataset.state = "idle";
      badge.textContent = state.loading ? "검증 중" : "선택 대기";
      container.innerHTML = "<p>서비스를 선택하고 계획을 확인하면 권위 데이터 기준의 호환성 결과가 표시됩니다.</p>";
      return;
    }
    badge.dataset.state = state.plan.compatible ? "ready" : "blocked";
    badge.textContent = state.plan.compatible ? "연결 가능" : "연결 차단";
    const checks = (state.plan.checks || []).map((check) => `
      <li data-status="${escapeHtml(check.status)}">
        <span><strong>${escapeHtml(check.label)}</strong>${escapeHtml(check.detail)}</span>
      </li>
    `).join("");
    const lease = state.plan.lease_preview
      ? `<div class="resource-pool-lease"><strong>${escapeHtml(state.plan.lease_preview.id)}</strong><span>저장되지 않는 15분 예약 미리보기</span></div>`
      : "";
    container.innerHTML = `<ul class="resource-pool-checks">${checks}</ul>${lease}`;
  }

  function renderBindings() {
    const container = byId("resourcePoolBindingList");
    if (!container) return;
    const bindings = state.payload?.bindings || [];
    container.innerHTML = bindings.length
      ? bindings.map((binding) => `
          <article class="resource-pool-binding">
            <div><span>EdgeX 센서 데이터</span><strong>${escapeHtml(binding.data_resource_name)}</strong></div>
            <span class="resource-pool-binding-arrow" aria-hidden="true">→</span>
            <div><span>${escapeHtml(binding.input_contract)}</span><strong>${escapeHtml(binding.service_name)}</strong></div>
            <span class="resource-pool-badge" data-status="${binding.status === "ready" ? "ready" : "degraded"}">${escapeHtml(statusLabel(binding.status === "ready" ? "ready" : "degraded"))}</span>
          </article>
        `).join("")
      : '<p class="resource-pool-empty">현재 관측된 디바이스-서비스 연결이 없습니다.</p>';
  }

  function renderAll() {
    renderSummary();
    renderNotice();
    renderServices();
    renderCatalog();
    renderSelection();
    renderFlow();
    renderPlan();
    renderBindings();
  }

  async function loadResourcePool(fetchFn = global.fetch) {
    if (state.loading || typeof fetchFn !== "function") return null;
    state.loading = true;
    renderSelection();
    try {
      const response = await fetchFn("/state/resource-pool", {cache: "no-store"});
      if (!response.ok) throw new Error(`resource pool ${response.status}`);
      state.payload = await response.json();
      const firstService = state.payload.resources?.find((item) => item.category === "service");
      if (!state.selectedServiceId && firstService) {
        state.selectedServiceId = serviceIdFromResource(firstService.id);
      }
      renderAll();
      return state.payload;
    } catch (error) {
      const notice = byId("resourcePoolError");
      if (notice) {
        notice.hidden = false;
        notice.textContent = "자원 풀을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.";
      }
      throw error;
    } finally {
      state.loading = false;
      renderSelection();
      renderPlan();
    }
  }

  async function previewPlan(fetchFn = global.fetch) {
    if (!state.selectedServiceId || state.loading || typeof fetchFn !== "function") return null;
    state.loading = true;
    state.plan = null;
    renderSelection();
    renderPlan();
    try {
      const response = await fetchFn("/state/resource-pool/plan", {
        method: "POST",
        cache: "no-store",
        headers: {"Content-Type": "application/json", Accept: "application/json"},
        body: JSON.stringify({
          service_id: state.selectedServiceId,
          data_resource_id: state.selectedDataId || null,
          compute_resource_id: state.selectedComputeId || null,
        }),
      });
      if (!response.ok) throw new Error(`resource plan ${response.status}`);
      state.plan = await response.json();
      state.selectedDataId = state.plan.selection?.data_resource_id || state.selectedDataId;
      state.selectedComputeId = state.plan.selection?.compute_resource_id || state.selectedComputeId;
      renderAll();
      return state.plan;
    } catch (error) {
      const container = byId("resourcePoolPlanResult");
      if (container) container.innerHTML = '<p class="resource-pool-empty">연결 계획을 검증하지 못했습니다. 관측 상태를 새로고침해 주세요.</p>';
      throw error;
    } finally {
      state.loading = false;
      renderSelection();
      renderPlan();
    }
  }

  function bindControls() {
    byId("resourcePoolSearch")?.addEventListener("input", (event) => {
      state.search = event.target.value || "";
      renderCatalog();
    });
    byId("resourcePoolStatusFilter")?.addEventListener("change", (event) => {
      state.status = event.target.value || "";
      renderCatalog();
    });
    document.querySelectorAll("[data-pool-category]").forEach((button) => {
      button.addEventListener("click", () => {
        state.category = button.dataset.poolCategory || "";
        document.querySelectorAll("[data-pool-category]").forEach((item) => {
          const active = item === button;
          item.classList.toggle("active", active);
          item.setAttribute("aria-pressed", active ? "true" : "false");
        });
        renderCatalog();
      });
    });
    byId("resourcePoolPlanButton")?.addEventListener("click", () => {
      previewPlan().catch(() => undefined);
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
    statusLabel,
    loadResourcePool,
    previewPlan,
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = {filterResources, statusLabel};
  }
  if (typeof document !== "undefined") {
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", initialize, {once: true});
    } else {
      initialize();
    }
  }
})(typeof globalThis !== "undefined" ? globalThis : window);
