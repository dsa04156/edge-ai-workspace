import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest

from runtime_operator.api import create_app
from runtime_operator.common_ai import AIServiceConfig
from runtime_operator.contract import ServiceSpec
from runtime_operator.journal import Journal
from test_three_tier import three_tier


CONFIG = json.loads((Path(__file__).resolve().parents[1] / "examples/llama-three-tier/common-ai.json").read_text())["spec"]["commonAI"]


def request_body(name, request_id="real-contract-test"):
    return {"schema_version": "edgeai.execution/v1", "request_id": request_id, "service_id": name,
            "source": {"type": "edgex", "device_id": "temperature", "profile_id": "temperature-profile",
                       "event_id": "event-123", "origin_ns": "1789361758946343000"},
            "timestamp": "2026-09-14T04:55:58.946343Z",
            "input": {"type": "sensor", "data": {"measurements": [{"name": "temperature_raw", "value": 354, "unit": "raw"}]}}}


def test_offload_cannot_be_enabled():
    data = copy.deepcopy(CONFIG)
    data["offload"]["enabled"] = True
    with pytest.raises(ValueError):
        AIServiceConfig.model_validate(data)


@pytest.mark.parametrize("fault", [None, "wrong_node", "wrong_model", "timeout", "negative_latency"])
def test_common_run_persist_readback_replay_and_fail_closed(tmp_path, fault):
    async def run():
        c, k, now, _ = three_tier(tmp_path)
        name, uid = k.resource["metadata"]["name"], k.resource["metadata"]["uid"]
        config = copy.deepcopy(CONFIG)
        config["service"].update(id=name, version="c" * 64)
        config["placement"].update(default_node="field-any", candidate_nodes=["field-any", "datacenter-any"])
        k.resource["spec"]["commonAI"] = config
        k.resource["spec"]["variants"][0]["nodeSelector"] = {"kubernetes.io/hostname": "field-any"}
        for node in k.data["nodes"]:
            node["metadata"]["labels"]["kubernetes.io/hostname"] = node["metadata"]["name"]
        sent = []
        async def handle(request):
            sent.append(json.loads(request.content))
            if fault == "timeout":
                raise httpx.ReadTimeout("lost response")
            result = {"request_id": sent[-1]["request_id"], "node_id": "field-any", "model": config["service"]["model"],
                      "model_digest": "c" * 64, "response": "temperature_raw is 354 raw.", "eval_count": 12,
                      "queue_wait_ms": 0.1, "inference_ms": 42, "actual_e2e_ms": 42.1}
            if fault == "wrong_node": result["node_id"] = "datacenter-any"
            if fault == "wrong_model": result["model_digest"] = "d" * 64
            if fault == "negative_latency": result["inference_ms"] = -1
            return httpx.Response(200, json=result)
        await c.transport.aclose()
        c.transport = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        try:
            await c.tick()
            await c.tick()
            assert c.states[uid]["serving"]
            before_samples = copy.deepcopy(c.latencies.__dict__)
            body = request_body(name)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(c)), base_url="http://test") as client:
                headers = {"X-Request-ID": body["request_id"]}
                path = f"/services/{name}/invoke"
                r = await client.post(path, json=body, headers=headers)
                assert r.status_code == (503 if fault else 200), r.text
                result = r.json()
                assert result["result"]["status"] == ("unknown" if fault else "success")
                assert result["execution"]["offloaded"] is False
                assert result["source"]["origin_ns"] == body["source"]["origin_ns"]
                read = await client.get(f"/services/{name}/requests/{body['request_id']}")
                assert read.json()["result"] == result
                replay = await client.post(path, json=body, headers=headers)
                assert replay.json() == result and len(sent) == 1
                conflict = copy.deepcopy(body)
                conflict["input"]["data"]["measurements"][0]["value"] = 355
                assert (await client.post(path, json=conflict, headers=headers)).status_code == 409
                assert len(sent) == 1
                assert c.latencies.__dict__ == before_samples
                assert "source" not in sent[0] and "354" in sent[0]["prompt"]
                c.journal.close()
                c.journal = Journal(str(tmp_path / "state.db"))
                assert (await client.get(f"/services/{name}/requests/{body['request_id']}" )).json()["result"] == result
                c.states[uid]["active"]["node"] = "datacenter-any"
                bad = request_body(name, "another")
                assert (await client.post(path, json=bad, headers={"X-Request-ID": "another"})).status_code == 400
                assert len(sent) == 1
        finally:
            await c.transport.aclose()
            c.journal.close()
    asyncio.run(run())


def test_restart_preserves_unknown_request_context(tmp_path):
    path = str(tmp_path / "journal.db")
    j = Journal(path)
    initial = {"schema_version": "edgeai.execution/v1", "source": {"device_id": "sensor"},
               "result": {"status": "unknown"}}
    j.dispatch("service", "request", "hash", "nano", initial)
    j.close()
    j = Journal(path)
    try:
        row = j.request("service", "request")
        assert row["state"] == "unknown" and row["status"] == 503
        assert json.loads(row["body"]) == initial
    finally:
        j.close()


