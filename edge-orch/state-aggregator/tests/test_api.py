from datetime import datetime, timedelta, timezone
import asyncio
import pytest

import httpx
from fastapi.testclient import TestClient

from app.main import app, service, create_app
from app.config import Settings
from app.service import StateAggregatorService
from app.edgex import EdgeXBackendError, EdgeXError, EdgeXHTTPStatusError
from app.models import (
    DeviceState,
    EdgeXDevice,
    EdgeXDeviceProfile,
    EdgeXDeviceResource,
    EventHistoryPage,
    NodeState,
    TelemetryPoint,
    WorkflowState,
)
import app.main as main_module
from app.virtual_device_bindings import VirtualDeviceBindingConfig


def test_metrics_exposes_node_and_workflow_gauges():
    service.store.nodes = {
        "etri-ser0001-CG0MSB": NodeState(
            hostname="etri-ser0001-CG0MSB",
            instance="192.168.0.56:9100",
            node_type="cloud_server",
            collected_at=datetime.now(timezone.utc),
            raw_metrics={
                "up": 1.0,
                "cpu_utilization": 0.91,
                "memory_usage_ratio": 0.42,
                "load_average": 2.1,
                "network_rx_rate": 1000.0,
                "network_tx_rate": 800.0,
            },
            compute_pressure="high",
            memory_pressure="low",
            network_pressure="low",
            node_health="degraded",
        )
    }
    service.store.workflows = {
        "wf-1": WorkflowState(
            workflow_id="wf-1",
            workflow_type="vision_pipeline",
            last_event_type="migration_event",
            last_stage_id="stage-a",
            last_stage_type="inference",
            assigned_node="etri-ser0001-CG0MSB",
            last_status="migrating",
            latest_timestamp=datetime.now(timezone.utc),
            event_count=3,
            migration_count_last_hour=1,
            workflow_urgency="high",
            sla_risk="medium",
            placement_stability="moving",
            recent_event={},
        )
    }

    with TestClient(app) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain; version=0.0.4")
    body = response.text
    assert "# HELP edge_orch_node_cpu_utilization_ratio" in body
    assert (
        'edge_orch_node_cpu_utilization_ratio{hostname="etri-ser0001-CG0MSB",'
        'instance="192.168.0.56:9100",node_type="cloud_server"} 0.91'
    ) in body
    assert (
        'edge_orch_node_health{hostname="etri-ser0001-CG0MSB",instance="192.168.0.56:9100",'
        'node_type="cloud_server",level="degraded"} 1.0'
    ) in body
    assert (
        'edge_orch_workflow_placement_stability{workflow_id="wf-1",'
        'workflow_type="vision_pipeline",assigned_node="etri-ser0001-CG0MSB",level="moving"} 1.0'
    ) in body
    assert "edge_orch_summary_recent_migration_count{} 1.0" in body
    assert "# HELP edge_orch_edgex_device_snapshot_refresh_total" in body
    assert "# HELP edge_orch_edgex_device_snapshot_refresh_in_flight" in body
    assert "# HELP edge_orch_edgex_event_observation_errors" in body


def test_cost_model_endpoint_returns_snapshot():
    with TestClient(app) as client:
        response = client.get("/state/cost-model")

    assert response.status_code == 200
    payload = response.json()
    assert "node_states" in payload
    assert "stage_cost_stats" in payload
    assert "migration_cost_stats" in payload


def test_virtual_device_collection_reports_disabled_without_a_failed_request():
    with TestClient(app) as client:
        response = client.get("/state/virtual-devices")
        detail_response = client.get("/state/virtual-devices/not-configured")

    assert response.status_code == 200
    assert response.json()["projection_enabled"] is False
    assert response.json()["items"] == []
    assert detail_response.status_code == 404
    assert detail_response.json()["detail"]["code"] == "projection_not_active"
def test_metrics_exposes_explicit_disabled_projection_gauge():
    with TestClient(app) as client:
        response = client.get("/metrics")

    assert 'edge_orch_virtual_device_projection_enabled{} 0.0' in response.text


def test_resource_profile_endpoints_return_service_requirement_profiles(monkeypatch):
    monkeypatch.setattr(service.settings, "resource_profile_recording_mode", "scheduled")

    async def fake_running_service_pods():
        return [
            {
                "namespace": "default",
                "name": "redis-abc",
                "workload": "redis",
                "node": "server-node",
                "phase": "Running",
                "containers": [
                    {
                        "name": "redis",
                        "requests": {"cpu": "100m", "memory": "128Mi"},
                        "limits": {"cpu": "200m", "memory": "256Mi"},
                    }
                ],
            },
            {
                "namespace": "default",
                "name": "state-aggregator-abc",
                "workload": "state-aggregator",
                "node": "server-node",
                "phase": "Running",
                "containers": [{"name": "app", "requests": {}, "limits": {}}],
            },
        ]

    monkeypatch.setattr(service.kube, "get_running_service_pods", fake_running_service_pods)

    record_calls = []

    async def fake_record_snapshot(profiles):
        record_calls.append(profiles)
        return True

    async def fake_collect_usage(*args, **kwargs):
        return [
            {
                "namespace": "default",
                "pod": "redis-abc",
                "container": "redis",
                "cpu_usage_cores": 0.04,
                "memory_working_set_mib": 80,
                "avg_cpu_usage_cores": 0.03,
                "max_cpu_usage_cores": 0.09,
                "p95_cpu_usage_cores": 0.07,
                "avg_memory_working_set_mib": 70,
                "max_memory_working_set_mib": 90,
                "p95_memory_working_set_mib": 85,
            },
        ]

    monkeypatch.setattr(service.resource_recorder, "record_snapshot", fake_record_snapshot)
    monkeypatch.setattr(service.prometheus, "collect_service_resource_usage", fake_collect_usage)
    monkeypatch.setattr(service.prometheus, "collect_service_resource_profile_usage", fake_collect_usage)
    service._service_resource_profiles = []
    service._last_resource_recorded_at = None
    service._last_resource_record_result = "never_recorded"

    with TestClient(app) as client:
        profile_response = client.get("/state/resource-profiles?refresh=true")
        service_response = client.get("/state/service-resource-profiles?service=redis")

    assert profile_response.status_code == 200
    profile_payload = profile_response.json()
    assert profile_payload["recording_backend"] == "influxdb"
    assert profile_payload["recording_mode"] == "scheduled"
    assert profile_payload["recording_interval_seconds"] == 600
    assert profile_payload["last_record_result"] == "never_recorded"
    assert profile_payload["profile_scope"] == "running_service_resource_requirements"
    assert profile_payload["summary"]["profile_count"] == 2
    assert "placement_advice" not in profile_payload
    assert service_response.status_code == 200
    service_payload = service_response.json()
    assert [item["service"] for item in service_payload["service_resource_profiles"]] == ["redis"]
    redis_profile = service_payload["service_resource_profiles"][0]
    assert redis_profile["resource_requirements"]["requests"]["cpu_cores"] == 0.1
    assert redis_profile["current_usage"]["cpu_cores"] == 0.04
    assert redis_profile["current_usage"]["memory_working_set_mib"] == 80
    assert record_calls == []

    with TestClient(app) as client:
        record_response = client.post("/state/service-resource-profiles/record?window=10m")

    assert record_response.status_code == 200
    record_payload = record_response.json()
    assert record_payload["recorded"] is True
    assert record_payload["recording_mode"] == "scheduled"
    assert record_payload["recording_interval_seconds"] == 600
    assert record_payload["profile_window"] == "10m"
    recorded_redis = [item for item in record_payload["service_resource_profiles"] if item["service"] == "redis"][0]
    assert recorded_redis["usage_profile"]["window"] == "10m"
    assert recorded_redis["usage_profile"]["avg_cpu_usage_cores"] == 0.03
    assert len(record_calls) == 1


