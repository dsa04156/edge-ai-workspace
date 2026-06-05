from datetime import datetime, timedelta, timezone
import asyncio

from fastapi.testclient import TestClient

from app.main import app, service
from app.config import Settings
from app.service import StateAggregatorService
from app.influx import InfluxTelemetryClient, TelemetrySample
from app.kube import KubeClient
from app.models import DeviceState, NodeState, WorkflowState


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
    assert calls[0]["url"] == "http://192.168.0.6:8000/v1/chat/completions"
    assert calls[0]["json"]["model"] == "qwen3.6-35b"
    assert calls[0]["json"]["messages"][0]["role"] == "system"
    assert "read-only" in calls[0]["json"]["messages"][0]["content"]


def test_dashboard_endpoint_combines_nodes_and_devices(monkeypatch):
    service.store.nodes = {
        "etri-dev0001-jetorn": NodeState(
            hostname="etri-dev0001-jetorn",
            instance="192.168.0.3:9100",
            node_type="edge_ai_device",
            collected_at=datetime.now(timezone.utc),
            raw_metrics={
                "up": 1.0,
                "cpu_utilization": 0.33,
                "memory_usage_ratio": 0.41,
                "load_average": 1.1,
                "network_rx_rate": 500.0,
                "network_tx_rate": 450.0,
            },
            compute_pressure="low",
            memory_pressure="low",
            network_pressure="low",
            node_health="healthy",
        )
    }

    async def fake_devices():
        return [
            {
                "metadata": {"name": "env-device-01", "namespace": "default"},
                "spec": {
                    "deviceModelRef": {"name": "virtual-env-model"},
                    "nodeName": "etri-dev0001-jetorn",
                        "properties": [
                            {
                                "name": "temperature",
                                "reportToCloud": False,
                                "pushMethod": {"dbMethod": {"influxdb2": {}}},
                            }
                        ],
                    "protocol": {"protocolName": "mqttvirtual"},
                },
                "status": {
                    "twins": {
                        "temperature": {
                            "actual": {"value": "24.1"},
                        }
                    }
                },
            }
        ]

    async def fake_mapper_nodes():
        return {"etri-dev0001-jetorn"}

    async def fake_device_statuses():
        return []

    async def fake_telemetry_samples():
        return {
            "env-device-01": TelemetrySample(
                device_id="env-device-01",
                timestamp=datetime.now(timezone.utc),
                property="temperature",
                value="24.1",
            )
        }

    monkeypatch.setattr(service.kube, "get_devices", fake_devices)
    monkeypatch.setattr(service.kube, "get_device_statuses", fake_device_statuses)
    monkeypatch.setattr(service.kube, "get_running_mapper_nodes", fake_mapper_nodes)
    monkeypatch.setattr(service.telemetry, "get_latest_by_device", fake_telemetry_samples)

    with TestClient(app) as client:
        response = client.get("/state/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kpis"]["active_node_count"] == 1
    assert payload["kpis"]["registered_device_count"] == 1
    assert payload["kpis"]["telemetry_device_count"] == 1
    assert payload["devices"][0]["name"] == "env-device-01"
    assert payload["devices"][0]["service_connected"] is True
    assert payload["devices"][0]["service_demo_group"] == "환경 상태 모니터링"
    assert payload["devices"][0]["service_binding_source"] == "device_name_pattern"
    assert payload["devices"][0]["service_binding_reason"] == "device name includes environment service keyword"
    assert "services" not in payload


def test_dashboard_endpoint_merges_kubeedge_device_status(monkeypatch):
    service.store.nodes = {
        "etri-dev0001-jetorn": NodeState(
            hostname="etri-dev0001-jetorn",
            instance="192.168.0.3:9100",
            node_type="edge_ai_device",
            collected_at=datetime.now(timezone.utc),
            raw_metrics={
                "up": 1.0,
                "cpu_utilization": 0.2,
                "memory_usage_ratio": 0.3,
                "load_average": 0.8,
                "network_rx_rate": 100.0,
                "network_tx_rate": 90.0,
            },
            compute_pressure="low",
            memory_pressure="low",
            network_pressure="low",
            node_health="healthy",
        )
    }

    async def fake_devices():
        return [
            {
                "metadata": {"name": "env-device-01", "namespace": "default"},
                "spec": {
                    "deviceModelRef": {"name": "virtual-env-model"},
                    "nodeName": "etri-dev0001-jetorn",
                    "properties": [
                        {
                            "name": "health",
                            "reportToCloud": True,
                            "pushMethod": {"dbMethod": {"influxdb2": {}}},
                        }
                    ],
                    "protocol": {"protocolName": "mqttvirtual"},
                },
                "status": {"reportToCloud": False, "reportCycle": 60000},
            }
        ]

    async def fake_device_statuses():
        return [
            {
                "metadata": {"name": "env-device-01", "namespace": "default"},
                "status": {
                    "state": "online",
                    "lastOnlineTime": datetime.now(timezone.utc).isoformat(),
                    "twins": [
                        {
                            "propertyName": "health",
                            "reported": {"value": "ok"},
                            "observedDesired": {"value": ""},
                        }
                    ],
                },
            }
        ]

    async def fake_mapper_nodes():
        return {"etri-dev0001-jetorn"}

    async def fake_telemetry_samples():
        return {}

    monkeypatch.setattr(service.kube, "get_devices", fake_devices)
    monkeypatch.setattr(service.kube, "get_device_statuses", fake_device_statuses)
    monkeypatch.setattr(service.kube, "get_running_mapper_nodes", fake_mapper_nodes)
    monkeypatch.setattr(service.telemetry, "get_latest_by_device", fake_telemetry_samples)

    with TestClient(app) as client:
        response = client.get("/state/dashboard")

    assert response.status_code == 200
    device = response.json()["devices"][0]
    assert device["status"] == "degraded"
    assert device["status_reason"] == "latest telemetry sample is missing"
    assert device["device_status_fresh"] is True
    assert device["telemetry_fresh"] is False
    assert device["twin"]["health"]["reported"]["value"] == "ok"