def test_declaration_does_not_change_existing_workload_revision():
    from runtime_operator.contract import revision
    root = Path(__file__).resolve().parents[1]
    data = json.loads((root / "examples/llama-three-tier/service.json").read_text())["spec"]
    old = ServiceSpec.model_validate(data)
    data["commonAI"] = CONFIG
    new = ServiceSpec.model_validate(data)
    assert revision(old, old.variants[0], "nano") == revision(new, new.variants[0], "nano")


def automatic_fixture(tmp_path):
    from runtime_operator.common_ai import AIServiceConfig
    c, k, now, calls = three_tier(tmp_path)
    name, uid = k.resource["metadata"]["name"], k.resource["metadata"]["uid"]
    cfg = copy.deepcopy(CONFIG)
    cfg["service"].update(id=name, version="c" * 64)
    nodes = ["field-any", "another-edge", "datacenter-any"]
    cfg["placement"].update(default_node=nodes[0], candidate_nodes=nodes)
    cfg["input"].update(device_id="temperature", profile_id="temperature-profile", resource_name="temperature_raw",
                        unit="raw", minimum=0, maximum=1023)
    cfg["offload"]["enabled"] = True
    profile = AIServiceConfig.model_validate(cfg).input_profile()
    spec = k.resource["spec"]
    spec.update(commonAI=cfg, demo=None)
    spec["policy"].update(approvalRequired=False, cooldownSeconds=1, pressureSeconds=1, returnSeconds=2,
        latency={"maxP95Milliseconds": 1000, "returnP95Milliseconds": 800, "windowSeconds": 5,
                 "minSamples": 3, "breachSeconds": 1})
    for v, node in zip(spec["variants"], nodes):
        v.update(nodeSelector={"kubernetes.io/hostname": node}, qualifiedInputProfile=profile,
                 qualifiedP95Milliseconds=100)
    for node in k.data["nodes"]:
        node["metadata"]["labels"]["kubernetes.io/hostname"] = node["metadata"]["name"]
    ServiceSpec.model_validate(spec)
    return c, k, now, calls


@pytest.mark.parametrize("change", ["model", "token_limit", "unit", "missing_measurement", "candidate", "legacy_demo"])
def test_automatic_input_needs_its_own_measurements(tmp_path, change):
    c, k, _, _ = automatic_fixture(tmp_path)
    try:
        spec = copy.deepcopy(k.resource["spec"])
        if change == "model": spec["commonAI"]["service"]["version"] = "b" * 64
        if change == "token_limit": spec["commonAI"]["max_tokens"] = 128
        if change == "unit": spec["commonAI"]["input"]["unit"] = "Celsius"
        if change == "missing_measurement": spec["variants"][1]["qualifiedInputProfile"] = None
        if change == "candidate": spec["commonAI"]["placement"]["candidate_nodes"].pop()
        if change == "legacy_demo": spec["demo"] = {"label": "old", "payload": {}}
        with pytest.raises(ValueError): ServiceSpec.model_validate(spec)
    finally:
        asyncio.run(c.transport.aclose())
        c.journal.close()


