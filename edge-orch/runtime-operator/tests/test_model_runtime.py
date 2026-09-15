import asyncio
import copy
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from pydantic import ValidationError

from runtime_operator.api import create_app
from runtime_operator.contract import ServiceSpec, revision
from runtime_operator.model_runtime import request_body
from runtime_operator.placement import candidates
from test_runtime import rig, activate, node, spec_data

ROOT = Path(__file__).resolve().parents[1]
module = importlib.util.spec_from_file_location('digits_worker_test', ROOT / 'model-worker/server.py')
worker = importlib.util.module_from_spec(module)
module.loader.exec_module(worker)
INPUT = json.loads((ROOT / 'examples/digits-model/input.json').read_text())


def configure(k):
    data = k.resource['spec']
    data.update(serviceKind='ai', requestPath='/v2/models/digits-centroid/infer',
                modelRuntime={'protocol':'inference-v2-json', 'modelName':worker.NAME,
                    'modelVersion':worker.VERSION, 'inputKind':'image', 'inputs':worker.INPUTS, 'outputs':worker.OUTPUTS},
                demo={'label':'actual image classifier', 'payload':INPUT})
    data['policy']['mode'] = 'preferred'
    for v in data['variants']:
        v['verifiedNodes'] = ['field-any', 'datacenter-any']
    return data


async def setup_model(c, k, calls, bad=None):
    configure(k)
    async def handle(request):
        calls.append(request)
        if request.method == 'GET':
            return httpx.Response(200, json={'ready':True,'inFlight':0,'ioContract':k.resource['spec']['ioContract'],
                'model_name':worker.NAME, 'model_version':worker.VERSION if bad != 'health' else '0'*64,
                'inputs':worker.INPUTS,'outputs':worker.OUTPUTS})
        result = worker.infer(json.loads(request.content))
        if bad == 'result':
            result['model_version'] = '0'*64
        return httpx.Response(200, json=result)
    await c.transport.aclose()
    c.transport = httpx.AsyncClient(transport=httpx.MockTransport(handle))


def test_model_contract_and_node_verification_are_not_inferred_from_service_name(rig):
    _, k, _, _, _ = rig
    data = configure(k)
    spec = ServiceSpec.model_validate(data)
    accepted, excluded = candidates(spec, [node(), node('new-edge')], [], [])
    assert [c.node for c in accepted] == ['field-any']
    assert any('model_execution_not_verified_on_node' in c['reasons'] for c in excluded if c['node'] == 'new-edge')
    original = revision(spec, spec.variants[0], 'field-any')
    data['variants'][0]['verifiedNodes'].append('new-edge')
    updated = ServiceSpec.model_validate(data)
    assert revision(updated, updated.variants[0], 'field-any') == original
    data['modelRuntime']['modelVersion'] = '1'*64
    updated = ServiceSpec.model_validate(data)
    assert revision(updated, updated.variants[0], 'field-any') != original
    data['policy']['mode'] = 'automatic'
    with pytest.raises(ValidationError, match='performance_qualification'):
        ServiceSpec.model_validate(data)


def test_legacy_revision_is_unchanged_by_new_optional_fields():
    spec = ServiceSpec.model_validate(spec_data())
    v = spec.variants[0].model_dump()
    for key in ['qualifiedP95Milliseconds','qualifiedInputProfile','verifiedNodes','resident','qualifiedRps']:
        v.pop(key, None)
    import hashlib
    old = {'variant':v,'node':'field-any','port':spec.port,'readyPath':spec.readyPath,'ioContract':spec.ioContract}
    assert revision(spec,spec.variants[0],'field-any') == hashlib.sha256(json.dumps(old,sort_keys=True).encode()).hexdigest()[:12]


def test_learned_model_computes_different_outputs_for_different_images():
    for label, centroid in enumerate(worker.MODEL['centroids']):
        body = copy.deepcopy(INPUT);body['inputs'][0]['data'] = centroid
        result = worker.infer(body)
        assert result['outputs'][0]['data'] == [label]
        assert result['outputs'][1]['data'][label] == 0


@pytest.mark.parametrize('corrupt', ['nan','bool','huge','shape','id','duplicate'])
def test_bounded_tensor_validation(corrupt, rig):
    _, k, _, _, _ = rig
    spec = configure(k)
    body = copy.deepcopy(INPUT)
    if corrupt in ['nan','bool','huge']:body['inputs'][0]['data'][0] = {'nan':float('nan'),'bool':True,'huge':10**500}[corrupt]
    if corrupt == 'shape':body['inputs'][0]['shape'] = [64]
    if corrupt == 'id':body['id'] = 'different'
    if corrupt == 'duplicate':body['inputs'] *= 2
    with pytest.raises(ValueError):request_body(spec,body,'request-one')


def test_real_model_inference_replay_policy_handoff_and_suspend(rig):
    async def run():
        c,k,now,_,calls = rig
        await setup_model(c,k,calls)
        old = await activate(c,k)
        uid=k.resource['metadata']['uid'];name=k.resource['metadata']['name']
        assert c.states[uid]['verifiedExecutionNodes'] == ['datacenter-any','field-any']
        app=create_app(c)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://gateway') as client:
            path=f'/services/{name}/invoke'
            response=await client.post(path,json=INPUT,headers={'X-Request-ID':'one'})
            assert response.status_code==200 and response.json()['outputs'][0]['data']==[7]
            assert response.headers['X-Runtime-Target']==old
            before=sum(r.method=='POST' for r in calls)
            assert (await client.post(path,json=INPUT,headers={'X-Request-ID':'one'})).json()==response.json()
            assert sum(r.method=='POST' for r in calls)==before
            k.resource['spec']['policy'].update(allowedRoles=['server'],preferredRole='server')
            await c.tick();target=c.states[uid]['target']
            assert target['node']=='datacenter-any' and c.states[uid]['active']['name']==old
            k.ready(target['name']);await c.tick()
            response=await client.post(path,json=INPUT,headers={'X-Request-ID':'two'})
            assert response.json()['outputs'][0]['data']==[7]
            assert response.headers['X-Runtime-Target']==target['name']
            assert c.states[uid]['placementDecision']['selectedRevision']==target['name']
            k.resource['spec']['suspended']=True
            await c.tick();await c.tick()
            assert c.states[uid]['phase']=='Suspended'
            assert (await client.post(path,json=INPUT,headers={'X-Request-ID':'three'})).status_code==503
    asyncio.run(run())


@pytest.mark.parametrize('bad',['health','result'])
def test_model_identity_mismatch_never_serves_or_retries(rig,bad):
    async def run():
        c,k,now,_,calls=rig
        await setup_model(c,k,calls,bad)
        uid=k.resource['metadata']['uid'];name=k.resource['metadata']['name']
        if bad=='health':
            await c.tick();k.ready(c.states[uid]['target']['name']);await c.tick()
            assert not c.states[uid]['serving']
            return
        await activate(c,k)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(c)),base_url='http://g') as client:
            response=await client.post(f'/services/{name}/invoke',json=INPUT,headers={'X-Request-ID':'bad-result'})
        assert response.status_code==503 and response.headers['X-Request-State']=='unknown'
        assert sum(r.method=='POST' for r in calls)==1
    asyncio.run(run())
