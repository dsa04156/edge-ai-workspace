from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_dashboard_refactor_stylesheet_is_last_ui_layer() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()

    refactor_link = "/static/dashboard-refactor.css?v=dashboard-refactor-20260619"
    assert refactor_link in html
    assert html.index(refactor_link) > html.index("/static/theme-refresh.css")


def test_dashboard_refactor_defines_non_overlapping_operating_layout() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-refactor.css").read_text()

    assert ".ops-shell" in css
    assert "display: block;" in css
    assert ".side-rail" in css
    assert "position: static;" in css
    assert "grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));" in css
    assert "letter-spacing: 0;" in css
    assert "overflow-wrap: anywhere;" in css


def test_dashboard_refactor_keeps_workflow_canvas_as_primary_workspace() -> None:
    css = (ROOT / "edge-orch/state-aggregator/app/static/dashboard-refactor.css").read_text()

    assert "grid-template-columns: minmax(220px, 0.55fr) minmax(720px, 1.9fr) minmax(260px, 0.65fr);" in css
    assert ".workflow-palette" in css
    assert ".workflow-canvas-shell" in css
    assert ".workflow-inspector" in css
    assert "grid-column: auto !important;" in css
