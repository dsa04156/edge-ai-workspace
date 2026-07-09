from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_refactor_stylesheet_is_last_ui_layer() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()

    refactor_link = "/static/dashboard-refactor.css?v=reference-console-20260622"
    screen_link = "/static/dashboard-screen.css?v=resource-console-v3-20260709"
    base_link = "/static/styles.css?v=explain-panel-slim-20260622"
    theme_link = "/static/theme-refresh.css?v=asset-device-slim-20260622"
    assert base_link in html
    assert theme_link in html
    assert refactor_link in html
    assert screen_link in html
    assert html.index(refactor_link) > html.index(theme_link)
    assert html.index(screen_link) > html.index(refactor_link)


def test_dashboard_screen_layer_codifies_screen_design_contract() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-screen.css").read_text()
    workflow_js = (ROOT / "edge-orch/state-aggregator/app/static/resource-augmentation-workflow.js").read_text()
    design = (ROOT / "DESIGN.md").read_text()
    screen_design = (ROOT / "docs/dashboard-screen-design.md").read_text()

    assert "--console-bg: #020617;" in css
    assert "--console-rail: #020617;" in css
    assert "--console-accent: #22c55e;" in css
    assert "--console-yellow: var(--console-accent);" in css
    assert "--line: var(--console-border);" in css
    assert "--text: var(--console-text);" in css
    assert "--muted: var(--console-muted);" in css
    assert "color-scheme: dark;" in css
    assert ".dashboard-page:not(.active)" in css
    assert 'grid-template-areas:\n    "rail command"\n    "rail workspace";' in css
    assert "grid-area: rail;" in css
    assert 'content: "Edge AI\\AResource Console";' in css
    assert ".global-search" in css
    assert "Search resources" in html
    assert "flex: 0 0 auto;" in css
    assert "border-left: 4px solid transparent;" in css
    assert "border-left-color: var(--console-yellow);" in css
    assert "background: var(--console-yellow);" in css
    assert "grid-template-columns: minmax(0, 1fr) 376px;" in css
    assert "grid-column: 2 !important;" in css
    assert "grid-column: 1 / -1 !important;" in css
    assert "word-break: keep-all;" in css
    assert ".ring-legend" in css
    assert "grid-template-columns: repeat(auto-fit, minmax(86px, 1fr));" in css
    assert "white-space: nowrap;" in css
    assert ".panel-head-meta span" in css
    assert ".metric," in css
    assert 'grid-template-areas:\n    "label value"\n    "caption value";' in css
    assert ".side-rail" in css
    assert "position: sticky;" in css
    assert "top: 86px;" in css
    assert ".augmentation-mode-toggle" in css
    assert '.augmentation-mode-toggle button[aria-pressed="true"]' in css
    assert ".augmentation-mode-toggle button.active" in css
    assert "color: var(--console-ink) !important;" in css
    assert ".augmentation-section-head" in css
    assert ".augmentation-kpis" in css
    assert ".augmentation-bottom-grid" in css
    assert ".augmentation-grid" in css
    assert ".augmentation-flow-canvas" in css
    assert ".augmentation-node-canvas" in css
    assert ".workflow-graph-canvas" in css
    assert "augmentation-kpis" in html
    assert "augmentation-flow-canvas" in html
    assert "augmentation-node-canvas" in html
    assert "workflow-graph-canvas" in html
    assert ".augmentation-recommendation-row small" in css
    assert "overflow-wrap: normal;" in css
    assert "augmentationEdgeBoundaryPoint" in workflow_js
    assert "AUGMENTATION_GRAPH_NODE_HALF_WIDTH" in workflow_js
    assert "@media (max-width: 1180px)" in css
    assert "@media (max-width: 900px)" in css
    assert "@media (max-width: 760px)" in css
    assert "clamp(" not in css
    assert "# Edge AI Resource Console Design System" in design
    assert "`dashboard-screen.css` is the final Resource Console visual contract." in design
    assert "Resource rail" in design
    assert "## Resource Augmentation" in screen_design
    assert "dark left resource rail" in screen_design


def test_dashboard_screen_overrides_legacy_light_augmentation_states() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-screen.css").read_text()

    assert ".augmentation-recommendation-detail" in css
    assert ".augmentation-workflow-steps li" in css
    assert ".augmentation-offload-path div" in css
    assert ".augmentation-playback-inspector" in css
    assert ".augmentation-execution-timeline li" in css
    assert ".augmentation-plan-preview" in css
    assert ".augmentation-graph-node.current" in css
    assert ".augmentation-recommendation-row b" in css
    assert "background: var(--console-row) !important;" in css
    assert "background: var(--console-panel-2) !important;" in css
    assert "-webkit-text-fill-color: var(--console-ink) !important;" in css


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
        ".workflow-template",
        ".device-card",
        ".workflow-node span",
        ".inspector-title strong",
        ".workflow-source-list",
        ".validation-item",
        ".workflow-plan-preview",
        ".workflow-graph-canvas::before",
        ".pod-placement-card",
    ]

    for selector in legacy_surface_selectors:
        assert selector in css

    assert "background: var(--console-row) !important;" in css
    assert ".workflow-edge-label" in css
    assert "fill: var(--console-muted) !important;" in css
    assert "stroke: var(--console-control) !important;" in css
    assert ".status.available" in css
    assert ".pill.unavailable" in css


