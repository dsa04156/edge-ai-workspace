const DASHBOARD_PAGES = ["overview", "operations", "inventory", "management", "designer"];

function requestedDashboardPage() {
  const hashPage = window.location.hash.replace(/^#/, "");
  return DASHBOARD_PAGES.includes(hashPage) ? hashPage : "overview";
}

function showDashboardPage(page) {
  const nextPage = DASHBOARD_PAGES.includes(page) ? page : "overview";
  document.querySelectorAll("[data-dashboard-page]").forEach((button) => {
    const active = button.dataset.dashboardPage === nextPage;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
  document.querySelectorAll("[data-page]").forEach((section) => {
    section.classList.toggle("active", section.dataset.page === nextPage);
  });
  document.body.dataset.dashboardPage = nextPage;
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
    requestedDashboardPage,
    showDashboardPage,
  };
}
