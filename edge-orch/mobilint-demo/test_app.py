import queue
import threading
import unittest
from unittest.mock import Mock

from app import Busy, Runtime, validate_request


class ContractTests(unittest.TestCase):
    def test_invalid_requests_are_rejected(self):
        for body in [[], {"seed": True}, {"iterations": 0}, {"iterations": 51},
                     {"model_path": "/tmp/model"}, {"seed": -1}]:
            with self.subTest(body=body), self.assertRaises(ValueError):
                validate_request(body)
        self.assertEqual(validate_request({}), (0, 1))

    def runtime(self):
        runtime = Runtime.__new__(Runtime)
        runtime.failed = set()
        runtime.locks = {"candy": threading.Lock(), "mosaic": threading.Lock()}
        return runtime

    def test_busy_parallel_releases_first_lock(self):
        runtime = self.runtime()
        runtime.locks["mosaic"].acquire()
        with self.assertRaises(Busy):
            runtime.infer(["candy", "mosaic"], {})
        self.assertFalse(runtime.locks["candy"].locked())

    def test_timeout_worker_cannot_reuse_stale_result(self):
        runtime = self.runtime()
        worker = {"process": Mock(), "inbox": Mock(), "outbox": Mock()}
        worker["process"].is_alive.return_value = True
        worker["outbox"].get.side_effect = queue.Empty
        runtime.workers = {"candy": worker}
        with self.assertRaises(RuntimeError):
            runtime.call("candy", 0, 1)
        with self.assertRaises(RuntimeError):
            runtime.call("candy", 0, 1)
        self.assertEqual(worker["inbox"].put_nowait.call_count, 1)

    def test_parallel_reports_intersection_and_releases_locks(self):
        runtime = self.runtime()
        runtime.call = Mock(side_effect=lambda name, *args: {
            "start_ns": 1000000 if name == "candy" else 2000000,
            "end_ns": 4000000 if name == "candy" else 5000000})
        result = runtime.infer(["candy", "mosaic"], {})
        self.assertEqual(result["overlap_ms"], 2)
        self.assertFalse(any(lock.locked() for lock in runtime.locks.values()))


if __name__ == "__main__":
    unittest.main()
