import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "edge-device" / "scripts" / "generate_devices.py"


def load_generate_devices():
    spec = importlib.util.spec_from_file_location("generate_devices", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class GenerateLegacyDevicesPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = load_generate_devices()

    def test_legacy_generation_is_disabled_by_default(self):
        output = io.StringIO()

        with redirect_stdout(output):
            self.module.main()

        self.assertFalse(self.module.ENABLE_LEGACY_VIRTUAL_DEVICES)
        self.assertIn("Legacy virtual Device generation is disabled by default", output.getvalue())
        self.assertNotIn("kind: Device", output.getvalue())

    def test_act_health_is_not_exported_by_legacy_mapper_db_method(self):
        self.assertFalse(self.module.should_store_to_influx("act", "health"))
        self.assertFalse(self.module.should_store_to_influx("rpi-act", "health"))

    def test_act_ts_is_not_used_because_mapper_crashes_on_unreported_push_only_property(self):
        self.assertFalse(self.module.should_store_to_influx("act", "ts"))
        self.assertFalse(self.module.should_store_to_influx("rpi-act", "ts"))

    def test_act_power_is_not_stored_to_influx_by_default(self):
        self.assertFalse(self.module.should_store_to_influx("act", "power"))

    def test_explicit_legacy_opt_in_preserves_raw_mapper_db_method_reference(self):
        self.assertTrue(self.module.should_store_to_influx("env", "temperature"))
        self.assertTrue(self.module.should_store_to_influx("env", "humidity"))
        self.assertTrue(self.module.should_store_to_influx("vib", "vibration"))


if __name__ == "__main__":
    unittest.main()
