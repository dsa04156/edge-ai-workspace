import asyncio
from datetime import datetime, timezone
from io import StringIO

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.local_data import ACCELERATION_SOURCES, LocalDataClient
from app.replay import PumpReplayDataset, ReplayDatasetError, create_replay_app
from app.runtime import AnomalyRuntime
from app.simulator import generate_pump_samples, write_jsonl
from app.storage import ResultStore


def replay_content(count: int = 4) -> str:
    records = generate_pump_samples(
        count=count,
        interval_ms=500,
        anomaly_start=2 if count > 2 else None,
        anomaly_length=1,
        asset_id="virtual-pump-001",
        device_id="pump-simulator-001",
        start=datetime(2026, 8, 3, tzinfo=timezone.utc),
        seed=7,
    )
    output = StringIO()
    write_jsonl(records, output)
    return output.getvalue()


def test_replay_server_exposes_contract_valid_data_as_local_data_v3() -> None:
    dataset = PumpReplayDataset.from_jsonl(replay_content())
    source = ACCELERATION_SOURCES[0]

    with TestClient(create_replay_app(dataset)) as client:
        status = client.get("/api/v1/replay/status")
        response = client.get(
            f"/api/v3/localdata/device/name/{source.device_name}/"
            f"resource/name/{source.resource_name}",
            params={"from": dataset.first_origin, "to": dataset.last_origin},
        )

    assert status.status_code == 200
    assert status.json()["recordCount"] == 4
    assert response.status_code == 200
    assert response.json()["count"] == 4
    assert {row["valueType"] for row in response.json()["samples"]} == {"Float64"}


def test_local_data_client_consumes_replay_server_float64_contract() -> None:
    dataset = PumpReplayDataset.from_jsonl(replay_content())
    replay_app = create_replay_app(dataset)
    source = ACCELERATION_SOURCES[0]

    async def run():
        from httpx import ASGITransport

        client = LocalDataClient(
            "http://replay.test",
            timeout_seconds=2,
            transport=ASGITransport(app=replay_app),
        )
        try:
            return await client.fetch(
                source,
                from_origin=dataset.first_origin,
                to_origin=dataset.last_origin,
            )
        finally:
            await client.close()

    rows = asyncio.run(run())

    assert len(rows) == 4
    assert all(row.value_type == "Float64" for row in rows)
    assert all(isinstance(row.value, float) for row in rows)


def test_replay_rebases_relative_timing_without_changing_identity() -> None:
    original = PumpReplayDataset.from_jsonl(replay_content())
    rebased = PumpReplayDataset.from_jsonl(
        replay_content(),
        rebase_origin_ns=10_000_000_000,
    )

    assert rebased.first_origin == 10_000_000_000
    assert rebased.last_origin - rebased.first_origin == (
        original.last_origin - original.first_origin
    )
    assert rebased.records[0].event_id == original.records[0].event_id


def test_replay_rejects_duplicate_identity_and_invalid_json_line() -> None:
    line = replay_content(count=1).strip()
    with pytest.raises(ReplayDatasetError, match="unique"):
        PumpReplayDataset.from_jsonl(f"{line}\n{line}\n")
    with pytest.raises(ReplayDatasetError, match="line 1"):
        PumpReplayDataset.from_jsonl('{"schemaVersion":"wrong"}\n')


def test_simulator_is_deterministic_for_same_seed() -> None:
    assert replay_content() == replay_content()


def test_replay_flows_through_runtime_into_restart_safe_result_store(tmp_path) -> None:
    from httpx import ASGITransport

    dataset = PumpReplayDataset.from_jsonl(replay_content(count=4))
    store_path = tmp_path / "results.db"
    runtime = AnomalyRuntime(
        settings=Settings(
            warmup_samples=1,
            vibration_window_samples=2,
            temperature_window_samples=2,
            result_db_path=str(store_path),
        ),
        client=LocalDataClient(
            "http://replay.test",
            timeout_seconds=2,
            transport=ASGITransport(app=create_replay_app(dataset)),
        ),
        result_store=ResultStore(str(store_path), retention_rows=100),
    )

    asyncio.run(runtime.poll_once(now_ns=dataset.last_origin + 1))

    assert runtime.status(now_ns=dataset.last_origin + 1).input_state == "fresh"
    assert [row.origin for row in runtime.results(10)] == [
        dataset.first_origin + offset * 500_000_000 for offset in range(4)
    ]
    assert {row.input_contract for row in runtime.results(10)} == {
        "okdong.pump-motor.telemetry/v1"
    }
    assert runtime.storage_status().result_count == 4
    asyncio.run(runtime.stop())

    reopened = ResultStore(str(store_path), retention_rows=100)
    assert reopened.status().result_count == 4
    assert len(reopened.results(10)) == 4
    reopened.close()


def test_replay_exercises_anomaly_open_and_clear_end_to_end() -> None:
    from httpx import ASGITransport

    records = generate_pump_samples(
        count=120,
        interval_ms=500,
        anomaly_start=80,
        anomaly_length=10,
        asset_id="virtual-pump-001",
        device_id="pump-simulator-001",
        start=datetime(2026, 8, 3, tzinfo=timezone.utc),
        seed=20260803,
    )
    dataset = PumpReplayDataset(records)
    runtime = AnomalyRuntime(
        settings=Settings(
            warmup_samples=30,
            vibration_window_samples=20,
            temperature_window_samples=10,
        ),
        client=LocalDataClient(
            "http://replay.test",
            timeout_seconds=2,
            transport=ASGITransport(app=create_replay_app(dataset)),
        ),
        result_store=ResultStore(":memory:", retention_rows=1_000),
    )

    asyncio.run(runtime.poll_once(now_ns=dataset.last_origin + 1))

    assert runtime.storage_status().result_count == 120
    assert [row.transition for row in runtime.alerts(10)] == [
        "cleared",
        "opened",
    ]
    assert runtime.storage_status().open_alert_count == 0
    assert any(row.anomaly for row in runtime.results(120))
    asyncio.run(runtime.stop())
