import asyncio
import copy
import json
from types import SimpleNamespace

import httpx
import pytest

from runtime_operator.api import create_app
from runtime_operator.kube import Kube
from test_augmentation import rig


def configure(k):
    k.resource["spec"]["policy"]["stages"] = [{"variant": "small", "label": "Nano"}, {"variant": "large", "label": "Orin"}]
    k.resource["spec"]["demo"].update(maxRequests=20, concurrency=3, pressureSeconds=1, recoverySeconds=1)
    for v, n in zip(k.resource["spec"]["variants"], k.data["nodes"]):
        v["nodeSelector"] = {"kubernetes.io/hostname": n["metadata"]["name"]}
        n["metadata"]["labels"]["kubernetes.io/hostname"] = n["metadata"]["name"]


def response(request):
    body = json.loads(request.content)
    return httpx.Response(200, json={"request_id": body["request_id"], "node_id": "field-any",
        "model_digest": "c" * 64, "response": "answer", "eval_count": 8})


def test_node_load_is_identity_bound_and_stop_cancels_queued_without_stopping_service(rig):
    async def run():
        c, k, _, calls = rig
        configure(k)
        await c.tick()
        uid, name = k.resource["metadata"]["uid"], k.resource["metadata"]["name"]
        started, release = asyncio.Event(), asyncio.Event()
        dispatched = []
        async def handle(request):
            dispatched.append(request)
            started.set()
            await release.wait()
            return response(request)
        await c.transport.aclose()
        c.transport = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        app = create_app(c)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            path = f"/demos/{name}/runs/node-load-one"
            body = {"serviceUid": uid, "mode": "node-load", "targetNode": "field-any"}
            assert (await client.post(path, json={**body, "targetNode": "datacenter-any"})).status_code == 409
            assert (await client.post(path, json={"serviceUid": uid, "mode": "node-load"})).status_code == 422
            assert (await client.post(path, json=body)).status_code == 202
            await started.wait()
            await asyncio.sleep(.02)
            assert c.pending[uid] == 2
            assert (await client.post(path, json={**body, "targetNode": "datacenter-any"})).status_code == 409
            receipt = (await client.post(path + "/stop", json={"serviceUid": uid})).json()
            assert receipt["phase"] == "Stopping"
            await asyncio.sleep(.08)
            assert c.pending[uid] == 0
            release.set()
            await asyncio.gather(*list(app.state.demo_runner.tasks.values()))
            result = (await client.get(path, params={"serviceUid": uid})).json()
            assert result["phase"] == "Stopped" and result["targetNode"] == "field-any"
            assert result["sent"] == 3 and result["succeeded"] == 1 and result["cancelled"] == 2
            assert len(dispatched) == 1 and not calls and c.states[uid]["serving"]
        await app.state.demo_runner.close()
    asyncio.run(run())


def test_route_switch_does_not_send_old_node_load_to_new_node(rig):
    async def run():
        c, k, _, _ = rig
        configure(k)
        await c.tick()
        uid, name = k.resource["metadata"]["uid"], k.resource["metadata"]["name"]
        started, release = asyncio.Event(), asyncio.Event()
        dispatched = []
        async def handle(request):
            dispatched.append(request.url.host)
            started.set()
            await release.wait()
            return response(request)
        await c.transport.aclose()
        c.transport = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        app = create_app(c)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            path = f"/demos/{name}/runs/node-load-route"
            await client.post(path, json={"serviceUid": uid, "mode": "node-load", "targetNode": "field-any"})
            await started.wait()
            c.states[uid]["active"] = {**c.states[uid]["active"], "node": "datacenter-any", "variant": "large", "name": "other-route"}
            await asyncio.sleep(.08)
            release.set()
            await asyncio.gather(*list(app.state.demo_runner.tasks.values()))
            result = (await client.get(path, params={"serviceUid": uid})).json()
            assert result["phase"] == "Stopped" and result["reason"] == "node_route_changed"
            assert len(dispatched) == 1 and dispatched[0].startswith("small.")
            assert result["cancelled"] == 2
        await app.state.demo_runner.close()
    asyncio.run(run())


def test_service_stop_drains_and_releases_then_start_reactivates_and_stopped_stays_in_catalog(rig):
    async def run():
        c, k, now, calls = rig
        configure(k)
        def set_suspended(name, uid, suspended):
            assert name == k.resource["metadata"]["name"] and uid == k.resource["metadata"]["uid"]
            k.resource["spec"]["suspended"] = suspended
            return copy.deepcopy(k.resource)
        k.set_suspended = set_suspended
        await c.tick()
        uid, name = k.resource["metadata"]["uid"], k.resource["metadata"]["name"]
        app = create_app(c)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://local") as client:
            path = f"/demos/{name}/service"
            assert (await client.post(path, json={"serviceUid": "wrong-uid", "action": "stop"})).status_code == 409
            r = await client.post(path, json={"serviceUid": uid, "action": "stop"})
            assert r.status_code == 202 and r.json()["phase"] == "Stopping"
            assert not c.states[uid]["serving"] and k.resource["spec"]["suspended"]
            assert (await client.post(path, json={"serviceUid": uid, "action": "start"})).status_code == 409
            await c.tick()
            await c.tick()
            assert c.states[uid]["phase"] == "Suspended" and ("small", "release") in calls
            now[0] += 30
            await c.tick()
            assert c.states[uid]["checkedAt"] == now[0]
            item = (await client.get("/demos")).json()["items"][0]
            assert item["serviceControl"]["phase"] == "Stopped" and item["serviceControl"]["canStart"]
            assert not item["available"] and not any(n["available"] for n in item["nodes"])
            r = await client.post(path, json={"serviceUid": uid, "action": "start"})
            assert r.json()["phase"] == "Starting" and not k.resource["spec"]["suspended"]
            await c.tick()
            await c.tick()
            assert c.states[uid]["serving"] and c.states[uid]["active"]["node"] == "field-any"
            assert ("small", "activate") in calls
        await app.state.demo_runner.close()
    asyncio.run(run())


def test_kube_service_toggle_preserves_latest_spec_and_fences_uid(rig):
    _, k, _, _ = rig
    writes = []
    adapter = object.__new__(Kube)
    adapter.namespace = "platform-runtime"
    resource = copy.deepcopy(k.resource)
    resource["metadata"]["resourceVersion"] = "latest-rv"
    adapter.custom = SimpleNamespace(get_namespaced_custom_object=lambda *a, **kw: copy.deepcopy(resource),
        replace_namespaced_custom_object=lambda *a, **kw: writes.append(a[-1]) or a[-1])
    result = adapter.set_suspended(resource["metadata"]["name"], resource["metadata"]["uid"], True)
    assert result["metadata"]["resourceVersion"] == "latest-rv"
    assert {k: v for k, v in result["spec"].items() if k != "suspended"} == resource["spec"]
    with pytest.raises(ValueError):
        adapter.set_suspended(resource["metadata"]["name"], "recreated-uid", True)
    assert len(writes) == 1
    resource["spec"].pop("demo")
    with pytest.raises(ValueError):
        adapter.set_suspended(resource["metadata"]["name"], resource["metadata"]["uid"], True)
    assert len(writes) == 1
