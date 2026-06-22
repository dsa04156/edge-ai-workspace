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
    assert 'id="augmentationPlaybackInspector"' in html
    assert 'id="augmentationExecutionTimeline"' in html
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
    assert "renderAugmentationPlaybackInspector" in js
    assert "renderAugmentationExecutionTimeline" in js
    assert "augmentationNodePayload" in js
    assert "augmentationNodeCanvasModel" in js
    assert "Observe Edge Device" in js
    assert "Detect Resource Pressure" in js
    assert "Evaluate Candidate Pool" in js
    assert "Select GPU Resource" in js
    assert "Select Cache Resource" in js
    assert "Plan Augmented Device Binding" in js
    assert "runtime metrics" in js
    assert "candidate scan" in js
    assert "select inference" in js
    assert "AI Service" not in js
    assert "ai-service" not in js
    assert "startAugmentationWorkflowPlayback" in js
    assert "scenario_timeline" in js
    assert "playback_interval_ms" in js
    assert "workflowAutomationLabel" in js
    assert "data-workflow-node-id" in js
    assert "flowing" in js
    assert "augmentation-flow-packet" in js
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


def test_dashboard_uses_english_assets_label_instead_of_korean_asset_copy() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    js = (ROOT / "edge-orch/state-aggregator/app/static/dashboard.js").read_text()

    assert ">Assets<" in html
    assert "Asset Inventory" in html
    assert "Registered Assets" in html
    assert "개 자산" not in js
    assert "자산 현황" not in html
    assert "등록 자산" not in html


def test_workflow_defaults_to_ai_pipeline_stages_without_ai_service_node() -> None:
    html = (ROOT / "edge-orch/state-aggregator/app/static/index.html").read_text()
    state_js = (ROOT / "edge-orch/state-aggregator/app/static/workflow-state.js").read_text()

    assert "/static/workflow.css?v=ai-pipeline-workflow-20260622" in html
    assert "/static/workflow-state.js?v=ai-pipeline-workflow-20260622" in html
    assert "/static/workflow-render-panels.js?v=ai-pipeline-workflow-20260622" in html
    assert "/static/workflow-actions.js?v=ai-pipeline-workflow-20260622" in html
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
