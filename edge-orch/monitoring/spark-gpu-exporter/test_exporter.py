import subprocess
import unittest
from unittest.mock import patch
import exporter


class ExporterTests(unittest.TestCase):
    def test_real_spark_observation_and_idle_zero(self):
        lines = exporter.parse_metrics("0, 37, 0, 4.86\n")
        self.assertIn('spark_gpu_temperature_celsius{gpu="0"} 37.0', lines)
        self.assertIn('spark_gpu_utilization_percent{gpu="0"} 0.0', lines)
        self.assertEqual(len(lines), 3)

    def test_unsupported_nonfinite_and_out_of_range_stay_absent(self):
        self.assertEqual(exporter.parse_metrics("0, [N/A], 40, NaN"), ['spark_gpu_utilization_percent{gpu="0"} 40.0'])
        for output in ["", "No devices were found", '0, 37, 0', '0, 999, -1, inf', '0, 37, 0, 4\n0, 38, 1, 4']:
            with self.subTest(output=output), self.assertRaises(ValueError):
                exporter.parse_metrics(output)

    def test_command_failure_does_not_reuse_last_sample(self):
        good = subprocess.CompletedProcess(exporter.COMMAND, 0, "0, 37, 0, 4.86")
        failures = [FileNotFoundError(), subprocess.TimeoutExpired(exporter.COMMAND, 3), subprocess.CalledProcessError(1, exporter.COMMAND)]
        for failure in failures:
            with self.subTest(failure=failure), patch.object(exporter.subprocess, "run", side_effect=[good, failure]):
                self.assertIn('spark_gpu_collector_success 1', exporter.collect())
                failed = exporter.collect()
                self.assertIn('spark_gpu_collector_success 0', failed)
                self.assertNotIn('gpu="0"', failed)


if __name__ == "__main__":
    unittest.main()
