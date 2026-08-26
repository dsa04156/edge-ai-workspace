from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from app.config import Settings
from app.execution_ownership import (
    ExecutionOwnershipGuard,
    KubernetesLeaseClient,
    LeaseConflictError,
)
from app.local_data import ACCELERATION_SOURCES, LocalDataSource
from app.models import AxisSample
from app.runtime import AnomalyRuntime
from app.storage import ResultStore


NOW = datetime(2026, 8, 26, 3, 0, tzinfo=timezone.utc)


def _lease(holder: str, *, renew_time: datetime | None = NOW, rv: str = "1"):
    spec = {
        "holderIdentity": holder,
        "leaseDurationSeconds": 15,
        "leaseTransitions": 0,
    }
    if renew_time is not None:
        spec["renewTime"] = renew_time.isoformat().replace("+00:00", "Z")
    return {
        "metadata": {"name": "sensor-anomaly-demo-execution", "resourceVersion": rv},
        "spec": spec,
    }


class FakeLeaseClient:
    def __init__(self, lease, *, conflict: bool = False):
        self.lease = deepcopy(lease)
        self.conflict = conflict
        self.replace_calls = []
        self.closed = False

    async def read(self, namespace, name):
        return deepcopy(self.lease)

    async def replace(self, namespace, name, body):
        self.replace_calls.append(deepcopy(body))
        if self.conflict:
            raise LeaseConflictError("conflict")
        assert body["metadata"]["resourceVersion"] == self.lease["metadata"][
            "resourceVersion"
        ]
        self.lease = deepcopy(body)
        self.lease["metadata"]["resourceVersion"] = str(
            int(body["metadata"]["resourceVersion"]) + 1
        )
        return deepcopy(self.lease)

    async def close(self):
        self.closed = True


def _settings(owner: str, mode: str = "SHADOW") -> Settings:
    return Settings(
        execution_mode=mode,
        execution_ownership_enabled=True,
        execution_owner_id=owner,
        execution_lease_duration_seconds=15,
        execution_lease_poll_interval_seconds=2,
    )


def test_custom_api_url_does_not_depend_on_reserved_kubernetes_host(
    monkeypatch,
    tmp_path,
) -> None:
    token_path = tmp_path / "token"
    ca_path = tmp_path / "ca.crt"
    token_path.write_text("test-token", encoding="utf-8")
    ca_path.write_text("test-ca", encoding="utf-8")
    captured = {}
    sentinel = object()

    def fake_async_client(**kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "")
    monkeypatch.setattr(
        "app.execution_ownership.httpx.AsyncClient",
        fake_async_client,
    )

    client = KubernetesLeaseClient(
        api_url="https://192.168.0.56:6443",
        token_path=token_path,
        ca_path=ca_path,
    )

    assert client._client is sentinel
    assert captured["base_url"] == "https://192.168.0.56:6443"
    assert captured["headers"] == {"Authorization": "Bearer test-token"}


def test_exact_unexpired_holder_renews_with_resource_version_cas() -> None:
    client = FakeLeaseClient(_lease("source"))
    guard = ExecutionOwnershipGuard(_settings("source"), client, now=lambda: NOW)

    state = asyncio.run(guard.refresh_once())

    assert state.effective_mode == "ACTIVE"
    assert state.lease_valid is True
    assert state.resource_version == "2"
    assert client.replace_calls[0]["metadata"]["resourceVersion"] == "1"


def test_non_holder_runs_shadow_without_production_authority() -> None:
    client = FakeLeaseClient(_lease("source"))
    guard = ExecutionOwnershipGuard(_settings("candidate"), client, now=lambda: NOW)

    state = asyncio.run(guard.refresh_once())

    assert state.effective_mode == "SHADOW"
    assert state.lease_valid is True
    assert state.holder_identity == "source"
    assert client.replace_calls == []


def test_expired_holder_fails_closed_and_is_not_resurrected() -> None:
    client = FakeLeaseClient(_lease("source", renew_time=NOW - timedelta(seconds=16)))
    guard = ExecutionOwnershipGuard(_settings("source"), client, now=lambda: NOW)

    state = asyncio.run(guard.refresh_once())

    assert state.effective_mode == "STANDBY"
    assert state.lease_valid is False
    assert state.reason_code == "execution_lease_expired"
    assert client.replace_calls == []

    candidate = ExecutionOwnershipGuard(
        _settings("candidate"),
        FakeLeaseClient(_lease("source", renew_time=NOW - timedelta(seconds=16))),
        now=lambda: NOW,
    )
    candidate_state = asyncio.run(candidate.refresh_once())
    assert candidate_state.effective_mode == "STANDBY"
    assert candidate_state.lease_valid is False


def test_renew_conflict_fails_closed() -> None:
    client = FakeLeaseClient(_lease("source"), conflict=True)
    guard = ExecutionOwnershipGuard(_settings("source"), client, now=lambda: NOW)

    state = asyncio.run(guard.refresh_once())

    assert state.effective_mode == "STANDBY"
    assert state.lease_valid is False
    assert state.reason_code == "execution_lease_cas_conflict"


class FakeLocalDataClient:
    def __init__(self, rows):
        self.rows = rows

    async def fetch(
        self,
        source: LocalDataSource,
        from_origin: int | None,
        to_origin: int,
    ):
        return [
            row
            for row in self.rows[source.key]
            if (from_origin is None or row.origin >= from_origin)
            and row.origin <= to_origin
        ]

    async def close(self):
        return None


def test_shadow_inference_is_visible_but_never_persisted() -> None:
    origin = 1_000_000_000
    rows = {
        "x": [AxisSample(origin, "Int32", 3)],
        "y": [AxisSample(origin, "Int32", 4)],
        "z": [AxisSample(origin, "Int32", 0)],
        "temperature": [AxisSample(origin - 10, "Int32", 300)],
    }
    store = ResultStore(":memory:", 100)
    runtime = AnomalyRuntime(
        settings=Settings(warmup_samples=1, execution_mode="SHADOW"),
        client=FakeLocalDataClient(rows),
        sources=ACCELERATION_SOURCES,
        result_store=store,
    )

    asyncio.run(runtime.poll_once(now_ns=origin + 100))
    state = runtime.status(now_ns=origin + 100)

    assert state.execution_ownership.effective_mode == "SHADOW"
    assert state.counters.frames_processed == 0
    assert state.counters.shadow_frames_processed == 1
    assert state.latest is not None
    assert len(runtime.results(10)) == 1
    assert store.results(10) == []
