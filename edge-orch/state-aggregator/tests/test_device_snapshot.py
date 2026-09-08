import asyncio

import pytest

from app.config import Settings
from app.edgex import EdgeXBackendError
from app.service import StateAggregatorService


def test_concurrent_readers_share_work_and_cancelled_reader_does_not_cancel_refresh(tmp_path):
    async def run():
        service = StateAggregatorService(Settings(data_dir=tmp_path))
        gate = asyncio.Event()
        calls = 0

        async def read():
            nonlocal calls
            calls += 1
            await gate.wait()
            return []

        service._read_device_snapshot = read
        first = asyncio.create_task(service.get_devices())
        second = asyncio.create_task(service.get_devices())
        await asyncio.sleep(0)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        gate.set()
        assert await second == []
        assert await service.get_devices() == []
        assert calls == 1
        await service.stop()

    asyncio.run(run())


def test_snapshot_timeout_cancels_work_and_backoff_does_not_return_old_success(tmp_path):
    async def run():
        service = StateAggregatorService(Settings(
            data_dir=tmp_path, edgex_device_snapshot_ttl_seconds=0,
            edgex_device_snapshot_timeout_seconds=0.02,
        ))
        service._device_snapshot = []
        cancelled = asyncio.Event()
        calls = 0

        async def read():
            nonlocal calls
            calls += 1
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()

        service._read_device_snapshot = read
        with pytest.raises(EdgeXBackendError, match="deadline"):
            await service.get_devices()
        assert cancelled.is_set()
        with pytest.raises(EdgeXBackendError):
            await service.get_devices()
        assert calls == 1
        assert service._device_snapshot is None
        await service.stop()

    asyncio.run(run())


def test_cache_recomputes_freshness_and_recovers_after_failure(tmp_path):
    async def run():
        service = StateAggregatorService(Settings(data_dir=tmp_path, edgex_device_error_backoff_seconds=0))
        fail = True
        normalized = []

        async def read():
            if fail:
                raise EdgeXBackendError("offline")
            return [("device", ["original timestamp"])]

        service._read_device_snapshot = read
        service._normalize_edgex_device = lambda d, r: normalized.append((d, r))
        with pytest.raises(EdgeXBackendError):
            await service.get_devices()
        fail = False
        await service.get_devices()
        await service.get_devices()
        assert normalized == [("device", ["original timestamp"])] * 2
        assert service._device_error is None
        await service.stop()

    asyncio.run(run())