def test_fresh_twin_timestamp_overrides_stale_last_online_time(monkeypatch):
    service.store.nodes = {
        "etri-dev0001-jetorn": NodeState(
            hostname="etri-dev0001-jetorn",
            instance="192.168.0.3:9100",
            node_type="edge_ai_device",
            collected_at=datetime.now(timezone.utc),
            raw_metrics={
                "up": 1.0,
                "cpu_utilization": 0.2,
                "memory_usage_ratio": 0.3,
                "load_average": 0.8,
                "network_rx_rate": 100.0,
                "network_tx_rate": 90.0,
            },
            compute_pressure="low",
            memory_pressure="low",
            network_pressure="low",
            node_health="healthy",
        )
    }
    fresh_twin_timestamp_ms = str(int(datetime.now(timezone.utc).timestamp() * 1000))

    async def fake_devices():
        return [
            {
                "metadata": {"name": "act-device-06", "namespace": "default"},
                "spec": {
                    "deviceModelRef": {"name": "virtual-act-model"},
                    "nodeName": "etri-dev0001-jetorn",
                    "properties": [
                        {
                            "name": "health",
                            "reportToCloud": True,
                            "pushMethod": {"dbMethod": {"influxdb2": {}}},
                        }
                    ],
                    "protocol": {"protocolName": "mqttvirtual"},
                },
                "status": {"reportToCloud": True, "reportCycle": 30000},
            }
        ]

    async def fake_device_statuses():
        return [
            {
                "metadata": {"name": "act-device-06", "namespace": "default"},
                "status": {
                    "lastOnlineTime": "2026-04-24T07:43:51Z",
                    "twins": [
                        {
                            "propertyName": "power",
                            "reported": {
                                "value": "on",
                                "metadata": {"timestamp": fresh_twin_timestamp_ms, "type": "string"},
                            },
                            "observedDesired": {"value": ""},
                        },
                        {
                            "propertyName": "health",
                            "reported": {
                                "value": "ok",
                                "metadata": {"timestamp": fresh_twin_timestamp_ms, "type": "string"},
                            },
                            "observedDesired": {"value": ""},
                        },
                    ],
                },
            }
        ]

    async def fake_mapper_nodes():
        return {"etri-dev0001-jetorn"}

    async def fake_telemetry_samples():
        return {}

    monkeypatch.setattr(service.kube, "get_devices", fake_devices)
    monkeypatch.setattr(service.kube, "get_device_statuses", fake_device_statuses)
    monkeypatch.setattr(service.kube, "get_running_mapper_nodes", fake_mapper_nodes)
    monkeypatch.setattr(service.telemetry, "get_latest_by_device", fake_telemetry_samples)

    with TestClient(app) as client:
        response = client.get("/state/dashboard")

    assert response.status_code == 200
    device = response.json()["devices"][0]
    assert device["status"] == "degraded"
    assert device["status_reason"] == "latest telemetry sample is missing"
    assert device["device_status_fresh"] is True
    assert device["device_status_last_reported_at"] is not None


def test_dashboard_kpis_use_service_binding_names():
    devices = [
        DeviceState(
            name="vib-device-01",
            namespace="default",
            device_type="sensor_device",
            node_name="etri-dev0001-jetorn",
            nodeName="etri-dev0001-jetorn",
            protocol="mqttvirtual",
            telemetry_enabled=True,
            service_connected=True,
            status="available",
            status_reason="fresh DeviceStatus reported timestamp and recent telemetry",
            overall_status="available",
            reason="fresh DeviceStatus reported timestamp and recent telemetry",
        ),
        DeviceState(
            name="rpi-env-device-01",
            namespace="default",
            device_type="sensor_device",
            node_name="etri-dev0002-raspi5",
            nodeName="etri-dev0002-raspi5",
            protocol="mqttvirtual",
            telemetry_enabled=True,
            service_connected=False,
            status="degraded",
            status_reason="DB latest timestamp is missing",
            overall_status="degraded",
            reason="DB latest timestamp is missing",
        ),
    ]

    kpis = service._build_dashboard_kpis([], devices, [])

    assert kpis["service_bound_device_count"] == 1
    assert kpis["device_service_binding_ratio"] == 0.5
    assert "workflow_bound_device_count" not in kpis
    assert "device_workflow_binding_ratio" not in kpis


