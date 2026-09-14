import asyncio
import copy

from test_runtime import activate, node, rig
from test_latency import configure, add


def test_initial_ranks_match_selection_and_freeze_until_ready(rig):
    async def run():
        c, k, now, _, _ = rig
        k.data['nodes'].append(node('edge-second'))
        await c.tick()
        uid = k.resource['metadata']['uid']
        state = c.states[uid]
        decision = copy.deepcopy(state['placementDecision'])
        assert [x['node'] for x in decision['candidates']] == ['edge-second', 'field-any', 'datacenter-any']
        assert decision['selectedRevision'] == state['target']['name']
        assert decision['status'] == 'Preparing'
        now[0] += 1
        await c.tick()
        assert c.states[uid]['placementDecision'] == decision
        k.ready(state['target']['name'])
        await c.tick()
        assert c.states[uid]['placementDecision']['status'] == 'Applied'
        assert c.states[uid]['active']['name'] == decision['selectedRevision']
        k.resource['spec']['suspended'] = True
        await c.tick()
        assert c.states[uid]['placementDecision'] is None
    asyncio.run(run())


def test_latency_ranking_uses_actual_qualified_p95_and_node_tie_break(rig):
    async def run():
        c, k, now, _, _ = rig
        configure(k)
        k.data['nodes'].append(node('server-second', 'amd64', 'server'))
        fast = copy.deepcopy(k.resource['spec']['variants'][1])
        fast.update(name='fast', qualifiedP95Milliseconds=20)
        k.resource['spec']['variants'].append(fast)
        old = await activate(c, k)
        uid = k.resource['metadata']['uid']
        add(c, uid, old, now[0], 200)
        await c.tick()
        now[0] += 2
        await c.tick()
        state = c.states[uid]; d = state['placementDecision']
        assert d['reason'] == 'sustained_latency_breach' and d['basis'] == 'qualified_latency'
        assert [(x['rank'], x['node'], x['variant']) for x in d['candidates']] == [
            (1, 'datacenter-any', 'fast'), (2, 'server-second', 'fast'),
            (3, 'datacenter-any', 'large'), (4, 'server-second', 'large')]
        assert state['target']['name'] == d['selectedRevision']
        assert state['target']['variant'] == d['candidates'][0]['variant']
    asyncio.run(run())


def test_pressure_ranking_and_failed_preparation_outcome(rig):
    async def run():
        c, k, now, _, _ = rig
        k.data['nodes'].append(node('z-server', 'amd64', 'server'))
        old = await activate(c, k)
        uid = k.resource['metadata']['uid']
        c.inflight[old] = 1
        await c.tick(); now[0] += 2; await c.tick()
        d = c.states[uid]['placementDecision']
        assert d['basis'] == 'smallest_sufficient_capacity'
        assert [x['node'] for x in d['candidates']] == ['datacenter-any', 'z-server']
        assert c.states[uid]['target']['name'] == d['selectedRevision']
        now[0] += 6; await c.tick()
        assert c.states[uid]['placementDecision']['status'] == 'Interrupted'
        assert c.states[uid]['placementDecision']['outcomeReason'] == 'candidate_invalid_or_prepare_timeout'
    asyncio.run(run())


def test_empty_qualified_set_is_not_a_fabricated_recommendation(rig):
    async def run():
        c, k, now, _, _ = rig
        configure(k)
        k.resource['spec']['variants'][1]['qualifiedP95Milliseconds'] = 150
        old = await activate(c, k)
        uid = k.resource['metadata']['uid']
        add(c, uid, old, now[0], 200)
        await c.tick(); now[0] += 2; await c.tick()
        d = c.states[uid]['placementDecision']
        assert d['candidates'] == [] and d['selectedRevision'] is None
        assert d['status'] == 'Evaluated' and d['reason'] == 'latency_no_qualified_target'
    asyncio.run(run())


def test_return_ranking_follows_recovered_latency_and_clears_on_restart(rig):
    async def run():
        c, k, now, _, _ = rig
        configure(k)
        old = await activate(c, k)
        uid = k.resource['metadata']['uid']
        add(c, uid, old, now[0], 200)
        await c.tick(); now[0] += 2; await c.tick()
        target = c.states[uid]['target']
        k.ready(target['name']); await c.tick()
        now[0] += 2
        add(c, uid, target['name'], now[0], 40); await c.tick()
        now[0] += 2
        add(c, uid, target['name'], now[0], 40); await c.tick()
        state = c.states[uid]; d = state['placementDecision']
        assert d['reason'] == 'sustained_low_load_return'
        assert d['sourceRevision'] == target['name']
        assert d['candidates'][0]['node'] == 'field-any'
        assert d['selectedRevision'] == state['target']['name']
        restarted = type(c)(k, c.journal, c.transport, c.clock)
        assert restarted.states[uid]['placementDecision'] is None
    asyncio.run(run())
