import importlib.util
import json
import unittest
from pathlib import Path

MODULE_PATH = Path(__file__).resolve().parents[1] / "sensor-collector" / "serial_mqtt_collector.py"
spec = importlib.util.spec_from_file_location("serial_mqtt_collector", MODULE_PATH)
assert spec and spec.loader
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


class SerialMqttCollectorTest(unittest.TestCase):
    def test_duplicate_serial_sample_is_not_republished_with_new_received_at(self):
        state = collector.CollectorState()
        line = json.dumps({"sensor": "temperature", "device_id": "arduino-001", "value": 23.5, "ts": 1710000000})

        first = collector.build_publish_record(line, state, now=1000, edge_node="edge-a", site="etri")
        second = collector.build_publish_record(line, state, now=1060, edge_node="edge-a", site="etri")

        self.assertIsNotNone(first)
        self.assertIsNone(second)

    def test_new_source_timestamp_is_published_even_if_value_is_same(self):
        state = collector.CollectorState()
        first_line = json.dumps({"sensor": "temperature", "device_id": "arduino-001", "value": 23.5, "ts": 1710000000})
        second_line = json.dumps({"sensor": "temperature", "device_id": "arduino-001", "value": 23.5, "ts": 1710000060})

        first = collector.build_publish_record(first_line, state, now=1000, edge_node="edge-a", site="etri")
        second = collector.build_publish_record(second_line, state, now=1060, edge_node="edge-a", site="etri")

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertEqual(json.loads(second.payload)["source_ts"], 1710000060)

    def test_payload_uses_collector_received_at_without_overwriting_source_timestamp(self):
        state = collector.CollectorState()
        line = json.dumps({"sensor": "light", "device_id": "arduino-001", "value": 42, "timestamp": 1710000000})

        record = collector.build_publish_record(line, state, now=2000, edge_node="edge-a", site="etri")

        payload = json.loads(record.payload)
        self.assertEqual(payload["source_ts"], 1710000000)
        self.assertEqual(payload["collector_received_at"], 2000)
        self.assertNotIn("received_at", payload)

    def test_consecutive_identical_line_without_source_timestamp_is_suppressed(self):
        state = collector.CollectorState()
        line = json.dumps({"sensor": "magnetic", "device_id": "arduino-001", "value": 1})

        first = collector.build_publish_record(line, state, now=1000, edge_node="edge-a", site="etri")
        second = collector.build_publish_record(line, state, now=1001, edge_node="edge-a", site="etri")

        self.assertIsNotNone(first)
        self.assertIsNone(second)


if __name__ == "__main__":
    unittest.main()
