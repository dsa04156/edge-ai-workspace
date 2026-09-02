import unittest

from tools.analyze_gpu_resource_pressure_experiment import (
    analyze,
    exact_two_sided_sign_p,
)


def run(rep, compute, memory, latency, throughput, gpu_util, memory_ratio):
    return {
        "run_index": rep,
        "repetition": rep,
        "compute_duty_ratio": compute,
        "memory_load_mib": memory,
        "requests_completed": 10,
        "elapsed_seconds": 1,
        "latency_ms": {"count": 10, "p50": latency, "p95": latency, "max": latency},
        "throughput_per_second": throughput,
        "gpu": {
            "gpu_utilization_percent": {"count": 2, "p50": gpu_util, "p95": gpu_util, "max": gpu_util},
            "assigned_memory_used_percent": {"count": 2, "p50": memory_ratio, "p95": memory_ratio, "max": memory_ratio},
        },
        "allocation_error": None,
        "inference_errors": [],
    }


class GpuPressureAnalysisTests(unittest.TestCase):
    def test_sign_test_all_six_same_direction(self):
        self.assertEqual(exact_two_sided_sign_p(6, 0), 0.03125)

    def test_shortage_requires_resource_pressure_and_service_degradation(self):
        runs = []
        for repetition in range(1, 3):
            runs.append(run(repetition, 0, 0, 10, 100, 10, 30))
            runs.append(run(repetition, 1, 0, 13, 90, 95, 35))
        result = analyze(
            {
                "generated_at": "2026-08-19T00:00:00Z",
                "model": {},
                "input_provenance": {},
                "execution": {},
                "design": {},
                "runs": runs,
            }
        )
        stressed = next(
            condition
            for condition in result["conditions"]
            if condition["compute_duty_ratio"] == 1
        )
        self.assertEqual(stressed["degraded_runs"], 2)
        self.assertEqual(stressed["shortage_qualified_runs"], 2)
        self.assertEqual(
            result["observed_compute_crossover"]["compute_duty_ratio"],
            1,
        )


if __name__ == "__main__":
    unittest.main()
