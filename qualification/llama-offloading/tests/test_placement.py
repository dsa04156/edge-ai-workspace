import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from placement import PlacementEngine, PolicyConfig


def snapshot(
    *, healthy=True, available=True, state="ACTIVE", activation=0,
    queue=0, active=0, ttft=500, tps=10, inference=1000, rtt=10,
):
    return {
        "healthy": healthy,
        "available": available,
        "node_state": state,
        "activation_estimate_ms": activation,
        "queue_length": queue,
        "active_requests": active,
        "max_concurrency": 1,
        "ewma_ttft_ms": ttft,
        "ewma_tokens_per_second": tps,
        "ewma_inference_ms": inference,
        "rtt_ms": rtt,
    }


class PlacementTests(unittest.TestCase):
    def engine(self):
        return PlacementEngine(PolicyConfig(overload_dwell_seconds=2, recovery_dwell_seconds=3, cooldown_seconds=4))

    def test_nano_is_default(self):
        engine = self.engine()
        snaps = {"nano": snapshot(inference=2000), "agx": snapshot(inference=1000), "spark": snapshot(inference=500)}
        self.assertEqual(engine.select(snaps, now=0).node, "nano")

    def test_sustained_pressure_and_improvement_offload_only_new_selection(self):
        engine = self.engine()
        snaps = {"nano": snapshot(queue=2, inference=2000), "agx": snapshot(inference=1000), "spark": snapshot(inference=500)}
        self.assertEqual(engine.select(snaps, now=0).node, "nano")
        decision = engine.select(snaps, now=2.1)
        self.assertEqual(decision.node, "agx")
        self.assertIn("offload:nano->agx", decision.reason)

    def test_improvement_gate_prevents_offload(self):
        engine = self.engine()
        snaps = {"nano": snapshot(queue=1, inference=1000), "agx": snapshot(inference=1900), "spark": snapshot(inference=500)}
        engine.select(snaps, now=0)
        self.assertEqual(engine.select(snaps, now=2.1).node, "nano")

    def test_inactive_candidate_cost_includes_activation(self):
        metrics = snapshot(state="CACHED", healthy=False, activation=750, inference=250, rtt=10)
        self.assertEqual(PlacementEngine.predicted_e2e(metrics), 1010)

    def test_available_inactive_candidate_can_be_selected_after_dwell(self):
        engine = self.engine()
        snaps = {
            "nano": snapshot(queue=4, inference=2000),
            "agx": snapshot(healthy=False, state="CACHED", activation=500, inference=500),
            "spark": snapshot(inference=500),
        }
        engine.select(snaps, now=0)
        self.assertEqual(engine.select(snaps, now=2.1).node, "agx")

    def test_cooldown_and_tierwise_recovery(self):
        engine = self.engine()
        engine.route = "spark"
        engine.cooldown_until = 4
        recovered = {"nano": snapshot(), "agx": snapshot(), "spark": snapshot()}
        engine.select(recovered, now=0)
        self.assertEqual(engine.select(recovered, now=3.5).node, "spark")
        self.assertEqual(engine.select(recovered, now=4.1).node, "agx")
        self.assertEqual(engine.select(recovered, now=8.2).node, "nano")

    def test_idle_recovery_does_not_depend_on_stale_latency_samples(self):
        engine = self.engine()
        engine.route = "spark"
        stale = {
            "nano": snapshot(ttft=9000, tps=1),
            "agx": snapshot(ttft=7000, tps=2),
            "spark": snapshot(),
        }
        self.assertEqual(engine.select(stale, now=0).node, "spark")
        self.assertEqual(engine.select(stale, now=3.1).node, "agx")
        self.assertEqual(engine.select(stale, now=7.2).node, "nano")

    def test_busy_current_tier_prevents_recovery_even_when_lower_is_idle(self):
        engine = self.engine()
        engine.route = "agx"
        snaps = {
            "nano": snapshot(),
            "agx": snapshot(active=1),
            "spark": snapshot(),
        }
        engine.select(snaps, now=0)
        self.assertEqual(engine.select(snaps, now=5).node, "agx")

    def test_static_requires_explicit_valid_target(self):
        engine = self.engine()
        snaps = {tier: snapshot() for tier in ("nano", "agx", "spark")}
        self.assertEqual(engine.select(snaps, mode="static", static_node="spark").node, "spark")
        with self.assertRaises(ValueError):
            engine.select(snaps, mode="static", static_node="bad")


if __name__ == "__main__":
    unittest.main()
