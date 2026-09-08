import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from exporter import parse_load, metrics

class ExporterTests(unittest.TestCase):
    def test_scale_and_invalid(self):
        self.assertEqual(parse_load("0\n"), 0)
        self.assertEqual(parse_load("470"), .47)
        self.assertEqual(parse_load("1000"), 1)
        for text in ["", "-1", "1001", "NaN", "2.3"]:
            with self.assertRaises(ValueError): parse_load(text)

    def test_missing_is_not_idle(self):
        with TemporaryDirectory() as d:
            path=Path(d)/"load"
            self.assertNotIn("jetson_gpu_utilization_ratio", metrics(path))
            path.write_text("bad")
            self.assertIn("jetson_gpu_collector_success 0", metrics(path))
            path.write_text("0")
            self.assertIn("jetson_gpu_utilization_ratio 0.0", metrics(path))

if __name__ == "__main__": unittest.main()
