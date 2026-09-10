import io
import json
import socket
import unittest
from unittest.mock import patch

import bench
from paired_client import schedule
from pathlib import Path


class StreamTests(unittest.TestCase):
    def run_stream(self, events):
        payload = b"".join(b"data: " + json.dumps(x).encode() + b"\n\n" for x in events)
        with patch("urllib.request.urlopen", return_value=io.BytesIO(payload)):
            return bench.stream("http://unused", {"prompt": [1, 2, 3], "n_predict": 7},
                                run_id="r", request_id="q", phase="measure", node="test",
                                planned_at=0, timeout=1)

    def test_chunks_are_not_tokens(self):
        result = self.run_stream([{"content": "multiple tokens here"}, {"stop": True, "tokens_evaluated": 3, "tokens_predicted": 7}])
        self.assertEqual(result["actual_output_tokens"], 7)
        self.assertEqual(result["status"], "ok")

    def test_empty_chunk_not_first_token(self):
        result = self.run_stream([{"content": ""}, {"stop": True, "tokens_evaluated": 3, "tokens_predicted": 7}])
        self.assertIsNone(result["ttft_ms"])

    def test_missing_terminal_is_failure(self):
        result = self.run_stream([{"content": "partial"}])
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["partial_response"])
        self.assertFalse(result["fallback"])

    def test_short_output_is_not_equal_work(self):
        result = self.run_stream([{"stop": True, "tokens_evaluated": 3, "tokens_predicted": 2}])
        self.assertEqual(result["status"], "short_output")

    def test_wrong_input_is_not_equal_work(self):
        result = self.run_stream([{"stop": True, "tokens_evaluated": 4, "tokens_predicted": 7}])
        self.assertEqual(result["status"], "input_length_mismatch")

    def test_timeout_no_retry(self):
        with patch("urllib.request.urlopen", side_effect=socket.timeout()):
            result = bench.stream("http://unused", {"prompt": [1], "n_predict": 1}, run_id="r", request_id="q", phase="measure", node="test", planned_at=0, timeout=1)
        self.assertEqual(result["status"], "timeout")
        self.assertFalse(result["retry"])

    def test_unmeasured_cache_is_not_verified(self):
        result = self.run_stream([{"content": "text"}, {"stop": True, "tokens_evaluated": 3, "tokens_predicted": 7}])
        self.assertFalse(result["zero_prefix_reuse_verified"])


class ConfigTests(unittest.TestCase):
    def test_paired_schedule_reproducible_and_balanced(self):
        plan = schedule(3, 42)
        self.assertEqual(plan, schedule(3, 42))
        self.assertEqual(len(plan), 18)
        for block in range(3):
            for concurrency in (1, 2, 4):
                self.assertEqual({x["route"] for x in plan if x["block"] == block and x["concurrency"] == concurrency}, {"nano", "remote"})

    def test_common_runtime_controls(self):
        root = Path(__file__).parent
        nano = bench.load_config(root / "nano-0332.json")
        remote = bench.load_config(root / "rtx5060ti-0332.json")
        for key in ("reported_revision", "threads", "context", "batch", "ubatch", "parallel_slots", "kv_type", "flash_attention"):
            self.assertEqual(nano["runtime"][key], remote["runtime"][key])
        self.assertEqual(nano["model"]["sha256"], remote["model"]["sha256"])

    def test_unknown_not_zero(self):
        self.assertIsNone(bench.percentile([], .95))
        self.assertIsNone(bench.summarize([])["failure_rate"])
        self.assertFalse(bench.summarize([])["threshold_validated"])

    def test_temperature_stop(self):
        with self.assertRaises(RuntimeError):
            bench.check_safety({"ram_available_mib": 2000, "gpu": [{"temperature_c": 81}]}, {"min_available_ram_mib": 1024, "max_temperature_c": 80})

    def test_exact_tokens(self):
        with patch("bench.api", return_value={"tokens": list(range(1024))}):
            rows = bench.dataset("unused", 2, {"input_tokens": 512, "output_tokens": 128, "seed": 12})
        self.assertEqual(len(rows[0]["prompt"]), 512)
        self.assertFalse(rows[0]["cache_prompt"])
        self.assertTrue(rows[0]["ignore_eos"])
        self.assertNotEqual(rows[0]["request_id"], rows[1]["request_id"])


if __name__ == "__main__":
    unittest.main()
