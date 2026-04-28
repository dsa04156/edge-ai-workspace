from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.main import app, service
from app.models import NodeState, WorkflowState


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
                    "properties": [{"name": "temperature", "reportToCloud": True}],
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

    monkeypatch.setattr(service.kube, "get_devices", fake_devices)
    monkeypatch.setattr(service.kube, "get_running_mapper_nodes", fake_mapper_nodes)

    with TestClient(app) as client:
        response = client.get("/state/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["kpis"]["active_node_count"] == 1
    assert payload["kpis"]["registered_device_count"] == 1
    assert payload["kpis"]["telemetry_device_count"] == 1
    assert payload["devices"][0]["name"] == "env-device-01"
    assert "services" not in payload


def test_dashboard_page_is_served():
    with TestClient(app) as client:
        response = client.get("/dashboard")

    assert response.status_code == 200
    assert "디바이스 운영 대시보드" in response.text


def test_device_without_live_status_is_unavailable():
    device = service._normalize_device(
        {
            "metadata": {"name": "env-device-offline", "namespace": "default"},
            "spec": {
                "nodeName": "etri-dev0001-jetorn",
                "properties": [{"name": "temperature", "reportToCloud": True}],
                "protocol": {"protocolName": "mqttvirtual"},
            },
            "status": {"reportToCloud": False, "reportCycle": 60000},
        },
        node_health={},
        workflows=[],
    )

    assert device.status == "unavailable"
    assert device.status_reason == "no live report from device twin"


def test_device_with_running_mapper_is_healthy_without_twin_report():
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

    assert device.status == "healthy"
    assert device.status_reason == "assigned node and mapper are running"
