from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from virtual_device.adapters.base import AdapterConnectionError
from virtual_device.adapters.fake import FakeAdapter
from virtual_device.config import DeviceProfile, load_profile
from virtual_device.publisher import InMemoryPublisher, PublishError, PublishRecord
from virtual_device.runtime import VirtualDeviceRuntime

from test_config import VALID_PROFILE, write_profile


class ManualClock:
    def __init__(self, now: float = 1710000001) -> None:
        self.now = now
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def profile(tmp_path: Path) -> DeviceProfile:
    return load_profile(write_profile(tmp_path, VALID_PROFILE))


def sample(source_ts: int = 1710000000, x: float = 0.12) -> dict[str, object]:
    return {
        "sensor": "vibration",
        "device_id": "etri-pd0001-arduino",
        "source_ts": source_ts,
        "x": x,
        "y": 0.08,
        "z": 0.91,
    }


def payloads(records: list[PublishRecord], topic: str) -> list[dict[str, object]]:
    return [json.loads(record.payload) for record in records if record.topic == topic]


def run_runtime(
    device_profile: DeviceProfile,
    adapter: FakeAdapter,
    *,
    max_iterations: int,
    clock: ManualClock | None = None,
) -> tuple[InMemoryPublisher, ManualClock]:
    runtime_clock = clock or ManualClock()
    publisher = InMemoryPublisher()
    runtime = VirtualDeviceRuntime(
        device_profile,
        adapter=adapter,
        publisher=publisher,
        clock=runtime_clock,
        sleeper=runtime_clock.sleep,
    )
    runtime.run(max_iterations=max_iterations)
    return publisher, runtime_clock


def test_fake_adapter_runs_end_to_end_and_emits_telemetry_and_status(tmp_path: Path) -> None:
    device_profile = profile(tmp_path)
    publisher, _ = run_runtime(device_profile, FakeAdapter([sample()]), max_iterations=1)

    telemetry = payloads(publisher.records, device_profile.output.mqtt.telemetry_topic)
    statuses = payloads(publisher.records, device_profile.output.mqtt.status_topic)

    assert len(telemetry) == 1
    assert telemetry[0]["sequence"] == 1
    assert telemetry[0]["sourceTimestamp"] == 1710000000
    assert telemetry[0]["collectedAt"] == 1710000001
    assert telemetry[0]["data"]["acceleration_x"] == {"value": 0.12, "unit": "g"}
    assert [status["phase"] for status in statuses][0] == "starting"
    assert any(status["phase"] == "running" and status["dataStatus"] == "fresh" for status in statuses)
    assert statuses[-1]["phase"] == "stopped"
    assert statuses[-1]["connection"] == "disconnected"


def test_runtime_suppresses_duplicate_but_accepts_same_value_at_new_timestamp(tmp_path: Path) -> None:
    device_profile = profile(tmp_path)
    adapter = FakeAdapter([sample(), sample(), sample(source_ts=1710000001)])

    publisher, _ = run_runtime(device_profile, adapter, max_iterations=3)

    telemetry = payloads(publisher.records, device_profile.output.mqtt.telemetry_topic)
    assert [item["sequence"] for item in telemetry] == [1, 2]
    assert [item["sourceTimestamp"] for item in telemetry] == [1710000000, 1710000001]


def test_same_timestamp_with_different_quality_payload_is_not_suppressed(tmp_path: Path) -> None:
    device_profile = profile(tmp_path)
    missing_y = sample()
    missing_y.pop("y")
    invalid_y = sample()
    invalid_y["y"] = "not-a-float"

    publisher, _ = run_runtime(
        device_profile,
        FakeAdapter([missing_y, invalid_y]),
        max_iterations=2,
    )

    telemetry = payloads(publisher.records, device_profile.output.mqtt.telemetry_topic)
    assert len(telemetry) == 2
    assert telemetry[0]["quality"]["errors"] == ["missing_required_property:y"]
    assert telemetry[1]["quality"]["errors"] == ["invalid_property:y:float"]


def test_invalid_json_does_not_terminate_runtime(tmp_path: Path) -> None:
    device_profile = profile(tmp_path)
    adapter = FakeAdapter(["not-json", sample()])

    publisher, _ = run_runtime(device_profile, adapter, max_iterations=2)

    telemetry = payloads(publisher.records, device_profile.output.mqtt.telemetry_topic)
    statuses = payloads(publisher.records, device_profile.output.mqtt.status_topic)
    assert len(telemetry) == 1
    assert any(status["phase"] == "degraded" and "invalid JSON" in status["lastError"] for status in statuses)
    assert any(status["phase"] == "running" and status["lastError"] is None for status in statuses)


