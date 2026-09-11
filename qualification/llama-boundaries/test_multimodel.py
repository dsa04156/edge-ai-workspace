import unittest
from unittest.mock import patch
import multimodel_report
import multimodel_cluster


class MultimodelTests(unittest.TestCase):
    def row(self, block, start, end, status="ok"):
        return dict(phase="measure", block=block, case="i512-o128-c1", planned_at=start,
                    completed_at=end, status=status, latency_ms=(end-start)*1000,
                    ttft_ms=20, decode_tokens_per_second=128/(end-start), actual_output_tokens=128)

    def test_throughput_excludes_between_block_reload_gaps(self):
        summary = multimodel_report.aggregate([self.row(0, 0, 1), self.row(1, 100, 101)])
        self.assertEqual(summary["active_wave_requests_s"], 1)
        self.assertEqual(summary["active_wave_output_tokens_s"], 128)

    def test_failed_requests_remain_in_denominator_and_elapsed_time(self):
        summary = multimodel_report.aggregate([self.row(0, 0, 1), self.row(1, 100, 102, "timeout")])
        self.assertEqual(summary["requests"], 2)
        self.assertEqual(summary["failures"], 1)
        self.assertAlmostEqual(summary["active_wave_requests_s"], 1/3)

    def test_warmup_excluded(self):
        warmup = self.row(0, 0, 9)
        warmup["phase"] = "warmup"
        summary = multimodel_report.aggregate([warmup, self.row(1, 10, 11)])
        self.assertEqual(summary["requests"], 1)
        self.assertEqual(summary["p50_latency_ms"], 1000)

    def test_empty_measurements_are_unavailable(self):
        summary = multimodel_report.aggregate([])
        self.assertIsNone(summary["active_wave_requests_s"])
        self.assertIsNone(summary["p95_latency_ms"])

    def test_only_requested_physical_nodes(self):
        self.assertEqual({n["node"] for n in multimodel_cluster.NODES.values()},
            {"etri-dev0001-jetorn", "etri-dev0005-jetagx", "etri-ser0003-cg0ms0"})

    def test_suspend_patch_guards_uid_and_prior_state(self):
        with patch.object(multimodel_cluster, "command") as cmd:
            multimodel_cluster.set_suspended(False, True, "fixed-uid")
        import json
        patch_ops = json.loads(cmd.call_args.args[0][-1])
        self.assertEqual(patch_ops[0], {"op": "test", "path": "/metadata/uid", "value": "fixed-uid"})
        self.assertEqual(patch_ops[1], {"op": "test", "path": "/spec/suspended", "value": False})


if __name__ == "__main__":
    unittest.main()
