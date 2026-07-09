from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_screen_overrides_clicked_explain_panel_light_surfaces() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-screen.css").read_text()

    explain_selectors = [
        ".side-rail .explain-badge",
        ".side-rail .explain-fields div",
        ".side-rail .explain-status-strip div",
        ".side-rail .explain-facts div",
        ".side-rail .explain-reasons li",
        ".side-rail .explain-rules li",
        ".side-rail .telemetry-chart",
        ".side-rail .telemetry-chart .chart-svg",
        ".side-rail .telemetry-summary-strip div",
        ".side-rail .telemetry-chart .chart-legend span",
        ".side-rail .chart-plot-bg",
        ".side-rail .chart-latest-marker",
    ]

    for selector in explain_selectors:
        assert selector in css

    assert ".side-rail .explain-header strong" in css
    assert "border-left-color: var(--console-blue) !important;" in css
    assert "fill: var(--console-control) !important;" in css
    assert "filter: none !important;" in css
    assert "stroke: var(--console-row) !important;" in css


def test_dashboard_screen_keeps_overview_ops_panels_from_overlapping_headers() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-screen.css").read_text()

    assert ".overview-ops-grid.dashboard-page.active" in css
    assert "grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));" in css
    assert ".overview-ops-grid .panel-head" in css
    assert "grid-template-columns: minmax(0, 1fr);" in css
    assert ".overview-ops-grid .panel-head-meta span" in css
    assert "overflow-wrap: anywhere;" in css


def test_dashboard_screen_keeps_kpi_catalog_cjk_labels_unsplit() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-screen.css").read_text()

    assert ".kpi-catalog-row span" in css
    assert "word-break: keep-all !important;" in css
    assert "overflow-wrap: normal !important;" in css
    assert "white-space: nowrap !important;" in css
    assert ".kpi-catalog-row code" in css
    assert "overflow-wrap: anywhere !important;" in css


def test_dashboard_screen_collapses_mid_width_layout_before_cards_overlap() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-screen.css").read_text()

    assert "grid-template-columns: minmax(0, 1fr) 376px;" in css
    assert "@media (max-width: 1360px)" in css
    assert ".ops-shell" in css
    assert ".side-rail" in css
    assert ".overview-ops-grid.dashboard-page.active" in css
    assert ".overview-visual-grid" in css
    assert ".kpi-catalog-row strong" in css


def test_dashboard_screen_keeps_side_rail_inside_ops_shell_grid() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-screen.css").read_text()
    final_guard_start = css.rfind("\n.ops-shell > .side-rail {\n")
    final_guard_end = css.find("\n@media (max-width: 1360px)", final_guard_start)
    final_guard = css[final_guard_start:final_guard_end]

    assert '<section class="ops-shell">' in html
    assert '<div class="ops-main">' in html
    assert '<aside class="side-rail t-panel-reveal"' in html
    assert '<div id="alertList" hidden></div>\n      </section>\n        </div>\n        <aside class="side-rail t-panel-reveal"' in html
    assert '<aside class="side-rail t-panel-reveal"' in html.split("</main>", 1)[0]
    assert "right: auto !important;" in css
    assert "left: auto !important;" in css
    assert "width: auto !important;" in css
    assert "height: auto !important;" in css
    assert "z-index: auto !important;" in final_guard
    assert "right: auto !important;" in final_guard
    assert "grid-column: 2 !important;" in final_guard
