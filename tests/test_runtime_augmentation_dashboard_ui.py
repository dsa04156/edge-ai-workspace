from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_resource_augmentation_dashboard_exposes_runtime_recommendations() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    js = (ROOT / "edge-orch/state-aggregator/app/static/resource-augmentation.js").read_text()

    assert 'id="augmentationRecommendationTotal"' in html
    assert 'id="augmentationRecommendationRows"' in html
    assert 'id="augmentationRecommendationDetail"' in html
    assert "/state/runtime-resource-augmentation" in js
    assert "renderAugmentationRecommendations" in js
    assert "pressure_reason" in js
