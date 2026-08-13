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


def test_inventory_uses_concise_korean_operator_labels() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    js = (ROOT / "edge-orch/state-aggregator/app/static/dashboard.js").read_text()

    assert ">디바이스 인벤토리<" in html
    assert "엣지 AI 서버" in html
    assert "물리 디바이스" in html
    assert "가상 디바이스" in html
    assert "센서 디바이스" in html
    assert ">EdgeX 디바이스<" not in html
    assert 'id="deviceFilterLabel"' in html
    assert "`전체 ${totalCount}개`" in js
    assert ">모든 노드<" in html


def test_dashboard_physical_device_contract_is_edgex_only() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    js = (ROOT / "edge-orch/state-aggregator/app/static/dashboard.js").read_text()

    assert "센서 · 엣지 노드 · AI 서비스" in html
    assert "EdgeX Core Metadata가 물리 디바이스 권위를 유지합니다." in html
    assert 'id="resourceInventorySections"' in html
    assert 'data-resource-category-section="${escapeHtml(category)}"' in js
    assert 'id="sensorDeviceCount"' in html
    assert 'data-kpi-key="device_service_availability_ratio"' in html
    assert "device_service_name" in js
    assert "profile_name" in js
    assert "operating_state" in js
    assert "latest_event_timestamp" in js
    assert "mapper_running" not in js
    assert "device_status_fresh" not in js
    assert "kubeedge_state" not in js

def test_dashboard_uses_korean_top_level_navigation_and_keeps_technical_terms() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()

    for label in (
        'data-dashboard-page="overview" aria-pressed="true">운영 현황</button>',
        'data-dashboard-page="inventory" aria-pressed="false">디바이스</button>',
        'data-dashboard-page="management" aria-pressed="false">장비 관리</button>',
        "EdgeX",
        "Kubernetes",
    ):
        assert label in html

    for old_label in (
        ">AI 파이프라인<",
        "AI Pipeline Builder",
        ">워크플로우<",
        ">자원증강<",
        "자원증강 가상디바이스",
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
    assert "/static/dashboard.js?v=cpu-aware-pressure-v3-20260804" in html


def test_inventory_device_rows_use_compact_progressive_disclosure_table() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    js = (ROOT / "edge-orch/state-aggregator/app/static/dashboard.js").read_text()
    render_devices = js[js.index("function renderDevices") : js.index("function renderResourceProfiles")]

    assert "/static/dashboard.js?v=cpu-aware-pressure-v3-20260804" in html
    assert "publisher:" not in render_devices
    assert "mapper:" not in render_devices
    assert "RESOURCE_CATEGORY_ORDER.map" in render_devices
    assert "renderResourceInventorySection" in render_devices
    render_section = js[
        js.index("function renderResourceInventorySection") : js.index("function renderSensorDeviceRows")
    ]
    assert "renderResourceInventoryRows" in render_section
    assert 'class="sensor-device-empty"' in render_section
    render_rows = js[js.index("function renderResourceInventoryRows") : js.index("function renderDevices")]
    assert 'class="sensor-device-row' in render_rows
    assert 'data-label="${escapeHtml(latestLabel)}"' in render_rows
    assert ">상세보기</button>" in render_rows
    assert 'aria-controls="contextDetailPanel"' in render_rows
    assert "profile:" not in render_devices


def test_ai_pipeline_builder_surface_and_assets_are_removed() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    static_dir = ROOT / "edge-orch/state-aggregator/app/static"

    assert 'data-dashboard-page="workflow"' not in html
    assert 'data-page="workflow"' not in html
    assert "AI 파이프라인" not in html
    assert "AI Pipeline Builder" not in html
    for asset in (
        "workflow.css",
        "workflow-state.js",
        "workflow-render.js",
        "workflow-render-panels.js",
        "workflow-actions.js",
        "workflow.js",
    ):
        assert f"/static/{asset}" not in html
        assert not (static_dir / asset).exists()
