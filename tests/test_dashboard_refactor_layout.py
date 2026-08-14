from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_refactor_stylesheet_is_last_ui_layer() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()

    refactor_link = "/static/dashboard-refactor.css?v=ai-pipeline-removed-20260730"
    screen_link = "/static/dashboard-screen.css?v=ai-pipeline-removed-20260730"
    apple_link = "/static/apple-dashboard.css?v=apple-operations-v1-20260814"
    base_link = "/static/styles.css?v=explain-panel-slim-20260622"
    theme_link = "/static/theme-refresh.css?v=asset-device-slim-20260622"
    assert base_link in html
    assert theme_link in html
    assert refactor_link in html
    assert screen_link in html
    assert apple_link in html
    assert html.index(refactor_link) > html.index(theme_link)
    assert html.index(screen_link) > html.index(refactor_link)
    assert html.index(apple_link) > html.index("/static/device-twins.css")
    assert html.rfind('rel="stylesheet"') < html.index(apple_link)


def test_apple_dashboard_layer_codifies_screen_design_contract() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    css = (ROOT / "edge-orch/state-aggregator/app/static/apple-dashboard.css").read_text()
    design = (ROOT / "DESIGN.md").read_text()
    screen_design = (ROOT / "docs/대시보드-화면-설계.md").read_text()

    assert "--apple-canvas: #07090d;" in css
    assert "--apple-rail: #0b0e13;" in css
    assert "--apple-accent: #5ac8c8;" in css
    assert "--console-accent: var(--apple-accent);" in css
    assert "--line: var(--apple-line);" in css
    assert "--text: var(--apple-text);" in css
    assert "--muted: var(--apple-secondary);" in css
    assert "color-scheme: dark;" in css
    assert 'grid-template-areas: "rail command" "rail workspace" !important;' in css
    assert 'content: "Edge AI\\AOperations" !important;' in css
    assert ".global-search" in css
    assert "리소스 검색" in html
    assert "backdrop-filter: saturate(145%) blur(22px);" in css
    assert "border-radius: var(--apple-radius-card)" in css
    assert ".kpi-grid.dashboard-page.active" in css
    assert "grid-template-columns: repeat(3, minmax(0, 1fr)) !important;" in css
    assert 'grid-template-areas:\n      "label value"\n      "caption value" !important;' in css
    assert ".side-rail" in css
    assert ".device-twins-inventory::before" in css
    assert 'tr[data-connection="bound"] td:first-child' in css
    assert "@media (max-width: 1180px)" in css
    assert "@media (max-width: 760px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert "@media (prefers-reduced-transparency: reduce)" in css
    assert "@media (prefers-contrast: more)" in css
    assert "transition: all" not in css
    assert "# Edge AI Apple Operations Design System" in design
    assert "`apple-dashboard.css` is the final visual contract." in design
    assert "물리 source → 관측 트윈 → AI 서비스" in design
    assert "Resource Augmentation" not in html
    assert "가상 디바이스 표시 경계" not in screen_design
    assert "읽기 전용" in screen_design
    assert "흑연색 운영 레일" in screen_design


def test_dashboard_screen_does_not_load_resource_augmentation_surface() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    nav_js = (ROOT / "edge-orch/state-aggregator/app/static/navigation.js").read_text()

    assert 'data-dashboard-page="augmentation"' not in html
    assert 'data-page="augmentation"' not in html
    assert "resource-augmentation.css" not in html
    assert "resource-augmentation.js" not in html
    assert '["overview", "inventory", "management", "services", "device-twins", "designer"]' in nav_js
    assert "workflow" not in nav_js
    assert "augmentation" not in nav_js


def test_dashboard_screen_overrides_legacy_light_surfaces_across_pages() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-screen.css").read_text()

    legacy_surface_selectors = [
        ".asset-column-head",
        ".scenario-grid > div",
        ".kpi-catalog-row",
        ".node-metric-card",
        ".resource-profile-list .compact-list li",
        ".device-status-list .item",
        ".node-card .item-title strong",
        ".device-row .item-title strong",
        ".topo-service",
        ".topo-pod-pill",
        ".device-card",
        ".inspector-title strong",
        ".validation-item",
        ".pod-placement-card",
    ]

    for selector in legacy_surface_selectors:
        assert selector in css

    assert "background: var(--console-row) !important;" in css
    assert "fill: var(--console-muted) !important;" in css
    assert "stroke: var(--console-control) !important;" in css
    assert ".status.available" in css
    assert ".pill.unavailable" in css


def test_dashboard_screen_navigation_keeps_only_current_poc_pages() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()

    assert ">운영 현황<" in html
    assert ">디바이스<" in html
    assert ">장비 관리<" in html
    assert ">디바이스 트윈<" in html
    assert ">AI 파이프라인<" not in html
    assert 'data-page="workflow"' not in html
    assert ">Resource Augmentation<" not in html


def test_dashboard_device_twin_inventory_is_read_only_and_responsive() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    css = (ROOT / "edge-orch/state-aggregator/app/static/device-twins.css").read_text()
    js = (ROOT / "edge-orch/state-aggregator/app/static/device-twins.js").read_text()

    assert 'data-page="device-twins"' in html
    assert 'id="deviceTwinsSearch"' in html
    assert 'class="device-twins-table"' in html
    assert "물리 디바이스" in html
    assert "관측 트윈" in html
    assert "사용 서비스" in html
    assert "물리 디바이스 → 트윈 → 서비스" in html
    assert 'fetchFn("/state/device-twins"' in js
    assert 'fetchFn("/state/resource-pool"' not in js
    assert "Kubernetes apply" not in js
    assert "@media (max-width: 720px)" in css
    assert "@media (max-width: 420px)" in css
    assert "overflow-wrap: anywhere;" in css


