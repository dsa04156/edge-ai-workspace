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


def test_dashboard_screen_uses_a_hidden_responsive_context_drawer() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    css = (
        ROOT / "edge-orch/state-aggregator/app/static/dashboard-responsive.css"
    ).read_text()

    assert '<section class="ops-shell">' in html
    assert '<div class="ops-main">' in html
    assert 'id="contextDetailPanel"' in html
    assert 'class="side-rail t-panel-reveal"' in html
    assert 'aria-hidden="true"' in html
    assert 'id="contextDetailClose"' in html
    assert 'id="contextDetailPanel"' in html.split("</main>", 1)[0]
    assert "#contextDetailPanel[hidden]" in css
    assert "position: fixed !important;" in css
    assert "width: min(440px, 100vw) !important;" in css
    assert "height: 100dvh !important;" in css
    assert "z-index: 100 !important;" in css
    assert "@media (max-width: 760px)" in css
    assert "width: 100vw !important;" in css
