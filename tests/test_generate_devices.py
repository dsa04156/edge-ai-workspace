import importlib.util
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "edge-device" / "scripts" / "generate_devices.py"


def load_generate_devices():
    spec = importlib.util.spec_from_file_location("generate_devices", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GenerateDevicesInfluxPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_generate_devices()

    def test_act_health_is_stored_to_influx_for_db_timestamp_liveness(self):
        self.assertTrue(self.module.should_store_to_influx("act", "health"))
        self.assertTrue(self.module.should_store_to_influx("rpi-act", "health"))

    def test_act_power_is_not_stored_to_influx_by_default(self):
        self.assertFalse(self.module.should_store_to_influx("act", "power"))

    def test_raw_sensor_values_are_stored_to_influx(self):
        self.assertTrue(self.module.should_store_to_influx("env", "temperature"))
        self.assertTrue(self.module.should_store_to_influx("env", "humidity"))
        self.assertTrue(self.module.should_store_to_influx("vib", "vibration"))


if __name__ == "__main__":
    unittest.main()
