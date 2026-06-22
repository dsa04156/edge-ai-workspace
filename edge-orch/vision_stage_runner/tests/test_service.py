from fastapi.testclient import TestClient

from vision_stage_runner.service import app


def test_healthz_names_factory_inspection_service():
    client = TestClient(app)

    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {
        "service": "factory-vision-inspection-ai",
        "scenario": "jetson-vision-inspection",
        "target_device": "etri-dev0001-jetorn",
        "status": "healthy",
    }


def test_inspect_runs_all_ai_workflow_stages():
    client = TestClient(app)

    response = client.get("/inspect", params={"workflow_id": "qa-green"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["service"] == "factory-vision-inspection-ai"
    assert payload["scenario"] == "jetson-vision-inspection"
    assert payload["target_device"] == "etri-dev0001-jetorn"
    assert payload["workflow_id"] == "qa-green"
    assert set(payload["stages"]) == {
        "capture",
        "preprocess",
        "inference",
        "postprocess",
        "result_delivery",
    }
    assert payload["stages"]["inference"]["result"]["predicted_class"] in {0, 1, 2, 3}
    assert payload["resource_request"] == {
        "needed": True,
        "reason": ["gpu_inference_pressure", "cache_required"],
        "augmentation_mode": "observed-only",
    }


def test_inspect_rejects_empty_workflow_id():
    client = TestClient(app)

    response = client.get("/inspect", params={"workflow_id": ""})

    assert response.status_code == 422
