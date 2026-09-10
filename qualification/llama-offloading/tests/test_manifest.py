import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class WorkerManifestTests(unittest.TestCase):
    def test_nano_uses_jetpack6_gpu_without_cpu_force(self):
        workers = (ROOT / "k8s" / "workers.yaml").read_text(encoding="utf-8")
        nano = workers.split("name: llama-worker-agx", maxsplit=1)[0]

        self.assertNotIn("runtimeClassName:", nano)
        self.assertNotIn("name: CUDA_VISIBLE_DEVICES", nano)
        self.assertNotIn("name: ROCR_VISIBLE_DEVICES", nano)
        self.assertIn('{name: JETSON_JETPACK, value: "6"}', nano)
        self.assertIn('{name: NVIDIA_VISIBLE_DEVICES, value: "all"}', nano)
        self.assertIn('{name: NVIDIA_DRIVER_CAPABILITIES, value: "compute,utility"}', nano)
        self.assertIn("privileged: true", nano)
        self.assertIn("name: jetson-nvidia-libs", nano)
        self.assertIn("name: jetson-tegra-libs", nano)
        self.assertIn('{name: PROFILE_INFERENCE_MS, value: "194"}', nano)

    def test_proxy_uses_orin_nano_gpu_saturation_thresholds(self):
        manifest = (ROOT / "k8s" / "proxy.yaml").read_text(encoding="utf-8")
        source = (ROOT / "proxy.py").read_text(encoding="utf-8")

        self.assertIn('name: QUEUE_HIGH\n              value: "8"', manifest)
        self.assertIn('name: MIN_TOKENS_PER_SECOND\n              value: "39.5"', manifest)
        self.assertIn('os.getenv("QUEUE_HIGH", "8")', source)
        self.assertIn('os.getenv("MIN_TOKENS_PER_SECOND", "39.5")', source)

    def test_unmeasured_remote_placeholders_are_scaled_to_zero(self):
        workers = (ROOT / "k8s" / "workers.yaml").read_text(encoding="utf-8")
        agx = workers.split("name: llama-worker-agx", maxsplit=1)[1].split(
            "name: llama-worker-spark", maxsplit=1
        )[0]
        spark = workers.split("name: llama-worker-spark", maxsplit=1)[1]

        self.assertIn("replicas: 0", agx)
        self.assertIn("replicas: 0", spark)

    def test_x86_remote_workers_request_gpu_without_cpu_force(self):
        workers = (ROOT / "k8s" / "workers.yaml").read_text(encoding="utf-8")
        agx = workers.split("name: llama-worker-agx", maxsplit=1)[1].split(
            "name: llama-worker-spark", maxsplit=1
        )[0]
        spark = workers.split("name: llama-worker-spark", maxsplit=1)[1]

        for remote in (agx, spark):
            self.assertNotIn("name: CUDA_VISIBLE_DEVICES", remote)
            self.assertNotIn("name: ROCR_VISIBLE_DEVICES", remote)
            self.assertIn("nvidia.com/gpu: 1", remote)


if __name__ == "__main__":
    unittest.main()
