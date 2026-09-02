from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.execution_ownership import (
    ExecutionOwnershipEngine,
    ExecutionOwnershipError,
    OwnershipContractCatalog,
)
from app.kube import KubeDeploymentError


NOW = datetime(2026, 8, 26, 3, 0, tzinfo=timezone.utc)
CATALOG = (
    Path(__file__).resolve().parents[1]
    / "app/config/execution_ownership_contracts.json"
)


def _lease(holder="sensor-anomaly-demo", *, renew=NOW, rv="1"):
    return {
        "metadata": {
            "name": "sensor-anomaly-demo-execution",
            "namespace": "edgex-edge",
            "resourceVersion": rv,
            "labels": {
                "edge-ai.io/managed-by": "runtime-execution-controller",
                "edge-ai.io/service-id": "sensor-anomaly-demo",
            },
        },
        "spec": {
            "holderIdentity": holder,
            "leaseDurationSeconds": 15,
            "acquireTime": renew,
            "renewTime": renew,
            "leaseTransitions": 2,
        },
    }


class FakeKube:
    def __init__(self, lease, *, conflicts=0):
        self.lease = deepcopy(lease)
        self.conflicts = conflicts
        self.replacements = []

    async def read_lease(self, namespace, name):
        return deepcopy(self.lease)

    async def replace_lease(self, namespace, name, body):
        self.replacements.append(deepcopy(body))
        if self.conflicts:
            self.conflicts -= 1
            self.lease["metadata"]["resourceVersion"] = str(
                int(self.lease["metadata"]["resourceVersion"]) + 1
            )
            raise KubeDeploymentError("execution_lease_cas_conflict", "conflict")
        assert body["metadata"]["resourceVersion"] == self.lease["metadata"][
            "resourceVersion"
        ]
        self.lease = deepcopy(body)
        self.lease["metadata"]["resourceVersion"] = str(
            int(body["metadata"]["resourceVersion"]) + 1
        )
        return deepcopy(self.lease)


def _contract():
    catalog = OwnershipContractCatalog.load(CATALOG)
    contract, error = catalog.resolve("sensor-anomaly-demo")
    assert error is None and contract is not None
    return contract


def test_git_approved_lease_contract_loads() -> None:
    contract = _contract()

    assert contract.mode == "runtime-lease"
    assert contract.lease_name == "sensor-anomaly-demo-execution"
    assert contract.source.holder_identity == "sensor-anomaly-demo"


def test_handoff_and_rollback_use_current_resource_version_cas() -> None:
    kube = FakeKube(_lease())
    engine = ExecutionOwnershipEngine(kube, now=lambda: NOW)

    handed_off = asyncio.run(
        engine.handoff(contract=_contract(), candidate_name="candidate-a")
    )
    rolled_back = asyncio.run(
        engine.rollback(contract=_contract(), ownership=handed_off)
    )

    assert handed_off.before.holder_identity == "sensor-anomaly-demo"
    assert kube.replacements[0]["metadata"]["resourceVersion"] == "1"
    assert kube.replacements[0]["spec"]["holderIdentity"] == "candidate-a"
    assert kube.replacements[1]["metadata"]["resourceVersion"] == "2"
    assert kube.replacements[1]["spec"]["holderIdentity"] == "sensor-anomaly-demo"
    assert rolled_back.active_owner == "source"
    assert rolled_back.rolled_back_at == NOW


def test_handoff_retries_only_resource_version_conflict() -> None:
    kube = FakeKube(_lease(), conflicts=1)
    engine = ExecutionOwnershipEngine(kube, now=lambda: NOW)

    result = asyncio.run(
        engine.handoff(contract=_contract(), candidate_name="candidate-a")
    )

    assert result.active_owner == "candidate"
    assert [item["metadata"]["resourceVersion"] for item in kube.replacements] == [
        "1",
        "2",
    ]


def test_expired_or_unexpected_holder_is_blocked_without_mutation() -> None:
    expired = FakeKube(_lease(renew=NOW - timedelta(seconds=16)))
    with pytest.raises(ExecutionOwnershipError) as expired_error:
        asyncio.run(
            ExecutionOwnershipEngine(expired, now=lambda: NOW).handoff(
                contract=_contract(), candidate_name="candidate-a"
            )
        )
    assert expired_error.value.reason_code == "execution_lease_expired"
    assert expired.replacements == []

    unexpected = FakeKube(_lease(holder="other-plan"))
    with pytest.raises(ExecutionOwnershipError) as conflict_error:
        asyncio.run(
            ExecutionOwnershipEngine(unexpected, now=lambda: NOW).handoff(
                contract=_contract(), candidate_name="candidate-a"
            )
        )
    assert conflict_error.value.reason_code == "execution_ownership_state_conflict"
    assert unexpected.replacements == []
