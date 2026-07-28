import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.catalog import RuntimeTemplateCatalog
from app.discovery import DeviceCandidateRegistry
from app.discovery_models import DiscoveryPlan
from app.discovery_store import SQLiteDiscoveryStore

from fakes import FakeKubernetesGateway


BASE = Path(__file__).resolve().parents[1]


def sense_hat_plan() -> dict:
    return {
        "nodeId": "etri-dev0003-raspi5",
        "version": 2,
        "i2c": {
            "enabled": True,
            "buses": [1],
            "allowedAddresses": ["0x1c", "0x6a"],
            "activeProbeEnabled": True,
            "identificationRules": [
                {
                    "identities": [
                        {
                            "address": "0x1c",
                            "register": "0x0f",
                            "expected": "0x3d",
                        },
                        {
                            "address": "0x6a",
                            "register": "0x0f",
                            "expected": "0x68",
                        },
                    ],
                    "model": "raspberry-pi-sense-hat-v1",
                    "profile": "etri-sensehat-gyroscope",
                    "capabilities": ["temperature", "gyroscope"],
                }
            ],
        },
    }


def test_composite_i2c_plan_is_valid_and_serializes_for_the_agent():
    plan = DiscoveryPlan.model_validate(sense_hat_plan())

    payload = plan.model_dump(
        by_alias=True,
        mode="json",
        exclude_none=True,
    )

    identities = payload["i2c"]["identificationRules"][0]["identities"]
    assert [(item["address"], item["expected"]) for item in identities] == [
        ("0x1c", "0x3d"),
        ("0x6a", "0x68"),
    ]


def test_active_i2c_plan_rejects_a_non_allowlisted_identity_address():
    payload = sense_hat_plan()
    payload["i2c"]["allowedAddresses"] = ["0x1c"]

    with pytest.raises(
        ValidationError,
        match="non-allowlisted address",
    ):
        DiscoveryPlan.model_validate(payload)


def test_newer_git_plan_seeds_over_an_older_persisted_plan(tmp_path):
    store = SQLiteDiscoveryStore(tmp_path / "discovery.db")
    store.put_plan(
        DiscoveryPlan(
            node_id="etri-dev0003-raspi5",
            version=1,
            updated_at=datetime.now(timezone.utc),
        )
    )
    plan_path = tmp_path / "plans.json"
    plan_path.write_text(
        json.dumps({"plans": [sense_hat_plan()]}),
        encoding="utf-8",
    )

    DeviceCandidateRegistry(
        RuntimeTemplateCatalog.load(
            BASE / "config" / "runtime_templates.json"
        ),
        FakeKubernetesGateway(),
        store=store,
        plans_path=plan_path,
    )

    seeded = store.get_plan("etri-dev0003-raspi5")
    assert seeded is not None
    assert seeded.version == 2
    assert seeded.i2c.active_probe_enabled is True


def test_raspberry_serial_seed_plans_are_passive_inventory_only():
    payload = json.loads(
        (BASE / "config" / "discovery_plans.json").read_text(
            encoding="utf-8"
        )
    )
    plans = {
        item["nodeId"]: DiscoveryPlan.model_validate(item)
        for item in payload["plans"]
    }

    for node_id in {"etri-dev0002-raspi5", "etri-dev0003-raspi5"}:
        serial = plans[node_id].serial
        assert serial.enabled is True
        assert serial.allowed_vid_pid == []
        assert serial.manifest_probe_enabled is False
    assert plans["etri-dev0002-raspi5"].version == 2
    assert plans["etri-dev0003-raspi5"].version == 3
