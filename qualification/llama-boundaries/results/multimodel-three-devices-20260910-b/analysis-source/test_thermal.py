import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
import bench


class ThermalTests(unittest.TestCase):
    def test_sysfs_read_and_safety(self):
        with tempfile.TemporaryDirectory() as root:
            zone = Path(root) / 'thermal_zone0'
            zone.mkdir()
            (zone / 'type').write_text('GPU-therm')
            (zone / 'temp').write_text('81000')
            rows = bench.thermal_zones(Path(root))
            self.assertEqual(rows, [{'name': 'GPU-therm', 'temperature_c': 81.0}])
            with self.assertRaisesRegex(RuntimeError, 'Thermal zone'):
                bench.check_safety({'ram_available_mib': 2000, 'thermal_zones': rows},
                                   {'min_available_ram_mib': 1024, 'max_temperature_c': 80})

    def test_unavailable_not_zero(self):
        with tempfile.TemporaryDirectory() as root:
            self.assertEqual(bench.thermal_zones(Path(root)), [])

    def test_sysfs_eagain_decode_typeerror_is_unavailable(self):
        with tempfile.TemporaryDirectory() as root:
            (Path(root) / 'thermal_zone2').mkdir()
            with patch.object(Path, 'read_text', side_effect=TypeError('cannot concat NoneType')):
                rows = bench.thermal_zones(Path(root))
            self.assertIsNone(rows[0]['temperature_c'])
            self.assertEqual(rows[0]['error'], 'TypeError')
