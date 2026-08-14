from __future__ import annotations

from .virtual_resources import VirtualResourceRegistryEntry


RESOURCE_REGISTRY: tuple[VirtualResourceRegistryEntry, ...] = (
    VirtualResourceRegistryEntry(
        id="server1-sensor-anomaly-inference",
        display_name="server1 Sensor Anomaly Inference",
        node="etri-ser0002-cgnmsb",
        resource_type="gpu",
        stage_type="ai_inference",
        capabilities=[
            "anomaly_model",
            "remote_inference",
            "cuda_inference",
            "hami_vgpu",
        ],
        workload_names=["sensor-anomaly-inference-server1"],
    ),
    VirtualResourceRegistryEntry(
        id="vd-aihat-inference",
        display_name="AI HAT Inference",
        node="etri-dev0002-raspi5",
        resource_type="ai-hat",
        stage_type="ai_inference",
        capabilities=["lightweight_inference"],
        workload_names=["vd-aihat-inference"],
    ),
    VirtualResourceRegistryEntry(
        id="vd-x86-gpu-inference",
        display_name="x86 GPU Inference",
        node="etri-ser0002-cgnmsb",
        resource_type="gpu",
        stage_type="ai_inference",
        capabilities=["gpu_inference", "anomaly_model"],
        workload_names=["vd-x86-gpu-inference"],
    ),
    VirtualResourceRegistryEntry(
        id="vd-jetson-gpu-lite",
        display_name="Jetson GPU-lite",
        node="etri-dev0001-jetorn",
        resource_type="gpu-lite",
        stage_type="preprocess/inference",
        capabilities=["edge_preprocess", "gpu_lite_inference"],
        workload_names=["vd-jetson-gpu-lite"],
    ),
    VirtualResourceRegistryEntry(
        id="vd-storage-cache",
        display_name="Storage Cache",
        node="etri-ser0002-cgnmsb",
        resource_type="storage/cache",
        stage_type="result_cache",
        capabilities=["result_cache", "window_storage"],
        workload_names=["vd-storage-cache"],
    ),
)