def test_dashboard_screen_keeps_augmentation_readable_in_narrow_desktop_workspace() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-screen.css").read_text()

    assert ".augmentation-section-head h3" in css
    assert "text-wrap: balance;" in css
    assert "@media (max-width: 1440px)" in css
    assert ".augmentation-workbench .augmentation-bottom-grid" in css
    assert ".augmentation-workbench .augmentation-grid" in css
    assert ".augmentation-workbench .augmentation-section-head" in css


def test_dashboard_screen_copy_stays_preview_oriented() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    js = (ROOT / "edge-orch/state-aggregator/app/static/resource-augmentation-panels.js").read_text()

    assert "Decision Playback" in html
    assert "Decision Path" in html
    assert "Evidence Timeline" in html
    assert "Auto Demo Playback" not in html
    assert "Planned Offload Path" not in html
    assert "Execution Timeline" not in html
    assert "augmentationStatusClass" in js
    assert 'class="augmentation-instance-chip ${resource.status}' not in js
    assert 'class="augmentation-status ${augEscape(resource.status)}' not in js


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


def test_operator_rail_groups_explain_panel_with_chat_and_keeps_topology_in_assets() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-refactor.css").read_text()

    assets_index = html.index('class="panel assets dashboard-page"')
    topology_index = html.index('class="panel topology-panel dashboard-page"')
    side_rail_index = html.index('class="side-rail')
    explain_index = html.index('class="panel explain-panel operator-context-panel"')
    chat_index = html.index('class="panel operator-chat"')

    assert assets_index < topology_index < side_rail_index < explain_index < chat_index
    assert html.count('id="explainPanel"') == 1
    assert html.index('id="explainPanel"') > side_rail_index
    assert 'aria-label="sticky operator assistance"' in html
    assert "Service Topology" in html
    assert ".operator-context-panel" in css
    assert ".topology-panel" in css
    assert ".topo-service-flow" in css
    assert ".topo-node-lane" in css


def test_dashboard_refactor_keeps_workflow_canvas_as_primary_workspace() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-refactor.css").read_text()

    assert "grid-template-columns: minmax(220px, 280px) minmax(0, 1fr);" in css
    assert ".workflow-palette" in css
    assert ".workflow-canvas-shell" in css
    assert ".workflow-inspector" in css
    assert "grid-column: 1 / -1 !important;" in css
    assert ".workflow-binding-inspector" in css
    assert "grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));" in css


def test_workflow_cards_handle_long_pipeline_labels_without_overlap() -> None:
    css = (
        (ROOT / "edge-orch/state-aggregator/app/static/workflow.css").read_text()
        + (ROOT / "edge-orch/state-aggregator/app/static/dashboard-refactor.css").read_text()
    )

    assert "width: 160px;" in css
    assert "min-height: 118px;" in css
    assert "-webkit-line-clamp: 2;" in css
    assert ".workflow-node small" in css
    assert ".workflow-message-text" in css
    assert "overflow-wrap: anywhere;" in css
    assert "text-overflow: ellipsis;" in css
    assert "grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));" in css


def test_workflow_canvas_uses_three_column_compact_layout() -> None:
    js = (ROOT / "edge-orch/state-aggregator/app/static/workflow-render-panels.js").read_text()
    actions_js = (ROOT / "edge-orch/state-aggregator/app/static/workflow-actions.js").read_text()

    assert "canvas.clientWidth < 980" in js
    assert "index % 3" in js
    assert "index / 3" in js
    assert "index * 190" in js
    assert "Math.min(workflowState.canvasScale, 0.96)" in js
    assert "(workflow.nodes.length % 3)" in actions_js


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


def test_dashboard_refactor_prevents_candidate_resource_row_overlap() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-refactor.css").read_text()

    assert ".augmentation-recommendation-row" in css
    assert "min-height: 58px;" in css
    assert "align-items: center;" in css
    assert ".augmentation-recommendation-row span" in css
    assert "line-height: 1.25;" in css


def test_dashboard_refactor_supports_augmentation_demo_progress_without_overflow() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-refactor.css").read_text()

    assert ".augmentation-demo-progress" in css
    assert ".augmentation-progress-bar" in css
    assert ".augmentation-workflow-steps li.current" in css
    assert "grid-template-columns: minmax(0, 1fr) auto;" in css
    assert "overflow-wrap: anywhere;" in css


def test_dashboard_refactor_adds_compact_augmentation_at_glance_panel() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-refactor.css").read_text()

    assert ".augmentation-at-glance" in css
    assert ".augmentation-glance-card" in css
    assert ".augmentation-glance-flow" in css
    assert "grid-template-columns: repeat(5, minmax(150px, 1fr));" in css
    assert ".augmentation-glance-card.current" in css


def test_dashboard_refactor_adds_n8n_style_augmentation_node_canvas() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-refactor.css").read_text()

    assert ".augmentation-node-canvas" in css
    assert ".augmentation-graph-edges" in css
    assert ".augmentation-graph-nodes" in css
    assert ".augmentation-edge-label" in css
    assert ".augmentation-flow-packet" in css
    assert ".augmentation-node-badge" in css
    assert ".augmentation-playback-inspector" in css
    assert ".augmentation-execution-timeline" in css
    assert "animation: augmentationEdgeFlow" in css
    assert "@keyframes augmentationNodePulse" in css
    assert ".augmentation-graph-node.current" in css
    assert "min-height: 430px;" in css
    assert "width: 152px;" in css
    assert "display: none;" in css
    assert "font-size: 10px;" in css
    assert "position: absolute;" in css
