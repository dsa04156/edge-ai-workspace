import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_saturation


class SaturationRunnerTests(unittest.TestCase):
    def test_single_nano_tier_is_supported(self):
        self.assertEqual(run_saturation.parse_tiers("nano"), ("nano",))
        schedule = run_saturation.make_schedule(("nano",), (1, 2, 4), blocks=2, seed=7)
        self.assertEqual({row["target_node"] for row in schedule}, {"nano"})
        self.assertEqual(len(schedule), 6)

    def test_unknown_or_duplicate_tier_is_rejected(self):
        for raw in ("", "nano,nano", "nano,missing"):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                run_saturation.parse_tiers(raw)


if __name__ == "__main__":
    unittest.main()
