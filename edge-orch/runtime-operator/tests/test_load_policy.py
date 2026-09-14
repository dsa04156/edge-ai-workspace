import asyncio

from runtime_operator.latency import LatencyWindow
from test_three_tier import three_tier
from test_idle_return import at_spark


def test_arrival_rate_follows_service_identity_across_routes():
    window = LatencyWindow()
    for uid, route, at in [('u', 'nano', 95), ('u', 'orin', 99),
                           ('u', 'nano', 70), ('other', 'orin', 99)]:
        window.arrival(uid, route, at)
    assert window.service_arrival_rps('u', 100, 20) == .1
    assert window.service_arrival_rps('missing', 100, 20) == 0


def test_single_busy_worker_is_not_pressure_and_queue_dwell_restarts_after_snapshot_loss(tmp_path):
    async def run():
        c, k, now, calls = three_tier(tmp_path)
        k.resource['spec']['policy'].update(pressureSeconds=10, cooldownSeconds=1)
        uid = k.resource['metadata']['uid']
        try:
            await c.tick()
            c.inflight[c.states[uid]['active']['name']] = 1
            for _ in range(15):
                now[0] += 1
                await c.tick()
                assert c.states[uid]['highSince'] is None
                assert not c.states[uid]['proposal']
            c.pending[uid] = 1
            for _ in range(8):
                now[0] += 1
                await c.tick()
            snapshot = k.snapshot
            def broken():
                raise RuntimeError('offline')
            k.snapshot = broken
            now[0] += 1
            await c.tick()
            assert c.states[uid]['highSince'] is None
            k.snapshot = snapshot
            for _ in range(10):
                now[0] += 1
                await c.tick()
                assert not c.states[uid]['proposal']
            now[0] += 1
            await c.tick()
            assert c.states[uid]['proposal']['reason'] == 'sustained_pressure'
            assert c.states[uid]['policyObservation']['pressureElapsedSeconds'] == 10
            assert not calls
        finally:
            await c.transport.aclose()
            c.journal.close()
    asyncio.run(run())


def test_fast_current_node_with_zero_queue_cannot_return_above_lower_node_capacity(tmp_path):
    async def run():
        c, k, now, calls, uid = await at_spark(tmp_path)
        try:
            for _ in range(15):
                now[0] += 1
                route = c.states[uid]['active']['name']
                for _ in range(5):
                    c.latencies.arrival(uid, route, now[0])
                    c.latencies.record(uid, route, now[0], 40, True)
                await c.tick()
            state = c.states[uid]
            assert state['active']['variant'] == 'large' and not state['target']
            assert state['latency']['valid'] and state['load']['pending'] == 0
            assert state['lowSince'] is None
            assert state['returnState']['phase'] == 'Blocked'
            assert state['returnState']['arrivalRps'] > state['returnState']['maxArrivalRps'] == 4
            # Once arrivals and completions leave the observation window, start
            # a new continuous dwell; the fast worker's old low queue is no credit.
            k.resource['spec']['policy'].update(returnSeconds=60, cooldownSeconds=60)
            for _ in range(65):
                now[0] += 1
                await c.tick()
                assert c.states[uid]['active']['variant'] == 'large'
            for _ in range(4):
                now[0] += 1
                await c.tick()
            assert c.states[uid]['active']['variant'] == 'medium'
            assert c.states[uid]['lastTransition']['reason'] == 'sustained_idle_return'
        finally:
            await c.transport.aclose()
            c.journal.close()
    asyncio.run(run())
