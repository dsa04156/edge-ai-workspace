import unittest
from analyze_paired import describe


class ActiveWaveTests(unittest.TestCase):
    def test_between_wave_gap_is_not_active_capacity(self):
        rows = []
        for block, start in enumerate((0, 100, 200)):
            rows.append(dict(block=block, status='ok', phase='measure',
                             planned_at=start, sent_at=start, completed_at=start+2,
                             latency_ms=2000, ttft_ms=100, actual_output_tokens=128))
        result = describe(rows)
        self.assertEqual(result['blocks'], 3)
        self.assertEqual(result['active_wave_completed_rps'], .5)
        self.assertEqual(result['p95_latency_ms'], 2000)
