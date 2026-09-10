import unittest
from pathlib import Path
import sys

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import analyze_saturation


class SaturationAnalysisTests(unittest.TestCase):
    def test_single_node_limits_do_not_require_remote_roles(self):
        summary = pd.DataFrame(
            [
                {"node": "nano", "concurrency": 1, "p95_ttft_ms": 40, "error_rate": 0,
                 "median_tokens_per_second": 50, "mean_throughput_rps": 5},
                {"node": "nano", "concurrency": 8, "p95_ttft_ms": 1400, "error_rate": 0,
                 "median_tokens_per_second": 49, "mean_throughput_rps": 5.1},
                {"node": "nano", "concurrency": 16, "p95_ttft_ms": 2900, "error_rate": 0.01,
                 "median_tokens_per_second": 49, "mean_throughput_rps": 5.1},
            ]
        )

        limits = analyze_saturation.derive_limits(summary)

        self.assertEqual(limits["node"].tolist(), ["nano"])
        self.assertEqual(limits.iloc[0]["slo_capacity_concurrency"], 8)
        self.assertEqual(limits.iloc[0]["first_slo_overload_concurrency"], 16)

    def test_offload_gates_are_empty_without_remote_measurements(self):
        summary = pd.DataFrame(
            [{"node": "nano", "concurrency": 1, "median_client_latency_ms": 200}]
        )
        self.assertTrue(analyze_saturation.derive_offload_gates(summary, pd.DataFrame()).empty)

    def test_orin_nano_gpu_report_uses_measured_queue_threshold(self):
        summary = pd.DataFrame(
            [{"node": "nano", "concurrency": 1, "requests": 1, "errors": 0,
              "p95_ttft_ms": 40, "p95_client_latency_ms": 200,
              "mean_throughput_rps": 5, "p95_observed_queue_length": 0}]
        )
        limits = pd.DataFrame(
            [{"node": "nano", "baseline_p95_ttft_ms": 40,
              "baseline_median_tokens_per_second": 50,
              "tokens_per_second_low": 40, "max_observed_throughput_rps": 5,
              "throughput_knee_concurrency": 1, "slo_capacity_concurrency": 8,
              "first_slo_overload_concurrency": 16, "ttft_high_ms": 1500}]
        )
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.md"
            analyze_saturation.render_report(
                summary, limits, pd.DataFrame(), output,
                {"execution_profile": "orin_nano_gpu", "blocks": 3, "seed": 1},
            )
            report = output.read_text(encoding="utf-8")

        self.assertIn("`queue_length >= 8`", report)
        self.assertNotIn("`queue_length >= 1`", report)

    def test_x86_gpu_substitute_report_does_not_claim_real_agx_hardware(self):
        summary = pd.DataFrame(
            [{"node": "agx", "concurrency": 1, "requests": 1, "errors": 0,
              "p95_ttft_ms": 20, "p95_client_latency_ms": 150,
              "mean_throughput_rps": 6, "p95_observed_queue_length": 0}]
        )
        limits = pd.DataFrame(
            [{"node": "agx", "baseline_p95_ttft_ms": 20,
              "baseline_median_tokens_per_second": 60,
              "tokens_per_second_low": 48, "max_observed_throughput_rps": 6,
              "throughput_knee_concurrency": 1, "slo_capacity_concurrency": 8,
              "first_slo_overload_concurrency": 16, "ttft_high_ms": 1500}]
        )
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.md"
            analyze_saturation.render_report(
                summary, limits, pd.DataFrame(), output,
                {
                    "execution_profile": "x86_gpu_substitute",
                    "physical_hardware": "NVIDIA GeForce RTX 5060 Ti",
                    "logical_role": "agx",
                    "blocks": 3,
                    "seed": 1,
                },
            )
            report = output.read_text(encoding="utf-8")

        self.assertIn("NVIDIA GeForce RTX 5060 Ti", report)
        self.assertIn("실제 Jetson AGX Orin이 아니다", report)
        self.assertNotIn("CPU-only", report)
        self.assertNotIn("Orin Nano GPU 단독 포화점만 측정", report)

    def test_x86_gpu_substitute_report_uses_spark_target_boundary(self):
        summary = pd.DataFrame(
            [{"node": "spark", "concurrency": 1, "requests": 1, "errors": 0,
              "p95_ttft_ms": 5, "p95_client_latency_ms": 24,
              "mean_throughput_rps": 45, "p95_observed_queue_length": 0}]
        )
        limits = pd.DataFrame(
            [{"node": "spark", "baseline_p95_ttft_ms": 5,
              "baseline_median_tokens_per_second": 540,
              "tokens_per_second_low": 432, "max_observed_throughput_rps": 50,
              "throughput_knee_concurrency": 2, "slo_capacity_concurrency": 16,
              "first_slo_overload_concurrency": 32, "ttft_high_ms": 1500}]
        )
        from tempfile import TemporaryDirectory
        with TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.md"
            analyze_saturation.render_report(
                summary, limits, pd.DataFrame(), output,
                {
                    "execution_profile": "x86_gpu_substitute",
                    "physical_hardware": "NVIDIA GeForce RTX 5080",
                    "logical_role": "spark",
                    "blocks": 3,
                    "seed": 1,
                },
            )
            report = output.read_text(encoding="utf-8")

        self.assertIn("실제 NVIDIA DGX Spark가 아니다", report)
        self.assertNotIn("실제 Jetson AGX Orin이 아니다", report)


if __name__ == "__main__":
    unittest.main()