def test_dashboard_page_is_served():
    with TestClient(app) as client:
        response = client.get("/dashboard")

    assert response.status_code == 200
    assert "디바이스 운영 대시보드" in response.text
    assert "서비스 바인딩" in response.text


def test_device_response_includes_backend_service_binding_detail():
    device = service._normalize_device(
        {
            "metadata": {"name": "vib-device-01", "namespace": "default"},
            "spec": {
                "nodeName": "etri-dev0001-jetorn",
                "properties": [
                    {
                        "name": "vibration",
                        "reportToCloud": False,
                        "pushMethod": {"dbMethod": {"influxdb2": {}}},
                    }
                ],
                "protocol": {"protocolName": "mqttvirtual"},
            },
            "status": {"reportToCloud": False, "reportCycle": 60000},
        },
        node_health={"etri-dev0001-jetorn": "healthy"},
        workflows=[],
        mapper_nodes={"etri-dev0001-jetorn"},
    )

    assert device.service_connected is True
    assert device.service_demo_group == "설비 상태 모니터링"
    assert device.service_binding_source == "device_name_pattern"
    assert device.service_binding_reason == "device name includes vibration service keyword"


def test_device_without_running_mapper_is_unavailable():
    device = service._normalize_device(
        {
            "metadata": {"name": "env-device-offline", "namespace": "default"},
            "spec": {
                "nodeName": "etri-dev0001-jetorn",
                "properties": [
                    {
                        "name": "temperature",
                        "reportToCloud": False,
                        "pushMethod": {"dbMethod": {"influxdb2": {}}},
                    }
                ],
                "protocol": {"protocolName": "mqttvirtual"},
            },
            "status": {"reportToCloud": False, "reportCycle": 60000},
        },
        node_health={},
        workflows=[],
    )

    assert device.status == "unavailable"
    assert device.status_reason == "assigned mapper is not running"


def test_device_with_running_mapper_is_available_when_devicestatus_does_not_report_data_problem():
    device = service._normalize_device(
        {
            "metadata": {"name": "env-device-01", "namespace": "default"},
            "spec": {
                "nodeName": "etri-dev0001-jetorn",
                "properties": [{"name": "temperature", "reportToCloud": False, "pushMethod": {"dbMethod": {"influxdb2": {}}}}],
                "protocol": {"protocolName": "mqttvirtual"},
            },
            "status": {"reportToCloud": False, "reportCycle": 60000},
        },
        node_health={"etri-dev0001-jetorn": "healthy"},
        workflows=[],
        mapper_nodes={"etri-dev0001-jetorn"},
    )

    assert device.status == "degraded"
    assert device.status_reason == "latest telemetry sample is missing"
    assert device.telemetry_enabled is True
    assert device.telemetry_fresh is False


def test_device_with_recent_sensor_data_keeps_freshness_separate_from_health():
    device = service._normalize_device(
        {
            "metadata": {"name": "env-device-01", "namespace": "default"},
            "spec": {
                "nodeName": "etri-dev0001-jetorn",
                "properties": [
                    {
                        "name": "temperature",
                        "reportToCloud": False,
                        "pushMethod": {"dbMethod": {"influxdb2": {}}},
                    }
                ],
                "protocol": {"protocolName": "mqttvirtual"},
            },
            "status": {"reportToCloud": False, "reportCycle": 60000},
        },
        node_health={"etri-dev0001-jetorn": "healthy"},
        workflows=[],
        mapper_nodes={"etri-dev0001-jetorn"},
        telemetry_samples={
            "env-device-01": TelemetrySample(
                device_id="env-device-01",
                timestamp=datetime.now(timezone.utc),
                property="temperature",
                value="24.1",
            )
        },
    )

    assert device.status == "available"
    assert device.status_reason == "latest telemetry sample is fresh"
    assert device.telemetry_enabled is True
    assert device.telemetry_fresh is True
    assert device.device_status_fresh is False
    assert device.telemetry_property == "temperature"
    assert device.telemetry_value == "24.1"


def test_device_with_stale_sensor_data_remains_available_until_devicestatus_reports_problem():
    device = service._normalize_device(
        {
            "metadata": {"name": "env-device-01", "namespace": "default"},
            "spec": {
                "nodeName": "etri-dev0001-jetorn",
                "properties": [
                    {
                        "name": "temperature",
                        "reportToCloud": False,
                        "pushMethod": {"dbMethod": {"influxdb2": {}}},
                    }
                ],
                "protocol": {"protocolName": "mqttvirtual"},
            },
            "status": {},
        },
        node_health={"etri-dev0001-jetorn": "healthy"},
        workflows=[],
        mapper_nodes={"etri-dev0001-jetorn"},
        telemetry_samples={
            "env-device-01": TelemetrySample(
                device_id="env-device-01",
                timestamp=datetime.now(timezone.utc) - timedelta(minutes=10),
                property="temperature",
                value="24.1",
            )
        },
    )

    assert device.status == "degraded"
    assert device.status_reason == "latest telemetry sample is stale"
    assert device.telemetry_fresh is False



