const DASHBOARD_PAGES = ["overview", "inventory", "workflow", "management"];
const DASHBOARD_VIEW_MODE_KEY = "edge-ai-dashboard-view-mode";

function normalizeDashboardViewMode(mode) {
  return mode === "detailed" ? "detailed" : "simple";
}

function dashboardViewModeButtonCopy(mode) {
  const detailed = normalizeDashboardViewMode(mode) === "detailed";
  return {
    label: detailed ? "간편 보기" : "전체 보기",
    ariaLabel: detailed
      ? "대시보드 간편 보기로 전환"
      : "대시보드 전체 보기로 전환",
    pressed: detailed,
  };
}

function storedDashboardViewMode() {
  try {
    return normalizeDashboardViewMode(globalThis.localStorage?.getItem(
      DASHBOARD_VIEW_MODE_KEY,
    ));
  } catch (_error) {
    return "simple";
  }
}

function setDashboardViewMode(mode, {persist = true} = {}) {
  const nextMode = normalizeDashboardViewMode(mode);
  document.body.dataset.viewMode = nextMode;
  const button = document.getElementById("dashboardViewModeToggle");
  const copy = dashboardViewModeButtonCopy(nextMode);
  if (button) {
    button.textContent = copy.label;
    button.setAttribute("aria-label", copy.ariaLabel);
    button.setAttribute("aria-pressed", String(copy.pressed));
    button.title = copy.ariaLabel;
  }
  if (persist) {
    try {
      globalThis.localStorage?.setItem(DASHBOARD_VIEW_MODE_KEY, nextMode);
    } catch (_error) {
      // Storage can be disabled without blocking dashboard use.
    }
  }
  return nextMode;
}

function bindDashboardViewMode() {
  setDashboardViewMode(storedDashboardViewMode(), {persist: false});
  document.getElementById("dashboardViewModeToggle")?.addEventListener(
    "click",
    () => {
      const current = normalizeDashboardViewMode(document.body.dataset.viewMode);
      setDashboardViewMode(current === "simple" ? "detailed" : "simple");
    },
  );
}

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
  bindDashboardViewMode();
  bindDashboardNavigation();
}

if (typeof module !== "undefined") {
  module.exports = {
    dashboardViewModeButtonCopy,
    normalizeDashboardViewMode,
  };
}
