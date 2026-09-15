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


def test_request_metrics_without_latency_policy_require_current_revision_and_observation():
    data = payload()
    raw = data['services'][0]
    raw.update(serviceKind='ai', aiInference=True, placementMode='automatic', testConfigured=False)
    raw['requestMetrics'] = {'at':99,'target':'revision','samples':3,'successfulSamples':2,
        'failures':1,'p95Milliseconds':150,'arrivalRps':.15,'completedRps':.1,
        'windowSeconds':20,'scope':'gateway_queue_and_worker_response','processLocal':True}
    item = project(data,100).services[0]
    assert item.latency is None and item.requestMetrics.failures == 1
    assert item.serviceKind == 'ai' and item.placementMode == 'automatic' and not item.testConfigured
    for field, value in [('target','other'),('at',50)]:
        old = raw['requestMetrics'][field]
        raw['requestMetrics'][field] = value
        assert project(data,100).services[0].requestMetrics is None
        raw['requestMetrics'][field] = old
    assert project(data,200).services[0].requestMetrics is None


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


def test_actual_placement_ranking_is_allowlisted_and_hidden_when_observation_is_stale():
    data = payload()
    data['services'][0]['placementDecision'] = {
        'at': 99, 'generation': 1, 'status': 'Preparing', 'reason': 'sustained_pressure',
        'basis': 'smallest_sufficient_capacity', 'staged': False,
        'selectedRevision': 'next', 'private': 'hidden', 'candidates': [
            {'rank': 1, 'node': 'node-b', 'variant': 'gpu', 'role': 'server', 'capacity': 2, 'endpoint': 'private'}]}
    item = project(data, 100).services[0]
    assert item.placementDecision.candidates[0].rank == 1
    assert 'hidden' not in item.model_dump_json() and 'endpoint' not in item.model_dump_json()
    assert project(data, 200).services[0].placementDecision is None


def test_ordered_stages_retain_configuration_but_not_live_eligibility_when_stale():
    data = payload()
    data["services"][0]["augmentationStages"] = [{"step": 1, "label": "Nano", "variant": "nano", "node": "nano-node", "eligible": True, "qualifiedRps": 2}]
    assert project(data, 100).services[0].augmentationStages[0].eligible
    stage = project(data, 200).services[0].augmentationStages[0]
    assert stage.label == "Nano" and not stage.eligible


def test_idle_return_is_separate_from_latency_recovery_and_removed_when_stale():
    data = payload()
    data['services'][0]['returnState'] = {
        'phase': 'Waiting', 'node': 'orin', 'label': 'Orin', 'reason': 'idle_dwell',
        'remainingSeconds': 7, 'windowSeconds': 20, 'dwellSeconds': 8, 'at': 99}
    item = project(data, 100).services[0]
    assert item.returnState.remainingSeconds == 7
    assert item.latency is None
    assert project(data, 200).services[0].returnState is None
    data['services'][0]['returnState']['at'] = 50
    assert project(data, 100).services[0].returnState is None


def test_policy_dwell_progress_expires_with_observation():
    data = payload()
    data['services'][0]['policyObservation'] = {'at':99, 'pressureSeconds':10,
        'pressureElapsedSeconds':3, 'latencyElapsedSeconds':0, 'returnSeconds':60,
        'cooldownSeconds':60, 'cooldownRemainingSeconds':12, 'arrivalRps':2,
        'windowSeconds':20, 'returnHeadroomRatio':.8}
    assert project(data,100).services[0].policyObservation.pressureElapsedSeconds == 3
    assert project(data,200).services[0].policyObservation is None
    data['lastError'] = 'snapshot_unavailable'
    assert project(data,100).services[0].policyObservation is None


def test_contract_summary_exposes_only_configuration_and_retains_it_when_suspended():
    data = payload()
    item = data["services"][0]
    item.update(phase="Suspended", serving=False, active=None, commonAI={
        "adapter":"generic-ai-test", "service":{"model":"vision-test","version":"a"*64,"secret":"hidden"},
        "input":{"type":"image","source":"registered-camera","payload":"private-input"},
        "resources":{"cpu":"500m","memory":"1Gi","gpu":"nvidia.com/gpu=1"},
        "placement":{"default_node":"node-a","candidate_nodes":["node-a","node-b"]},
        "worker_models":{"private_endpoint":"hidden"}})
    result = project(data,100).services[0]
    assert result.contractSummary.model == "vision-test"
    assert result.contractSummary.candidateNodes == ["node-a","node-b"]
    assert result.contractSummary.cpuRequest == "500m"
    assert all(x not in result.model_dump_json() for x in ["private-input","private_endpoint","hidden"])
    assert project(data,200).services[0].contractSummary.model == "vision-test"
    item["commonAI"]["placement"] = []
    assert project(data,100).services[0].contractSummary.candidateNodes == []


def test_generic_model_contract_summary_does_not_need_llama_or_leak_tensor_data():
    data = payload(); raw = data['services'][0]
    raw.update(phase='Suspended', active=None, serving=False, verifiedExecutionNodes=['raspi','server'],
        modelRuntime={'protocol':'inference-v2-json','modelName':'digits-centroid','modelVersion':'a'*64,
                      'inputKind':'image','inputs':[{'privateTensor':'hidden'}]})
    summary = project(data,100).services[0].contractSummary
    assert summary.model == 'digits-centroid' and summary.inputType == 'image'
    assert summary.candidateNodes == ['raspi','server']
    assert 'hidden' not in project(data,100).model_dump_json()