def _base_mqttvirtual_device(status: dict | None = None, node_name: str | None = "etri-dev0001-jetorn") -> dict:
    spec = {
        "properties": [
            {"name": "temperature", "reportToCloud": False, "pushMethod": {"dbMethod": {"influxdb2": {}}}},
        ],
        "protocol": {"protocolName": "mqttvirtual"},
    }
    if node_name is not None:
        spec["nodeName"] = node_name
    return {
        "metadata": {"name": "env-device-availability", "namespace": "default"},
        "spec": spec,
        "status": status or {},
    }


def test_availability_unavailable_when_device_has_no_assigned_node():
    device = service._normalize_device(
        _base_mqttvirtual_device(node_name=None),
        node_health={"etri-dev0001-jetorn": "healthy"},
        workflows=[],
        mapper_nodes={"etri-dev0001-jetorn"},
    )

    assert device.status == "unavailable"
    assert device.status_reason == "device is not assigned to a node"


def test_availability_unavailable_when_assigned_node_is_not_ready():
    device = service._normalize_device(
        _base_mqttvirtual_device(),
        node_health={"etri-dev0001-jetorn": "unavailable"},
        workflows=[],
        mapper_nodes={"etri-dev0001-jetorn"},
    )

    assert device.status == "unavailable"
    assert device.status_reason == "assigned node is unavailable"


def test_availability_unavailable_when_kubernetes_node_ready_is_false():
    device = service._normalize_device(
        _base_mqttvirtual_device(),
        node_health={"etri-dev0001-jetorn": "healthy"},
        workflows=[],
        mapper_nodes={"etri-dev0001-jetorn"},
        node_readiness={"etri-dev0001-jetorn": False},
    )

    assert device.status == "unavailable"
    assert device.status_reason == "assigned node is unavailable"


def test_availability_unavailable_when_mapper_pod_is_missing():
    device = service._normalize_device(
        _base_mqttvirtual_device(),
        node_health={"etri-dev0001-jetorn": "healthy"},
        workflows=[],
        mapper_nodes=set(),
    )

    assert device.status == "unavailable"
    assert device.status_reason == "assigned mapper is not running"


def test_availability_unavailable_when_device_status_health_is_offline():
    device = service._normalize_device(
        _base_mqttvirtual_device(
            status={
                "twins": {
                    "health": {
                        "actual": {
                            "value": "offline",
                            "metadata": {"timestamp": datetime.now(timezone.utc).isoformat()},
                        }
                    }
                }
            }
        ),
        node_health={"etri-dev0001-jetorn": "healthy"},
        workflows=[],
        mapper_nodes={"etri-dev0001-jetorn"},
    )

    assert device.status == "unavailable"
    assert device.status_reason == "DeviceStatus health is offline"


def test_availability_unavailable_when_device_status_online_is_false():
    device = service._normalize_device(
        _base_mqttvirtual_device(
            status={
                "twins": {
                    "online": {
                        "actual": {
                            "value": "false",
                            "metadata": {"timestamp": datetime.now(timezone.utc).isoformat()},
                        }
                    }
                }
            }
        ),
        node_health={"etri-dev0001-jetorn": "healthy"},
        workflows=[],
        mapper_nodes={"etri-dev0001-jetorn"},
    )

    assert device.status == "unavailable"
    assert device.status_reason == "DeviceStatus online is false"


def test_availability_degraded_when_status_heartbeat_is_stale():
    stale = (datetime.now(timezone.utc) - timedelta(seconds=service.settings.device_status_fresh_seconds + 30)).isoformat()
    device = service._normalize_device(
        _base_mqttvirtual_device(
            status={
                "twins": {
                    "statusLastSeen": {"actual": {"value": stale, "metadata": {"timestamp": stale}}},
                    "health": {"actual": {"value": "ok", "metadata": {"timestamp": stale}}},
                }
            }
        ),
        node_health={"etri-dev0001-jetorn": "healthy"},
        workflows=[],
        mapper_nodes={"etri-dev0001-jetorn"},
    )

    assert device.status == "degraded"
    assert device.status_reason == "latest telemetry sample is missing"
    assert device.device_status_fresh is False


def test_availability_available_when_raw_telemetry_missing_but_control_status_is_normal():
    now = datetime.now(timezone.utc).isoformat()
    device = service._normalize_device(
        _base_mqttvirtual_device(
            status={
                "twins": {
                    "statusLastSeen": {"actual": {"value": now, "metadata": {"timestamp": now}}},
                    "health": {"actual": {"value": "ok", "metadata": {"timestamp": now}}},
                }
            }
        ),
        node_health={"etri-dev0001-jetorn": "healthy"},
        workflows=[],
        mapper_nodes={"etri-dev0001-jetorn"},
        telemetry_samples={},
    )

    assert device.status == "degraded"
    assert device.status_reason == "latest telemetry sample is missing"
    assert device.telemetry_fresh is False
    assert device.telemetry_status == "stale"


