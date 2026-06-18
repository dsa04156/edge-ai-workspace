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


class CheckDashboardApiVirtualResourceTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_check_dashboard_api()

    def test_zero_runtime_virtual_resource_profile_is_valid(self):
        payload = {
            "mode": "read_only",
            "scope": "resource_augmentation_virtual_devices",
            "resources": [
                {
                    "id": "vd-aihat-inference",
                    "display_name": "AI HAT Inference",
                    "node": "etri-dev0002-raspi5",
                    "resource_type": "ai-hat",
                    "desired_instances": 1,
                    "observed_instances": 0,
                    "free_instances": 0,
                    "allocated_instances": 0,
                    "status": "configured_not_running",
                    "twin": {"binding_state": "not_running"},
                }
            ],
        }

        errors, warnings = self.module.check_virtual_resources(payload)

        self.assertEqual(errors, [])
        self.assertEqual(warnings, [])

    def test_virtual_resource_payload_requires_read_only_scope(self):
        payload = {"mode": "control", "scope": "virtual_sensors", "resources": []}

        errors, _ = self.module.check_virtual_resources(payload)

        self.assertIn("virtual resources mode='control', expected 'read_only'", errors)
        self.assertIn("virtual resources scope='virtual_sensors', expected 'resource_augmentation_virtual_devices'", errors)

    def test_sensehat_input_source_uses_third_raspberry_pi_node(self):
        self.assertEqual(self.module.expected_node("env-sensehat-temperature-01"), "etri-dev0003-raspi5")
        self.assertEqual(self.module.expected_node("imu-sensehat-gyroscope-01"), "etri-dev0003-raspi5")


if __name__ == "__main__":
    unittest.main()
