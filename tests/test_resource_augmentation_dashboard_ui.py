from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / "edge-orch" / "state-aggregator" / "app" / "static"


def test_resource_augmentation_dashboard_exposes_execution_controls() -> None:
    html = (STATIC / "index.html").read_text(encoding="utf-8")
    js = (STATIC / "resource-augmentation.js").read_text(encoding="utf-8")

    assert 'id="augmentationExecute"' in html
    assert 'id="augmentationExecutionStatus"' in html
    assert 'id="augmentationExecutionArtifact"' in html
    assert "/state/resource-augmentation/execution" in js
    assert "renderAugmentationExecution" in js