def test_real_common_requests_drive_automatic_route_switch_and_idle_return(tmp_path):
    async def run():
        c, k, now, calls = automatic_fixture(tmp_path)
        name, uid = k.resource["metadata"]["name"], k.resource["metadata"]["uid"]
        sent, entered = [], asyncio.Event()
        release = asyncio.Event()
        async def handle(request):
            data = json.loads(request.content)
            node = "field-any" if "edge-runtime" in request.url.host else "another-edge"
            # Derive the actual selected endpoint from the registered resident binding.
            node = next(t["node"] for s in c.states.values() for t in
                [s.get("active"), *s.get("retiring", [])] if t and c.endpoint(t).split("//")[1].split(":")[0] == request.url.host)
            sent.append((data["request_id"], node))
            if len(sent) == 1:
                entered.set()
                await release.wait()
            return httpx.Response(200, json={"request_id": data["request_id"], "node_id": node,
                "model": CONFIG["service"]["model"], "model_digest": "c" * 64,
                "response": "temperature_raw is 354 raw.", "eval_count": 12,
                "queue_wait_ms": 0, "inference_ms": 30, "actual_e2e_ms": 30})
        await c.transport.aclose()
        c.transport = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        try:
            await c.tick()
            app = create_app(c)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                async def send(i):
                    body = request_body(name, "stream-" + str(i))
                    return await client.post(f"/services/{name}/invoke", json=body, headers={"X-Request-ID": body["request_id"]})
                tasks = [asyncio.create_task(send(i)) for i in range(4)]
                await entered.wait()
                await asyncio.sleep(.02)
                for _ in range(3):
                    now[0] += 2
                    await c.tick()
                assert c.states[uid]["active"]["node"] == "another-edge"
                assert ("medium", "activate") in calls
                assert c.inflight[next(t["name"] for t in c.states[uid]["retiring"] if t["node"] == "field-any")] == 1
                release.set()
                responses = await asyncio.gather(*tasks)
                assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
                assert {r.json()["execution"]["offloaded"] for r in responses} == {False, True}
                assert len(sent) == 4
                assert c.latencies.service_arrival_rps(uid, now[0], 20) == .2
                replay = await send(0)
                assert replay.json() == responses[0].json() and len(sent) == 4
                for i, response in enumerate(responses):
                    saved = await client.get(f"/services/{name}/requests/stream-{i}")
                    assert saved.json()["result"] == response.json()
                invalid = request_body(name, "out-of-range")
                invalid["input"]["data"]["measurements"][0]["value"] = 1024
                assert (await client.post(f"/services/{name}/invoke", json=invalid,
                    headers={"X-Request-ID": "out-of-range"})).status_code == 400
                legacy = {"prompt": "qualified input", "max_tokens": 8}
                assert (await client.post(f"/services/{name}/invoke", json=legacy,
                    headers={"X-Request-ID": "old-demo"})).status_code == 400
                for _ in range(45):
                    now[0] += 2
                    await c.tick()
                assert c.states[uid]["active"]["node"] == "field-any"
                assert not c.states[uid]["retiring"]
        finally:
            release.set()
            await c.transport.aclose()
            c.journal.close()
    asyncio.run(run())


def test_registered_worker_alias_still_requires_exact_model_digest():
    from runtime_operator.common_ai import validate_result
    cfg = AIServiceConfig.model_validate(CONFIG)
    cfg.worker_models = {"agx": "llama3.2:1b"}
    result = {"request_id": "r", "node_id": "agx", "model": "llama3.2:1b", "model_digest": cfg.service.version,
              "response": "raw 329", "eval_count": 4, "queue_wait_ms": 0, "inference_ms": 1, "actual_e2e_ms": 1}
    validate_result({"node": "agx"}, cfg, "r", result)
    for changed in [{"model": "unregistered"}, {"model_digest": "0" * 64}]:
        with pytest.raises(ValueError): validate_result({"node": "agx"}, cfg, "r", result | changed)


def test_common_demo_assigns_unique_request_ids_to_registered_replay_input(tmp_path):
    async def run():
        c, k, now, _ = automatic_fixture(tmp_path)
        name, uid = k.resource["metadata"]["name"], k.resource["metadata"]["uid"]
        k.resource["spec"]["demo"] = {"label": "registered sensor replay", "payload": request_body(name, "template")}
        sent = []
        async def handle(request):
            payload = json.loads(request.content)
            sent.append(payload["request_id"])
            return httpx.Response(200, json={"request_id": payload["request_id"], "node_id": "field-any",
                "model": CONFIG["service"]["model"], "model_digest": "c" * 64,
                "response": "raw 354", "eval_count": 4, "queue_wait_ms": 0, "inference_ms": 10, "actual_e2e_ms": 10})
        await c.transport.aclose()
        c.transport = httpx.AsyncClient(transport=httpx.MockTransport(handle))
        try:
            await c.tick()
            app = create_app(c)
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                r = await client.post(f"/demos/{name}/runs/common-replay-01", json={"serviceUid": uid, "mode": "single"})
                assert r.status_code == 202, r.text
                await asyncio.gather(*app.state.demo_runner.tasks.values())
                r = await client.get(f"/demos/{name}/runs/common-replay-01", params={"serviceUid": uid})
                assert r.json()["succeeded"] == 1, r.text
                assert sent[0].startswith("demo-") and sent[0] != "template"
        finally:
            await c.transport.aclose()
            c.journal.close()
    asyncio.run(run())


def test_periodic_real_input_returns_with_a_brief_inflight_request_but_never_with_queue(tmp_path):
    async def run():
        c,k,now,_=automatic_fixture(tmp_path)
        uid=k.resource["metadata"]["uid"]
        try:
            await c.tick()
            c.pending[uid]=3
            for _ in range(3):
                now[0]+=2
                await c.tick()
            assert c.states[uid]["active"]["variant"]=="medium"
            c.pending[uid]=0
            for _ in range(25):
                now[0]+=2
                active=c.states[uid]["active"]
                c.inflight[active["name"]]=1
                c.latencies.arrival(uid,active["name"],now[0])
                c.latencies.record(uid,active["name"],now[0],100,True)
                await c.tick()
                c.inflight[active["name"]]=0
                if c.states[uid]["active"]["variant"]=="small":break
            assert c.states[uid]["active"]["variant"]=="small"
        finally:
            await c.transport.aclose(); c.journal.close()
    asyncio.run(run())
