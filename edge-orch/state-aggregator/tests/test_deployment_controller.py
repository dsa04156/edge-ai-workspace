from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from fastapi.testclient import TestClient

from app.config import Settings
from app.deployment_controller import DeploymentController
from app.kube import KubeDeploymentError
from app.main import app, service, settings
from app.models import (
    DeploymentCreateRequest,
    PlacementRequirements,
    PlacementSelectionResult,
    PlacementServiceProfileRef,
)
from app.service import StateAggregatorService


DIGEST = "a" * 64
IMAGE = f"192.168.0.56:5000/state-aggregator@sha256:{DIGEST}"


def _request(**updates) -> DeploymentCreateRequest:
    values = {
        "deployment_name": "placement-smoke",
        "image": IMAGE,
        "placement": {
            "namespace": "default",
            "service": "redis",
            "architecture": "amd64",
        },
        "container_port": 8000,
        "readiness_path": "/",
    }
    values.update(updates)
    return DeploymentCreateRequest(**values)


def _placement(
    *,
    status: str = "selected",
    pod_count: int = 1,
    selected_node: str | None = "server01",
) -> PlacementSelectionResult:
    return PlacementSelectionResult(
        generated_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
        status=status,
        service_profile=PlacementServiceProfileRef(
            namespace="default",
            service="redis",
            generated_at=datetime(2026, 8, 25, tzinfo=timezone.utc),
            pod_count=pod_count,
            request_coverage_ratio=1,
        ),
        requirements=PlacementRequirements(
            cpu_cores=0.1,
            memory_bytes=128 * 1024**2,
            memory_gb=0.134,
            architecture="amd64",
            accelerator=None,
            accelerator_units={},
        ),
        selected_node=selected_node,
        selected_score=88.5 if selected_node else None,
        reason_codes=(
            ["eligible_node_selected"]
            if selected_node
            else ["no_eligible_nodes"]
        ),
    )


def _ready_deployment():
    return SimpleNamespace(
        status=SimpleNamespace(
            ready_replicas=1,
            available_replicas=1,
            conditions=[],
        )
    )


def _pod(
    *,
    ready: bool = True,
    waiting_reason: str | None = None,
):
    waiting = (
        SimpleNamespace(reason=waiting_reason, message="container wait")
        if waiting_reason
        else None
    )
    return SimpleNamespace(
        metadata=SimpleNamespace(name="placement-smoke-abc"),
        spec=SimpleNamespace(node_name="server01"),
        status=SimpleNamespace(
            phase="Running" if ready else "Pending",
            reason=None,
            message=None,
            conditions=[
                SimpleNamespace(
                    type="Ready",
                    status="True" if ready else "False",
                    reason=None,
                    message=None,
                )
            ],
            container_statuses=[
                SimpleNamespace(
                    state=SimpleNamespace(waiting=waiting, terminated=None)
                )
            ],
        ),
    )


class FakeKube:
    def __init__(self) -> None:
        self.exists = False
        self.created_body = None
        self.deployment = _ready_deployment()
        self.pods = [_pod()]
        self.create_error: KubeDeploymentError | None = None

    async def deployment_exists(self, namespace, name):
        return self.exists

    async def create_deployment(self, namespace, body):
        if self.create_error:
            raise self.create_error
        self.created_body = body
        return SimpleNamespace()

    async def read_deployment(self, namespace, name):
        return self.deployment

    async def list_deployment_pods(self, namespace, name):
        return self.pods


def _controller(kube: FakeKube, **settings_updates) -> DeploymentController:
    values = {
        "deployment_controller_enabled": True,
        "deployment_management_token": "test-token",
        "deployment_target_namespace": "edge-ai-workloads",
        "deployment_ready_timeout_seconds": 1,
        "deployment_poll_interval_seconds": 0.1,
    }
    values.update(settings_updates)
    return DeploymentController(Settings(**values), kube)


def test_controller_creates_exact_node_deployment_and_returns_pod_ready():
    kube = FakeKube()
    result = asyncio.run(
        _controller(kube).deploy(_request(), _placement(), "operation-1")
    )

    assert result.status == "ready"
    assert result.created is True
    assert result.selected_node == "server01"
    assert result.pod_ready is True
    assert result.reason_codes == ["deployment_created", "pod_ready"]
    assert result.pods[0].node == "server01"
    manifest = kube.created_body
    assert manifest is not None
    pod_spec = manifest["spec"]["template"]["spec"]
    assert pod_spec["nodeSelector"] == {"kubernetes.io/hostname": "server01"}
    expression = pod_spec["affinity"]["nodeAffinity"][
        "requiredDuringSchedulingIgnoredDuringExecution"
    ]["nodeSelectorTerms"][0]["matchExpressions"][0]
    assert expression == {
        "key": "kubernetes.io/hostname",
        "operator": "In",
        "values": ["server01"],
    }
    container = pod_spec["containers"][0]
    assert container["resources"]["requests"] == {
        "cpu": "0.1",
        "memory": str(128 * 1024**2),
    }
    assert "env" not in container
    assert "command" not in container
    assert "volumes" not in pod_spec
    assert manifest["spec"]["replicas"] == 1


