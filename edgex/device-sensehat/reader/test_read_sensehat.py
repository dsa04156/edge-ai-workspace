from __future__ import annotations

import importlib.util
import math
import pathlib
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("read_sensehat.py")


def load_reader_module():
    spec = importlib.util.spec_from_file_location("read_sensehat", MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class ReadSenseHatTest(unittest.TestCase):
    def test_rtimu_source_enables_imu_before_other_sensor_initialization(self):
        reader = load_reader_module()
        calls = []

        class IMU:
            def IMUInit(self):
                calls.append("imu_init")
                return True

            def setCompassEnable(self, enabled):
                calls.append(("compass", enabled))

            def setGyroEnable(self, enabled):
                calls.append(("gyro", enabled))

            def setAccelEnable(self, enabled):
                calls.append(("accel", enabled))

            def IMURead(self):
                calls.append("imu_read")
                return True

            @staticmethod
            def IMUGetPollInterval():
                return 3

        class Pressure:
            def pressureInit(self):
                calls.append("pressure_init")
                return True

        class Humidity:
            def humidityInit(self):
                calls.append("humidity_init")
                return True

        settings = object()

        class FakeRTIMU:
            Settings = staticmethod(lambda _settings_base: settings)
            RTIMU = staticmethod(lambda _settings: IMU())
            RTPressure = staticmethod(lambda _settings: Pressure())
            RTHumidity = staticmethod(lambda _settings: Humidity())

        source = reader.RTIMUSource(FakeRTIMU, "/tmp/RTIMULib")

        self.assertIs(source._settings, settings)
        self.assertEqual(
            calls,
            [
                "imu_init",
                ("compass", True),
                ("gyro", True),
                ("accel", True),
                "imu_read",
                "pressure_init",
                "humidity_init",
            ],
        )

    def test_rtimu_source_allows_sensor_fusion_warmup(self):
        reader = load_reader_module()

        class WarmupIMU:
            def __init__(self):
                self.calls = 0

            def IMURead(self):
                self.calls += 1
                return self.calls >= 5

            def getIMUData(self):
                return {
                    "fusionPoseValid": True,
                    "fusionPose": [0.0, 0.0, 0.0],
                    "gyroValid": True,
                    "gyro": [0.0, 0.0, 0.0],
                }

        class Pressure:
            @staticmethod
            def pressureRead():
                return [1, 1000.0, 1, 20.0]

        class Humidity:
            @staticmethod
            def humidityRead():
                return [1, 40.0, 1, 21.0]

        source = reader.RTIMUSource.__new__(reader.RTIMUSource)
        source._imu = WarmupIMU()
        source._pressure = Pressure()
        source._humidity = Humidity()
        source._poll_interval = 0.001

        sample = source.read("sensehat-001")

        self.assertEqual(source._imu.calls, 5)
        self.assertEqual(sample["device_id"], "sensehat-001")

    def test_build_sample_normalizes_typed_sensor_values(self):
        reader = load_reader_module()

        sample = reader.build_sample(
            device_id="sensehat-001",
            origin=123456789,
            pressure=[1, 1005.125, 1, 36.5],
            humidity=[1, 35.25, 1, 39.5],
            imu={
                "fusionPoseValid": True,
                "fusionPose": [-0.01, -0.02, -0.25],
                "gyroValid": True,
                "gyro": [0.1, 0.2, -0.3],
            },
        )

        self.assertEqual(sample["device_id"], "sensehat-001")
        self.assertEqual(sample["origin"], 123456789)
        self.assertEqual(sample["temp_humidity"], 39.5)
        self.assertEqual(sample["temp_pressure"], 36.5)
        self.assertEqual(sample["humidity"], 35.25)
        self.assertEqual(sample["pressure"], 1005.125)
        self.assertAlmostEqual(sample["roll"], math.degrees(-0.01) % 360)
        self.assertAlmostEqual(sample["pitch"], math.degrees(-0.02) % 360)
        self.assertAlmostEqual(sample["yaw"], math.degrees(-0.25) % 360)
        self.assertEqual(sample["compass"], sample["yaw"])
        self.assertEqual(sample["gyro_x"], 0.1)
        self.assertEqual(sample["gyro_y"], 0.2)
        self.assertEqual(sample["gyro_z"], -0.3)

    def test_build_sample_rejects_invalid_or_non_finite_sensor_data(self):
        reader = load_reader_module()
        valid_imu = {
            "fusionPoseValid": True,
            "fusionPose": [0.0, 0.0, 0.0],
            "gyroValid": True,
            "gyro": [0.0, 0.0, 0.0],
        }

        with self.assertRaisesRegex(ValueError, "pressure"):
            reader.build_sample("sensehat-001", 1, [0, 0.0, 1, 20.0], [1, 40.0, 1, 21.0], valid_imu)
        with self.assertRaisesRegex(ValueError, "humidity"):
            reader.build_sample("sensehat-001", 1, [1, 1000.0, 1, 20.0], [0, 0.0, 1, 21.0], valid_imu)
        with self.assertRaisesRegex(ValueError, "IMU"):
            reader.build_sample(
                "sensehat-001",
                1,
                [1, 1000.0, 1, 20.0],
                [1, 40.0, 1, 21.0],
                {**valid_imu, "gyroValid": False},
            )
        with self.assertRaisesRegex(ValueError, "finite"):
            reader.build_sample(
                "sensehat-001",
                1,
                [1, float("nan"), 1, 20.0],
                [1, 40.0, 1, 21.0],
                valid_imu,
            )

    def test_parse_args_requires_positive_interval(self):
        reader = load_reader_module()

        self.assertEqual(reader.parse_args([]).runtime_settings, "/tmp/RTIMULib")
        self.assertEqual(reader.parse_args(["--interval", "0.25"]).interval, 0.25)
        with self.assertRaises(SystemExit):
            reader.parse_args(["--interval", "0"])


if __name__ == "__main__":
    unittest.main()