def test_missing_required_mapping_is_published_with_invalid_quality(tmp_path: Path) -> None:
    device_profile = profile(tmp_path)
    incomplete = sample()
    incomplete.pop("y")

    publisher, _ = run_runtime(device_profile, FakeAdapter([incomplete]), max_iterations=1)

    telemetry = payloads(publisher.records, device_profile.output.mqtt.telemetry_topic)
    statuses = payloads(publisher.records, device_profile.output.mqtt.status_topic)
    assert telemetry[0]["quality"]["valid"] is False
    assert "missing_required_property:y" in telemetry[0]["quality"]["errors"]
    assert any(status["phase"] == "degraded" for status in statuses)


def test_adapter_disconnect_emits_degraded_status_and_waits_before_retry(tmp_path: Path) -> None:
    device_profile = profile(tmp_path)
    adapter = FakeAdapter([AdapterConnectionError("serial unplugged")])

    publisher, clock = run_runtime(device_profile, adapter, max_iterations=1)

    statuses = payloads(publisher.records, device_profile.output.mqtt.status_topic)
    degraded = [status for status in statuses if status["phase"] == "degraded"]
    assert degraded[-1]["connection"] == "disconnected"
    assert degraded[-1]["dataStatus"] == "stale"
    assert degraded[-1]["lastError"] == "serial unplugged"
    assert clock.sleeps == [1.0]


def test_adapter_start_retries_with_exponential_backoff(tmp_path: Path) -> None:
    device_profile = profile(tmp_path)
    adapter = FakeAdapter([sample()], fail_start_times=2)

    publisher, clock = run_runtime(device_profile, adapter, max_iterations=3)

    telemetry = payloads(publisher.records, device_profile.output.mqtt.telemetry_topic)
    assert adapter.start_calls == 3
    assert clock.sleeps == [1.0, 2.0]
    assert len(telemetry) == 1


def test_reconnect_backoff_is_capped(tmp_path: Path) -> None:
    device_profile = profile(tmp_path)
    device_profile = replace(
        device_profile,
        runtime=replace(
            device_profile.runtime,
            reconnect_backoff_seconds=1,
            reconnect_backoff_max_seconds=2,
        ),
    )
    adapter = FakeAdapter([], fail_start_times=4)

    _, clock = run_runtime(device_profile, adapter, max_iterations=4)

    assert clock.sleeps == [1, 2, 2, 2]


def test_heartbeat_marks_connected_device_stale_after_offline_threshold(tmp_path: Path) -> None:
    device_profile = profile(tmp_path)
    device_profile = replace(
        device_profile,
        runtime=replace(
            device_profile.runtime,
            heartbeat_seconds=10,
            offline_after_seconds=30,
            idle_sleep_seconds=10,
        ),
    )
    clock = ManualClock(now=1000)

    publisher, _ = run_runtime(
        device_profile,
        FakeAdapter([]),
        max_iterations=4,
        clock=clock,
    )

    statuses = payloads(publisher.records, device_profile.output.mqtt.status_topic)
    degraded = [status for status in statuses if status["phase"] == "degraded"]
    assert degraded
    assert degraded[-1]["connection"] == "connected"
    assert degraded[-1]["dataStatus"] == "stale"
    assert degraded[-1]["lastSeenAt"] is None


def test_status_payload_contains_only_runtime_snapshot_fields(tmp_path: Path) -> None:
    device_profile = profile(tmp_path)

    publisher, _ = run_runtime(device_profile, FakeAdapter([sample()]), max_iterations=1)

    status = payloads(publisher.records, device_profile.output.mqtt.status_topic)[-1]
    assert set(status) == {
        "virtualDeviceId",
        "physicalDeviceId",
        "phase",
        "connection",
        "dataStatus",
        "lastSeenAt",
        "lastError",
    }


class TelemetryFailingPublisher(InMemoryPublisher):
    def __init__(self, telemetry_topic: str) -> None:
        super().__init__()
        self.telemetry_topic = telemetry_topic

    def publish(self, topic: str, payload: str, *, qos: int) -> None:
        if topic == self.telemetry_topic:
            raise PublishError("telemetry output unavailable")
        super().publish(topic, payload, qos=qos)


def test_unrecoverable_output_failure_emits_failed_phase(tmp_path: Path) -> None:
    device_profile = profile(tmp_path)
    publisher = TelemetryFailingPublisher(device_profile.output.mqtt.telemetry_topic)
    clock = ManualClock()
    runtime = VirtualDeviceRuntime(
        device_profile,
        adapter=FakeAdapter([sample()]),
        publisher=publisher,
        clock=clock,
        sleeper=clock.sleep,
    )

    with pytest.raises(PublishError, match="telemetry output unavailable"):
        runtime.run(max_iterations=1)

    statuses = payloads(publisher.records, device_profile.output.mqtt.status_topic)
    assert any(status["phase"] == "failed" for status in statuses)
    assert statuses[-1]["phase"] == "stopped"
