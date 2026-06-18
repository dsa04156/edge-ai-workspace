from __future__ import annotations

from .virtual_resources import VirtualResourceRegistryEntry


RESOURCE_REGISTRY: tuple[VirtualResourceRegistryEntry, ...] = (
    VirtualResourceRegistryEntry(
        id="vd-aihat-inference",
        display_name="AI HAT Inference",
        node="etri-dev0002-raspi5",
        resource_type="ai-hat",
        stage_type="ai_inference",
        capabilities=["lightweight_inference"],
        keywords=["aihat", "ai-hat", "npu"],
    ),
    VirtualResourceRegistryEntry(
        id="vd-x86-gpu-inference",
        display_name="x86 GPU Inference",
        node="etri-ser0002-cgnmsb",
        resource_type="gpu",
        stage_type="ai_inference",
        capabilities=["gpu_inference", "anomaly_model"],
        keywords=["gpu", "inference", "vision", "anomaly"],
    ),
    VirtualResourceRegistryEntry(
        id="vd-jetson-gpu-lite",
        display_name="Jetson GPU-lite",
        node="etri-dev0001-jetorn",
        resource_type="gpu-lite",
        stage_type="preprocess/inference",
        capabilities=["edge_preprocess", "gpu_lite_inference"],
        keywords=["jetson", "gpu-lite", "edge-ai"],
    ),
    VirtualResourceRegistryEntry(
        id="vd-storage-cache",
        display_name="Storage Cache",
        node="etri-ser0002-cgnmsb",
        resource_type="storage/cache",
        stage_type="result_cache",
        capabilities=["result_cache", "window_storage"],
        keywords=["cache", "storage", "redis", "minio", "bucket"],
    ),
)