def test_virtual_resources_endpoint_returns_resource_profiles_with_observed_instances(monkeypatch):
    async def fake_resource_state(refresh=False):
        return {
            "service_resource_profiles": [
                {
                    "namespace": "edge-ai",
                    "service": "gpu-inference",
                    "pod_count": 1,
                    "nodes": ["etri-ser0002-cgnmsb"],
                    "pods_by_node": {"etri-ser0002-cgnmsb": 1},
                    "containers": [
                        {
                            "namespace": "edge-ai",
                            "pod": "gpu-inference-abc",
                            "container": "runtime",
                            "node": "etri-ser0002-cgnmsb",
                            "labels": {
                                "edge-ai.io/augmentation-resource": "vd-x86-gpu-inference",
                                "edge-ai.io/binding-state": "free",
                            },
                            "pod_ready": True,
                            "endpoint_ready": True,
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(service, "get_resource_profile_state", fake_resource_state)
    service.store.nodes = {
        "etri-ser0002-cgnmsb": NodeState(
            hostname="etri-ser0002-cgnmsb",
            instance="192.168.0.5:9100",
            node_type="server",
            collected_at=datetime.now(timezone.utc),
            raw_metrics={"up": 1.0},
            compute_pressure="low",
            memory_pressure="low",
            network_pressure="low",
            node_health="healthy",
        )
    }

    with TestClient(app) as client:
        response = client.get("/state/virtual-resources")

    assert response.status_code == 200
    payload = response.json()
    gpu = next(item for item in payload["resources"] if item["id"] == "vd-x86-gpu-inference")
    assert gpu["observed_instances"] == 1
    assert gpu["free_instances"] == 1
    assert gpu["status"] == "idle"
    assert gpu["instances"][0]["pod"] == "gpu-inference-abc"
    assert gpu["twin"]["endpoint_ready"] is True


def test_virtual_resources_endpoint_requires_exact_runtime_identity_not_node_or_keyword(monkeypatch):
    async def fake_resource_state(refresh=False):
        return {
            "service_resource_profiles": [
                {
                    "namespace": "edge-ai",
                    "service": "gpu-inference",
                    "pod_count": 2,
                    "nodes": ["etri-ser0002-cgnmsb", "etri-dev0001-jetorn"],
                    "containers": [
                        {
                            "namespace": "edge-ai",
                            "pod": "gpu-server-abc",
                            "container": "runtime",
                            "node": "etri-ser0002-cgnmsb",
                            "labels": {},
                            "pod_ready": True,
                            "endpoint_ready": True,
                        },
                        {
                            "namespace": "edge-ai",
                            "pod": "gpu-jetson-abc",
                            "container": "runtime",
                            "node": "etri-dev0001-jetorn",
                            "labels": {
                                "edge-ai.io/augmentation-resource": "vd-jetson-gpu-lite",
                                "edge-ai.io/binding-state": "free",
                            },
                            "pod_ready": True,
                            "endpoint_ready": True,
                        },
                    ],
                }
            ]
        }

    monkeypatch.setattr(service, "get_resource_profile_state", fake_resource_state)
    service.store.nodes = {
        "etri-ser0002-cgnmsb": NodeState(
            hostname="etri-ser0002-cgnmsb",
            instance="192.168.0.5:9100",
            node_type="server",
            collected_at=datetime.now(timezone.utc),
            raw_metrics={"up": 1.0},
            compute_pressure="low",
            memory_pressure="low",
            network_pressure="low",
            node_health="healthy",
        ),
        "etri-dev0001-jetorn": NodeState(
            hostname="etri-dev0001-jetorn",
            instance="192.168.0.6:9100",
            node_type="edge",
            collected_at=datetime.now(timezone.utc),
            raw_metrics={"up": 1.0},
            compute_pressure="low",
            memory_pressure="low",
            network_pressure="low",
            node_health="healthy",
        ),
    }

    with TestClient(app) as client:
        response = client.get("/state/virtual-resources")

    assert response.status_code == 200
    payload = response.json()
    server_gpu = next(item for item in payload["resources"] if item["id"] == "vd-x86-gpu-inference")
    jetson_gpu = next(item for item in payload["resources"] if item["id"] == "vd-jetson-gpu-lite")
    assert server_gpu["instances"] == []
    assert server_gpu["status"] == "configured_not_running"
    assert [item["pod"] for item in jetson_gpu["instances"]] == ["gpu-jetson-abc"]


def test_virtual_resources_endpoint_does_not_claim_available_without_endpoint_or_binding_evidence(monkeypatch):
    async def fake_resource_state(refresh=False):
        return {
            "service_resource_profiles": [
                {
                    "namespace": "edge-ai",
                    "service": "gpu-inference",
                    "pod_count": 1,
                    "nodes": ["etri-ser0002-cgnmsb"],
                    "containers": [
                        {
                            "namespace": "edge-ai",
                            "pod": "gpu-inference-abc",
                            "container": "runtime",
                            "node": "etri-ser0002-cgnmsb",
                            "labels": {"edge-ai.io/augmentation-resource": "vd-x86-gpu-inference"},
                            "pod_ready": True,
                            "endpoint_ready": False,
                        }
                    ],
                }
            ]
        }

    monkeypatch.setattr(service, "get_resource_profile_state", fake_resource_state)
    service.store.nodes = {
        "etri-ser0002-cgnmsb": NodeState(
            hostname="etri-ser0002-cgnmsb",
            instance="192.168.0.5:9100",
            node_type="server",
            collected_at=datetime.now(timezone.utc),
            raw_metrics={"up": 1.0},
            compute_pressure="low",
            memory_pressure="low",
            network_pressure="low",
            node_health="healthy",
        )
    }

    with TestClient(app) as client:
        response = client.get("/state/virtual-resources")

    resource = next(item for item in response.json()["resources"] if item["id"] == "vd-x86-gpu-inference")
    assert resource["observed_instances"] == 1
    assert resource["free_instances"] == 0
    assert resource["status"] == "degraded"
    assert resource["twin"]["endpoint_ready"] is False
    assert resource["twin"]["binding_state"] == "unknown"


def test_virtual_resources_endpoint_keeps_registry_when_observation_fails(monkeypatch):
    async def fake_resource_state(refresh=False):
        raise httpx.ConnectError("prometheus unavailable")

    monkeypatch.setattr(service, "get_resource_profile_state", fake_resource_state)
    service.store.nodes = {}

    with TestClient(app) as client:
        response = client.get("/state/virtual-resources")
        twin_response = client.get("/state/virtual-resources/vd-aihat-inference/twin")

    assert response.status_code == 200
    payload = response.json()
    assert payload["observation_error"] == "service resource observation unavailable: ConnectError"
    assert len(payload["resources"]) == 4
    assert {item["status"] for item in payload["resources"]} == {"configured_not_running"}
    assert twin_response.status_code == 200
    assert twin_response.json()["binding_state"] == "not_running"


def test_service_start_schedules_operational_resource_profile_recorder(monkeypatch, tmp_path):
    import app.service as service_module

    created_tasks = []

    def fake_create_task(coroutine):
        created_tasks.append(coroutine.cr_code.co_name)
        coroutine.close()
        return asyncio.Future()

    settings = Settings(
        data_dir=tmp_path,
        resource_profile_recording_mode="scheduled",
        resource_profile_record_interval_seconds=600,
    )
    aggregator = StateAggregatorService(settings)
    monkeypatch.setattr(service_module.asyncio, "create_task", fake_create_task)

    asyncio.run(aggregator.start())

    assert "_poll_prometheus" in created_tasks
    assert "_record_resource_profiles_periodically" in created_tasks


def test_refresh_nodes_replaces_snapshot_and_filters_unmapped_targets(monkeypatch, tmp_path):
    now = datetime.now(timezone.utc)
    aggregator = StateAggregatorService(Settings(data_dir=tmp_path))
    aggregator.store.nodes = {
        "deleted-node": NodeState(
            hostname="deleted-node",
            instance="192.168.0.99:9100",
            node_type="edge_light_device",
            collected_at=now,
            raw_metrics={
                "up": 1.0,
                "cpu_utilization": 0.1,
                "memory_usage_ratio": 0.2,
                "load_average": 0.1,
                "network_rx_rate": 1.0,
                "network_tx_rate": 1.0,
            },
            compute_pressure="low",
            memory_pressure="low",
            network_pressure="low",
            node_health="healthy",
        )
    }

    async def fake_node_map():
        return {
            "192.168.0.6:9100": {"hostname": "etri-dev0003-raspi5", "node_type": "edge_light_device"},
            "192.168.0.6": {"hostname": "etri-dev0003-raspi5", "node_type": "edge_light_device"},
        }

    async def fake_collect_node_metrics():
        from app.models import NodeRawMetrics

        return [
            NodeRawMetrics(
                instance="192.168.0.6:9100",
                hostname="etri-dev0003-raspi5",
                node_type="edge_light_device",
                up=1.0,
                cpu_utilization=0.1,
                memory_usage_ratio=0.2,
                load_average=0.1,
                network_rx_rate=1.0,
                network_tx_rate=1.0,
                collected_at=now,
            ),
            NodeRawMetrics(
                instance="192.168.0.99:9100",
                hostname="192.168.0.99:9100",
                up=0.0,
                collected_at=now,
            ),
        ]

    async def fake_refresh_profiles():
        return []

    monkeypatch.setattr(aggregator.kube, "get_node_map", fake_node_map)
    monkeypatch.setattr(aggregator.prometheus, "collect_node_metrics", fake_collect_node_metrics)
    monkeypatch.setattr(aggregator, "refresh_service_resource_profiles", fake_refresh_profiles)

    states = asyncio.run(aggregator.refresh_nodes())

    assert [state.hostname for state in states] == ["etri-dev0003-raspi5"]
    assert [node.hostname for node in aggregator.get_nodes()] == ["etri-dev0003-raspi5"]


def test_operator_chat_returns_safe_response_when_qwen_unavailable(monkeypatch):
    import app.service as service_module

    async def fake_operator_assistant():
        from app.models import OperatorAssistantState

        return OperatorAssistantState(
            generated_at=datetime.now(timezone.utc),
            summary_ko="등록 device 1개 중 live device 1개입니다.",
            focus_devices=[],
            recommended_actions=["dashboard KPI를 확인한다."],
            guardrails=["read-only endpoint"],
            source_endpoints=["/state/dashboard"],
        )

    class FailingQwenClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, *args, **kwargs):
            raise service_module.httpx.ConnectError("qwen unavailable")

    monkeypatch.setattr(service, "get_operator_assistant", fake_operator_assistant)
    monkeypatch.setattr(service_module.httpx, "AsyncClient", FailingQwenClient)

    with TestClient(app) as client:
        response = client.post("/state/operator-chat", json={"message": "현재 상태 요약해줘"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "read_only"
    assert payload["model"] == "qwen3.6-35b"
    assert payload["upstream_status"] == "unavailable"
    assert "연결하지 못했습니다" in payload["answer"]


def test_operator_chat_posts_openai_compatible_payload(monkeypatch):
    import app.service as service_module

    calls = []

    async def fake_operator_assistant():
        from app.models import OperatorAssistantState

        return OperatorAssistantState(
            generated_at=datetime.now(timezone.utc),
            summary_ko="Sense HAT device 6개가 fresh입니다.",
            focus_devices=[{"name": "env-sensehat-humidity-01", "status": "available", "reason": "fresh", "node_name": "etri-dev0003-raspi5"}],
            recommended_actions=["dashboard KPI를 확인한다."],
            guardrails=["read-only endpoint"],
            source_endpoints=["/state/dashboard", "/state/devices"],
        )

    class FakeQwenResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "현재 Sense HAT 데이터는 fresh입니다."}}]}

    class FakeQwenClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return None

        async def post(self, url, json):
            calls.append({"url": url, "json": json})
            return FakeQwenResponse()

    monkeypatch.setattr(service, "get_operator_assistant", fake_operator_assistant)
    monkeypatch.setattr(service_module.httpx, "AsyncClient", FakeQwenClient)

    with TestClient(app) as client:
        response = client.post("/state/operator-chat", json={"message": "Sense HAT 상태 알려줘"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["answer"] == "현재 Sense HAT 데이터는 fresh입니다."
    assert payload["source_endpoints"] == ["/state/dashboard", "/state/devices"]
    assert calls[0]["url"] == "http://192.168.0.5:8080/v1/chat/completions"
    assert calls[0]["json"]["model"] == "qwen3.6-35b"
    assert calls[0]["json"]["messages"][0]["role"] == "system"
    assert "read-only" in calls[0]["json"]["messages"][0]["content"]


def _edgex_device(
    name: str,
    *,
    admin_state: str = "UNLOCKED",
    operating_state: str = "UP",
    node_name: str | None = "edge-node-diagnostic",
) -> EdgeXDevice:
    return EdgeXDevice(
        name=name,
        profile_name="temperature-profile",
        device_service_name="device-rest",
        protocol_names=["REST"],
        admin_state=admin_state,
        operating_state=operating_state,
        tags={"nodeName": node_name} if node_name else {},
        node_name=node_name,
    )


def _reading(name: str, timestamp: datetime) -> TelemetryPoint:
    return TelemetryPoint(
        device_name=name,
        source_name="temperature",
        resource_name="Temperature",
        value_type="Float64",
        value=24.3,
        timestamp=timestamp,
        origin=int(timestamp.timestamp() * 1_000_000_000),
        event_id="event-1",
        units="Cel",
    )


def test_devices_endpoint_uses_edgex_inventory_and_latest_event(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_devices():
        return [_edgex_device("sensor-01")]

    async def fake_latest(device_name: str):
        assert device_name == "sensor-01"
        return [_reading(device_name, now)]

    monkeypatch.setattr(service.edgex, "get_devices", fake_devices)
    monkeypatch.setattr(service.edgex, "get_latest_source_readings", fake_latest)

    with TestClient(app) as client:
        response = client.get("/state/devices")

    assert response.status_code == 200
    device = response.json()[0]
    assert device["source"] == "edgex"
    assert device["profile_name"] == "temperature-profile"
    assert device["device_service_name"] == "device-rest"
    assert device["protocol_names"] == ["REST"]
    assert device["connection_state"] == "connected"
    assert device["device_service_available"] is True
    assert device["telemetry_freshness"] == "fresh"
    assert device["latest_readings"][0]["resource_name"] == "Temperature"
    assert device["overall_status"] == "available"
    assert "Core Data event is fresh" in device["reason"]


def test_devices_endpoint_isolates_one_core_data_failure(monkeypatch):
    inventory = [_edgex_device("sensor-failed"), _edgex_device("sensor-ready")]
    now = datetime.now(timezone.utc)

    async def fake_devices():
        return inventory

    async def fake_latest(device_name: str):
        if device_name == "sensor-failed":
            raise EdgeXHTTPStatusError(
                "Core Data timeout",
                operation="events",
                identity=device_name,
                status_code=503,
                retryable=True,
            )
        return [_reading(device_name, now)]

    monkeypatch.setattr(service.edgex, "get_devices", fake_devices)
    monkeypatch.setattr(service.edgex, "get_latest_source_readings", fake_latest)

    with TestClient(app) as client:
        response = client.get("/state/devices")

    assert response.status_code == 200
    by_name = {device["name"]: device for device in response.json()}
    assert by_name["sensor-ready"]["overall_status"] == "available"
    assert by_name["sensor-failed"]["overall_status"] == "degraded"
    assert by_name["sensor-failed"]["telemetry_freshness"] == "no_events"
    assert (
        by_name["sensor-failed"]["telemetry_observation_error"]
        == "EdgeXHTTPStatusError (HTTP 503)"
    )
    assert (
        by_name["sensor-failed"]["reason"]
        == "EdgeX Core Data event observation failed: EdgeXHTTPStatusError"
    )


def test_device_event_queries_share_service_wide_concurrency_limit(tmp_path):
    aggregator = StateAggregatorService(
        Settings(data_dir=tmp_path, edgex_event_query_concurrency=1)
    )
    active = 0
    max_active = 0
    inventory_calls = 0
    event_calls = 0

    async def fake_devices():
        nonlocal inventory_calls
        inventory_calls += 1
        return [_edgex_device(f"sensor-{index}") for index in range(4)]

    async def fake_latest(device_name: str):
        nonlocal active, max_active, event_calls
        event_calls += 1
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.01)
        active -= 1
        return []

    aggregator.edgex.get_devices = fake_devices
    aggregator.edgex.get_latest_source_readings = fake_latest

    async def run_both():
        return await asyncio.gather(
            aggregator.get_devices(),
            aggregator.get_devices(),
        )

    first, second = asyncio.run(run_both())

    assert len(first) == 4
    assert len(second) == 4
    assert max_active == 1
    assert inventory_calls == 1
    assert event_calls == 4


def test_device_snapshot_cache_expires_before_refreshing(tmp_path):
    monotonic_now = [100.0]
    aggregator = StateAggregatorService(
        Settings(
            data_dir=tmp_path,
            edgex_device_snapshot_ttl_seconds=10,
        ),
        monotonic=lambda: monotonic_now[0],
    )
    inventory_calls = 0

    async def fake_devices():
        nonlocal inventory_calls
        inventory_calls += 1
        return [_edgex_device("sensor-01")]

    async def fake_latest(_device_name: str):
        return []

    aggregator.edgex.get_devices = fake_devices
    aggregator.edgex.get_latest_source_readings = fake_latest

    async def exercise_cache():
        await aggregator.get_devices()
        monotonic_now[0] = 109.9
        await aggregator.get_devices()
        monotonic_now[0] = 110.0
        await aggregator.get_devices()

    asyncio.run(exercise_cache())

    assert inventory_calls == 2
    assert aggregator.device_snapshot_diagnostics()["refresh_count"] == 2


def test_device_inventory_failure_uses_backoff_instead_of_retry_storm(tmp_path):
    monotonic_now = [200.0]
    aggregator = StateAggregatorService(
        Settings(
            data_dir=tmp_path,
            edgex_device_error_backoff_seconds=30,
        ),
        monotonic=lambda: monotonic_now[0],
    )
    inventory_calls = 0

    async def failing_devices():
        nonlocal inventory_calls
        inventory_calls += 1
        raise EdgeXBackendError("metadata unavailable", operation="inventory")

    aggregator.edgex.get_devices = failing_devices

    async def exercise_backoff():
        with pytest.raises(EdgeXBackendError):
            await aggregator.get_devices()
        with pytest.raises(EdgeXError):
            await aggregator.get_devices()
        monotonic_now[0] = 230.0
        with pytest.raises(EdgeXBackendError):
            await aggregator.get_devices()

    asyncio.run(exercise_backoff())

    diagnostics = aggregator.device_snapshot_diagnostics()
    assert inventory_calls == 2
    assert diagnostics["refresh_count"] == 2
    assert diagnostics["refresh_failure_count"] == 2


@pytest.mark.parametrize(
    ("admin_state", "operating_state", "freshness", "expected_status"),
    [
        ("LOCKED", "UP", "fresh", "unavailable"),
        ("UNLOCKED", "DOWN", "fresh", "unavailable"),
        ("UNLOCKED", "UNKNOWN", "fresh", "degraded"),
        ("UNLOCKED", "UP", "stale", "degraded"),
        ("UNLOCKED", "UP", "no_events", "degraded"),
        ("UNLOCKED", "UP", "fresh", "available"),
    ],
)
def test_edgex_health_contract(
    admin_state: str,
    operating_state: str,
    freshness: str,
    expected_status: str,
):
    device = DeviceState(
        name="sensor-01",
        profile_name="temperature-profile",
        device_service_name="device-rest",
        admin_state=admin_state,
        operating_state=operating_state,
        connection_state=(
            "connected"
            if operating_state == "UP"
            else "disconnected"
            if operating_state == "DOWN"
            else "unknown"
        ),
        device_service_available=operating_state == "UP",
        telemetry_freshness=freshness,
        node_name=None,
    )

    status, reason = service._device_health(device)

    assert status == expected_status
    assert "EdgeX" in reason or "Core Data" in reason


def test_node_diagnostic_does_not_gate_physical_availability():
    device = service._normalize_edgex_device(
        _edgex_device("sensor-01", node_name="missing-kubernetes-node"),
        [_reading("sensor-01", datetime.now(timezone.utc))],
    )

    assert service._device_health(device)[0] == "available"


def test_edgex_backend_failure_is_not_treated_as_empty_inventory(monkeypatch):
    async def failing_devices():
        raise EdgeXBackendError("Core Metadata unavailable")

    monkeypatch.setattr(service.edgex, "get_devices", failing_devices)

    with pytest.raises(EdgeXBackendError, match="Core Metadata unavailable"):
        asyncio.run(service.get_devices())


def test_dashboard_kpis_use_edgex_connection_service_and_core_data_semantics():
    fresh = DeviceState(
        name="fresh",
        profile_name="profile",
        device_service_name="device-rest",
        admin_state="UNLOCKED",
        operating_state="UP",
        connection_state="connected",
        device_service_available=True,
        telemetry_freshness="fresh",
    )
    down = DeviceState(
        name="down",
        profile_name="profile",
        device_service_name="device-rest",
        admin_state="UNLOCKED",
        operating_state="DOWN",
        connection_state="disconnected",
        device_service_available=False,
        telemetry_freshness="no_events",
    )

    kpis = service._build_dashboard_kpis([], [fresh, down], [])

    assert kpis["available_device_count"] == 1
    assert kpis["unavailable_device_count"] == 1
    assert kpis["edgex_connection_ratio"] == 0.5
    assert kpis["device_service_availability_ratio"] == 0.5
    assert kpis["core_data_freshness_ratio"] == 0.5
    assert kpis["edgex_operating_up_count"] == 1
    assert kpis["edgex_operating_down_count"] == 1
    assert kpis["edgex_operating_unknown_count"] == 0
    assert kpis["edgex_admin_unlocked_count"] == 2
    assert kpis["edgex_admin_locked_count"] == 0
    assert "device_status_freshness_ratio" not in kpis


def test_operator_assistant_uses_edgex_focus_and_actions(monkeypatch):
    async def fake_devices():
        return [_edgex_device("sensor-down", operating_state="DOWN")]

    async def no_events(_device_name: str):
        return []

    async def fake_resource_state(refresh=False):
        return {"summary": {}, "service_resource_profiles": []}

    monkeypatch.setattr(service.edgex, "get_devices", fake_devices)
    monkeypatch.setattr(service.edgex, "get_latest_source_readings", no_events)
    monkeypatch.setattr(service, "get_resource_profile_state", fake_resource_state)

    with TestClient(app) as client:
        response = client.get("/state/operator-assistant")

    assert response.status_code == 200
    payload = response.json()
    assert payload["focus_devices"][0]["operating_state"] == "DOWN"
    assert "EdgeX device service" in " ".join(payload["recommended_actions"])
    serialized = response.text
    assert "mapper" not in serialized
    assert "DeviceStatus" not in serialized


def test_device_telemetry_history_endpoint_returns_edgex_points(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_history(
        device_name: str,
        *,
        offset: int = 0,
        limit: int = 100,
        start=None,
        end=None,
    ):
        assert device_name == "sensor-01"
        assert limit == 2
        assert start is not None
        return [_reading(device_name, now)]

    monkeypatch.setattr(service.edgex, "get_event_history", fake_history)

    with TestClient(app) as client:
        response = client.get("/state/devices/sensor-01/telemetry?window=-10m&limit=2")

    assert response.status_code == 200
    point = response.json()[0]
    assert point["device_name"] == "sensor-01"
    assert point["source_name"] == "temperature"
    assert point["resource_name"] == "Temperature"
    assert point["value_type"] == "Float64"
    assert point["value"] == 24.3


def test_settings_default_to_central_edgex_services(monkeypatch):
    monkeypatch.delenv("EDGEX_CORE_METADATA_URL", raising=False)
    monkeypatch.delenv("EDGEX_CORE_DATA_URL", raising=False)

    settings = Settings()

    assert (
        settings.edgex_core_metadata_url
        == "http://edgex-core-metadata.edgex-system.svc.cluster.local:59881"
    )
    assert (
        settings.edgex_core_data_url
        == "http://edgex-core-data.edgex-system.svc.cluster.local:59880"
    )


def test_settings_disable_optional_influx_recording_by_default(monkeypatch):
    monkeypatch.delenv("RESOURCE_PROFILE_RECORDING_MODE", raising=False)
    monkeypatch.delenv("INFLUXDB_URL", raising=False)

    settings = Settings()

    assert settings.resource_profile_recording_mode == "disabled"
    assert settings.influxdb_url == "http://influxdb:8086"
def test_virtual_device_projection_settings_are_disabled_without_a_binding_path(monkeypatch):
    monkeypatch.delenv("VIRTUAL_DEVICE_PROJECTION_ENABLED", raising=False)
    monkeypatch.delenv("VIRTUAL_DEVICE_BINDINGS_PATH", raising=False)

    settings = Settings()

    assert settings.virtual_device_projection_enabled is False
    assert settings.virtual_device_bindings_path is None


def test_virtual_device_projection_settings_require_a_path_when_enabled():
    with pytest.raises(ValueError, match="virtual_device_bindings_path"):
        Settings(virtual_device_projection_enabled=True)


def test_virtual_device_projection_settings_reject_invalid_boolean_token(monkeypatch):
    monkeypatch.setenv("VIRTUAL_DEVICE_PROJECTION_ENABLED", "tru")
    with pytest.raises(ValueError, match="must be a boolean token"):
        Settings()

def test_projection_service_is_inert_without_enablement():
    disabled = Settings()
    projection = StateAggregatorService(disabled)

    assert projection.bindings is None
    assert projection._projection_observation is None
def test_enabled_virtual_detail_unknown_id_short_circuits_authority_calls(tmp_path):
    bindings = VirtualDeviceBindingConfig.model_validate({
        "apiVersion": "virtual-device-binding/v1",
        "instances": [{
            "id": "configured",
            "physicalDeviceRef": {"name": "device", "expectedProfileName": "profile"},
            "capabilities": [{
                "id": "capability", "freshnessSeconds": 60,
                "inputs": [{
                    "inputId": "input", "capabilityField": "field", "required": True,
                    "bindings": [{"sourceName": "source", "resourceName": "resource"}],
                    "acceptedValueTypes": ["Float64"], "acceptedUnits": ["Cel"],
                }],
            }],
            "aiServiceRef": {
                "serviceId": "ai", "inputContract": "ai/v1",
                "bindingMode": "declarative_read_only",
                "inputFieldMap": [{"inputId": "input", "aiField": "field"}],
            },
        }],
    })

    class NoAuthority:
        calls = 0

        async def get_devices(self):
            self.calls += 1
            raise AssertionError("unknown configured ID must not query EdgeX")

    projection_settings = Settings(
        data_dir=tmp_path, virtual_device_projection_enabled=True,
        virtual_device_bindings_path=tmp_path / "bindings.json",
    )
    projection = StateAggregatorService(
        projection_settings, edgex=NoAuthority(), bindings=bindings,
    )

    async def no_op():
        return None

    projection.start = no_op
    projection.stop = no_op
    with TestClient(create_app(projection_settings, dependencies={"service": projection})) as client:
        response = client.get("/state/virtual-devices/not-configured")

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "virtual_device_not_configured"
    assert projection.edgex.calls == 0


def _projection_bindings(*, include_second: bool = False) -> VirtualDeviceBindingConfig:
    def instance(identifier: str, device_name: str, profile_name: str) -> dict:
        return {
            "id": identifier,
            "physicalDeviceRef": {
                "name": device_name,
                "expectedProfileName": profile_name,
            },
            "capabilities": [
                {
                    "id": "vibration",
                    "freshnessSeconds": 90,
                    "inputs": [
                        {
                            "inputId": f"{identifier}.acceleration-x",
                            "capabilityField": "acceleration_x",
                            "required": True,
                            "bindings": [
                                {
                                    "sourceName": "telemetry",
                                    "resourceName": "acceleration_x",
                                }
                            ],
                            "acceptedValueTypes": ["Float64"],
                            "acceptedUnits": ["g"],
                        }
                    ],
                }
            ],
            "aiServiceRef": {
                "serviceId": "pump-anomaly-v1",
                "inputContract": "pump-anomaly-input/v1",
                "bindingMode": "declarative_read_only",
                "inputFieldMap": [
                    {
                        "inputId": f"{identifier}.acceleration-x",
                        "aiField": "accel_x",
                    }
                ],
            },
        }

    instances = [instance("virtual-one", "device-one", "profile-one")]
    if include_second:
        instances.append(instance("virtual-two", "device-two", "profile-two"))
    return VirtualDeviceBindingConfig.model_validate(
        {
            "apiVersion": "virtual-device-binding/v1",
            "instances": instances,
        }
    )


def _projection_point(
    now: datetime,
    *,
    device_name: str,
    profile_name: str,
    event_id: str,
) -> TelemetryPoint:
    return TelemetryPoint(
        device_name=device_name,
        profile_name=profile_name,
        source_name="telemetry",
        resource_name="acceleration_x",
        value_type="Float64",
        value=1.25,
        timestamp=now,
        origin=2,
        event_id=event_id,
        event_origin=1,
        reading_origin=2,
        units="g",
    )


def _projection_service(
    tmp_path,
    edgex,
    bindings: VirtualDeviceBindingConfig,
    now: datetime,
) -> tuple[Settings, StateAggregatorService]:
    settings = Settings(
        data_dir=tmp_path,
        virtual_device_projection_enabled=True,
        virtual_device_bindings_path=tmp_path / "bindings.json",
    )
    projection = StateAggregatorService(
        settings,
        edgex=edgex,
        bindings=bindings,
        clock=lambda: now,
    )

    async def no_op():
        return None

    projection.start = no_op
    projection.stop = no_op
    return settings, projection


def test_enabled_projection_list_and_detail_preserve_revision_and_provenance(tmp_path):
    now = datetime.now(timezone.utc)

    class Authority:
        async def get_devices(self):
            return [
                EdgeXDevice(
                    name="device-one",
                    profile_name="profile-one",
                    device_service_name="device-serial",
                    admin_state="UNLOCKED",
                    operating_state="UP",
                )
            ]

        async def get_device_profile(self, profile_name):
            assert profile_name == "profile-one"
            return EdgeXDeviceProfile(
                name=profile_name,
                device_resources=[EdgeXDeviceResource(name="acceleration_x")],
            )

        async def get_bounded_event_history(self, device_name, **kwargs):
            assert device_name == "device-one"
            return EventHistoryPage(
                total_count=1,
                events=[
                    _projection_point(
                        now,
                        device_name=device_name,
                        profile_name="profile-one",
                        event_id="event-one",
                    )
                ],
            )

    bindings = _projection_bindings()
    settings, projection = _projection_service(tmp_path, Authority(), bindings, now)

    with TestClient(create_app(settings, dependencies={"service": projection})) as client:
        collection_response = client.get("/state/virtual-devices")
        detail_response = client.get("/state/virtual-devices/virtual-one")
        metrics_response = client.get("/metrics")

    assert (
        collection_response.json()["items"][0]["physical_device_ref"]
        == {
            "name": "device-one",
            "expected_profile_name": "profile-one",
            "actual_profile_name": "profile-one",
            "device_service_name": "device-serial",
            "admin_state": "UNLOCKED",
            "operating_state": "UP",
            "node_name": None,
            "profile_resolved": True,
        }
    )
    assert collection_response.status_code == 200
    collection = collection_response.json()
    detail = detail_response.json()
    assert detail_response.status_code == 200
    assert collection["config_revision"] == detail["config_revision"]
    assert collection["items"][0]["binding_status"] == "ready"
    event_ref = detail["capabilities"][0]["inputs"][0]["original_event_ref"]
    assert event_ref == {
        "event_id": "event-one",
        "event_origin": 1,
        "reading_origin": 2,
        "device_name": "device-one",
        "profile_name": "profile-one",
        "source_name": "telemetry",
        "resource_name": "acceleration_x",
    }
    assert "edge_orch_virtual_device_observation_up{} 0.0" in metrics_response.text


@pytest.mark.parametrize(
    ("operation", "status_code", "expected_code"),
    [
        ("inventory", 403, "authority_access_denied"),
        ("inventory", 503, "authority_inventory_unavailable"),
        ("profile", 503, "authority_profile_unavailable"),
        ("events", 503, "authority_event_unavailable"),
    ],
)
def test_projection_detail_maps_authority_failures(
    tmp_path,
    operation,
    status_code,
    expected_code,
):
    now = datetime.now(timezone.utc)

    class FailingAuthority:
        async def get_devices(self):
            if operation == "inventory":
                raise EdgeXHTTPStatusError(
                    "failed",
                    operation=operation,
                    status_code=status_code,
                    retryable=status_code >= 500,
                )
            return [
                EdgeXDevice(
                    name="device-one",
                    profile_name="profile-one",
                    device_service_name="device-serial",
                    admin_state="UNLOCKED",
                    operating_state="UP",
                )
            ]

        async def get_device_profile(self, profile_name):
            if operation == "profile":
                raise EdgeXHTTPStatusError(
                    "failed",
                    operation=operation,
                    identity=profile_name,
                    status_code=status_code,
                    retryable=True,
                )
            return EdgeXDeviceProfile(
                name=profile_name,
                device_resources=[EdgeXDeviceResource(name="acceleration_x")],
            )

        async def get_bounded_event_history(self, device_name, **kwargs):
            raise EdgeXHTTPStatusError(
                "failed",
                operation="events",
                identity=device_name,
                status_code=status_code,
                retryable=True,
            )

    settings, projection = _projection_service(
        tmp_path,
        FailingAuthority(),
        _projection_bindings(),
        now,
    )

    with TestClient(create_app(settings, dependencies={"service": projection})) as client:
        response = client.get("/state/virtual-devices/virtual-one")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == expected_code
    assert response.json()["detail"]["operation"] == operation
    expected_identity = {
        "inventory": None,
        "profile": "profile-one",
        "events": "device-one",
    }[operation]
    assert response.json()["detail"]["identity"] == expected_identity


@pytest.mark.parametrize(
    ("operation", "status_code", "expected_code"),
    [
        ("inventory", 403, "authority_access_denied"),
        ("inventory", 503, "authority_inventory_unavailable"),
        ("profile", 503, "authority_profile_unavailable"),
        ("events", 503, "authority_event_unavailable"),
    ],
)
def test_projection_list_maps_total_authority_failures(
    tmp_path,
    operation,
    status_code,
    expected_code,
):
    now = datetime.now(timezone.utc)

    def failure(identity=None):
        return EdgeXHTTPStatusError(
            "failed",
            operation=operation,
            identity=identity,
            status_code=status_code,
            retryable=status_code >= 500,
        )

    class FailingAuthority:
        async def get_devices(self):
            if operation == "inventory":
                raise failure()
            return [
                EdgeXDevice(
                    name="device-one",
                    profile_name="profile-one",
                    device_service_name="device-serial",
                    admin_state="UNLOCKED",
                    operating_state="UP",
                )
            ]

        async def get_device_profile(self, profile_name):
            if operation == "profile":
                raise failure(profile_name)
            return EdgeXDeviceProfile(
                name=profile_name,
                device_resources=[EdgeXDeviceResource(name="acceleration_x")],
            )

        async def get_bounded_event_history(self, device_name, **kwargs):
            if operation == "events":
                raise failure(device_name)
            return EventHistoryPage(
                total_count=1,
                events=[
                    _projection_point(
                        now,
                        device_name=device_name,
                        profile_name="profile-one",
                        event_id="event-one",
                    )
                ],
            )

    settings, projection = _projection_service(
        tmp_path, FailingAuthority(), _projection_bindings(), now
    )

    with TestClient(
        create_app(settings, dependencies={"service": projection})
    ) as client:
        response = client.get("/state/virtual-devices")

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == expected_code
    assert response.json()["detail"]["operation"] == operation


def test_projection_list_preserves_healthy_sibling_during_partial_profile_failure(tmp_path):
    now = datetime.now(timezone.utc)

    class PartialAuthority:
        async def get_devices(self):
            return [
                EdgeXDevice(
                    name="device-one",
                    profile_name="profile-one",
                    device_service_name="device-serial",
                    admin_state="UNLOCKED",
                    operating_state="UP",
                ),
                EdgeXDevice(
                    name="device-two",
                    profile_name="profile-two",
                    device_service_name="device-serial",
                    admin_state="UNLOCKED",
                    operating_state="UP",
                ),
            ]

        async def get_device_profile(self, profile_name):
            if profile_name == "profile-two":
                raise EdgeXHTTPStatusError(
                    "failed",
                    operation="profile",
                    identity=profile_name,
                    status_code=503,
                    retryable=True,
                )
            return EdgeXDeviceProfile(
                name=profile_name,
                device_resources=[EdgeXDeviceResource(name="acceleration_x")],
            )

        async def get_bounded_event_history(self, device_name, **kwargs):
            return EventHistoryPage(
                total_count=1,
                events=[
                    _projection_point(
                        now,
                        device_name=device_name,
                        profile_name="profile-one",
                        event_id="event-one",
                    )
                ],
            )

    settings, projection = _projection_service(
        tmp_path,
        PartialAuthority(),
        _projection_bindings(include_second=True),
        now,
    )

    with TestClient(create_app(settings, dependencies={"service": projection})) as client:
        list_response = client.get("/state/virtual-devices")
        failed_detail = client.get("/state/virtual-devices/virtual-two")

    assert list_response.status_code == 200
    payload = list_response.json()
    by_id = {item["id"]: item for item in payload["items"]}
    assert by_id["virtual-one"]["binding_status"] == "ready"
    assert by_id["virtual-two"]["reason_codes"] == ["upstream_profile_error"]
    assert payload["observation_error"]["code"] == "authority_profile_unavailable"
    assert payload["observation_error"]["identity"] == "profile-two"
    assert failed_detail.status_code == 503
    assert failed_detail.json()["detail"]["code"] == "authority_profile_unavailable"


def test_projection_observer_clears_stale_readiness_after_authority_failure(tmp_path):
    now = datetime.now(timezone.utc)

    class Authority:
        async def get_devices(self):
            return [
                EdgeXDevice(
                    name="device-one",
                    profile_name="profile-one",
                    device_service_name="device-serial",
                    admin_state="UNLOCKED",
                    operating_state="UP",
                )
            ]

        async def get_device_profile(self, profile_name):
            return EdgeXDeviceProfile(
                name=profile_name,
                device_resources=[EdgeXDeviceResource(name="acceleration_x")],
            )

        async def get_bounded_event_history(self, device_name, **kwargs):
            return EventHistoryPage(
                total_count=1,
                events=[
                    _projection_point(
                        now,
                        device_name=device_name,
                        profile_name="profile-one",
                        event_id="event-one",
                    )
                ],
            )

    settings, projection = _projection_service(
        tmp_path, Authority(), _projection_bindings(), now
    )
    asyncio.run(projection.record_virtual_device_observation())
    successful = projection._projection_observation

    assert successful is not None
    assert successful.binding_ready == {"virtual-one": True}
    assert successful.capability_ready == {
        "virtual-one": {"vibration": True}
    }
    assert successful.input_fresh == {
        "virtual-one": {
            "vibration": {
                "virtual-one.acceleration-x": True,
            }
        }
    }
    with TestClient(
        create_app(settings, dependencies={"service": projection})
    ) as client:
        successful_metrics = client.get("/metrics").text

    assert (
        'edge_orch_virtual_device_capability_ready{virtual_device_id="virtual-one",capability_id="vibration"} 1.0'
        in successful_metrics
    )
    assert (
        'edge_orch_virtual_device_input_fresh{virtual_device_id="virtual-one",capability_id="vibration",input_id="virtual-one.acceleration-x"} 1.0'
        in successful_metrics
    )

    async def fail_inventory():
        raise EdgeXBackendError("authority unavailable")

    projection.edgex.get_devices = fail_inventory
    asyncio.run(projection.record_virtual_device_observation())
    failed = projection._projection_observation

    assert failed is not None
    assert failed.error_class == "EdgeXBackendError"
    assert failed.last_success_at == successful.last_success_at
    assert failed.binding_ready == {}
    assert failed.capability_ready == {}
    assert failed.input_fresh == {}

    with TestClient(
        create_app(settings, dependencies={"service": projection})
    ) as client:
        response = client.get("/metrics")

    assert response.status_code == 200
    assert "edge_orch_virtual_device_observation_up{} 0.0" in response.text
    assert (
        'edge_orch_virtual_device_observation_error{reason="EdgeXBackendError"} 1.0'
        in response.text
    )
    assert 'edge_orch_virtual_device_binding_ready{virtual_device_id=' not in response.text


def test_binding_event_query_can_lower_operational_history_budgets(tmp_path):
    now = datetime.now(timezone.utc)
    document = _projection_bindings().model_dump(mode="json", by_alias=True)
    document["eventQuery"] = {
        "pageSize": 7,
        "maxPages": 2,
        "maxEventsPerDevice": 11,
        "maxPriorProbeEventsPerDevice": 3,
    }
    bindings = VirtualDeviceBindingConfig.model_validate(document)

    class Authority:
        history_kwargs = None

        async def get_devices(self):
            return [
                EdgeXDevice(
                    name="device-one",
                    profile_name="profile-one",
                    device_service_name="device-serial",
                    admin_state="UNLOCKED",
                    operating_state="UP",
                )
            ]

        async def get_device_profile(self, profile_name):
            return EdgeXDeviceProfile(
                name=profile_name,
                device_resources=[EdgeXDeviceResource(name="acceleration_x")],
            )

        async def get_bounded_event_history(self, device_name, **kwargs):
            self.history_kwargs = kwargs
            return EventHistoryPage(
                total_count=1,
                events=[
                    _projection_point(
                        now,
                        device_name=device_name,
                        profile_name="profile-one",
                        event_id="event-one",
                    )
                ],
            )

    authority = Authority()
    settings, projection = _projection_service(tmp_path, authority, bindings, now)
    asyncio.run(projection.get_virtual_devices())

    assert authority.history_kwargs == {
        "observation_time": now,
        "freshness_seconds": 90,
        "page_size": 7,
        "max_pages": 2,
        "max_events_per_device": 11,
        "max_prior_probe_events_per_device": 3,
    }


def test_global_app_enabled_lifespan_loads_bindings_before_start(
    monkeypatch, tmp_path
):
    path = tmp_path / "bindings.json"
    path.write_text(
        _projection_bindings().model_dump_json(by_alias=True),
        encoding="utf-8",
    )
    enabled_settings = Settings(
        data_dir=tmp_path,
        virtual_device_projection_enabled=True,
        virtual_device_bindings_path=path,
    )
    enabled_service = StateAggregatorService(enabled_settings)
    started_with_bindings = False

    async def start():
        nonlocal started_with_bindings
        started_with_bindings = enabled_service.bindings is not None

    async def stop():
        return None

    enabled_service.start = start
    enabled_service.stop = stop
    monkeypatch.setattr(main_module, "settings", enabled_settings)
    monkeypatch.setattr(main_module, "service", enabled_service)

    with TestClient(main_module.app):
        pass

    assert started_with_bindings is True
    assert enabled_service.bindings == _projection_bindings()


def test_global_projection_route_uses_typed_authority_error_mapping(
    monkeypatch, tmp_path
):
    enabled_settings = Settings(
        data_dir=tmp_path,
        virtual_device_projection_enabled=True,
        virtual_device_bindings_path=tmp_path / "bindings.json",
    )
    enabled_service = StateAggregatorService(
        enabled_settings,
        bindings=_projection_bindings(),
    )

    async def fail_inventory():
        raise EdgeXHTTPStatusError(
            "denied",
            operation="inventory",
            status_code=403,
            retryable=False,
        )

    async def start():
        return None

    async def stop():
        return None

    enabled_service.edgex.get_devices = fail_inventory
    enabled_service.start = start
    enabled_service.stop = stop
    monkeypatch.setattr(main_module, "settings", enabled_settings)
    monkeypatch.setattr(main_module, "service", enabled_service)

    with TestClient(main_module.app) as client:
        response = client.get("/state/virtual-devices")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "authority_access_denied",
        "upstream": "edgex",
        "operation": "inventory",
        "identity": None,
        "retryable": False,
        "status_code": 403,
    }


def test_profile_mismatch_short_circuits_profile_and_event_reads(tmp_path):
    now = datetime.now(timezone.utc)

    class Authority:
        profile_calls = 0
        event_calls = 0

        async def get_devices(self):
            return [
                EdgeXDevice(
                    name="device-one",
                    profile_name="unexpected-profile",
                    device_service_name="device-serial",
                    admin_state="UNLOCKED",
                    operating_state="UP",
                )
            ]

        async def get_device_profile(self, profile_name):
            self.profile_calls += 1
            raise AssertionError("profile mismatch must short-circuit profile reads")

        async def get_bounded_event_history(self, device_name, **kwargs):
            self.event_calls += 1
            raise AssertionError("profile mismatch must short-circuit Event reads")

    authority = Authority()
    settings, projection = _projection_service(
        tmp_path, authority, _projection_bindings(), now
    )

    with TestClient(
        create_app(settings, dependencies={"service": projection})
    ) as client:
        response = client.get("/state/virtual-devices")

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["binding_status"] == "unresolved"
    assert item["reason_codes"] == ["profile_mismatch"]
    assert authority.profile_calls == 0
    assert authority.event_calls == 0


def test_shared_physical_device_uses_one_bounded_history_scan(tmp_path):
    now = datetime.now(timezone.utc)
    document = _projection_bindings(
        include_second=True
    ).model_dump(mode="json", by_alias=True)
    second = document["instances"][1]
    second["physicalDeviceRef"] = {
        "name": "device-one",
        "expectedProfileName": "profile-one",
    }
    bindings = VirtualDeviceBindingConfig.model_validate(document)

    class Authority:
        history_calls = 0

        async def get_devices(self):
            return [
                EdgeXDevice(
                    name="device-one",
                    profile_name="profile-one",
                    device_service_name="device-serial",
                    admin_state="UNLOCKED",
                    operating_state="UP",
                )
            ]

        async def get_device_profile(self, profile_name):
            return EdgeXDeviceProfile(
                name=profile_name,
                device_resources=[EdgeXDeviceResource(name="acceleration_x")],
            )

        async def get_bounded_event_history(self, device_name, **kwargs):
            self.history_calls += 1
            return EventHistoryPage(
                total_count=1,
                events=[
                    _projection_point(
                        now,
                        device_name=device_name,
                        profile_name="profile-one",
                        event_id="event-one",
                    )
                ],
            )

    authority = Authority()
    settings, projection = _projection_service(
        tmp_path, authority, bindings, now
    )
    collection = asyncio.run(projection.get_virtual_devices())

    assert authority.history_calls == 1
    assert [item.binding_status for item in collection.items] == [
        "ready",
        "ready",
    ]


def test_shared_scan_keeps_ready_sibling_when_other_binding_is_truncated(tmp_path):
    now = datetime.now(timezone.utc)
    document = _projection_bindings(
        include_second=True
    ).model_dump(mode="json", by_alias=True)
    second = document["instances"][1]
    second["physicalDeviceRef"] = {
        "name": "device-one",
        "expectedProfileName": "profile-one",
    }
    second["capabilities"][0]["inputs"][0]["bindings"] = [
        {"sourceName": "telemetry", "resourceName": "missing_resource"}
    ]
    bindings = VirtualDeviceBindingConfig.model_validate(document)

    class Authority:
        history_calls = 0
        prior_calls = 0

        async def get_devices(self):
            return [
                EdgeXDevice(
                    name="device-one",
                    profile_name="profile-one",
                    device_service_name="device-serial",
                    admin_state="UNLOCKED",
                    operating_state="UP",
                )
            ]

        async def get_device_profile(self, profile_name):
            return EdgeXDeviceProfile(
                name=profile_name,
                device_resources=[
                    EdgeXDeviceResource(name="acceleration_x"),
                    EdgeXDeviceResource(name="missing_resource"),
                ],
            )

        async def get_bounded_event_history(self, device_name, **kwargs):
            self.history_calls += 1
            return EventHistoryPage(
                total_count=1,
                events=[
                    _projection_point(
                        now,
                        device_name=device_name,
                        profile_name="profile-one",
                        event_id="event-one",
                    )
                ],
            )

        async def get_prior_event_history(self, device_name, **kwargs):
            self.prior_calls += 1
            return EventHistoryPage(
                total_count=2,
                events=[],
                events_scanned=0,
                history_truncated=True,
            )

    authority = Authority()
    settings, projection = _projection_service(
        tmp_path, authority, bindings, now
    )
    collection = asyncio.run(projection.get_virtual_devices())
    by_id = {item.id: item for item in collection.items}

    assert authority.history_calls == 1
    assert authority.prior_calls == 1
    assert by_id["virtual-one"].binding_status == "ready"
    assert by_id["virtual-one"].history_truncated is False
    assert by_id["virtual-two"].binding_status == "degraded"
    assert by_id["virtual-two"].reason_codes == ["history_truncated"]

def test_undeclared_fresh_alias_does_not_suppress_declared_prior_probe(tmp_path):
    now = datetime.now(timezone.utc)
    document = _projection_bindings().model_dump(mode="json", by_alias=True)
    document["instances"][0]["capabilities"][0]["inputs"][0]["bindings"] = [
        {"sourceName": "primary", "resourceName": "undeclared"},
        {"sourceName": "telemetry", "resourceName": "acceleration_x"},
    ]
    bindings = VirtualDeviceBindingConfig.model_validate(document)

    class Authority:
        prior_calls = 0

        async def get_devices(self):
            return [
                EdgeXDevice(
                    name="device-one",
                    profile_name="profile-one",
                    device_service_name="device-serial",
                    admin_state="UNLOCKED",
                    operating_state="UP",
                )
            ]

        async def get_device_profile(self, profile_name):
            return EdgeXDeviceProfile(
                name=profile_name,
                device_resources=[
                    EdgeXDeviceResource(name="acceleration_x"),
                ],
            )

        async def get_bounded_event_history(self, device_name, **kwargs):
            point = _projection_point(
                now,
                device_name=device_name,
                profile_name="profile-one",
                event_id="fresh-undeclared",
            ).model_copy(
                update={
                    "source_name": "primary",
                    "resource_name": "",
                }
            )
            return EventHistoryPage(total_count=1, events=[point])

        async def get_prior_event_history(self, device_name, **kwargs):
            self.prior_calls += 1
            point = _projection_point(
                now - timedelta(seconds=120),
                device_name=device_name,
                profile_name="profile-one",
                event_id="prior-declared",
            )
            return EventHistoryPage(total_count=1, events=[point])

    authority = Authority()
    _, projection = _projection_service(tmp_path, authority, bindings, now)
    collection = asyncio.run(projection.get_virtual_devices())

    assert authority.prior_calls == 1
    assert collection.items[0].binding_status == "degraded"
    assert collection.items[0].reason_codes == ["stale"]
