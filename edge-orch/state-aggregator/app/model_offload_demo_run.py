"""Bounded, single-owner live demonstration. The executor chooses every hop."""
from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid

from fastapi import APIRouter, HTTPException

from .model_offload_controller import ModelOffloadError


PHASES = [("Nano 정상 부하", 2, 30), ("AGX 승격 부하", 3.8, 140),
          ("Spark 승격 부하", 5.6, 100), ("AGX 복귀 부하", 2.7, 100),
          ("Nano 복귀 부하", 2, 100)]
ACTIVE = {"running", "stopping", "settling"}


class OrderedDemoRun:
    def __init__(self, controller, phases=PHASES, settle_seconds=240):
        self.controller = controller
        self.phases = phases
        self.settle_seconds = settle_seconds
        self.task = None
        self.stop_event = asyncio.Event()
        self.pending = set()
        self.path = Path(controller.journal.lock.name).parent / "demo-ui-run.json"
        self.dirty = False
        row = controller.journal.db.execute("SELECT value FROM metadata WHERE key='demo-ui-run'").fetchone()
        self.run = json.loads(self.path.read_text()) if self.path.exists() else json.loads(row[0]) if row else None
        if self.run and self.run["status"] in ACTIVE:
            self.run.update(status="interrupted", finished_at=time.time(), reason="controller_restarted")
            self.save()

    @property
    def active(self):
        return self.task is not None and not self.task.done()

    def save(self):
        # UI summaries must not add synchronous FULL-WAL commits/checkpoints to
        # the request/health event loop. A single asynchronous writer coalesces
        # summaries; the existing request WAL remains the admission authority.
        self.dirty = True

    def write_snapshot(self, encoded):
        temporary = self.path.with_suffix(".tmp")
        with temporary.open("w") as file:
            file.write(encoded)
            file.flush()
            os.fsync(file.fileno())
        temporary.replace(self.path)
        descriptor = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    async def persist(self):
        encoded = json.dumps(self.run)
        self.dirty = False
        task = asyncio.create_task(asyncio.to_thread(self.write_snapshot, encoded))
        try:
            await asyncio.shield(task)
        except asyncio.CancelledError:
            # Finish an already-started atomic write before a final write or
            # shutdown, so an older snapshot cannot replace a newer one.
            await task
            raise

    def ready(self):
        c = self.controller
        return (c.running and not c.closing and c.state == "LOCAL" and c.target == c.edge
                and not c.touched and not c.recovering and c.rate() == 0
                and not any(c.inflight.values()) and all(q.empty() for q in c.queues.values())
                and c.healthy(c.edge) and all(c.resource_ready(n) for n in c.order))

    def observe(self):
        c = self.controller
        if self.run["visited"][-1] != c.target:
            self.run["visited"].append(c.target)
            self.run["transitions"].append({"at": time.time(), "node": c.target, "reason": c.reason})
            self.save()

    def snapshot(self):
        run = copy.deepcopy(self.run)
        if run:
            run["elapsed_seconds"] = max(0, (run.get("finished_at") or time.time()) - run["started_at"])
        return {"run": run, "active": self.active, "can_start": not self.active and self.ready(),
                "runtime": self.controller.snapshot(),
                "phases": [{"label": p, "rps": r, "seconds": s} for p, r, s in self.phases]}

    def start(self):
        if self.active:
            raise ModelOffloadError("demo_already_running", 409)
        if not self.ready():
            raise ModelOffloadError("demo_workers_not_ready_or_busy", 409)
        c = self.controller
        self.stop_event = asyncio.Event()
        self.run = {"id": uuid.uuid4().hex, "status": "running", "started_at": time.time(),
                    "finished_at": None, "phase": 0, "phase_label": self.phases[0][0],
                    "offered_rps": self.phases[0][1], "planned": sum(round(r*s) for _, r, s in self.phases),
                    "attempted": 0, "completed": 0, "ok": 0, "errors": {}, "by_node": {},
                    "visited": [c.edge], "transitions": [], "baseline_cycles": c.cycles,
                    "expected": c.order + c.order[-2::-1], "passed": False, "last_result": None}
        self.save()
        self.task = asyncio.create_task(self.execute())
        return self.snapshot()

    def stop(self):
        if self.active:
            self.stop_event.set()
            self.run.update(status="stopping", offered_rps=0, phase_label="신규 요청 중지 · 복귀 대기")
            self.save()
        return self.snapshot()

    async def wait_or_stop(self, seconds):
        try:
            await asyncio.wait_for(self.stop_event.wait(), timeout=max(0.0001, seconds))
        except TimeoutError:
            pass

    def fail(self, status):
        self.run["errors"][status] = self.run["errors"].get(status, 0) + 1
        self.run["completed"] += 1
        self.save()

    async def request(self, request_id):
        try:
            c = self.controller
            response = await c.submit(request_id, c.contract.prompt, c.contract.max_tokens)
            if response["status"] != "ok":
                self.fail(response["status"])
                return
            result = response["result"]
            node = result.get("node_id")
            if node != response["node"] or node not in c.order:
                self.fail("response_identity_mismatch")
                return
            self.run["ok"] += 1
            self.run["completed"] += 1
            self.run["by_node"][node] = self.run["by_node"].get(node, 0) + 1
            self.run["last_result"] = {"node": node, "text": result.get("response", ""),
                                       "ttft_ms": result.get("gateway_ttft_ms"), "at": time.time()}
            self.save()
        except Exception as exc:
            self.fail(exc.reason if isinstance(exc, ModelOffloadError) else "request_error")

    async def watch(self, finished):
        while not finished.is_set():
            self.observe()
            if self.dirty:
                await self.persist()
            try:
                await asyncio.wait_for(finished.wait(), timeout=.5)
            except TimeoutError:
                pass

    async def execute(self):
        finished = asyncio.Event()
        watcher = None
        database = self.controller.journal.db
        checkpoint_limit = database.execute("PRAGMA wal_autocheckpoint").fetchone()[0]
        try:
            # No generated request precedes its durable run header.
            await self.persist()
            # This fixed-size run has at most 1,622 requests. Keep FULL WAL
            # durability, but move checkpoint I/O out of the active event loop.
            # Direct /generate is excluded while this runner owns admissions.
            database.execute("PRAGMA wal_autocheckpoint=0")
            watcher = asyncio.create_task(self.watch(finished))
            for phase, (label, rate, duration) in enumerate(self.phases):
                if self.stop_event.is_set():
                    break
                self.run.update(phase=phase, phase_label=label, offered_rps=rate)
                self.save()
                start = time.monotonic()
                for index in range(round(rate * duration)):
                    await self.wait_or_stop(start + index / rate - time.monotonic())
                    if self.stop_event.is_set():
                        break
                    self.run["attempted"] += 1
                    self.save()
                    if len(self.pending) >= 32:
                        self.fail("load_generator_capacity")
                        continue
                    request = asyncio.create_task(self.request(f"ui-{self.run['id']}-{phase}-{index}"))
                    self.pending.add(request)
                    request.add_done_callback(self.pending.discard)
            self.run.update(status="settling", offered_rps=0, phase_label="요청 마무리 · 모델 메모리 해제 확인")
            self.save()
            if self.pending:
                await asyncio.gather(*self.pending)
            deadline = time.monotonic() + self.settle_seconds
            while time.monotonic() < deadline:
                self.observe()
                if self.ready():
                    break
                await asyncio.sleep(.5)
            self.observe()
            self.run["passed"] = (not self.stop_event.is_set() and self.ready()
                and self.run["ok"] == self.run["planned"] and not self.run["errors"]
                and self.run["visited"] == self.run["expected"]
                and self.controller.cycles > self.run["baseline_cycles"])
            status = "passed" if self.run["passed"] else "failed"
            if self.stop_event.is_set() and self.ready():
                status = "stopped"
            self.run.update(status=status, reason="cleanup_not_verified" if not self.ready() else None)
        except asyncio.CancelledError:
            self.run.update(status="interrupted", reason="controller_stopped")
            raise
        except Exception as exc:
            self.run.update(status="failed", reason=type(exc).__name__)
        finally:
            finished.set()
            if watcher:
                await watcher
            self.run.update(finished_at=time.time(), offered_rps=0)
            try:
                def checkpoint():
                    with sqlite3.connect(Path(self.controller.journal.lock.name).with_suffix(""), timeout=2) as connection:
                        return connection.execute("PRAGMA wal_checkpoint(PASSIVE)").fetchone()
                task = asyncio.create_task(asyncio.to_thread(checkpoint))
                try:
                    result = await asyncio.shield(task)
                except asyncio.CancelledError:
                    await task
                    raise
                self.run["journal_checkpoint"] = dict(zip(("busy", "wal_pages", "checkpointed_pages"), result))
            finally:
                database.execute(f"PRAGMA wal_autocheckpoint={int(checkpoint_limit)}")
                await self.persist()

    async def close(self):
        if self.active:
            self.stop()
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        if self.pending:
            await asyncio.gather(*self.pending, return_exceptions=True)


def create_demo_run_router(runner):
    router = APIRouter(prefix="/api/demo", tags=["ordered-demo"])

    @router.get("")
    async def state():
        return runner.snapshot()

    @router.post("/start")
    async def start():
        try:
            return runner.start()
        except ModelOffloadError as exc:
            raise HTTPException(exc.status_code, exc.reason) from None

    @router.post("/stop")
    async def stop():
        return runner.stop()

    return router
