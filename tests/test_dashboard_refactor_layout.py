from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_refactor_stylesheet_is_last_ui_layer() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()

    refactor_link = "/static/dashboard-refactor.css?v=telemetry-kube-ui-20260622"
    assert refactor_link in html
    assert html.index(refactor_link) > html.index("/static/theme-refresh.css")


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
