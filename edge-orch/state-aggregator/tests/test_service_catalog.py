from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from app import main
from app.service_catalog import ServiceCatalog
from app.service_demo import degraded_service_demo_state


CATALOG_PATH = Path(__file__).resolve().parents[1] / "app/config/service_catalog.json"


def catalog_payload() -> dict:
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def write_catalog(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "service_catalog.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


def test_checked_in_service_catalog_loads_current_service() -> None:
    catalog = ServiceCatalog.load(CATALOG_PATH)

    service = catalog.require("sensor-anomaly-demo")

    assert catalog.version == "edgeai.etri/service-catalog/v1"
    assert service.input_contract.authority == "EdgeX"
    assert service.input_contract.schema_name == "okdong.pump-motor.telemetry/v1"
    assert [stage.slot for stage in service.graph.stages] == [
        "Input",
        "Alignment",
        "Features",
        "Inference",
        "Result",
    ]
    assert {target.slot for target in service.graph.targets} == {"Device1", "Server1"}
    assert [execution.target_slot for execution in service.graph.stages[3].executions] == [
        "Device1",
        "Server1",
    ]
    assert service.graph.stages[0].executions[0].executor == "device-serial-jetson"
    assert service.augmentation_qualification.status == "rejected"
    assert service.augmentation_qualification.experiment_id == (
        "sensor-augmentation-20260818"
    )
    assert service.augmentation_qualification.max_validated_rps == 200
    assert service.augmentation_qualification.latency_p95_improvement_percent == 10
    assert service.augmentation_qualification.throughput_noninferiority_percent == 5
    assert service.augmentation_qualification.requires_zero_errors_and_oom is True
    assert service.augmentation_qualification.qualified_condition_count == 0
    assert service.augmentation_qualification.validated_condition_count == 15
    assert service.augmentation_qualification.evidence_document.endswith(
        "AI-서비스-자원-증강-부하-실험.md"
    )


def test_service_catalog_rejects_duplicate_service_ids(tmp_path: Path) -> None:
    payload = catalog_payload()
    payload["services"].append(payload["services"][0].copy())

    with pytest.raises(ValueError, match="serviceId values must be unique"):
        ServiceCatalog.load(write_catalog(tmp_path, payload))


def test_service_catalog_rejects_cycles(tmp_path: Path) -> None:
    payload = catalog_payload()
    payload["services"][0]["graph"]["stages"][0]["depends_on"] = ["store"]

    with pytest.raises(ValidationError, match="acyclic"):
        ServiceCatalog.load(write_catalog(tmp_path, payload))


def test_service_catalog_rejects_external_observability_urls(tmp_path: Path) -> None:
    payload = catalog_payload()
    payload["services"][0]["observability"]["state_path"] = "http://example.test/state"

    with pytest.raises(ValidationError, match="relative /state/ path"):
        ServiceCatalog.load(write_catalog(tmp_path, payload))


def test_service_catalog_rejects_impossible_qualification_counts(
    tmp_path: Path,
) -> None:
    payload = catalog_payload()
    qualification = payload["services"][0]["augmentation_qualification"]
    qualification["qualified_condition_count"] = 16

    with pytest.raises(ValidationError, match="cannot exceed"):
        ServiceCatalog.load(write_catalog(tmp_path, payload))


def test_catalog_only_service_is_listed_without_inventing_runtime_state(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = catalog_payload()
    second = json.loads(json.dumps(payload["services"][0]))
    second["service_id"] = "production-quality-demo"
    second["display_name"] = "생산품질 판별"
    second["workload"]["name"] = "production-quality-demo"
    payload["services"].append(second)
    catalog = ServiceCatalog.load(write_catalog(tmp_path, payload))
    monkeypatch.setattr(main, "service_catalog", catalog)

    state = main._deployed_service_state(
        degraded_service_demo_state(RuntimeError("offline"))
    )

    assert [service.service_id for service in state.services] == [
        "sensor-anomaly-demo",
        "production-quality-demo",
    ]
    added = state.services[1]
    assert added.mode == "unavailable"
    assert added.status == "degraded"
    assert added.observation_error == "service runtime adapter is not connected"
