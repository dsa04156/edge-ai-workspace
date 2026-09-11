import unittest
from pathlib import Path
import bench
import sweep
from analyze_sweep import summarize


class SweepTests(unittest.TestCase):
    def test_unsent_is_not_success_and_latency_not_zero(self):
        record={'case':'rate-1.2','pattern':'open-loop','input_tokens':512,'target_output_tokens':128,
                'concurrency':8,'status':'not_sent','sent_at':None,'planned_at':1,'completed_at':2}
        got=summarize([record])['rate-1.2']
        self.assertEqual(got['ok'],0)
        self.assertEqual(got['not_sent'],1)
        self.assertIsNone(got['p95_latency_ms'])

    def test_bounded_workload_cases(self):
        self.assertEqual(sweep.cases()[0], (512,128,1))
        self.assertEqual(len(sweep.cases()),10)
        self.assertTrue(all(i+o<4096 and c<=8 for i,o,c in sweep.cases()))
        self.assertIn((2048,256,1),sweep.cases())

    def test_common_context(self):
        for name in ('nano','agx','rtx5060ti','spark'):
            cfg=bench.load_config(Path(__file__).with_name(name+'-sweep.json'))
            self.assertEqual(cfg['runtime']['context'],4096)
            self.assertEqual(cfg['runtime']['threads'],4)
            self.assertEqual(cfg['runtime']['kv_type'],'f16')