def test_controller_rejects_no_fit_multi_pod_profile_and_unapproved_image():
    cases = [
        (
            _request(),
            _placement(status="no_fit", selected_node=None),
            "placement_not_selected",
        ),
        (_request(), _placement(pod_count=2), "service_profile_replica_count_unsupported"),
        (
            _request(
                image=f"registry.example/unknown@sha256:{DIGEST}"
            ),
            _placement(),
            "image_not_allowed",
        ),
    ]

    for request, placement, reason in cases:
        kube = FakeKube()
        result = asyncio.run(
            _controller(kube).deploy(request, placement, "operation-rejected")
        )
        assert result.status == "rejected"
        assert reason in result.reason_codes
        assert kube.created_body is None


def test_controller_never_updates_existing_deployment_and_reports_create_failure():
    existing_kube = FakeKube()
    existing_kube.exists = True
    existing = asyncio.run(
        _controller(existing_kube).deploy(_request(), _placement(), "operation-existing")
    )
    failing_kube = FakeKube()
    failing_kube.create_error = KubeDeploymentError(
        "deployment_create_forbidden",
        "forbidden",
    )
    failing = asyncio.run(
        _controller(failing_kube).deploy(_request(), _placement(), "operation-failed")
    )

    assert existing.status == "failed"
    assert existing.created is False
    assert existing.reason_codes == ["deployment_already_exists"]
    assert failing.status == "failed"
    assert failing.created is False
    assert failing.reason_codes == ["deployment_create_forbidden"]


def test_controller_reports_image_pull_failure_and_ready_timeout():
    image_kube = FakeKube()
    image_kube.deployment = SimpleNamespace(
        status=SimpleNamespace(ready_replicas=0, available_replicas=0, conditions=[])
    )
    image_kube.pods = [_pod(ready=False, waiting_reason="ImagePullBackOff")]
    image_failure = asyncio.run(
        _controller(image_kube).deploy(_request(), _placement(), "operation-image")
    )

    timeout_kube = FakeKube()
    timeout_kube.deployment = SimpleNamespace(
        status=SimpleNamespace(ready_replicas=0, available_replicas=0, conditions=[])
    )
    timeout_kube.pods = []
    timeout = asyncio.run(
        _controller(
            timeout_kube,
            deployment_ready_timeout_seconds=0.001,
        ).deploy(_request(), _placement(), "operation-timeout")
    )

    assert image_failure.reason_codes == ["image_pull_failed"]
    assert image_failure.pods[0].reason == "ImagePullBackOff"
    assert timeout.reason_codes == ["pod_ready_timeout"]
    assert timeout.created is True


def test_service_connects_placement_selection_to_deployment_controller(
    monkeypatch,
    tmp_path,
):
    aggregator = StateAggregatorService(Settings(data_dir=tmp_path))
    expected_placement = _placement()
    expected_result = asyncio.run(
        _controller(FakeKube()).deploy(
            _request(),
            expected_placement,
            "operation-service",
        )
    )

    async def fake_select(request):
        assert request.service == "redis"
        return expected_placement

    async def fake_deploy(request, placement, operation_id):
        assert placement is expected_placement
        assert operation_id == "operation-service"
        return expected_result

    monkeypatch.setattr(aggregator, "select_placement", fake_select)
    monkeypatch.setattr(aggregator.deployment_controller, "deploy", fake_deploy)

    result = asyncio.run(
        aggregator.deploy_workload(_request(), "operation-service")
    )
    assert result is expected_result


def test_deployment_api_requires_enablement_token_and_idempotency(monkeypatch):
    request_json = _request().model_dump(mode="json", by_alias=True)
    monkeypatch.setattr(settings, "deployment_controller_enabled", False)
    with TestClient(app) as client:
        disabled = client.post("/api/deployments", json=request_json)
    assert disabled.status_code == 503
    assert disabled.json()["detail"]["code"] == "deployment_controller_disabled"

    monkeypatch.setattr(settings, "deployment_controller_enabled", True)
    monkeypatch.setattr(settings, "deployment_management_token", "test-token")
    with TestClient(app) as client:
        unauthorized = client.post("/api/deployments", json=request_json)
        missing_key = client.post(
            "/api/deployments",
            json=request_json,
            headers={"X-Deployment-Token": "test-token"},
        )
    assert unauthorized.status_code == 401
    assert unauthorized.json()["detail"]["code"] == "deployment_authentication_failed"
    assert missing_key.status_code == 400
    assert missing_key.json()["detail"]["code"] == "invalid_idempotency_key"


def test_deployment_api_returns_camel_case_ready_result(monkeypatch):
    expected = asyncio.run(
        _controller(FakeKube()).deploy(
            _request(),
            _placement(),
            "ignored-by-api",
        )
    )

    async def fake_deploy(request, operation_id):
        assert request.deployment_name == "placement-smoke"
        return expected.model_copy(update={"operation_id": operation_id})

    monkeypatch.setattr(settings, "deployment_controller_enabled", True)
    monkeypatch.setattr(settings, "deployment_management_token", "test-token")
    monkeypatch.setattr(service, "deploy_workload", fake_deploy)
    with TestClient(app) as client:
        response = client.post(
            "/api/deployments",
            json=_request().model_dump(mode="json", by_alias=True),
            headers={
                "X-Deployment-Token": "test-token",
                "Idempotency-Key": "placement-test-1",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["deploymentName"] == "placement-smoke"
    assert payload["selectedNode"] == "server01"
    assert payload["podReady"] is True
    assert payload["status"] == "ready"
    assert len(payload["operationId"]) == 64
