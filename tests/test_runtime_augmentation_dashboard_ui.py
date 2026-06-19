from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_resource_augmentation_dashboard_exposes_runtime_recommendations() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    js = (ROOT / "edge-orch/state-aggregator/app/static/resource-augmentation.js").read_text()

    assert 'id="augmentationRecommendationTotal"' in html
    assert 'id="augmentationVirtualDeviceRows"' in html
    assert 'id="augmentationDecisionDetail"' in html
    assert 'id="augmentationRecommendationService"' in html
    assert "대기 가상디바이스 풀" in html
    assert "스케줄링 결정" in html
    assert "/state/runtime-resource-augmentation" in js
    assert "renderAugmentationDecision" in js
    assert "virtual_devices" in js
    assert "decision" in js
    assert "ai_service" in js
