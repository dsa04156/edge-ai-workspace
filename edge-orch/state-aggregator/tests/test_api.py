from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from app.main import app, service
from app.influx import InfluxTelemetryClient, TelemetrySample
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
                    "properties": [{"name": "health", "reportToCloud": True}],
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
    assert device["status"] == "healthy"
    assert device["status_reason"] == "fresh DeviceStatus snapshot"
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
                    "properties": [{"name": "power", "reportToCloud": True}],
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
    assert device["status"] == "healthy"
    assert device["status_reason"] == "fresh DeviceStatus snapshot"
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
            status="healthy",
            status_reason="fresh DeviceStatus reported timestamp and recent telemetry",
            overall_status="healthy",
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
            status_reason="mapper is running but telemetry has not reached InfluxDB",
            overall_status="degraded",
            reason="mapper is running but telemetry has not reached InfluxDB",
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


def test_device_with_running_mapper_is_degraded_without_twin_report():
    device = service._normalize_device(
        {
            "metadata": {"name": "env-device-01", "namespace": "default"},
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
    )

    assert device.status == "degraded"
    assert device.status_reason == "registered but live status is unknown"


def test_device_with_recent_influx_telemetry_is_healthy():
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

    assert device.status == "degraded"
    assert device.status_reason == "recent telemetry but DeviceStatus snapshot is stale"
    assert device.telemetry_enabled is True
    assert device.telemetry_fresh is True
    assert device.device_status_fresh is False
    assert device.telemetry_property == "temperature"
    assert device.telemetry_value == "24.1"


def test_device_with_stale_influx_telemetry_is_degraded():
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
    assert device.status_reason.startswith("telemetry and DeviceStatus stale: ")


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

    assert kpis["device_healthy_ratio"] == 0.333
    assert kpis["device_operational_ratio"] == 0.667
    assert kpis["live_device_count"] == 1
    assert kpis["operational_device_count"] == 2
    assert kpis["unavailable_device_count"] == 1
    assert kpis["operator_focus_count"] == 1


def test_influx_csv_parser_reads_latest_device_samples():
    client = InfluxTelemetryClient(
        url="http://influxdb:8086",
        org="edgeai",
        bucket="device_telemetry",
        token="token",
        measurement="virtual_device_telemetry",
        query_window="-30m",
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
