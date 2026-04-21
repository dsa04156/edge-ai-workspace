from fastapi.testclient import TestClient

from placement_engine.main import app


def test_healthz():
    client = TestClient(app)
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_decide_endpoint_with_inline_node_state():
    client = TestClient(app)
    response = client.post(
        "/placement/decide",
        json={
            "workflow_id": "wf-api",
            "stage_id": "infer",
            "workflow_type": "large_model_serving",
            "current_placement": "etri-dev0001-jetorn",
            "stage_metadata": {
                "stage_type": "inference",
                "requires_accelerator": True,
                "compute_intensity": "high",
                "memory_intensity": "medium",
                "latency_sensitivity": "medium",
                "input_size_kb": 1024,
                "output_size_kb": 128,
            },
            "node_profiles": [
                {
                    "hostname": "etri-ser0001-CG0MSB",
                    "node_type": "cloud_server",
                    "arch": "x86_64",
                    "compute_class": "high",
                    "memory_class": "high",
                    "accelerator_type": "gpu_discrete",
                    "preferred_workload": ["large_model_serving"],
                    "risky_workload": [],
                },
                {
                    "hostname": "etri-dev0001-jetorn",
                    "node_type": "edge_ai_device",
                    "arch": "aarch64",
                    "compute_class": "medium",
                    "memory_class": "medium",
                    "accelerator_type": "gpu_embedded",
                    "preferred_workload": ["edge_inference"],
                    "risky_workload": ["large_model_serving"],
                },
            ],
            "node_states": [
                {
                    "hostname": "etri-ser0001-CG0MSB",
                    "compute_pressure": "low",
                    "memory_pressure": "low",
                    "network_pressure": "low",
                    "node_health": "healthy",
                },
                {
                    "hostname": "etri-dev0001-jetorn",
                    "compute_pressure": "low",
                    "memory_pressure": "low",
                    "network_pressure": "low",
                    "node_health": "healthy",
                },
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["decision"]["target_node"] == "etri-ser0001-CG0MSB"
