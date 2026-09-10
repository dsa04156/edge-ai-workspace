import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("NANO_URL", "http://nano")
os.environ.setdefault("AGX_URL", "http://agx")
os.environ.setdefault("SPARK_URL", "http://spark")

import proxy
from placement import PlacementDecision


class ProxyRoutingTests(unittest.TestCase):
    def test_request_is_forwarded_once_to_the_selected_node(self):
        snapshots = {
            tier: {
                "healthy": True,
                "inference_ready": True,
                "node_state": "ACTIVE",
                "node_id": tier,
                "queue_length": 0,
                "active_requests": 0,
            }
            for tier in ("nano", "agx", "spark")
        }
        decision = PlacementDecision(
            node="agx",
            reason="test-selection",
            predicted_e2e_ms=100.0,
            candidates={"nano": 200.0, "agx": 100.0, "spark": 80.0},
        )
        worker_result = {
            "request_id": "fixed-request",
            "node_id": "agx",
            "ttft_ms": 10.0,
            "tokens_per_second": 20.0,
            "actual_e2e_ms": 30.0,
        }
        with (
            patch.object(proxy, "METHOD_READY", True),
            patch.object(proxy, "CURRENT_METHOD", "always_on"),
            patch.object(proxy, "all_snapshots", return_value=snapshots),
            patch.object(proxy.ENGINE, "select", return_value=decision),
            patch.object(proxy, "http_json", return_value=(worker_result, 30.0)) as forward,
            patch.object(proxy, "append_jsonl"),
        ):
            response = proxy.route_generate(
                {"request_id": "fixed-request", "prompt": "hello", "max_tokens": 2}
            )

        forward.assert_called_once()
        self.assertEqual(forward.call_args.args[0], "http://agx/generate")
        self.assertEqual(response["placement"]["selected_node"], "agx")

    def test_request_waits_for_activation_before_forwarding(self):
        snapshots = {
            "nano": {"node_state": "ACTIVE", "inference_ready": True, "node_id": "nano"},
            "agx": {"node_state": "CACHED", "inference_ready": False, "node_id": "agx"},
            "spark": {"node_state": "CACHED", "inference_ready": False, "node_id": "spark"},
        }
        decision = PlacementDecision("agx", "offload:test", 100.0, {tier: 100.0 for tier in snapshots})
        worker_result = {
            "request_id": "activation-request", "ttft_ms": 10.0,
            "tokens_per_second": 20.0, "actual_e2e_ms": 30.0,
        }
        activated = {"activation_required": True, "activation_time_ms": 500.0}
        with (
            patch.object(proxy, "METHOD_READY", True),
            patch.object(proxy, "CURRENT_METHOD", "cached_on_demand"),
            patch.object(proxy, "all_snapshots", return_value=snapshots),
            patch.object(proxy.ENGINE, "select", return_value=decision),
            patch.object(proxy, "activate_node", return_value=activated) as activate,
            patch.object(proxy, "snapshot", return_value={"inference_ready": True}),
            patch.object(proxy, "http_json", return_value=(worker_result, 30.0)) as forward,
            patch.object(proxy, "append_jsonl"),
        ):
            response = proxy.route_generate({"request_id": "activation-request", "prompt": "hello"})
        activate.assert_called_once()
        forward.assert_called_once()
        self.assertTrue(response["placement"]["activation_required"])


if __name__ == "__main__":
    unittest.main()
