import copy
import importlib.util
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.models import NodeSchedulingResource, NodeResourceUtilization, SchedulingResourceAmounts
from app.profile_spec import BUNDLE, VALIDATORS, compare, create_profile_router, observation, validate_document

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)


def node(name="node-1", architecture="arm64", observed_at=NOW):
    return NodeSchedulingResource(
        node=name, kubernetes_ready=True, cpu_available=4, memoryAvailableGB=8,
        health="healthy", schedulable=True, architecture=architecture,
        allocatable=SchedulingResourceAmounts(cpu_cores=6, memory_bytes=8*1024**3),
        requested=SchedulingResourceAmounts(cpu_cores=2, memory_bytes=0),
        available=SchedulingResourceAmounts(cpu_cores=4, memory_bytes=8*1024**3),
        utilization=NodeResourceUtilization(cpu_ratio=0.1, memory_ratio=0.2, observed_at=observed_at))


def client(reader=None):
    async def default_reader(): return [node()]
    app = FastAPI()
    app.include_router(create_profile_router(reader or default_reader))
    return TestClient(app)


def test_bundle_matches_canonical_files():
    path = Path(__file__).resolve().parents[3] / "profile-spec/build_bundle.py"
    spec = importlib.util.spec_from_file_location("profile_bundle", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert BUNDLE == module.bundle()


@pytest.mark.parametrize("kind", BUNDLE["schemas"])
def test_schemas_and_examples_are_valid(kind):
    VALIDATORS[kind].check_schema(BUNDLE["schemas"][kind])
    assert not validate_document(BUNDLE["examples"][kind])


@pytest.mark.parametrize("bad", [None, [], {}, {"kind": []}, {"kind": {}}, {"kind":"Unknown"}])
def test_invalid_kind_returns_validation_error(bad):
    assert client().post("/api/v1/profile-spec/validate", content=json.dumps(bad)).json()["valid"] is False


def test_device_names_and_runtime_values_cannot_leak_into_static_contracts():
    service = copy.deepcopy(BUNDLE["examples"]["ServiceProfile"])
    service["spec"]["compatibleDevices"] = ["jetson"]
    assert validate_document(service)
    device = copy.deepcopy(BUNDLE["examples"]["DeviceProfile"])
    device["spec"]["cpuUsage"] = 0.2
    assert validate_document(device)


@pytest.mark.parametrize("value", ["0Gi", "-1Gi", "4GB", "NaN", "4GiB"])
def test_bad_memory_quantities_rejected(value):
    doc = copy.deepcopy(BUNDLE["examples"]["ServiceProfile"])
    doc["spec"]["resources"]["minimum"]["memory"]["capacity"] = value
    assert validate_document(doc)


def test_cross_tier_units_and_latency():
    doc = copy.deepcopy(BUNDLE["examples"]["ServiceProfile"])
    doc["spec"]["resources"]["recommended"]["memory"]["capacity"] = "4095Mi"
    assert any("recommended" in e["path"] for e in validate_document(doc))
    doc = copy.deepcopy(BUNDLE["examples"]["ServiceProfile"])
    doc["spec"]["qos"]["latency"]["targetMs"] = 3000
    assert validate_document(doc)


def test_projection_preserves_unknowns_shares_profiles_and_separates_reservations():
    result = observation([node("one"), node("two")], now=NOW)
    assert len(result["profiles"]) == 1
    assert len(result["devices"]) == 2
    p = result["profiles"][0]
    assert p["spec"]["hardware"]["cpu"]["cores"] is None
    assert p["spec"]["runtime"]["backends"] is None
    assert not result["registered"]
    for document in result["profiles"] + result["states"]:
        assert not validate_document(document)
    assert result["states"][0]["status"]["reservation"]["available"]["cpuCores"] == 4


@pytest.mark.parametrize("offset", [-61, 1])
def test_stale_or_future_metrics_are_unavailable(offset):
    result = observation([node(observed_at=NOW+timedelta(seconds=offset))], now=NOW)
    assert result["states"][0]["status"]["utilization"] is None


def test_comparison_never_grants_execution_and_explains_mismatch():
    result = observation([node(), node("x86", "amd64")], now=NOW)
    candidates = compare(BUNDLE["examples"]["ServiceProfile"], result)
    assert candidates[0]["status"] == "needs-verification"
    assert candidates[1]["status"] == "excluded"
    assert "architecture_mismatch" in candidates[1]["reasons"]
    assert all(c["executionAllowed"] is False for c in candidates)


def test_api_distinguishes_failure_from_empty_and_never_persists():
    async def unavailable(): raise RuntimeError("test source failed")
    c = client(unavailable)
    response = c.get("/api/v1/profile-spec/observations")
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["observationError"] == "node_source_unavailable"
    doc = BUNDLE["examples"]["ServiceProfile"]
    assert c.post("/api/v1/profile-spec/compare", json=doc).json()["observationError"]
    result = c.post("/api/v1/profile-spec/validate", json=doc).json()
    assert result["valid"] and result["persisted"] is False
    assert c.delete("/api/v1/profile-spec").status_code == 405


@pytest.mark.parametrize("raw", ['{"kind":NaN}', '{"kind":1e999}', '{', '[[[['])
def test_malformed_or_nonfinite_json_is_client_error(raw):
    assert client().post("/api/v1/profile-spec/validate", content=raw).status_code == 400


def test_request_size_and_wrong_compare_kind():
    c = client()
    assert c.post("/api/v1/profile-spec/validate", content=" "*65537).status_code == 413
    assert c.post("/api/v1/profile-spec/compare", json=BUNDLE["examples"]["DeviceProfile"]).status_code == 422


@pytest.mark.parametrize("invalid_time", ["invalid", "2026-09-30", "2026-09-30T00:00:00", "2026-02-30T00:00:00Z"])
def test_runtime_timestamp_requires_rfc3339_with_timezone(invalid_time):
    doc = copy.deepcopy(BUNDLE["examples"]["RuntimeState"])
    doc["status"]["observedAt"] = invalid_time
    assert validate_document(doc)


def test_profile_reference_version_is_validated():
    doc = copy.deepcopy(BUNDLE["examples"]["RuntimeState"])
    doc["metadata"]["profileRef"]["version"] = "unversioned"
    assert validate_document(doc)


def test_network_requirement_is_not_silently_satisfied():
    doc = copy.deepcopy(BUNDLE["examples"]["ServiceProfile"])
    doc["spec"]["resources"]["minimum"]["network"] = {"bandwidthMbps":100}
    doc["spec"]["resources"]["recommended"]["network"] = {"bandwidthMbps":200}
    assert not validate_document(doc)
    result = compare(doc, observation([node()], now=NOW))
    assert "network_capacity_unreported" in result[0]["reasons"]