def test_dashboard_screen_copy_omits_removed_augmentation_preview() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()

    assert "Decision Playback" not in html
    assert "Decision Path" not in html
    assert "Evidence Timeline" not in html
    assert "Auto Demo Playback" not in html
    assert "Planned Offload Path" not in html
    assert "Execution Timeline" not in html


def test_dashboard_refactor_defines_non_overlapping_operating_layout() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-refactor.css").read_text()

    assert ".ops-shell" in css
    assert "grid-template-columns: minmax(0, 1fr) minmax(320px, 360px);" in css
    assert ".side-rail" in css
    assert "position: sticky;" in css
    assert "height: calc(100vh - 124px);" in css
    assert "grid-template-rows: minmax(180px, auto) minmax(0, 1fr);" in css
    assert ".side-rail .explain-panel" in css
    assert ".side-rail .operator-chat" in css
    assert "letter-spacing: 0;" in css
    assert "overflow-wrap: anywhere;" in css


def test_dashboard_refactor_upgrades_telemetry_history_chart() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-refactor.css").read_text()

    assert ".telemetry-summary-strip" in css
    assert ".chart-plot-bg" in css
    assert ".chart-gridline line" in css
    assert ".chart-area" in css
    assert ".chart-latest-marker" in css
    assert ".chart-time-tick" in css
    assert "aspect-ratio: 16 / 7;" in css


def test_device_selection_loads_core_data_history_instead_of_latest_snapshot() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    js = (ROOT / "edge-orch/state-aggregator/app/static/dashboard.js").read_text()
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-refactor.css").read_text()
    show_device = js[js.index("function showDeviceExplanation") : js.index("function kpiKeysForCard")]

    assert "/static/dashboard-refactor.css?v=ai-pipeline-removed-20260730" in html
    assert "/static/dashboard.js?v=cpu-aware-pressure-v3-20260804" in html
    assert "renderDeviceTelemetryHistory(history)" in show_device
    assert "renderTelemetryChart(device.latest_readings" not in show_device
    assert "void loadDeviceTelemetryHistory(device);" in js
    assert 'target?.closest?.("[data-telemetry-window]")' in js
    assert 'target?.closest?.("[data-telemetry-refresh]")' in js
    assert ".telemetry-history-toolbar" in css
    assert ".telemetry-history-state" in css
    assert ".telemetry-history-meta" in css


def test_context_drawer_groups_explain_panel_with_collapsed_chat_and_keeps_topology_in_assets() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-refactor.css").read_text()
    responsive_css = (
        ROOT / "edge-orch/state-aggregator/app/static/dashboard-responsive.css"
    ).read_text()

    assets_index = html.index('class="panel assets dashboard-page"')
    topology_index = html.index('class="panel topology-panel')
    side_rail_index = html.index('class="side-rail')
    explain_index = html.index('class="panel explain-panel operator-context-panel"')
    chat_index = html.index('class="panel operator-chat"')

    assert assets_index < topology_index < side_rail_index < explain_index < chat_index
    assert html.count('id="explainPanel"') == 1
    assert html.index('id="explainPanel"') > side_rail_index
    assert 'id="contextDetailPanel"' in html
    assert 'aria-label="선택 항목 상세정보"' in html
    assert 'class="context-assistant-details"' in html
    assert "Service Topology" in html
    assert ".operator-context-panel" in css
    assert ".topology-panel" in css
    assert ".topo-service-flow" in css
    assert ".topo-node-lane" in css
    assert "#contextDetailPanel[hidden]" in responsive_css
    assert "position: fixed !important;" in responsive_css


def test_operator_explain_panel_avoids_nested_scroll() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-refactor.css").read_text()

    assert ".side-rail .explain-panel" in css
    assert ".side-rail .explain-content" in css
    assert "max-height: none;" in css
    assert "overflow: visible;" in css
    assert "overflow-y: auto;" in css


def test_device_explain_panel_uses_line_items_not_gray_cards() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/theme-refresh.css").read_text()

    assert ".explain-status-strip" in css
    assert ".explain-facts" in css
    assert ".explain-reasons" in css
    assert ".explain-facts div" in css
    assert ".explain-facts div {\n  border-bottom: 1px solid #dce8ef;" in css
    assert ".explain-reasons li {\n  border-left: 2px solid #087f96;" in css
    assert ".command-hints" not in css


def test_inventory_device_metadata_is_plain_text_not_pills() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    css = (ROOT / "edge-orch/state-aggregator/app/static/theme-refresh.css").read_text()

    assert "/static/theme-refresh.css?v=asset-device-slim-20260622" in html
    assert ".assets .device-row .meta span" in css
    assert ".assets .device-row .meta span {\n  border: 0;" in css
    assert "background: transparent;" in css
    assert "border-radius: 0;" in css
    assert "padding: 0;" in css


def test_dashboard_refactor_no_longer_requires_candidate_resource_rows() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()

    assert "augmentationCandidateResourceRows" not in html
    assert "augmentationDecisionDetail" not in html


def test_dashboard_refactor_no_longer_requires_augmentation_demo_progress() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()

    assert "augmentationWorkflowProgress" not in html
    assert "augmentationWorkflowSteps" not in html


def test_dashboard_refactor_no_longer_requires_augmentation_at_glance_panel() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()

    assert "augmentationAtGlance" not in html
    assert "augmentationAtGlancePhase" not in html


def test_dashboard_refactor_no_longer_requires_augmentation_node_canvas() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()

    assert "augmentationNodeCanvas" not in html
    assert "augmentationGraphEdges" not in html
    assert "augmentationGraphNodes" not in html
