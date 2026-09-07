const DASHBOARD_PAGES = ["overview", "connections", "operations", "nodes", "management", "designer", "virtual-devices"];
const DASHBOARD_PAGE_ALIASES = {inventory: "connections", "device-twins": "connections", services: "operations"};
const DASHBOARD_PAGE_LABELS = {
  overview: "운영 개요", connections: "디바이스·서비스 연결", operations: "AI 서비스",
  nodes: "노드·자원", management: "장비 연결·관리", designer: "서비스 설계",
  "virtual-devices": "가상 디바이스 시험",
};

function canonicalDashboardPage(page) {
  return DASHBOARD_PAGE_ALIASES[page] || (DASHBOARD_PAGES.includes(page) ? page : "overview");
}

function requestedDashboardPage() {
  const hashPage = window.location.hash.replace(/^#/, "");
  return canonicalDashboardPage(hashPage);
}

function showDashboardPage(page) {
  const nextPage = canonicalDashboardPage(page);
  document.querySelectorAll("[data-dashboard-page]").forEach((button) => {
    const active = button.dataset.dashboardPage === nextPage;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  document.querySelectorAll("[data-page]").forEach((section) => {
    section.classList.toggle("active", section.dataset.page === nextPage);
  });
  document.body.dataset.dashboardPage = nextPage;
  const breadcrumb = document.getElementById("workspaceBreadcrumb");
  if (breadcrumb) breadcrumb.textContent = DASHBOARD_PAGE_LABELS[nextPage];
  if (["overview", "connections"].includes(nextPage)) globalThis.onDeviceTwinsVisible?.();
  if (nextPage === "virtual-devices" && typeof globalThis.onVirtualDevicesVisible === "function") {
    globalThis.onVirtualDevicesVisible();
  }
  if (
    nextPage === "designer"
    && typeof globalThis.onServiceDesignerVisible === "function"
  ) {
    globalThis.onServiceDesignerVisible();
  }
  if (
    nextPage === "operations"
    && typeof globalThis.onRuntimeOperationsVisible === "function"
  ) {
    globalThis.onRuntimeOperationsVisible();
  }
}

function bindDashboardNavigation() {
  document.querySelector(".workspace-skip")?.addEventListener("click", (event) => {
    event.preventDefault();
    document.getElementById("workspaceMain")?.focus();
  });
  document.querySelectorAll("[data-dashboard-page]").forEach((button) => {
    button.addEventListener("click", () => {
      const page = button.dataset.dashboardPage || "overview";
      if (window.location.hash !== `#${page}`) {
        window.location.hash = page;
        return;
      }
      showDashboardPage(page);
    });
  });
  window.addEventListener("hashchange", () => showDashboardPage(requestedDashboardPage()));
  showDashboardPage(requestedDashboardPage());
}

if (typeof document !== "undefined") {
  bindDashboardNavigation();
}

if (typeof globalThis !== "undefined") {
  globalThis.DASHBOARD_PAGES = DASHBOARD_PAGES;
  globalThis.showDashboardPage = showDashboardPage;
}

if (typeof module !== "undefined") {
  module.exports = {
    DASHBOARD_PAGES,
    canonicalDashboardPage,
    requestedDashboardPage,
    showDashboardPage,
  };
}
