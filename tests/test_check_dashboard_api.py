import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "check_dashboard_api.py"


def load_check_dashboard_api():
    spec = importlib.util.spec_from_file_location("check_dashboard_api", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CheckDashboardApiTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_check_dashboard_api()

    def test_sensehat_input_source_uses_third_raspberry_pi_node(self):
        self.assertEqual(self.module.expected_node("env-sensehat-temperature-01"), "etri-dev0003-raspi5")
        self.assertEqual(self.module.expected_node("imu-sensehat-gyroscope-01"), "etri-dev0003-raspi5")

    def test_current_edgex_dashboard_contract_passes_without_legacy_mapper_fields(self):
        payload = {
            "generated_at": "2026-07-22T10:00:00Z",
            "kpis": {
                "registered_device_count": 1,
                "available_device_count": 1,
                "degraded_device_count": 0,
                "unavailable_device_count": 0,
                "edgex_connected_device_count": 1,
                "edgex_connection_ratio": 1.0,
                "edgex_operating_up_count": 1,
                "edgex_operating_down_count": 0,
                "edgex_operating_unknown_count": 0,
                "edgex_admin_unlocked_count": 1,
                "edgex_admin_locked_count": 0,
                "device_service_available_count": 1,
                "device_service_availability_ratio": 1.0,
                "core_data_event_device_count": 1,
                "fresh_core_data_event_device_count": 1,
                "stale_core_data_event_device_count": 0,
                "core_data_freshness_ratio": 1.0,
                "active_node_count": 1,
                "sla_risk_workflow_count": 0,
                "operator_focus_count": 0,
            },
            "devices": [
                {
                    "name": "virtual-temperature-001",
                    "source": "edgex",
                    "profile_name": "etri-arduino-temperature",
                    "device_service_name": "device-serial-jetson",
                    "protocol_names": ["serial"],
                    "admin_state": "UNLOCKED",
                    "operating_state": "UP",
                    "connection_state": "connected",
                    "device_service_available": True,
                    "latest_event_timestamp": "2026-07-22T10:00:00Z",
                    "latest_readings": [{"resource_name": "temperature_raw", "value": 277}],
                    "telemetry_freshness": "fresh",
                    "overall_status": "available",
                    "reason": "EdgeX device service is UP and latest Core Data event is fresh",
                    "node_name": "etri-dev0001-jetorn",
                }
            ],
            "nodes": [{"node_health": "unavailable"}],
        }

        errors, warnings = self.module.check_payload(payload, None)

        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_current_device_contract_requires_edgex_source(self):
        payload = {
            "kpis": {field: 0 for field in self.module.KPI_FIELDS},
            "devices": [{field: None for field in self.module.DEVICE_FIELDS if field != "source"}],
            "nodes": [],
        }

        errors, _ = self.module.check_payload(payload, None)

        self.assertIn("<unknown>: missing device field devices[].source", errors)


if __name__ == "__main__":
    unittest.main()