def test_availability_degraded_when_devicestatus_reports_telemetry_input_stale():
    now = datetime.now(timezone.utc).isoformat()
    device = service._normalize_device(
        _base_mqttvirtual_device(
            status={
                "twins": {
                    "statusLastSeen": {"actual": {"value": now, "metadata": {"timestamp": now}}},
                    "health": {"actual": {"value": "degraded", "metadata": {"timestamp": now}}},
                    "severity": {"actual": {"value": "warning", "metadata": {"timestamp": now}}},
                    "online": {"actual": {"value": "true", "metadata": {"timestamp": now}}},
                    "last_error_code": {"actual": {"value": "telemetry_input_stale", "metadata": {"timestamp": now}}},
                    "last_error_message": {"actual": {"value": "telemetry input is stale", "metadata": {"timestamp": now}}},
                }
            }
        ),
        node_health={"etri-dev0001-jetorn": "healthy"},
        workflows=[],
        mapper_nodes={"etri-dev0001-jetorn"},
        telemetry_samples={},
    )

    assert device.status == "degraded"
    assert device.status_reason == "latest telemetry sample is missing"
    assert device.health == "degraded"
    assert device.severity == "warning"
    assert device.twin["last_error_code"]["actual"]["value"] == "telemetry_input_stale"


def test_operator_assistant_endpoint_returns_korean_read_only_summary(monkeypatch):
    service.store.nodes = {
        "etri-dev0001-jetorn": NodeState(
            hostname="etri-dev0001-jetorn",
            instance="192.168.0.3:9100",
            node_type="edge_ai_device",
            collected_at=datetime.now(timezone.utc),
            raw_metrics={
                "up": 1.0,
                "cpu_utilization": 0.25,
                "memory_usage_ratio": 0.35,
                "load_average": 0.7,
                "network_rx_rate": 120.0,
                "network_tx_rate": 90.0,
            },
            compute_pressure="low",
            memory_pressure="low",
            network_pressure="low",
            node_health="healthy",
        )
    }

    async def fake_devices():
        return [
            {
                "metadata": {"name": "vib-device-01", "namespace": "default"},
                "spec": {
                    "deviceModelRef": {"name": "virtual-vib-model"},
                    "nodeName": "etri-dev0001-jetorn",
                    "properties": [
                        {
                            "name": "vibration",
                            "reportToCloud": False,
                            "pushMethod": {"dbMethod": {"influxdb2": {}}},
                        }
                    ],
                    "protocol": {"protocolName": "mqttvirtual"},
                },
                "status": {},
            }
        ]

    async def fake_device_statuses():
        return []

    async def fake_mapper_nodes():
        return {"etri-dev0001-jetorn"}

    async def fake_telemetry_samples():
        return {
            "vib-device-01": TelemetrySample(
                device_id="vib-device-01",
                timestamp=datetime.now(timezone.utc),
                property="vibration",
                value="1",
            )
        }

    monkeypatch.setattr(service.kube, "get_devices", fake_devices)
    monkeypatch.setattr(service.kube, "get_device_statuses", fake_device_statuses)
    monkeypatch.setattr(service.kube, "get_running_mapper_nodes", fake_mapper_nodes)
    monkeypatch.setattr(service.telemetry, "get_latest_by_device", fake_telemetry_samples)

    with TestClient(app) as client:
        response = client.get("/state/operator-assistant")

    assert response.status_code == 200
    payload = response.json()
    assert payload["assistant_name"] == "kagenti-operator-assistant-poc"
    assert payload["mode"] == "read_only"
    assert "운영 보조" in payload["summary_ko"]
    assert "등록 device 1개" in payload["summary_ko"]
    assert payload["focus_devices"] == []
    assert payload["recommended_actions"] == ["현재 우선 점검 대상이 없으므로 dashboard KPI와 service demo group만 확인한다."]
    assert payload["source_endpoints"] == [
        "/state/dashboard",
        "/state/devices",
        "/state/nodes",
        "/state/summary",
    ]
    assert "kubectl delete" not in " ".join(payload["recommended_actions"])


def test_dashboard_kpis_separate_operational_and_live_devices():
    devices = [
        service._normalize_device(
            {
                "metadata": {"name": "env-live", "namespace": "default"},
                "spec": {
                    "nodeName": "etri-dev0001-jetorn",
                    "properties": [
                        {
                            "name": "temperature",
                            "reportToCloud": False,
                            "pushMethod": {"dbMethod": {"influxdb2": {}}},
                        }
                    ],
                    "protocol": {"protocolName": "mqttvirtual"},
                },
                    "status": {
                        "lastOnlineTime": datetime.now(timezone.utc).isoformat(),
                        "twins": {"health": {"actual": {"value": "ok"}}},
                    },
            },
            node_health={"etri-dev0001-jetorn": "healthy"},
            workflows=[],
            mapper_nodes={"etri-dev0001-jetorn"},
            telemetry_samples={
                "env-live": TelemetrySample(
                    device_id="env-live",
                    timestamp=datetime.now(timezone.utc),
                    property="temperature",
                    value="24.1",
                )
            },
        ),
        service._normalize_device(
            {
                "metadata": {"name": "env-pending", "namespace": "default"},
                "spec": {
                    "nodeName": "etri-dev0001-jetorn",
                    "properties": [{"name": "temperature", "reportToCloud": True}],
                    "protocol": {"protocolName": "mqttvirtual"},
                },
                "status": {"reportToCloud": False, "reportCycle": 60000},
            },
            node_health={"etri-dev0001-jetorn": "healthy"},
            workflows=[],
            mapper_nodes={"etri-dev0001-jetorn"},
        ),
        service._normalize_device(
            {
                "metadata": {"name": "env-down", "namespace": "default"},
                "spec": {
                    "nodeName": "etri-dev0002-raspi5",
                    "properties": [{"name": "temperature", "reportToCloud": True}],
                    "protocol": {"protocolName": "mqttvirtual"},
                },
                "status": {},
            },
            node_health={"etri-dev0002-raspi5": "healthy"},
            workflows=[],
            mapper_nodes=set(),
        ),
    ]

    kpis = service._build_dashboard_kpis(nodes=[], devices=devices, workflows=[])

    assert kpis["device_healthy_ratio"] == 0.667
    assert kpis["device_operational_ratio"] == 0.667
    assert kpis["live_device_count"] == 2
    assert kpis["operational_device_count"] == 2
    assert kpis["unavailable_device_count"] == 1
    assert kpis["operator_focus_count"] == 1


