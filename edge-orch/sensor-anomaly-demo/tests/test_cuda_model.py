from __future__ import annotations

import pytest

from app.config import Settings
from app.model_adapter import CudaOnlineBaselinePumpModel
from app.models import AccelerationFrame, AxisSample


class FakeCudaRuntime:
    name = "cuda"
    device_name = "Fake NVIDIA GPU"
    ready = True

    def __init__(self) -> None:
        self.score_calls = 0
        self.fuse_calls = 0

    def score_vector(
        self,
        values: list[float],
        means: list[float],
        standard_deviations: list[float],
    ) -> float:
        self.score_calls += 1
        return max(
            abs(value - mean) / standard_deviation
            for value, mean, standard_deviation in zip(
                values, means, standard_deviations, strict=True
            )
        )

    def weighted_average(
        self,
        values: list[float],
        weights: list[float],
    ) -> float:
        self.fuse_calls += 1
        return sum(value * weight for value, weight in zip(values, weights, strict=True)) / sum(weights)


def test_cuda_model_runs_scoring_and_fusion_on_accelerator() -> None:
    runtime = FakeCudaRuntime()
    model = CudaOnlineBaselinePumpModel(
        Settings(
            service_role="inference-server",
            model_backend="cuda-online-baseline",
            model_version="cuda-baseline-1.0.0",
            warmup_samples=1,
            vibration_window_samples=2,
            temperature_window_samples=2,
        ),
        cuda_runtime=runtime,
    )
    frame = AccelerationFrame(origin=1, x=1.0, y=2.0, z=3.0)
    temperature = AxisSample(origin=1, value_type="Float64", value=30.0)
    model.ingest_temperature(temperature)

    decision = model.infer(frame, temperature.origin)

    assert decision is not None
    assert model.runtime_ready is True
    assert model.accelerator == "cuda"
    assert model.accelerator_device == "Fake NVIDIA GPU"
    assert runtime.score_calls == 0  # warm-up establishes the baseline
    assert runtime.fuse_calls == 1


def test_cuda_model_refuses_an_unavailable_accelerator() -> None:
    runtime = FakeCudaRuntime()
    runtime.ready = False

    with pytest.raises(RuntimeError, match="CUDA runtime is not ready"):
        CudaOnlineBaselinePumpModel(
            Settings(
                service_role="inference-server",
                model_backend="cuda-online-baseline",
            ),
            cuda_runtime=runtime,
        )
