import asyncio

import httpx
import pytest
from pydantic import ValidationError

from runtime_operator.api import create_app
from runtime_operator.contract import LatencyPolicy, ServiceSpec, revision
from runtime_operator.latency import LatencyWindow
from test_runtime import activate, rig, spec_data


def policy():
    return LatencyPolicy(maxP95Milliseconds=100, returnP95Milliseconds=80,
                         windowSeconds=5, minSamples=3, breachSeconds=1)


def configure(kube):
    kube.resource["spec"]["policy"]["latency"] = policy().model_dump()
    for index, v in enumerate(kube.resource["spec"]["variants"]):
        v["qualifiedP95Milliseconds"] = 50 if index == 0 else 40


def add(c, uid, target, at, ms, success=True):
    for _ in range(3):
        c.latencies.record(uid, target, at, ms, success)


def test_nearest_rank_minimum_failures_staleness_and_identity():
    w = LatencyWindow()
    for value in range(1, 21):
        w.record("service", "rev-a", 100, value, True)
    report = w.observe("service", "rev-a", 101, policy())
    assert report["valid"] and report["p95Milliseconds"] == 19
    assert not w.observe("other-service", "rev-a", 101, policy())["valid"]
    assert not w.observe("service", "other-revision", 101, policy())["valid"]
    assert not w.observe("service", "rev-a", 110, policy())["valid"]
    assert not w.observe("service", "rev-a", 101, policy(), since=101)["valid"]
    w.record("service", "rev-a", 101, 1, False)
    report = w.observe("service", "rev-a", 101, policy())
    assert report["failures"] == 1 and not report["valid"]
    assert report["reason"] == "recent_request_failure"
    for _ in range(4096):
        w.record("service", "rev-a", 101, 1, True)
    assert len(w.samples[("service", "rev-a")]) == 2048
    w.prune(1000)
    assert not w.samples


def test_policy_contract_and_qualification_do_not_replace_workload():
    with pytest.raises(ValidationError):
        LatencyPolicy(maxP95Milliseconds=100, returnP95Milliseconds=100)
    first = ServiceSpec.model_validate(spec_data())
    data = spec_data()
    data["policy"]["latency"] = policy().model_dump()
    data["variants"][0]["qualifiedP95Milliseconds"] = 50
    second = ServiceSpec.model_validate(data)
    assert revision(first, first.variants[0], "arbitrary") == revision(second, second.variants[0], "arbitrary")


def test_latency_alone_offloads_then_requires_new_recovery_samples_and_candidate_cooloff(rig):
    async def run():
        c, k, now, _, _ = rig
        configure(k)
        old = await activate(c, k)
        uid = k.resource["metadata"]["uid"]
        add(c, uid, old, now[0], 200)
        await c.tick()
        assert not c.states[uid]["target"]  # breach dwell has not elapsed
        now[0] += 2
        await c.tick()
        target = c.states[uid]["target"]
        assert target and target["triggerReason"] == "sustained_latency_breach"
        assert c.states[uid]["load"]["inFlightAndPending"] == 0
        k.ready(target["name"])
        await c.tick()
        assert c.states[uid]["active"]["role"] == "server"
        now[0] += 2
        await c.tick()
        assert not c.states[uid]["target"]  # no samples is not recovery
        add(c, uid, target["name"], now[0], 40)
        await c.tick()
        now[0] += 2
        add(c, uid, target["name"], now[0], 40)
        await c.tick()
        assert c.states[uid]["target"]["role"] == "edge"
        assert c.states[uid]["target"]["triggerReason"] == "sustained_low_load_return"
    asyncio.run(run())


@pytest.mark.parametrize("case", ["unqualified", "too_slow", "recent_failure", "preferred_mode"])
def test_latency_cannot_move_to_unqualified_or_failing_candidate_or_override_preferred_mode(rig, case):
    async def run():
        c, k, now, _, _ = rig
        configure(k)
        if case == "unqualified":
            k.resource["spec"]["variants"][1].pop("qualifiedP95Milliseconds")
        if case == "too_slow":
            k.resource["spec"]["variants"][1]["qualifiedP95Milliseconds"] = 150
        if case == "preferred_mode":
            k.resource["spec"]["policy"]["mode"] = "preferred"
        old = await activate(c, k)
        uid = k.resource["metadata"]["uid"]
        if case == "recent_failure":
            spec = ServiceSpec.model_validate(k.resource["spec"])
            choice = type("Choice", (), {"node": "datacenter-any", "role": "server", "variant": spec.variants[1]})()
            candidate = c.target(k.resource, spec, choice)
            add(c, uid, candidate["name"], now[0], 1, False)
        add(c, uid, old, now[0], 200)
        await c.tick()
        now[0] += 2
        await c.tick()
        assert not c.states[uid]["target"]
        assert c.states[uid]["active"]["name"] == old
    asyncio.run(run())


def test_gateway_includes_queue_wait_and_does_not_count_replay(rig):
    async def run():
        c, k, _, _, _ = rig
        target = await activate(c, k)
        uid = k.resource["metadata"]["uid"]
        c.inflight[target] = 1
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(c)), base_url="http://gateway") as client:
            path = "/services/" + k.resource["metadata"]["name"] + "/invoke"
            request = asyncio.create_task(client.post(path, json={"input": "x"}, headers={"X-Request-ID": "latency-once"}))
            await asyncio.sleep(.03)
            c.inflight[target] = 0
            assert (await request).status_code == 200
            rows = c.latencies.samples[(uid, target)]
            assert len(rows) == 1 and rows[0][1] >= 25 and rows[0][2]
            assert (await client.post(path, json={"input": "x"}, headers={"X-Request-ID": "latency-once"})).status_code == 200
            assert len(rows) == 1
    asyncio.run(run())


def test_saturated_admission_counts_as_failure_not_fast_success(rig):
    async def run():
        c, k, now, _, _ = rig
        target = await activate(c, k)
        uid = k.resource["metadata"]["uid"]
        add(c, uid, target, now[0], 40)
        c.pending[uid] = 128
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(c)), base_url="http://gateway") as client:
            response = await client.post("/services/" + k.resource["metadata"]["name"] + "/invoke",
                                         json={}, headers={"X-Request-ID": "saturated"})
            assert response.status_code == 429
        report = c.latencies.observe(uid, target, now[0], policy())
        assert report["failures"] == 1 and not report["valid"]
    asyncio.run(run())


def test_persisting_overload_cannot_bounce_to_slower_qualification_after_old_samples_expire(rig):
    async def run():
        c, k, now, _, _ = rig
        configure(k)
        old = await activate(c, k)
        uid = k.resource["metadata"]["uid"]
        add(c, uid, old, now[0], 200)
        await c.tick()
        now[0] += 2
        await c.tick()
        target = c.states[uid]["target"]
        k.ready(target["name"])
        await c.tick()
        now[0] += 10  # old edge's bad observations expired
        add(c, uid, target["name"], now[0], 200)
        await c.tick()
        now[0] += 2
        add(c, uid, target["name"], now[0], 200)
        await c.tick()
        assert c.states[uid]["active"]["role"] == "server"
        assert not c.states[uid]["target"]
        assert c.states[uid]["reason"] == "latency_no_qualified_target"
    asyncio.run(run())