def test_influx_csv_parser_reads_latest_device_samples():
    client = InfluxTelemetryClient(
        "http://influxdb:8086",
        "edgeai",
        "device_telemetry",
        "[REDACTED]",
        "virtual_device_telemetry",
        "-30m",
    )

    samples = client._parse_csv(
        "#datatype,string,long,dateTime:RFC3339,string,string,string\n"
        ",result,table,_time,_value,device_id,property\n"
        ",_result,0,2026-04-28T10:30:48.353750014Z,282,env-device-01,temperature\n"
        ",_result,1,2026-04-28T10:30:48.32595157Z,2.367,vib-device-01,vibration\n"
    )

    assert samples["env-device-01"].property == "temperature"
    assert samples["env-device-01"].value == "282"
    assert samples["vib-device-01"].property == "vibration"


def test_device_telemetry_ratio_and_freshness_calculation():
    # device_telemetry_ratio = telemetry_enabled devices / total devices
    # telemetry_freshness_ratio = fresh telemetry devices / telemetry-enabled devices
    devices = [
        service._normalize_device(
            {
                "metadata": {"name": "dev-a", "namespace": "default"},
                "spec": {"properties": [{"name": "p", "pushMethod": {"dbMethod": {"influxdb2": {}}}}]},
                "status": {},
            },
            node_health={"n": "healthy"},
            workflows=[],
            mapper_nodes=set(),
            telemetry_samples={"dev-a": TelemetrySample(device_id="dev-a", timestamp=datetime.now(timezone.utc), property="p", value="1")},
        ),
        service._normalize_device(
            {
                "metadata": {"name": "dev-b", "namespace": "default"},
                "spec": {"properties": [{"name": "p2"}]},
                "status": {},
            },
            node_health={"n": "healthy"},
            workflows=[],
            mapper_nodes=set(),
        ),
    ]

    kpis = service._build_dashboard_kpis(nodes=[], devices=devices, workflows=[])
    assert kpis["telemetry_device_count"] == 1
    assert kpis["device_telemetry_ratio"] == 0.5
    # fresh telemetry devices = 1, freshness ratio = 1/1 = 1.0
    assert kpis["fresh_telemetry_device_count"] == 1
    assert kpis["telemetry_freshness_ratio"] == 1.0


def test_operator_focus_count_counts_degraded_and_nonhealthy_nodes():
    # One node degraded, one device degraded
    nodes = [
        NodeState(
            hostname="n1",
            instance="i",
            node_type="edge",
            collected_at=datetime.now(timezone.utc),
            raw_metrics={},
            compute_pressure="low",
            memory_pressure="low",
            network_pressure="low",
            node_health="degraded",
        ),
        NodeState(
            hostname="n2",
            instance="i2",
            node_type="edge",
            collected_at=datetime.now(timezone.utc),
            raw_metrics={},
            compute_pressure="low",
            memory_pressure="low",
            network_pressure="low",
            node_health="healthy",
        ),
    ]

    devices = [
        DeviceState(
            name="good",
            namespace="default",
            device_type="sensor_device",
            node_name="n2",
            nodeName="n2",
            protocol="mqttvirtual",
            telemetry_enabled=False,
            service_connected=False,
            status="available",
            status_reason="",
            overall_status="available",
            reason="",
        ),
        DeviceState(
            name="bad",
            namespace="default",
            device_type="sensor_device",
            node_name="n1",
            nodeName="n1",
            protocol="mqttvirtual",
            telemetry_enabled=False,
            service_connected=False,
            status="degraded",
            status_reason="DB latest timestamp is missing",
            overall_status="degraded",
            reason="",
        ),
    ]

    kpis = service._build_dashboard_kpis(nodes=nodes, devices=devices, workflows=[])
    # focus_devices = 1 (bad), focus_nodes = 1 (n1 degraded)
    assert kpis["operator_focus_count"] == 2


