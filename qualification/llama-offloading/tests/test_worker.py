import unittest
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import worker


class FakeTemperaturePath:
    def __init__(self, value=None, error=None):
        self.value = value
        self.error = error

    def read_text(self):
        if self.error:
            raise self.error
        return self.value


class WorkerMetricsTests(unittest.TestCase):
    def test_unreadable_thermal_zone_does_not_break_metrics(self):
        paths = [
            FakeTemperaturePath(error=TypeError("kernel sysfs read returned no bytes")),
            FakeTemperaturePath(value="42000\n"),
        ]
        with patch.object(Path, "glob", return_value=paths):
            self.assertEqual(worker.read_temperature(), 42.0)

    def test_node_without_dcgm_reports_explicitly_unavailable_gpu_metrics(self):
        with patch.object(worker, "GPU_MODEL", ""):
            gpu = worker.read_gpu_metrics()
        self.assertIsNone(gpu["gpu_utilization_percent"])
        self.assertEqual(gpu["gpu_metrics_reason"], "dcgm_not_available_for_node")

    def test_cached_activation_skips_remote_download(self):
        original_state = worker.STATE.node_state
        worker.STATE.node_state = "CACHED"
        metadata = {"digest": "same-model"}
        try:
            with (
                patch.object(worker, "model_metadata", return_value=metadata),
                patch.object(worker, "model_loaded", return_value=False),
                patch.object(worker, "wait_runtime", return_value=100.0),
                patch.object(worker, "pull_model") as pull,
                patch.object(worker, "warm_model", return_value=(250.0, "same-model")),
                patch.object(worker.STATE, "transition", return_value={"old_state": "CACHED", "new_state": "ACTIVE"}),
            ):
                result = worker.activate({"target_state": "ACTIVE", "reason": "test"})
            pull.assert_not_called()
            self.assertEqual(result["model_remote_download_ms"], 0.0)
            self.assertEqual(result["model_load_ms"], 250.0)
        finally:
            worker.STATE.node_state = original_state

    def test_cached_state_comes_from_ollama_metadata_without_loaded_runner(self):
        original_state = worker.STATE.node_state
        worker.STATE.node_state = "CACHED"
        try:
            with (
                patch.object(worker, "runtime_up", return_value=True),
                patch.object(worker, "model_metadata", return_value={"digest": "same-model"}),
                patch.object(worker, "model_loaded", return_value=False),
            ):
                status = worker.health()
            self.assertTrue(status["management_runtime_running"])
            self.assertTrue(status["model_cached"])
            self.assertFalse(status["inference_worker_running"])
            self.assertFalse(status["inference_ready"])
        finally:
            worker.STATE.node_state = original_state

    def test_already_active_does_not_replay_old_activation_as_required(self):
        original_state = worker.STATE.node_state
        original_activation = worker.STATE.last_activation
        worker.STATE.node_state = "ACTIVE"
        worker.STATE.last_activation = {
            "activation_required": True,
            "node_state_before": "COLD",
            "node_state": "ACTIVE",
            "activation_time_ms": 34119.18,
        }
        try:
            with patch.object(worker, "model_loaded", return_value=True):
                result = worker.activate({"target_state": "ACTIVE", "reason": "test"})
            self.assertFalse(result["activation_required"])
            self.assertEqual(result["node_state_before"], "ACTIVE")
            self.assertEqual(result["node_state"], "ACTIVE")
        finally:
            worker.STATE.node_state = original_state
            worker.STATE.last_activation = original_activation

    def test_busy_worker_cannot_be_deactivated(self):
        original_active = worker.STATE.active_requests
        worker.STATE.active_requests = 1
        try:
            with self.assertRaisesRegex(RuntimeError, "worker_busy"):
                worker.deactivate({"target_state": "CACHED"})
        finally:
            worker.STATE.active_requests = original_active


if __name__ == "__main__":
    unittest.main()
