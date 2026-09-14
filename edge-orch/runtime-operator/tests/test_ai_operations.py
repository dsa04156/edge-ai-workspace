import asyncio
import copy

import httpx
import pytest

from runtime_operator.api import create_app
from runtime_operator.contract import ServiceSpec
from test_runtime import rig, activate
from test_three_tier import three_tier


def test_generic_ai_failed_node_moves_to_ready_alternative_without_approval(rig):
    async def run():
        c,k,now,_,_=rig
        k.resource['spec']['serviceKind']='ai'
        await activate(c,k)
        uid=k.resource['metadata']['uid']
        k.data['nodes'][0]['status']['conditions'][0]['status']='False'
        now[0]+=1
        await c.tick()
        state=c.states[uid]
        assert state['target']['node']=='datacenter-any' and not state.get('proposal')
        assert any('node_not_ready' in x['reasons'] for x in state['excludedCandidates'])
        k.ready(state['target']['name'])
        await c.tick()
        assert c.states[uid]['active']['node']=='datacenter-any'
        assert c.states[uid]['serving']
        await c.transport.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('staged', [False, True])
def test_non_llama_ai_automatically_moves_on_pressure_and_returns_without_samples(rig, staged):
    async def run():
        c, k, now, _, _ = rig
        # Emulate Deployment reconciliation when a released revision is reused.
        ensure = k.ensure
        def reconcile(resource, spec, candidate, name):
            k.data['deployments'] = [d for d in k.data['deployments']
                if not (d['metadata']['name'] == name and d['spec']['replicas'] == 0)]
            ensure(resource, spec, candidate, name)
        k.ensure = reconcile
        k.resource['metadata']['name'] = 'vision-defect-detector'
        spec = k.resource['spec']
        spec['serviceKind'] = 'ai'
        spec['policy']['latency'] = {'maxP95Milliseconds':100,'returnP95Milliseconds':80,'windowSeconds':5,'minSamples':3,'breachSeconds':1}
        for v, rate, p95 in zip(spec['variants'], [2,8], [60,30]):
            v.update(qualifiedRps=rate, qualifiedP95Milliseconds=p95)
        if staged:
            spec['policy']['stages'] = [{'variant':'small','label':'Field'},{'variant':'large','label':'Compute'}]
        assert ServiceSpec.model_validate(spec).is_ai and not spec.get('inference')
        await activate(c,k)
        uid = k.resource['metadata']['uid']
        c.pending[uid] = 3
        for _ in range(3):
            now[0] += 1
            await c.tick()
        assert c.states[uid]['target']['variant'] == 'large'
        assert not c.states[uid].get('proposal')
        k.ready(c.states[uid]['target']['name'])
        await c.tick()
        assert c.states[uid]['active']['role'] == 'server'
        c.pending[uid] = 0
        for _ in range(12):
            now[0] += 1
            await c.tick()
            if c.states[uid].get('target'):
                k.ready(c.states[uid]['target']['name'])
        assert c.states[uid]['active']['role'] == 'edge'
        assert c.states[uid]['lastTransition']['reason'] == 'sustained_idle_return'
        assert c.states[uid]['requestMetrics']['samples'] == 0
        assert not c.states[uid]['latency']['valid']
        await c.transport.aclose()
    asyncio.run(run())


def test_ai_without_test_payload_is_visible_and_controllable_but_cannot_invent_load(rig):
    async def run():
        c,k,_,_,_ = rig
        k.resource['spec']['serviceKind'] = 'ai'
        await activate(c,k)
        def set_suspended(name,uid,suspended):
            k.resource['spec']['suspended'] = suspended
            return copy.deepcopy(k.resource)
        k.set_suspended = set_suspended
        app = create_app(c)
        uid,name=k.resource['metadata']['uid'],k.resource['metadata']['name']
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://local') as client:
            item=(await client.get('/demos')).json()['items'][0]
            assert not item['testConfigured'] and not item['available'] and item['serviceControl']['canStop']
            r=await client.post(f'/demos/{name}/runs/no-input-test',json={'serviceUid':uid,'mode':'service-load'})
            assert r.status_code==403
            assert (await client.post(f'/demos/{name}/service',json={'serviceUid':uid,'action':'stop'})).status_code==202
        await app.state.demo_runner.close()
        await c.transport.aclose()
    asyncio.run(run())


def test_automatic_resident_stages_advance_and_return_without_approval(tmp_path):
    async def run():
        c,k,now,calls=three_tier(tmp_path)
        k.resource['spec']['policy']['approvalRequired']=False
        uid=k.resource['metadata']['uid']
        try:
            await c.tick()
            visited=['small']
            c.pending[uid]=3
            for _ in range(14):
                now[0]+=1
                await c.tick()
                v=c.states[uid]['active']['variant']
                if visited[-1]!=v:visited.append(v)
                assert not c.states[uid].get('proposal')
            c.pending[uid]=0
            for _ in range(14):
                now[0]+=1
                await c.tick()
                v=c.states[uid]['active']['variant']
                if visited[-1]!=v:visited.append(v)
            assert visited==['small','medium','large','medium','small']
            assert not c.states[uid].get('lastApproval')
        finally:
            await c.transport.aclose();c.journal.close()
    asyncio.run(run())
