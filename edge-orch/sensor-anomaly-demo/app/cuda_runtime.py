from __future__ import annotations

from typing import Protocol


class CudaRuntime(Protocol):
    name: str
    device_name: str
    ready: bool

    def score_vector(
        self,
        values: list[float],
        means: list[float],
        standard_deviations: list[float],
    ) -> float: ...

    def weighted_average(
        self,
        values: list[float],
        weights: list[float],
    ) -> float: ...


class CupyCudaRuntime:
    """Small fail-closed CUDA execution provider used by the server model.

    Import, device selection, allocation, a kernel operation and stream
    synchronization all happen during construction. The inference Pod therefore
    cannot report model readiness when HAMi did not expose a working GPU.
    """

    name = "cuda"

    def __init__(self) -> None:
        try:
            import cupy

            if cupy.cuda.runtime.getDeviceCount() < 1:
                raise RuntimeError("no CUDA device was assigned")
            device = cupy.cuda.Device()
            device.use()
            probe = cupy.asarray([1.0, 2.0], dtype=cupy.float64)
            probe = cupy.square(probe).sum()
            if float(probe.item()) != 5.0:
                raise RuntimeError("CUDA probe returned an unexpected result")
            device.synchronize()
            properties = cupy.cuda.runtime.getDeviceProperties(device.id)
            raw_name = properties.get("name", "unknown CUDA device")
            self.device_name = (
                raw_name.decode("utf-8", errors="replace")
                if isinstance(raw_name, bytes)
                else str(raw_name)
            )
            self._cupy = cupy
            self._device = device
            self.ready = True
        except Exception as exc:
            raise RuntimeError(f"CUDA runtime initialization failed: {exc}") from exc

    def score_vector(
        self,
        values: list[float],
        means: list[float],
        standard_deviations: list[float],
    ) -> float:
        cupy = self._cupy
        vector = cupy.asarray(values, dtype=cupy.float64)
        baseline = cupy.asarray(means, dtype=cupy.float64)
        deviations = cupy.asarray(standard_deviations, dtype=cupy.float64)
        score = cupy.max(cupy.abs(vector - baseline) / deviations)
        self._device.synchronize()
        return float(score.item())

    def weighted_average(
        self,
        values: list[float],
        weights: list[float],
    ) -> float:
        cupy = self._cupy
        vector = cupy.asarray(values, dtype=cupy.float64)
        weight_vector = cupy.asarray(weights, dtype=cupy.float64)
        fused = cupy.sum(vector * weight_vector) / cupy.sum(weight_vector)
        self._device.synchronize()
        return float(fused.item())
