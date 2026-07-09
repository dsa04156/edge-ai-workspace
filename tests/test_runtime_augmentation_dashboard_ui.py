from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_resource_augmentation_dashboard_surface_is_removed_for_redesign() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()

    assert ">Resource Augmentation<" not in html
    assert 'data-dashboard-page="augmentation"' not in html
    assert 'data-page="augmentation"' not in html
    assert "resource-augmentation.css" not in html
    assert "resource-augmentation-crd.js" not in html
    assert "resource-augmentation-state.js" not in html
    assert "resource-augmentation-workflow-model.js" not in html
    assert "resource-augmentation-workflow.js" not in html
    assert "resource-augmentation-panels.js" not in html
    assert "resource-augmentation.js" not in html
    assert 'class="augmentation-workbench dashboard-page"' not in html
    assert 'id="augmentationRecommendationTotal"' not in html
    assert 'id="augmentationNodeCanvas"' not in html


def test_dashboard_uses_english_assets_label_instead_of_korean_asset_copy() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    js = (ROOT / "edge-orch/state-aggregator/app/static/dashboard.js").read_text()

    assert ">Assets<" in html
    assert "Asset Inventory" in html
    assert ">Edge Nodes<" in html
    assert ">Devices<" in html
    assert "Registered Assets" in html
    assert 'id="deviceFilterLabel" hidden' in html
    assert "개 자산" not in js
    assert "자산 현황" not in html
    assert "등록 자산" not in html


def test_dashboard_uses_consistent_english_domain_terms() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()

    for label in (
        ">Overview<",
        ">Assets<",
        ">AI Pipeline<",
        "AI Pipeline Builder",
    ):
        assert label in html

    for old_label in (
        ">개요<",
        ">워크플로우<",
        ">자원증강<",
        "자원증강 가상디바이스",
        "AI 서비스",
        "증강 자원 후보",
        "결과 가상디바이스",
        "스케줄링 결정",
        "자동 데모 진행",
    ):
        assert old_label not in html


def test_device_explanation_panel_omits_command_hints() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    js = (ROOT / "edge-orch/state-aggregator/app/static/dashboard.js").read_text()
    css = (
        (ROOT / "edge-orch/state-aggregator/app/static/styles.css").read_text()
        + (ROOT / "edge-orch/state-aggregator/app/static/theme-refresh.css").read_text()
    )

    show_device = js[js.index("function showDeviceExplanation") : js.index("function kpiKeysForCard")]

    assert "command-hints" not in show_device
    assert "renderReadOnlyCommandHints" not in js
    assert ".command-hints" not in css
    assert "explain-status-strip" in show_device
    assert "renderDeviceFactList" in js
    assert "explain-facts" in js
    assert "renderDeviceReasonList" in js
    assert "explain-reasons" in js
    assert "/static/dashboard.js?v=terminology-cleanup-20260622" in html


def test_inventory_device_rows_are_not_gray_metadata_chip_lists() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    js = (ROOT / "edge-orch/state-aggregator/app/static/dashboard.js").read_text()
    render_devices = js[js.index("function renderDevices") : js.index("function renderResourceProfiles")]

    assert "/static/dashboard.js?v=terminology-cleanup-20260622" in html
    assert "publisher:" not in render_devices
    assert "mapper:" not in render_devices
    assert "service:" not in render_devices
    assert "reason:" not in render_devices
    assert "node:" in render_devices
    assert "sensor:" in render_devices
    assert "age:" in render_devices


def test_workflow_defaults_to_ai_pipeline_stages_without_ai_service_node() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    state_js = (ROOT / "edge-orch/state-aggregator/app/static/workflow-state.js").read_text()

    assert "/static/workflow.css?v=ai-pipeline-compact-20260622" in html
    assert "/static/workflow-state.js?v=terminology-cleanup-20260622" in html
    assert "/static/workflow-render-panels.js?v=terminology-cleanup-20260622" in html
    assert "/static/workflow-actions.js?v=terminology-cleanup-20260622" in html
    assert "factory-vision-inspection-pipeline" in state_js
    for label in ("Collect", "Preprocess", "Inference", "Postprocess", "Store & Observe", "Dashboard"):
        assert f'label: "{label}"' in state_js
    assert "Collect Raw Telemetry" in state_js
    assert "Normalize Feature Window" in state_js
    assert "Run Defect Inference" in state_js
    assert "Format Inspection Event" in state_js
    assert "Persist Result Cache" in state_js
    assert "Publish Dashboard Signal" in state_js
    assert "AI Service" not in state_js
    assert "ai-service" not in state_js
