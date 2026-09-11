import asyncio
import copy

import pytest
from pydantic import ValidationError
from runtime_operator.contract import ServiceSpec
from runtime_operator.controller import Controller
from runtime_operator.journal import Journal
from test_resident import setup
from test_runtime import node


def three_tier(tmp_path):
    k, _ = setup()
    spec = k.resource["spec"]
    medium = copy.deepcopy(spec["variants"][0])
    medium.update(name="medium", qualifiedRps=5)
    medium["resident"].update(service="medium", selector={"app": "medium"})
    spec["variants"].insert(1, medium)
    k.data["nodes"].append(node("another-edge"))
    pod = copy.deepcopy(k.data["pods"][0])
    pod["metadata"].update(name="medium", uid="medium-uid", labels={"app": "medium"})
    pod["spec"]["nodeName"] = "another-edge"
    k.data["pods"].append(pod)
    service = copy.deepcopy(k.data["kubeServices"][0])
    service["metadata"]["name"] = "medium"
    service["spec"]["selector"] = {"app": "medium"}
    k.data["kubeServices"].append(service)
    spec["policy"].update(approvalRequired=True, stages=[{"variant": name, "label": label} for name, label in
        [("small", "Nano"), ("medium", "Orin"), ("large", "Spark")]])
    spec["demo"] = {"label": "three tier", "payload": {"prompt": "qualified input", "max_tokens": 8}}
    now = [100.]
    loaded = {"small": True, "medium": False, "large": False}
    calls = []
    c = Controller(k, Journal(str(tmp_path / "state.db")), clock=lambda: now[0])
    async def probe(target):
        active = loaded[target["variant"]]
        return {"ready": active, "inFlight": 0, "released": not active, "modelVramMiB": 1000 if active else 0}
    def lifecycle(target, action):
        calls.append((target["variant"], action))
        loaded[target["variant"]] = action == "activate"
    c.probe, c.lifecycle = probe, lifecycle
    return c, k, now, calls


def test_three_tier_requires_two_approvals_and_returns_through_same_role_edge(tmp_path):
    async def run():
        c, k, now, calls = three_tier(tmp_path)
        uid = k.resource["metadata"]["uid"]
        try:
            await c.tick()
            assert c.states[uid]["active"]["variant"] == "small"
            c.pending[uid] = 3
            for expected in ["medium", "large"]:
                for _ in range(3):
                    now[0] += 2
                    await c.tick()
                proposal = c.states[uid]["proposal"]
                assert proposal["variant"] == expected
                assert (expected, "activate") not in calls
                await c.approve(k.resource["metadata"]["name"], uid, proposal["id"])
                await c.tick()
                await c.tick()
                assert c.states[uid]["active"]["variant"] == expected
            c.pending[uid] = 0
            returned = []
            for _ in range(12):
                now[0] += 2
                await c.tick()
                name = c.states[uid]["active"]["variant"]
                if not returned or returned[-1] != name:
                    returned.append(name)
            assert returned == ["large", "medium", "small"]
        finally:
            await c.transport.aclose()
            c.journal.close()
    asyncio.run(run())


@pytest.mark.parametrize("unavailable", [False, True])
def test_latency_never_skips_the_next_stage_for_a_faster_server(tmp_path, unavailable):
    async def run():
        c, k, now, calls = three_tier(tmp_path)
        uid = k.resource["metadata"]["uid"]
        spec = k.resource["spec"]
        spec["policy"]["latency"] = {"maxP95Milliseconds": 100, "returnP95Milliseconds": 80,
            "windowSeconds": 20, "minSamples": 3, "breachSeconds": 1}
        for v, p95 in zip(spec["variants"], [30, 50, 20]):
            v["qualifiedP95Milliseconds"] = p95
        try:
            await c.tick()
            active = c.states[uid]["active"]["name"]
            if unavailable:
                k.data["nodes"][-1]["spec"]["unschedulable"] = True
            for _ in range(3):
                now[0] += 2
                c.latencies.record(uid, active, now[0], 200, True)
            await c.tick()
            now[0] += 2
            await c.tick()
            proposal = c.states[uid].get("proposal")
            assert proposal is None if unavailable else proposal["variant"] == "medium"
            assert not calls
        finally:
            await c.transport.aclose()
            c.journal.close()
    asyncio.run(run())


def test_stage_contract_rejects_duplicate_missing_and_unapproved_stages(tmp_path):
    c, k, _, _ = three_tier(tmp_path)
    data = k.resource["spec"]
    try:
        for change in ["duplicate", "missing", "unapproved"]:
            modified = copy.deepcopy(data)
            if change == "duplicate": modified["policy"]["stages"][1]["variant"] = "small"
            if change == "missing": modified["policy"]["stages"].pop()
            if change == "unapproved": modified["policy"]["approvalRequired"] = False
            with pytest.raises(ValidationError): ServiceSpec.model_validate(modified)
    finally:
        asyncio.run(c.transport.aclose())
        c.journal.close()


def test_demo_records_same_role_departure_and_return_at_first_stage(tmp_path):
    from runtime_operator.demo import DemoRunner
    from types import SimpleNamespace
    c, k, now, _ = three_tier(tmp_path)
    uid = k.resource["metadata"]["uid"]
    runner = DemoRunner(SimpleNamespace(state=SimpleNamespace(controller=c)))
    run = {"uid": uid, "routeHistory": [], "startRole": "edge", "leftStartRole": False,
           "baselineVariant": "small", "leftBaseline": False}
    c.last_snapshot = now[0]
    try:
        for variant, host, role in [("small", "nano", "edge"), ("medium", "orin", "edge"), ("small", "nano", "edge")]:
            c.states[uid] = {"serving": True, "active": {"variant": variant, "node": host, "role": role}}
            runner.observe(run)
        assert run["returned"] and run["leftBaseline"]
        assert [r["node"] for r in run["routeHistory"]] == ["nano", "orin", "nano"]
    finally:
        asyncio.run(c.transport.aclose())
        c.journal.close()
