from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "docker-build-push.yml"


def test_adapter_images_have_reproducible_build_entries() -> None:
    source = WORKFLOW.read_text()

    assert '"edgex/adapter-controller/**"' in source
    assert '"edgex/device-serial/**"' in source
    assert '"edgex/device-sensehat/**"' in source
    assert "Build and Push edge-adapter-controller" in source
    assert "Build and Push edgex-device-serial" in source
    assert "Build and Push edgex-device-sensehat" in source
    assert "--metadata-file /tmp/edge-adapter-controller-build-metadata.json" in source
    assert "SENSEHAT_REPOSITORY=" in source
    assert 'select(.adapter.runtimeAdapterId == "sensehat-raspi")' in source
    assert (
        "rollout status daemonset/edge-device-discovery-i2c"
        in source
    )
    assert "Deploy EdgeX adapter management images through Argo CD" in source


def test_device_service_builds_include_local_cache_module() -> None:
    serial = (ROOT / "edgex" / "device-serial" / "Dockerfile").read_text()
    sensehat = (ROOT / "edgex" / "device-sensehat" / "Dockerfile").read_text()

    for source in (serial, sensehat):
        assert "COPY local-data-cache" in source
        assert "go build" in source
        assert "CGO_ENABLED=0" in source
    assert "EDGEX_SERVICE_NAME" in (
        ROOT / "edgex" / "device-serial" / "cmd" / "device-serial" / "main.go"
    ).read_text()
    assert "EDGEX_SERVICE_NAME" in (
        ROOT / "edgex" / "device-sensehat" / "cmd" / "device-sensehat" / "main.go"
    ).read_text()
