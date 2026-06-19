from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_resource_augmentation_dashboard_exposes_runtime_recommendations() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    js = (ROOT / "edge-orch/state-aggregator/app/static/resource-augmentation.js").read_text()

    assert 'id="augmentationRecommendationTotal"' in html
    assert 'id="augmentationCandidateResourceRows"' in html
    assert 'id="augmentationDecisionDetail"' in html
    assert 'id="augmentationWorkflowStatus"' in html
    assert 'id="augmentationWorkflowSteps"' in html
    assert 'id="augmentationOffloadPath"' in html
    assert 'id="augmentationRecommendationService"' in html
    assert "증강 자원 후보" in html
    assert "결과 가상디바이스" in html
    assert "오프로딩 경로" in html
    assert "스케줄링 결정" in html
    assert "/state/runtime-resource-augmentation" in js
    assert "renderAugmentationDecision" in js
    assert "renderAugmentationWorkflowDemo" in js
    assert "workflow_demo" in js
    assert "offload_path" in js
    assert "candidate_resources" in js
    assert "resulting_augmented_device" in js
    assert "decision" in js
    assert "ai_service" in js
    assert html.index('class="augmentation-flow"') < html.index('class="augmentation-recommendations"')
    assert html.index('class="augmentation-bottom-grid"') < html.index('class="augmentation-grid"')
