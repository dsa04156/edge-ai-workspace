import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from app.common_runtime import create_common_runtime_router, project


def payload():
    return {"snapshotAgeSeconds": 1, "lastError": None, "services": [{
        "uid": "u1", "name": "external-service", "phase": "Serving", "serving": True,
        "checkedAt": 99, "active": {"name": "revision", "node": "arbitrary-node",
        "role": "edge", "variant": "gpu", "capacity": 1, "resident": {"service": "private"},
        "spec": {"image": "private", "prompt": "not exposed"},
        "observation": {"at": 99, "health": {"ready": True, "inFlight": 0, "modelVramMiB": 1234}}}}]}


def test_projection_retains_model_evidence_but_excludes_internal_contract():
    state = project(payload(), 100)
    item = state.services[0]
    assert item.serving and item.active.memoryOnlyRelease
    assert item.active.observation.health.modelVramMiB == 1234
    result = state.model_dump_json()
    assert "private" not in result and "not exposed" not in result


def test_stale_snapshot_service_or_worker_cannot_claim_current_model_state():
    for field in ("snapshot", "service", "worker"):
        data = payload()
        if field == "snapshot":
            data["snapshotAgeSeconds"] = 30
        elif field == "service":
            data["services"][0]["checkedAt"] = 50
        else:
            data["services"][0]["active"]["observation"]["at"] = 50
        result = project(data, 100)
        assert result.services[0].active.observation is None
        if field != "worker":
            assert not result.services[0].serving


def test_latency_is_only_projected_for_current_active_revision_and_fresh_sample():
    data = payload()
    data["services"][0]["latency"] = {"at": 99, "target": "revision", "samples": 20,
        "successfulSamples": 20, "failures": 0, "p95Milliseconds": 123, "valid": True,
        "reason": "measured", "maxP95Milliseconds": 100, "returnP95Milliseconds": 80,
        "windowSeconds": 60, "scope": "gateway_queue_and_worker_response", "processLocal": True}
    assert project(data, 100).services[0].latency.p95Milliseconds == 123
    data["services"][0]["latency"]["target"] = "old-revision"
    assert project(data, 100).services[0].latency is None
    data["services"][0]["latency"].update(target="revision", at=50)
    assert project(data, 100).services[0].latency is None


def test_read_route_handles_invalid_and_unreachable_sources_without_mutations():
    async def run():
        for mode in ("ok", "unavailable", "invalid", "redirect"):
            requests = []
            def upstream(request):
                requests.append(request)
                if mode == "unavailable":
                    raise httpx.ConnectError("private detail")
                if mode == "redirect":
                    return httpx.Response(302, headers={"Location": "http://other/private"})
                return httpx.Response(200, json=payload() if mode == "ok" else {"bad": True})
            app = FastAPI()
            app.include_router(create_common_runtime_router(SimpleNamespace(common_runtime_url="http://operator"),
                transport=httpx.MockTransport(upstream), clock=lambda: 100))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://app") as client:
                response = await client.get("/state/runtime-services")
                assert response.status_code == 200 and response.headers["cache-control"] == "no-store"
                assert len(requests) == 1 and requests[0].method == "GET" and requests[0].url.path == "/services"
                if mode == "ok":
                    assert response.json()["services"][0]["serving"]
                else:
                    assert response.json()["observation_error"] == "runtime_source_unavailable"
                    assert "private" not in response.text
                assert (await client.post("/state/runtime-services")).status_code == 405
    asyncio.run(run())


def test_map_candidates_are_typed_public_metadata_and_removed_when_stale():
    data = payload()
    data["services"][0]["eligibleCandidates"] = [{"node": "candidate", "variant": "gpu", "role": "server", "private": "hidden"}]
    item = project(data, 100).services[0]
    assert item.eligibleCandidates[0].node == "candidate"
    assert "hidden" not in item.model_dump_json()
    assert project(data, 200).services[0].eligibleCandidates == []
