import asyncio

import pytest

from test_three_tier import three_tier


async def at_spark(tmp_path):
    c, k, now, calls = three_tier(tmp_path)
    k.resource['spec']['policy']['latency'] = {
        'maxP95Milliseconds': 100, 'returnP95Milliseconds': 80,
        'windowSeconds': 5, 'minSamples': 3, 'breachSeconds': 1}
    for variant, p95 in zip(k.resource['spec']['variants'], [60, 50, 40]):
        variant['qualifiedP95Milliseconds'] = p95
    uid = k.resource['metadata']['uid']
    await c.tick()
    c.pending[uid] = 3
    for expected in ['medium', 'large']:
        for _ in range(3):
            now[0] += 2
            await c.tick()
        proposal = c.states[uid]['proposal']
        assert proposal['variant'] == expected
        await c.approve(k.resource['metadata']['name'], uid, proposal['id'])
        await c.tick()
        await c.tick()
        assert c.states[uid]['active']['variant'] == expected
    c.pending[uid] = 0
    await c.tick()  # Finish the previous route drain before the idle observation.
    return c, k, now, calls, uid


def test_zero_requests_returns_spark_orin_nano_without_fabricated_latency_samples(tmp_path):
    async def run():
        c, k, now, calls, uid = await at_spark(tmp_path)
        try:
            visited = ['large']
            transitions = []
            for _ in range(25):
                now[0] += 1
                await c.tick()
                state = c.states[uid]
                assert state['latency'] is None or not state['latency']['valid']
                assert state['latency'] is None or state['latency']['samples'] == 0
                variant = state['active']['variant']
                if visited[-1] != variant:
                    visited.append(variant)
                    transitions.append(state['lastTransition']['reason'])
            assert visited == ['large', 'medium', 'small']
            assert transitions == ['sustained_idle_return', 'sustained_idle_return']
            assert c.states[uid]['returnState']['phase'] == 'Baseline'
            assert not c.states[uid]['retiring']
            assert ('large', 'release') in calls and ('medium', 'release') in calls
            assert not k.actions  # Resident model lifecycle, no Pod provisioning.
        finally:
            await c.transport.aclose()
            c.journal.close()
    asyncio.run(run())


@pytest.mark.parametrize('blocker', ['arrival', 'failure', 'worker_busy', 'pending', 'unhealthy', 'missing_middle', 'unqualified_middle'])
def test_idle_return_does_not_skip_middle_or_treat_work_errors_as_idle(tmp_path, blocker):
    async def run():
        c, k, now, calls, uid = await at_spark(tmp_path)
        original_probe = c.probe
        async def probe(target):
            value = await original_probe(target)
            if target['variant'] == 'large':
                if blocker == 'worker_busy': value['inFlight'] = 1
                if blocker == 'unhealthy': value['ready'] = False
            return value
        c.probe = probe
        try:
            if blocker == 'missing_middle':
                k.data['nodes'][-1]['spec']['unschedulable'] = True
            if blocker == 'unqualified_middle':
                k.resource['spec']['variants'][1]['qualifiedP95Milliseconds'] = 90
            for _ in range(12):
                now[0] += 1
                name = c.states[uid]['active']['name']
                if blocker == 'arrival': c.latencies.arrival(uid, name, now[0])
                if blocker == 'failure': c.latencies.record(uid, name, now[0], 1, False)
                if blocker == 'pending': c.pending[uid] = 1
                await c.tick()
                # An unhealthy active route can use the existing failover path;
                # it must never be mistaken for an idle return.
                assert (c.states[uid].get('target') or {}).get('triggerReason') != 'sustained_idle_return'
                assert c.states[uid].get('lastTransition', {}).get('reason') != 'sustained_idle_return'
            if blocker != 'unhealthy':
                assert c.states[uid]['active']['variant'] == 'large'
            if blocker in ['missing_middle', 'unqualified_middle']:
                assert c.states[uid]['returnState']['phase'] == 'Blocked'
        finally:
            await c.transport.aclose()
            c.journal.close()
    asyncio.run(run())


def test_new_arrival_and_snapshot_failure_reset_idle_dwell(tmp_path):
    async def run():
        c, k, now, calls, uid = await at_spark(tmp_path)
        try:
            now[0] += 5
            await c.tick()
            assert c.states[uid]['returnState']['phase'] == 'Waiting'
            now[0] += 1
            c.latencies.arrival(uid, c.states[uid]['active']['name'], now[0])
            await c.tick()
            assert c.states[uid]['idleSince'] is None
            now[0] += 6
            await c.tick()
            assert c.states[uid]['returnState']['phase'] == 'Waiting'
            snapshot = k.snapshot
            def broken(): raise RuntimeError('offline')
            k.snapshot = broken
            now[0] += 1
            await c.tick()
            assert c.states[uid]['idleSince'] is None
            k.snapshot = snapshot
            now[0] += 3
            await c.tick()
            assert c.states[uid]['active']['variant'] == 'large'
            assert c.states[uid]['returnState']['phase'] == 'Observing'
        finally:
            await c.transport.aclose()
            c.journal.close()
    asyncio.run(run())


def test_arrival_during_return_preparation_preserves_spark_route(tmp_path):
    async def run():
        c, k, now, calls, uid = await at_spark(tmp_path)
        try:
            now[0] += 5
            await c.tick()
            now[0] += 2
            await c.tick()
            assert c.states[uid]['target']['variant'] == 'medium'
            assert c.states[uid]['returnState']['phase'] == 'Preparing'
            now[0] += 1
            c.latencies.arrival(uid, c.states[uid]['active']['name'], now[0])
            await c.tick()
            assert c.states[uid]['active']['variant'] == 'large'
            assert c.states[uid]['target'] is None
            assert c.states[uid]['reason'] == 'idle_return_interrupted'
        finally:
            await c.transport.aclose()
            c.journal.close()
    asyncio.run(run())


def test_restart_does_not_reuse_persisted_idle_time(tmp_path):
    from runtime_operator.controller import Controller
    async def run():
        c, k, now, calls, uid = await at_spark(tmp_path)
        try:
            now[0] += 5
            await c.tick()
            assert c.states[uid]['idleSince'] is not None
            old = c
            c = Controller(k, old.journal, clock=lambda: now[0])
            c.probe, c.lifecycle = old.probe, old.lifecycle
            await old.transport.aclose()
            assert c.states[uid]['idleSince'] is None
            now[0] += 2
            await c.tick()
            assert c.states[uid]['active']['variant'] == 'large'
            assert c.states[uid]['returnState']['phase'] == 'Observing'
        finally:
            await c.transport.aclose()
            c.journal.close()
    asyncio.run(run())
