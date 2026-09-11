import asyncio

import httpx
import pytest
from fastapi import HTTPException

from runtime_operator.api import create_app
from runtime_operator.controller import Controller
from runtime_operator.journal import Journal
from test_resident import setup


@pytest.fixture
def rig(tmp_path):
    k, _ = setup()
    k.resource["spec"]["policy"]["approvalRequired"] = True
    k.resource["spec"]["demo"] = {"label": "synthetic test of AI contract", "payload": {"prompt": "qualified input", "max_tokens": 8}}
    now = [100.]
    calls = []
    loaded = {"small": True, "large": False}
    j = Journal(str(tmp_path / "journal.db"))
    c = Controller(k, j, clock=lambda: now[0])
    async def probe(t):
        active = loaded[t["variant"]]
        return {"ready": active, "inFlight": 0, "released": not active, "modelVramMiB": 1000 if active else 0}
    def lifecycle(t, action):
        calls.append((t["variant"], action))
        loaded[t["variant"]] = action == "activate"
    c.probe = probe
    c.lifecycle = lifecycle
    yield c, k, now, calls
    asyncio.run(c.transport.aclose())
    j.close()


async def recommend(rig):
    c, k, now, calls = rig
    uid = k.resource["metadata"]["uid"]
    await c.tick()
    assert c.states[uid]["active"]["node"] == "field-any"
    c.pending[uid] = 3
    now[0] += 2
    await c.tick()
    now[0] += 2
    await c.tick()
    return uid, c.states[uid]["proposal"]["id"]


def test_pressure_never_prepares_before_approval_then_routes_after_ready_and_replay_is_idempotent(rig):
    async def run():
        c, k, now, calls = rig
        uid, pid = await recommend(rig)
        for _ in range(3):
            now[0] += 2
            await c.tick()
        assert not c.states[uid]["target"] and not calls and not k.actions
        app = create_app(c)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
            path = "/services/" + k.resource["metadata"]["name"] + "/augmentation/approve"
            body = {"serviceUid": uid, "recommendationId": pid}
            assert (await client.post(path, json=body)).json()["status"] == "Approved"
            assert not calls
            await c.tick()
            assert c.states[uid]["active"]["node"] == "field-any"
            assert c.states[uid]["lastApproval"]["status"] == "Preparing"
            await c.tick()
            assert c.states[uid]["active"]["node"] == "datacenter-any"
            assert c.states[uid]["lastApproval"]["status"] == "Applied"
            count = len(calls)
            assert (await client.post(path, json=body)).json()["status"] == "Applied"
            assert len(calls) == count
    asyncio.run(run())


@pytest.mark.parametrize("change", ["load", "candidate", "generation", "expiry", "uid"])
def test_approval_revalidates_current_conditions(rig, change):
    async def run():
        c, k, now, calls = rig
        uid, pid = await recommend(rig)
        if change == "load": c.pending[uid] = 0
        if change == "candidate": k.data["nodes"][1]["spec"]["unschedulable"] = True
        if change == "generation": k.resource["metadata"]["generation"] += 1
        if change == "expiry": now[0] += 61
        if change == "uid": uid = "wrong-uid"
        with pytest.raises(HTTPException) as error:
            await c.approve(k.resource["metadata"]["name"], uid, pid)
        assert error.value.status_code == 409 and not calls
    asyncio.run(run())


def test_approval_is_not_a_future_authorization_when_load_drops_or_process_restarts(rig):
    async def run():
        c, k, now, calls = rig
        uid, pid = await recommend(rig)
        await c.approve(k.resource["metadata"]["name"], uid, pid)
        c.pending[uid] = 0
        await c.tick()
        assert c.states[uid]["lastApproval"]["status"] == "Expired"
        assert not calls
        c.pending[uid] = 3
        await c.tick()
        now[0] += 2
        await c.tick()
        pid = c.states[uid]["proposal"]["id"]
        await c.approve(k.resource["metadata"]["name"], uid, pid)
        restarted = Controller(k, c.journal, c.transport, c.clock)
        assert restarted.states[uid]["lastApproval"]["status"] == "Interrupted"
        assert restarted.states[uid]["proposal"] is None
        assert not calls
    asyncio.run(run())


def test_AI_load_has_bounded_requests_and_does_not_imply_augmentation(rig):
    async def run():
        c,k,now,calls=rig
        k.resource["spec"]["demo"].update(maxRequests=2,concurrency=2,pressureSeconds=1,recoverySeconds=1)
        uid=k.resource["metadata"]["uid"]
        await c.tick()
        async def handler(request):
            import json
            body=json.loads(request.content)
            return httpx.Response(200,json={"request_id":body["request_id"],"node_id":"field-any",
                "model_digest":"c"*64,"response":"answer","eval_count":8})
        await c.transport.aclose()
        c.transport=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        app=create_app(c)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://runtime") as client:
            path="/demos/"+k.resource["metadata"]["name"]+"/runs/ai-load-test"
            body={"serviceUid":uid,"mode":"load"}
            assert (await client.post(path,json=body)).status_code==202
            assert (await client.post(path,json=body)).status_code==202
            await asyncio.gather(*list(app.state.demo_runner.tasks.values()))
            result=(await client.get(path,params={"serviceUid":uid})).json()
            assert result["phase"]=="Completed" and result["reason"]=="bounded_load_completed"
            assert result["sent"]==result["succeeded"]==2
            assert not calls and not c.states[uid].get("lastApproval")
            assert c.states[uid]["active"]["node"]=="field-any"
        await app.state.demo_runner.close()
    asyncio.run(run())
