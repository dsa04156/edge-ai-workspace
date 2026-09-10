import asyncio
import copy
import json

import httpx
import pytest
from pydantic import ValidationError

from runtime_operator.api import create_app
from runtime_operator.contract import ServiceSpec, revision
from runtime_operator.journal import Journal
from runtime_operator.demo import StartRequest
from fastapi import HTTPException
from test_runtime import activate, rig, spec_data


def enable(k):
    k.resource["spec"]["demo"] = {"label": "Synthetic echo", "payload": {"input": {"x": 42}},
        "pressureSeconds": 1, "recoverySeconds": 1, "maxRequests": 2, "concurrency": 2}


def test_demo_contract_is_opt_in_bounded_and_not_a_workload_revision():
    first = ServiceSpec.model_validate(spec_data())
    data = spec_data()
    data["demo"] = {"label": "echo", "payload": {"input": [1, 2, {"a": True}]}}
    second = ServiceSpec.model_validate(data)
    assert revision(first, first.variants[0], "edge") == revision(second, second.variants[0], "edge")
    data["demo"]["payload"] = {"value": float("nan")}
    with pytest.raises(ValidationError):
        ServiceSpec.model_validate(data)
    data["demo"]["payload"] = {"value": "x" * 70000}
    with pytest.raises(ValidationError):
        ServiceSpec.model_validate(data)


def test_demo_single_durable_idempotency_conflict_and_uid_fencing(rig):
    async def run():
        c, k, now, _, calls = rig
        enable(k)
        await activate(c, k)
        app = create_app(c)
        uid, name = k.resource["metadata"]["uid"], k.resource["metadata"]["name"]
        path = f"/demos/{name}/runs/request-one"
        body = {"serviceUid": uid, "mode": "single"}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            assert (await client.post(path, json=body)).status_code == 202
            assert (await client.post(path, json=body)).status_code == 202
            await asyncio.gather(*list(app.state.demo_runner.tasks.values()))
            result = (await client.get(path, params={"serviceUid": uid})).json()
            assert result["phase"] == "Completed" and result["sent"] == result["succeeded"] == 1
            assert "contract" not in result and len(result["recentRequests"]) == 1
            assert json.loads(result["lastResult"])["answer"] == k.resource["spec"]["demo"]["payload"]
            before = sum(r.method == "POST" for r in calls)
            assert (await client.post(path, json=body)).json()["phase"] == "Completed"
            assert sum(r.method == "POST" for r in calls) == before
            assert (await client.post(path, json={**body, "mode": "round-trip"})).status_code == 409
            assert (await client.post(path + "-new", json=body)).status_code == 429
            response = await client.post(f"/services/{name}/invoke", json={},
                headers={"X-Request-ID": "wrong-service", "X-Runtime-Service-Uid": "different-uid"})
            assert response.status_code == 409 and sum(r.method == "POST" for r in calls) == before
            k.resource["metadata"]["uid"] = "new-uid"
            c.snapshot = k.snapshot()
            now[0] += 20
            c.last_snapshot = now[0]
            assert (await client.post(path + "-new", json=body)).status_code == 409
        await app.state.demo_runner.close()
    asyncio.run(run())


def test_demo_requires_opt_in_current_snapshot_and_stable_runtime(rig):
    async def run():
        c, k, now, _, _ = rig
        await activate(c, k)
        app = create_app(c)
        uid, name = k.resource["metadata"]["uid"], k.resource["metadata"]["name"]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            path = f"/demos/{name}/runs/request-one"
            body = {"serviceUid": uid, "mode": "single"}
            assert (await client.post(path, json=body)).status_code == 403
            enable(k)
            await c.tick()
            now[0] += 20
            assert (await client.post(path, json=body)).status_code == 503
            catalog = (await client.get("/demos")).json()
            assert not catalog["items"] and catalog["observation_error"]
        await app.state.demo_runner.close()
    asyncio.run(run())


