from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_resource_augmentation_dashboard_exposes_runtime_recommendations() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    js = (ROOT / "edge-orch/state-aggregator/app/static/resource-augmentation.js").read_text()

    assert 'id="augmentationRecommendationTotal"' in html
    assert 'id="augmentationCandidateResourceRows"' in html
    assert 'id="augmentationDecisionDetail"' in html
    assert 'id="augmentationWorkflowStatus"' in html
    assert 'id="augmentationWorkflowProgress"' in html
    assert 'id="augmentationWorkflowProgressText"' in html
    assert 'id="augmentationWorkflowSummary"' in html
    assert 'id="augmentationAtGlance"' in html
    assert 'id="augmentationAtGlancePhase"' in html
    assert 'id="augmentationAtGlanceService"' in html
    assert 'id="augmentationAtGlanceTarget"' in html
    assert 'id="augmentationAtGlanceResources"' in html
    assert 'id="augmentationAtGlanceResult"' in html
    assert 'id="augmentationNodeCanvas"' in html
    assert 'id="augmentationGraphEdges"' in html
    assert 'id="augmentationGraphNodes"' in html
    assert 'id="augmentationWorkflowSteps"' in html
    assert 'id="augmentationOffloadPath"' in html
    assert 'id="augmentationRecommendationService"' in html
    assert "자동 데모 진행" in html
    assert "증강 자원 후보" in html
    assert "결과 가상디바이스" in html
    assert "오프로딩 경로" in html
    assert "스케줄링 결정" in html
    assert "/state/runtime-resource-augmentation" in js
    assert "renderAugmentationDecision" in js
    assert "renderAugmentationWorkflowDemo" in js
    assert "renderAugmentationWorkflowFrame" in js
    assert "renderAugmentationAtGlance" in js
    assert "renderAugmentationNodeCanvas" in js
    assert "augmentationNodeCanvasModel" in js
    assert "startAugmentationWorkflowPlayback" in js
    assert "scenario_timeline" in js
    assert "playback_interval_ms" in js
    assert "workflowAutomationLabel" in js
    assert "workflow_demo" in js
    assert "progress_percent" in js
    assert "current_step_id" in js
    assert "operator_summary" in js
    assert "offload_path" in js
    assert "candidate_resources" in js
    assert "resulting_augmented_device" in js
    assert "decision" in js
    assert "ai_service" in js
    assert html.index('class="augmentation-flow"') < html.index('class="augmentation-recommendations"')
    assert html.index('class="augmentation-bottom-grid"') < html.index('class="augmentation-grid"')