def test_dashboard_kpis_count_telemetry_enabled_and_freshness_separately():
    devices = [
        DeviceState(
            name="fresh-telemetry",
            namespace="default",
            device_type="sensor_device",
            telemetry_enabled=True,
            telemetry_fresh=True,
            service_connected=False,
            status="available",
            status_reason="control/status path is available",
            overall_status="available",
            reason="control/status path is available",
        ),
        DeviceState(
            name="stale-telemetry",
            namespace="default",
            device_type="sensor_device",
            telemetry_enabled=True,
            telemetry_fresh=False,
            service_connected=False,
            status="degraded",
            status_reason="InfluxDB telemetry stale",
            overall_status="degraded",
            reason="InfluxDB telemetry stale",
        ),
        DeviceState(
            name="status-only",
            namespace="default",
            device_type="sensor_device",
            telemetry_enabled=False,
            telemetry_fresh=True,
            service_connected=False,
            status="available",
            status_reason="control/status path is available",
            overall_status="available",
            reason="control/status path is available",
        ),
        DeviceState(
            name="no-telemetry",
            namespace="default",
            device_type="sensor_device",
            telemetry_enabled=False,
            telemetry_fresh=False,
            service_connected=False,
            status="degraded",
            status_reason="registered but live status is unknown",
            overall_status="degraded",
            reason="registered but live status is unknown",
        ),
    ]

    kpis = service._build_dashboard_kpis(nodes=[], devices=devices, workflows=[])

    assert kpis["telemetry_device_count"] == 2
    assert kpis["device_telemetry_ratio"] == 0.5
    assert kpis["fresh_telemetry_device_count"] == 1
    assert kpis["telemetry_freshness_ratio"] == 0.5


def test_dashboard_kpis_count_device_status_freshness_separately():
    devices = [
        DeviceState(
            name="fresh-status",
            namespace="default",
            device_type="sensor_device",
            telemetry_enabled=True,
            telemetry_fresh=False,
            device_status_fresh=True,
            service_connected=False,
            status="degraded",
            status_reason="DB latest timestamp is missing",
            overall_status="degraded",
            reason="DB latest timestamp is missing",
        ),
        DeviceState(
            name="stale-status-a",
            namespace="default",
            device_type="sensor_device",
            telemetry_enabled=True,
            telemetry_fresh=True,
            device_status_fresh=False,
            service_connected=False,
            status="available",
            status_reason="control/status path is available",
            overall_status="available",
            reason="control/status path is available",
        ),
        DeviceState(
            name="stale-status-b",
            namespace="default",
            device_type="sensor_device",
            telemetry_enabled=False,
            telemetry_fresh=False,
            device_status_fresh=False,
            service_connected=False,
            status="degraded",
            status_reason="registered but live status is unknown",
            overall_status="degraded",
            reason="registered but live status is unknown",
        ),
    ]

    kpis = service._build_dashboard_kpis(nodes=[], devices=devices, workflows=[])

    assert kpis["fresh_device_status_count"] == 1
    assert kpis["device_status_freshness_ratio"] == 0.333


def test_operator_focus_count_ignores_workflow_risk():
    node = NodeState(
        hostname="healthy-node",
        instance="i",
        node_type="edge",
        collected_at=datetime.now(timezone.utc),
        raw_metrics={},
        compute_pressure="low",
        memory_pressure="low",
        network_pressure="low",
        node_health="healthy",
    )
    workflow = WorkflowState(
        workflow_id="wf-risk",
        workflow_type="vision_pipeline",
        last_event_type="migration_event",
        last_stage_id="stage-a",
        assigned_node="healthy-node",
        latest_timestamp=datetime.now(timezone.utc),
        workflow_urgency="high",
        sla_risk="high",
        placement_stability="unstable",
        recent_event={},
    )
    device = DeviceState(
        name="healthy-device",
        namespace="default",
        device_type="sensor_device",
        telemetry_enabled=True,
        telemetry_fresh=True,
        service_connected=False,
        status="available",
        status_reason="control/status path is available",
        overall_status="available",
        reason="control/status path is available",
    )

    kpis = service._build_dashboard_kpis(nodes=[node], devices=[device], workflows=[workflow])

    assert kpis["sla_risk_workflow_count"] == 1
    assert kpis["operator_focus_count"] == 0


def test_sensor_data_freshness_does_not_gate_control_health_when_device_status_is_stale():
    stale_device_status_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
    device = service._normalize_device(
        {
            "metadata": {"name": "env-device-db-fresh", "namespace": "default"},
            "spec": {
                "nodeName": "etri-dev0001-jetorn",
                "properties": [
                    {
                        "name": "temperature",
                        "reportToCloud": False,
                        "pushMethod": {"dbMethod": {"influxdb2": {}}},
                    }
                ],
                "protocol": {"protocolName": "mqttvirtual"},
            },
            "status": {
                "lastOnlineTime": stale_device_status_time,
                "twins": {
                    "temperature": {
                        "actual": {
                            "value": "24.1",
                            "metadata": {"timestamp": stale_device_status_time},
                        }
                    }
                },
            },
        },
        node_health={"etri-dev0001-jetorn": "healthy"},
        workflows=[],
        mapper_nodes={"etri-dev0001-jetorn"},
        telemetry_samples={
            "env-device-db-fresh": TelemetrySample(
                device_id="env-device-db-fresh",
                timestamp=datetime.now(timezone.utc),
                property="temperature",
                value="24.1",
            )
        },
    )

    assert device.telemetry_enabled is True
    assert device.telemetry_fresh is True
    assert device.device_status_fresh is False
    assert device.status == "available"
    assert device.status_reason == "latest telemetry sample is fresh"


