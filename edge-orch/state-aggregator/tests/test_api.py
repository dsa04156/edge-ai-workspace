from datetime import datetime, timezone
import asyncio
import pytest

import httpx
from fastapi.testclient import TestClient

from app.main import app, service
from app.config import Settings
from app.service import StateAggregatorService
from app.edgex import EdgeXBackendError
from app.models import DeviceState, EdgeXDevice, NodeState, TelemetryPoint, WorkflowState


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


def test_cost_model_endpoint_returns_snapshot():
    with TestClient(app) as client:
        response = client.get("/state/cost-model")

    assert response.status_code == 200
    payload = response.json()
    assert "node_states" in payload
    assert "stage_cost_stats" in payload
    assert "migration_cost_stats" in payload


def test_virtual_device_routes_are_not_registered():
    with TestClient(app) as client:
        response = client.get("/state/virtual-devices")

    assert response.status_code == 404


def test_resource_profile_endpoints_return_service_requirement_profiles(monkeypatch):
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

    monkeypatch.setattr(service.prometheus, "collect_service_resource_usage", fake_collect_usage)
    service._service_resource_profiles = []

    with TestClient(app) as client:
        profile_response = client.get("/state/resource-profiles?refresh=true")
        service_response = client.get("/state/service-resource-profiles?service=redis")

    assert profile_response.status_code == 200
    profile_payload = profile_response.json()
    assert set(profile_payload) == {
        "generated_at",
        "profile_scope",
        "summary",
        "service_resource_profiles",
    }
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
    assert set(service_payload) == {
        "generated_at",
        "profile_scope",
        "summary",
        "service_resource_profiles",
    }

    with TestClient(app) as client:
        record_response = client.post("/state/service-resource-profiles/record?window=10m")

    assert record_response.status_code == 404


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
                            "pod": "gpu-inference-abc",
                            "container": "runtime",
                            "node": "etri-ser0002-cgnmsb",
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


def test_virtual_resources_endpoint_scopes_instances_to_registry_node(monkeypatch):
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
                            "pod": "gpu-server-abc",
                            "container": "runtime",
                            "node": "etri-ser0002-cgnmsb",
                        },
                        {
                            "pod": "gpu-jetson-abc",
                            "container": "runtime",
                            "node": "etri-dev0001-jetorn",
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
    assert [item["pod"] for item in server_gpu["instances"]] == ["gpu-server-abc"]
    assert [item["pod"] for item in jetson_gpu["instances"]] == ["gpu-jetson-abc"]


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


def test_service_start_schedules_only_prometheus_poller(monkeypatch, tmp_path):
    import app.service as service_module

    created_tasks = []

    def fake_create_task(coroutine):
        created_tasks.append(coroutine.cr_code.co_name)
        coroutine.close()
        return asyncio.Future()

    settings = Settings(data_dir=tmp_path)
    aggregator = StateAggregatorService(settings)
    monkeypatch.setattr(service_module.asyncio, "create_task", fake_create_task)

    asyncio.run(aggregator.start())

    assert created_tasks == ["_poll_prometheus"]


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
    assert "Never expose chain-of-thought" in calls[0]["json"]["messages"][0]["content"]


def test_operator_chat_extracts_final_answer_without_reasoning():
    aggregator = StateAggregatorService(Settings())
    payload = {
        "choices": [{
            "message": {
                "content": (
                    "Here's a thinking process:\n"
                    "1. Analyze the dashboard.\n"
                    "2. Compare the constraints.\n"
                    "3. **Draft:**\n"
                    "현재 장비 이벤트는 최신 상태입니다. Core Data 시각을 먼저 확인하세요.\n"
                    "4. **Check against constraints:** read only"
                ),
                "reasoning_content": "private chain of thought",
            },
        }],
    }

    answer = aggregator._extract_chat_answer(payload)

    assert answer == "현재 장비 이벤트는 최신 상태입니다. Core Data 시각을 먼저 확인하세요."
    assert "thinking process" not in answer
    assert "private chain" not in answer


def test_operator_chat_does_not_fallback_to_reasoning_content():
    aggregator = StateAggregatorService(Settings())

    answer = aggregator._extract_chat_answer({
        "choices": [{"message": {"content": "", "reasoning_content": "private reasoning"}}],
    })

    assert answer == ""


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
        tags={
            **({"nodeName": node_name} if node_name else {}),
            "physicalDeviceId": "physical-sensor-01",
            "hardwareBindingId": "edge-sensor-binding-01",
        },
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
    assert device["physical_device_id"] == "physical-sensor-01"
    assert device["hardware_binding_id"] == "edge-sensor-binding-01"
    assert device["connection_state"] == "connected"
    assert device["device_service_available"] is True
    assert device["telemetry_freshness"] == "fresh"
    assert device["latest_readings"][0]["resource_name"] == "Temperature"
    assert device["overall_status"] == "available"
    assert "Core Data event is fresh" in device["reason"]


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


def test_settings_have_no_influx_recording_contract():
    settings = Settings()

    for attribute in (
        "influxdb_url",
        "influxdb_org",
        "influxdb_bucket",
        "influxdb_token",
        "resource_profile_recording_mode",
        "resource_profile_window",
        "resource_profile_record_interval_seconds",
    ):
        assert not hasattr(settings, attribute)