def test_bounded_run_without_role_roundtrip_is_incomplete_even_with_good_responses(rig):
    async def run():
        c, k, _, _, calls = rig
        enable(k)
        await activate(c, k)
        app = create_app(c)
        uid, name = k.resource["metadata"]["uid"], k.resource["metadata"]["name"]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            path = f"/demos/{name}/runs/bounded-run"
            body = {"serviceUid": uid, "mode": "round-trip"}
            assert (await client.post(path, json=body)).status_code == 202
            assert (await client.post(path + "-duplicate", json=body)).status_code == 409
            await asyncio.gather(*list(app.state.demo_runner.tasks.values()))
            result = (await client.get(path, params={"serviceUid": uid})).json()
            assert result["phase"] == "Incomplete" and not result["returned"]
            assert result["sent"] == result["succeeded"] == 2
            assert sum(r.method == "POST" for r in calls) == 2
        await app.state.demo_runner.close()
    asyncio.run(run())


def test_stop_waits_for_dispatched_request_and_admits_no_more(rig):
    async def run():
        c, k, _, remote, _ = rig
        enable(k)
        k.resource["spec"]["demo"].update(concurrency=1, maxRequests=10)
        await activate(c, k)
        started, release = asyncio.Event(), asyncio.Event()
        async def handler(request):
            if request.method == "GET":
                return httpx.Response(200, json=remote)
            started.set()
            await release.wait()
            return httpx.Response(200, json={"answer": "done"})
        await c.transport.aclose()
        c.transport = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        app = create_app(c)
        uid, name = k.resource["metadata"]["uid"], k.resource["metadata"]["name"]
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            path = f"/demos/{name}/runs/stop-one"
            await client.post(path, json={"serviceUid": uid, "mode": "round-trip"})
            await started.wait()
            result = (await client.post(path + "/stop", json={"serviceUid": uid})).json()
            assert result["phase"] == "Stopping"
            release.set()
            await asyncio.gather(*list(app.state.demo_runner.tasks.values()))
            result = (await client.get(path, params={"serviceUid": uid})).json()
            assert result["phase"] == "Stopped" and result["sent"] == result["succeeded"] == 1
        await app.state.demo_runner.close()
    asyncio.run(run())


def test_restart_marks_accepted_intent_unknown_and_never_restarts_run(tmp_path):
    path = str(tmp_path / "journal.sqlite3")
    journal = Journal(path)
    journal.demo_save({"uid": "u", "id": "r", "name": "service", "phase": "Running", "createdAt": 1,
                       "unknown": 0, "requests": [{"id": "request", "state": "pending"}]})
    journal.close()

    journal = Journal(path)
    result = journal.demo_get("u", "r")
    assert result["phase"] == "Interrupted" and result["unknown"] == 1
    assert result["requests"][0]["state"] == "unknown"
    assert not journal.demo_list(active=True)
    journal.close()


def test_global_limit_and_shutdown_before_first_request_preserve_durable_interruption(rig):
    async def run():
        c, k, _, _, _ = rig
        enable(k)
        await activate(c, k)
        original = k.resource["metadata"]["uid"]
        for index in (2, 3):
            other = copy.deepcopy(k.resource)
            other["metadata"].update(uid="uid-"+str(index), name="service-"+str(index))
            k.data["services"].append(other)
            c.states[other["metadata"]["uid"]] = copy.deepcopy(c.states[original])
        c.snapshot = k.snapshot()
        app = create_app(c)
        runner = app.state.demo_runner
        runner.start(k.resource["metadata"]["name"], "run-first", StartRequest(serviceUid=original, mode="single"))
        runner.start("service-2", "run-second", StartRequest(serviceUid="uid-2", mode="single"))
        with pytest.raises(HTTPException) as exc:
            runner.start("service-3", "run-third", StartRequest(serviceUid="uid-3", mode="single"))
        assert exc.value.status_code == 409
        await runner.close()
        assert not c.journal.demo_list(active=True)
        assert all(r["phase"] == "Interrupted" and r["sent"] == 0 for r in c.journal.demo_list())
    asyncio.run(run())