def test_dashboard_treats_pushmethod_raw_sensor_properties_as_telemetry(monkeypatch):
    service.store.nodes = {
        "etri-dev0001-jetorn": NodeState(
            hostname="etri-dev0001-jetorn",
            instance="192.168.0.3:9100",
            node_type="edge_ai_device",
            collected_at=datetime.now(timezone.utc),
            raw_metrics={"up": 1.0, "cpu_utilization": 0.1, "memory_usage_ratio": 0.2, "load_average": 0.1, "network_rx_rate": 1.0, "network_tx_rate": 1.0},
            compute_pressure="low",
            memory_pressure="low",
            network_pressure="low",
            node_health="healthy",
        )
    }

    async def fake_devices():
        return [
            {
                "metadata": {"name": "env-device-01", "namespace": "default"},
                "spec": {
                    "deviceModelRef": {"name": "virtual-env-model"},
                    "nodeName": "etri-dev0001-jetorn",
                    "properties": [
                        {"name": "temperature", "reportToCloud": False, "pushMethod": {"dbMethod": {"influxdb2": {}}}},
                        {"name": "health", "reportToCloud": True},
                    ],
                    "protocol": {"protocolName": "mqttvirtual"},
                },
                "status": {},
            }
        ]

    async def fake_mapper_nodes():
        return {"etri-dev0001-jetorn"}

    async def fake_device_statuses():
        return []

    async def fake_telemetry_samples():
        return {
            "env-device-01": TelemetrySample(
                device_id="env-device-01",
                timestamp=datetime.now(timezone.utc),
                property="temperature",
                value="24.1",
            )
        }

    monkeypatch.setattr(service.kube, "get_devices", fake_devices)
    monkeypatch.setattr(service.kube, "get_device_statuses", fake_device_statuses)
    monkeypatch.setattr(service.kube, "get_running_mapper_nodes", fake_mapper_nodes)
    monkeypatch.setattr(service.telemetry, "get_latest_by_device", fake_telemetry_samples)

    with TestClient(app) as client:
        response = client.get("/state/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["devices"][0]["telemetry_enabled"] is True
    assert payload["kpis"]["telemetry_device_count"] == 1
    assert payload["devices"][0]["overall_status"] == "available"


def test_device_status_bridge_writes_only_control_status_summary_fields():
    patched_bodies = []

    class DummyCustom:
        def patch_namespaced_custom_object(self, **kwargs):
            patched_bodies.append(kwargs["body"])

    kube = KubeClient.__new__(KubeClient)
    kube.enabled = True
    kube.custom = DummyCustom()

    async def fake_devices():
        return [
            {
                "metadata": {"name": "env-arduino-temperature-01", "namespace": "default"},
                "spec": {"nodeName": "etri-dev0001-jetorn"},
            }
        ]

    async def fake_mapper_nodes(namespace="default"):
        return {"etri-dev0001-jetorn"}

    kube.get_devices = fake_devices
    kube.get_running_mapper_nodes = fake_mapper_nodes

    patched = asyncio.run(kube.bridge_device_status_heartbeats())

    assert patched == 1
    twins = patched_bodies[0]["status"]["twins"]
    names = {twin["propertyName"] for twin in twins}
    assert names == {
        "health",
        "severity",
        "online",
        "mapperLastSeen",
        "statusLastSeen",
        "statusSource",
        "last_error_code",
        "last_error_message",
    }
    assert "temperature" not in names
    assert "humidity" not in names
    assert "vibration" not in names
    values = {twin["propertyName"]: twin["reported"]["value"] for twin in twins}
    assert values["health"] == "online"
    assert values["statusSource"] == "mapper-framework/bridge"


def test_device_telemetry_history_endpoint_returns_recent_points(monkeypatch):
    now = datetime.now(timezone.utc)

    async def fake_history(device_id: str, window: str = "-30m", limit: int = 300):
        assert device_id == "env-arduino-temperature-01"
        assert window == "-10m"
        assert limit == 2
        return [
            TelemetrySample(
                device_id=device_id,
                timestamp=now - timedelta(seconds=2),
                property="temperature",
                value="24.1",
            ),
            TelemetrySample(
                device_id=device_id,
                timestamp=now,
                property="temperature",
                value="24.3",
            ),
        ]

    monkeypatch.setattr(service.telemetry, "get_history", fake_history, raising=False)

    with TestClient(app) as client:
        response = client.get("/state/devices/env-arduino-temperature-01/telemetry?window=-10m&limit=2")

    assert response.status_code == 200
    payload = response.json()
    assert [point["value"] for point in payload] == ["24.1", "24.3"]
    assert payload[0]["property"] == "temperature"
    assert payload[0]["device_id"] == "env-arduino-temperature-01"
