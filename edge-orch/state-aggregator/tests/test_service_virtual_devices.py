import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from app.common_runtime import project
from app.service_virtual_devices import create_service_virtual_device_router, project_service_devices


def payload():
    return {"snapshotAgeSeconds": 1, "services": [{
        "uid": "llama-uid", "name": "llama-inference", "serviceKind": "ai",
        "phase": "Serving", "serving": True, "checkedAt": 99,
        "active": {"name": "revision-a", "node": "node-a", "role": "edge", "variant": "cpu", "capacity": 1,
                   "observation": {"at": 99, "health": {"ready": True, "inFlight": 2}}}}]}


def test_one_service_retains_identity_across_start_move_stop_and_multiple_locations():
    data = payload(); raw = data["services"][0]
    def view():
        return project_service_devices(project(data, 100), 100)
    first = view(); assert first.total == 1 and first.running == 1
    assert first.devices[0].id == "runtime:llama-uid"
    raw["target"] = {**raw["active"], "name": "revision-b", "node": "node-b", "observation": None}
    moving = view(); assert moving.total == 1 and moving.devices[0].state == "running"
    assert [p.role for p in moving.devices[0].locations] == ["active", "preparing"]
    raw.update(phase="Preparing", serving=False, active=None)
    assert view().devices[0].state == "starting"
    raw.update(phase="Draining", retiring=[raw["target"]], target=None)
    assert view().devices[0].state == "stopping"
    raw.update(phase="Suspended", retiring=[])
    stopped = view(); assert stopped.total == 1 and stopped.running == 0
    assert stopped.devices[0].state == "stopped" and stopped.devices[0].locations == []
    assert stopped.devices[0].id == first.devices[0].id
    raw["uid"] = "replacement-uid"
    assert view().devices[0].id != first.devices[0].id


def test_stale_or_failed_observations_do_not_invent_running_or_stopped_state():
    for field in ["snapshot", "service", "health", "future"]:
        data = payload(); raw = data["services"][0]
        if field == "snapshot": data["snapshotAgeSeconds"] = 20
        if field == "service": raw["checkedAt"] = 50
        if field == "health": raw["active"]["observation"]["at"] = 50
        if field == "future": raw["checkedAt"] = 200
        result = project_service_devices(project(data, 100), 100)
        row = result.devices[0]
        assert row.state == "unknown" and row.serving is None and result.running is None
        if field != "health": assert row.locations == []
    raw["phase"] = "Deleted"
    assert project_service_devices(project(data, 100), 100).devices == []


def test_router_is_get_only_retains_definitions_on_outage_and_recovers_or_removes_deleted():
    async def run():
        mode = "ok"; requests = []
        def upstream(request):
            requests.append(request)
            assert request.method == "GET" and request.url.path == "/services"
            if mode == "offline": raise httpx.ConnectError("private endpoint")
            if mode == "empty": return httpx.Response(200, json={"snapshotAgeSeconds": 1, "services": []})
            return httpx.Response(200, json=payload())
        app = FastAPI(); app.include_router(create_service_virtual_device_router(
            SimpleNamespace(common_runtime_url="http://operator"), transport=httpx.MockTransport(upstream), clock=lambda: 100))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app") as client:
            path = "/api/service-virtual-devices"
            response = await client.get(path)
            assert response.headers["cache-control"] == "no-store" and response.json()["running"] == 1
            mode = "offline"; failed = (await client.get(path)).json()
            assert failed["total"] is None and failed["devices"][0]["state"] == "unknown"
            assert failed["devices"][0]["locations"] == [] and "private" not in str(failed)
            mode = "ok"; assert (await client.get(path)).json()["running"] == 1
            mode = "empty"; assert (await client.get(path)).json()["total"] == 0
            assert (await client.post(path)).status_code == 405
            assert len(requests) == 4
    asyncio.run(run())
