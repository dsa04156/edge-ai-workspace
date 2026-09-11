import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from app.common_runtime_demo import create_common_demo_router


def receipt():
    return {"id": "run-one1", "uid": "service-uid", "name": "service", "label": "Fixed demo",
        "mode": "single", "phase": "Running", "stage": "single", "createdAt": 100,
        "sent": 0, "succeeded": 0, "failed": 0, "unknown": 0, "lastResult": None,
        "routeHistory": [], "recentRequests": [], "startNode": "any-edge", "startRole": "edge",
        "returned": False, "retiring": 0, "stopRequested": False}


def test_token_free_same_origin_proxy_restricts_mutations_to_declared_run_identity():
    async def run():
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(202, json=receipt())
        app = FastAPI()
        app.include_router(create_common_demo_router(SimpleNamespace(common_runtime_demo_enabled=True,
            common_runtime_url="http://operator"), transport=httpx.MockTransport(handler)))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://nexus") as client:
            path = "/api/runtime-demos/service/runs/run-one1"
            body = {"serviceUid": "service-uid", "mode": "single"}
            good = {"Origin": "http://nexus", "X-Runtime-Demo": "1"}
            for headers in ({}, {"Origin": "http://evil", "X-Runtime-Demo": "1"}, {"Origin": "http://nexus"}):
                assert (await client.post(path, json=body, headers=headers)).status_code == 403
            assert not calls
            assert (await client.post(path, json={**body, "payload": {"arbitrary": True}}, headers=good)).status_code == 422
            response = await client.post(path, json=body, headers=good)
            assert response.status_code == 202 and response.json()["phase"] == "Running"
            assert len(calls) == 1 and calls[0].url == "http://operator/demos/service/runs/run-one1"
            assert "execution-token" not in str(calls[0].headers).lower()
            assert (await client.post(path+"/stop", json={"serviceUid": "service-uid"}, headers=good)).status_code == 200
            assert calls[-1].url.path.endswith("/stop")
    asyncio.run(run())


def test_disabled_demo_and_source_failures_are_explicit_without_following_redirects():
    async def run():
        for mode in ("disabled", "offline", "redirect", "malformed"):
            calls = []
            def handler(request):
                calls.append(request)
                if mode == "offline":
                    raise httpx.ConnectError("private-url")
                if mode == "redirect":
                    return httpx.Response(302, headers={"Location": "http://other"}, json={})
                return httpx.Response(500, json=[])
            app = FastAPI()
            app.include_router(create_common_demo_router(SimpleNamespace(common_runtime_demo_enabled=mode!="disabled",
                common_runtime_url="http://operator"), transport=httpx.MockTransport(handler), clock=lambda:100))
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://nexus") as client:
                response = await client.get("/state/runtime-demos")
                assert response.headers["Cache-Control"] == "no-store"
                data = response.json()
                if mode == "disabled":
                    assert not data["enabled"] and not calls
                else:
                    assert data["observation_error"] == "demo_source_unavailable" and len(calls) == 1
                    assert "private" not in response.text
    asyncio.run(run())


def test_augmentation_approval_preserves_identity_and_requires_same_origin():
    async def run():
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(202, json={"id":"a"*32,"createdAt":100,"expiresAt":160,
                "sourceNode":"edge","node":"server","role":"server","variant":"model",
                "reason":"sustained_pressure","status":"Approved"})
        app=FastAPI()
        app.include_router(create_common_demo_router(SimpleNamespace(common_runtime_demo_enabled=True,
            common_runtime_url="http://operator"),transport=httpx.MockTransport(handler)))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url="http://nexus") as client:
            path="/api/runtime-demos/llama/augmentation/approve"
            body={"serviceUid":"service-uid","recommendationId":"a"*32}
            assert (await client.post(path,json=body)).status_code==403
            assert not calls
            response=await client.post(path,json=body,headers={"Origin":"http://nexus","X-Runtime-Demo":"1"})
            assert response.status_code==202 and response.json()["status"]=="Approved"
            assert calls[0].url.path=="/services/llama/augmentation/approve"
    asyncio.run(run())
