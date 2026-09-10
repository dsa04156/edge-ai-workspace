import asyncio
import json
import time

import httpx
from fastapi import FastAPI
import pytest

from app.model_offload_controller import ModelOffloadError
from app.model_offload_demo_run import OrderedDemoRun, create_demo_run_router
from test_model_offload_ordered import controller_at_start


def test_tokenless_start_duplicate_and_stop_preserves_admitted_request(tmp_path):
    async def run():
        c, transport = await controller_at_start(tmp_path)
        runner = OrderedDemoRun(c, phases=[("test", 20, 1)], settle_seconds=.05)
        # Real controller admissions count arrivals; no new requests are admitted
        # after stop. For this short test only, clear the rate window after drain.
        transport.request_gate = asyncio.Event()
        app = FastAPI()
        app.include_router(create_demo_run_router(runner))
        try:
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                assert not runner.active
                assert (await client.post("/api/demo/start")).status_code == 200
                assert (await client.post("/api/demo/start")).status_code == 409
                await asyncio.sleep(.02)
                assert runner.run["attempted"] == 1
                assert c.journal.db.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == 0
                assert c.journal.db.execute("PRAGMA synchronous").fetchone()[0] == 2
                assert (await client.post("/api/demo/stop")).status_code == 200
                await asyncio.sleep(.02)
                assert runner.active and runner.run["completed"] == 0
                transport.request_gate.set()
                await asyncio.sleep(.02)
                c.arrivals.clear()
                await runner.task
                result = (await client.get("/api/demo")).json()
                assert result["run"]["status"] == "stopped"
                assert result["run"]["ok"] == 1 and result["run"]["attempted"] == 1
                assert not result["run"]["passed"]
                assert c.journal.db.execute("PRAGMA wal_autocheckpoint").fetchone()[0] == 1000
                assert result["run"]["journal_checkpoint"]["busy"] == 0
        finally:
            transport.request_gate.set()
            await runner.close()
            await c.stop()
    asyncio.run(run())


def test_source_only_completion_cannot_pass_ordered_demo(tmp_path):
    async def run():
        c, _ = await controller_at_start(tmp_path)
        runner = OrderedDemoRun(c, phases=[("test", 100, .02)], settle_seconds=.01)
        try:
            runner.start()
            await runner.task
            assert runner.run["ok"] == 2
            assert runner.run["status"] == "failed" and not runner.run["passed"]
        finally:
            await runner.close()
            await c.stop()
    asyncio.run(run())


def test_unavailable_worker_blocks_start_and_saved_run_is_interrupted(tmp_path):
    async def run():
        c, _ = await controller_at_start(tmp_path)
        runner = OrderedDemoRun(c)
        try:
            c.samples[c.order[-1]] = {}
            with pytest.raises(ModelOffloadError, match="demo_workers_not_ready_or_busy"):
                runner.start()
            runner.run = {"id": "saved", "status": "settling", "ok": 3, "passed": False}
            runner.save()
            await runner.persist()
            restored = OrderedDemoRun(c)
            assert restored.run["status"] == "interrupted"
            assert restored.run["ok"] == 3 and not restored.run["passed"]
            assert not restored.active
        finally:
            await c.stop()
    asyncio.run(run())


def test_slow_summary_disk_write_does_not_block_health_event_loop(tmp_path):
    async def run():
        c, _ = await controller_at_start(tmp_path)
        runner = OrderedDemoRun(c)
        runner.run = {"status": "running", "ok": 0}
        original = runner.write_snapshot
        def slow_write(encoded):
            time.sleep(.2)
            original(encoded)
        runner.write_snapshot = slow_write
        ticks = 0
        async def heartbeat():
            nonlocal ticks
            for _ in range(5):
                await asyncio.sleep(.02)
                ticks += 1
        try:
            write = asyncio.create_task(runner.persist())
            await heartbeat()
            assert ticks == 5 and not write.done()
            await write
            assert json.loads(runner.path.read_text())["ok"] == 0
        finally:
            await c.stop()
    asyncio.run(run())
