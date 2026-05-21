import importlib.util
import sys
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "edge-orch" / "raw-stream-bridge" / "raw_stream_bridge" / "core.py"


def load_core():
    spec = importlib.util.spec_from_file_location("raw_stream_bridge_core", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_normalizes_factory_device_topic_to_single_sample():
    core = load_core()

    samples = core.normalize_mqtt_message(
        "factory/devices/env-arduino-temperature-01/telemetry",
        b'{"sensor":"temperature","value":28.1,"edge_node":"etri-dev0001-jetorn","timestamp":1710000000000}',
        received_at_ms=1710000000123,
    )

    assert len(samples) == 1
    sample = samples[0]
    assert sample.device_id == "env-arduino-temperature-01"
    assert sample.sensor == "temperature"
    assert sample.value == 28.1
    assert sample.edge_node == "etri-dev0001-jetorn"
    assert sample.timestamp_ms == 1710000000000
    assert sample.received_at_ms == 1710000000123


def test_normalizes_axis_payload_to_multiple_samples():
    core = load_core()

    samples = core.normalize_mqtt_message(
        "factory/devices/vib-arduino-acceleration-01/telemetry",
        b'{"edge_node":"etri-dev0001-jetorn","x":0.1,"y":0.2,"z":0.3}',
        received_at_ms=1710000000123,
    )

    assert [(sample.sensor, sample.value) for sample in samples] == [("x", 0.1), ("y", 0.2), ("z", 0.3)]


def test_builds_redis_stream_and_latest_records():
    core = load_core()
    sample = core.Sample(
        device_id="env-arduino-temperature-01",
        sensor="temperature",
        value=28.1,
        edge_node="etri-dev0001-jetorn",
        topic="factory/devices/env-arduino-temperature-01/telemetry",
        timestamp_ms=1710000000000,
        received_at_ms=1710000000123,
    )

    stream_fields = core.to_redis_stream_fields(sample)
    latest_key, latest_fields = core.to_redis_latest_record(sample, prefix="telemetry:latest")

    assert stream_fields["device_id"] == "env-arduino-temperature-01"
    assert stream_fields["sensor"] == "temperature"
    assert stream_fields["value"] == "28.1"
    assert latest_key == "telemetry:latest:env-arduino-temperature-01:temperature"
    assert latest_fields["received_at"] == "1710000000123"


def test_builds_influx_point_line_protocol_without_write_time_as_sample_time():
    core = load_core()
    sample = core.Sample(
        device_id="env-arduino-temperature-01",
        sensor="temperature",
        value=28.1,
        edge_node="etri-dev0001-jetorn",
        topic="factory/devices/env-arduino-temperature-01/telemetry",
        timestamp_ms=1710000000000,
        received_at_ms=1710000000123,
    )

    line = core.to_line_protocol(sample, measurement="raw_sensor_telemetry")

    assert line.startswith("raw_sensor_telemetry,")
    assert "device_id=env-arduino-temperature-01" in line
    assert "sensor=temperature" in line
    assert "value=28.1" in line
    assert line.endswith("1710000000000000000")
