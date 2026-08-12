(() => {
  const CLASS_META = {
    data_source: ["데이터 입력", "EdgeX Device/Profile과 최신 Event 기준"],
    runtime_candidate: ["특수 실행 후보", "전용 runtime identity와 endpoint가 필요한 자원"],
    node_diagnostic: ["노드 진단", "배치 참고용이며 물리 디바이스 availability gate가 아님"],
    service: ["실행 서비스", "Kubernetes workload 관측"],
  };
  const STATUS_LABEL = {
    verified: "확인됨",
    partial: "일부 확인",
    declared: "정의만 존재",
    unavailable: "사용 불가",
  };
  const STAGE_LABEL = {definition: "정의", runtime: "런타임", endpoint: "엔드포인트", binding: "바인딩"};
  let poolState = null;
  let selectedClass = "all";

  const escapeHtml = (value) => String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  function evidenceMarkup(evidence) {
    return `<div class="resource-evidence" aria-label="판정 증거">${(evidence || []).map((item) => `
      <div class="resource-evidence-step" data-state="${escapeHtml(item.state)}" title="${escapeHtml(item.detail)}">
        <strong>${escapeHtml(STAGE_LABEL[item.stage] || item.stage)}</strong>
        <span>${escapeHtml(item.detail)}</span>
      </div>`).join("")}</div>`;
  }

  function rowMarkup(item) {
    return `<article class="resource-pool-row" data-resource-id="${escapeHtml(item.id)}">
      <div class="resource-pool-identity">
        <div class="resource-pool-identity-top">
          <strong title="${escapeHtml(item.name)}">${escapeHtml(item.name)}</strong>
          <span class="resource-pool-badge" data-status="${escapeHtml(item.status)}">${escapeHtml(STATUS_LABEL[item.status] || item.status)}</span>
        </div>
        <p>${escapeHtml(item.kind)}${item.location ? ` · ${escapeHtml(item.location)}` : ""}</p>
      </div>
      <div class="resource-pool-role">
        <strong>${escapeHtml(item.role)}</strong>
        <p>${escapeHtml(item.authority)} · ${escapeHtml(item.status_reason)}</p>
      </div>
      ${evidenceMarkup(item.evidence)}
    </article>`;
  }

  function renderSummary(summary = {}) {
    const setText = (id, value) => {
      const element = document.getElementById(id);
      if (element) element.textContent = String(value ?? 0);
    };
    setText("resourcePoolReadySources", summary.ready_data_sources);
    setText("resourcePoolVerified", summary.verified_candidates);
    setText("resourcePoolAttention", summary.attention_candidates);
    setText("resourcePoolDeclared", summary.declared_candidates);
    const caption = document.getElementById("resourcePoolSourceCaption");
    if (caption) caption.textContent = `전체 ${summary.data_sources || 0}개 · EdgeX 기준`;
  }

  function renderPool() {
    const list = document.getElementById("resourcePoolList");
    if (!list || !poolState) return;
    const query = (document.getElementById("resourcePoolSearch")?.value || "").trim().toLocaleLowerCase("ko");
    const resources = (poolState.resources || []).filter((item) => {
      if (selectedClass !== "all" && item.resource_class !== selectedClass) return false;
      if (!query) return true;
      return [item.name, item.kind, item.location, item.role, item.authority]
        .some((value) => String(value || "").toLocaleLowerCase("ko").includes(query));
    });
    list.setAttribute("aria-busy", "false");
    if (!resources.length) {
      list.innerHTML = '<div class="resource-pool-empty">조건에 맞는 관측 항목이 없습니다.</div>';
      return;
    }
    list.innerHTML = Object.entries(CLASS_META).map(([key, meta]) => {
      const items = resources.filter((item) => item.resource_class === key);
      if (!items.length) return "";
      return `<section class="resource-pool-group" data-pool-group="${key}">
        <header class="resource-pool-group-head"><h3>${meta[0]} · ${items.length}</h3><p>${meta[1]}</p></header>
        <div class="resource-pool-rows">${items.map(rowMarkup).join("")}</div>
      </section>`;
    }).join("");
  }

  async function loadResourcePool(fetchFn = fetch) {
    const error = document.getElementById("resourcePoolError");
    try {
      const response = await fetchFn("/state/resource-pool", {cache: "no-store"});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      poolState = await response.json();
      renderSummary(poolState.summary);
      renderPool();
      const updated = document.getElementById("resourcePoolUpdatedAt");
      if (updated) updated.textContent = `마지막 관측 ${new Date(poolState.generated_at).toLocaleString("ko-KR")}`;
      if (error) {
        const messages = poolState.observation_errors || [];
        error.hidden = messages.length === 0;
        error.textContent = messages.length ? `일부 권위 소스 관측 실패 · ${messages.join(" · ")}` : "";
      }
      return poolState;
    } catch (reason) {
      if (error) {
        error.hidden = false;
        error.textContent = `자원 풀을 불러오지 못했습니다. ${reason.message || reason}`;
      }
      const list = document.getElementById("resourcePoolList");
      if (list) {
        list.setAttribute("aria-busy", "false");
        list.innerHTML = '<div class="resource-pool-empty">관측 API 연결을 확인한 뒤 새로고침하세요.</div>';
      }
      return null;
    }
  }

  function bindResourcePool() {
    document.querySelectorAll("[data-pool-class]").forEach((button) => {
      button.addEventListener("click", () => {
        selectedClass = button.dataset.poolClass || "all";
        document.querySelectorAll("[data-pool-class]").forEach((candidate) => {
          const active = candidate === button;
          candidate.classList.toggle("active", active);
          candidate.setAttribute("aria-pressed", active ? "true" : "false");
        });
        renderPool();
      });
    });
    document.getElementById("resourcePoolSearch")?.addEventListener("input", renderPool);
    document.querySelector('[data-dashboard-page="resource-pool"]')?.addEventListener("click", () => {
      if (!poolState) loadResourcePool();
    });
    document.getElementById("refreshButton")?.addEventListener("click", () => {
      if (document.body.dataset.dashboardPage === "resource-pool") loadResourcePool();
    });
    if (window.location.hash === "#resource-pool") loadResourcePool();
  }

  globalThis.ResourcePoolDashboard = {evidenceMarkup, rowMarkup, renderSummary, loadResourcePool};
  if (typeof document !== "undefined") bindResourcePool();
})();
