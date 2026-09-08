import asyncio
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI

from app.operations import create_operations_router, project
from app.service_catalog import ServiceCatalog

CATALOG = ServiceCatalog.load(Path(__file__).parents[1] / 'app/config/service_catalog.json')
NOW = datetime(2026, 9, 8, tzinfo=timezone.utc)
STAMP = NOW.isoformat()


def fixture():
    return {
        'demo': {'mode': 'live', 'generated_at': STAMP, 'status': 'healthy', 'input_state': 'fresh',
                 'model_state': 'ready', 'execution_ownership': {'effective_mode': 'STANDBY', 'enabled': True,
                    'lease_valid': False, 'reason_code': 'execution_lease_expired'},
                 'performance': {'observed_at': STAMP, 'metrics_valid': False, 'sample_count': 0,
                    'processing_latency_p95_ms': 0, 'backlog': 0, 'throughput_per_second': 0}},
        'devices': [], 'profiles': {'service_resource_profiles': []},
    }


def test_registered_service_survives_every_reader_failure():
    result = project(CATALOG, {}, {'demo': 'offline', 'devices': 'offline'}, NOW)
    assert result.services[0]['service_id'] == 'sensor-anomaly-demo'
    assert result.services[0]['observation_state'] == 'Unknown'
    assert all(b['state'] == 'unknown' for b in result.services[0]['bindings'])
    assert result.sources['devices']['status'] == 'unknown'


def test_zero_samples_and_expired_lease_are_not_success():
    result = project(CATALOG, fixture(), {}, NOW)
    svc = result.services[0]
    assert svc['quality']['processing_latency_p95_ms'] is None
    assert svc['quality']['backlog'] is None
    assert svc['application']['state'] == 'NOT_APPLIED'
    assert any(i['reason'] == 'execution_lease_expired' for i in result.issues)
    assert all(s['state'] != 'PROCESSING_OBSERVED' for s in svc['stages'])


def test_configured_target_is_not_observed_placement_and_stale_profiles_are_unknown():
    data = fixture()
    data['profiles']['service_resource_profiles'] = [{
        'namespace': 'edgex-edge', 'service': 'sensor-anomaly-demo',
        'generated_at': '2026-08-01T00:00:00Z', 'nodes': ['old-node'], 'containers': [{'pod': 'old-pod'}],
    }]
    stages = project(CATALOG, data, {}, NOW).services[0]['stages']
    executor = stages[1]['executors'][0]
    assert executor['configured_node'] == 'etri-dev0001-jetorn'
    assert executor['observed_nodes'] == []
    assert executor['pods'] == []
    assert executor['state'] == 'Configured'


def test_remote_mode_or_ready_candidate_alone_never_proves_applied():
    data = fixture()
    data['demo']['inference_routing'] = {'inference_mode': 'REMOTE', 'observed_at': STAMP}
    data['demo']['latest'] = {'execution_mode': 'remote', 'observed_at': '2026-08-01T00:00:00Z',
                              'remote_node': 'server', 'request_id': 'r1'}
    svc = project(CATALOG, data, {}, NOW).services[0]
    assert svc['application']['state'] == 'NOT_APPLIED'
    assert svc['comparison']['improvement_percent'] is None
    assert svc['recovery']['duration_ms'] is None


def test_streaming_stages_share_processing_evidence_without_fake_stage_metrics():
    data = fixture()
    demo = data['demo']
    demo['execution_ownership'] = {'effective_mode': 'ACTIVE', 'enabled': True, 'lease_valid': True, 'observed_at': STAMP}
    demo['performance'].update(metrics_valid=True, sample_count=10, throughput_per_second=2,
                               processing_latency_p95_ms=12)
    stages = project(CATALOG, data, {}, NOW).services[0]['stages']
    assert [s['state'] for s in stages[1:4]] == ['PROCESSING_OBSERVED'] * 3
    assert all('shared_workload' in s['metrics_scope'] for s in stages)


def test_timeline_uses_recorded_step_time_and_keeps_failure():
    data = fixture()
    data['executions'] = [{'plan_id': 'plan-1', 'service_id': 'sensor-anomaly-demo',
                          'status': 'FAILED', 'steps': [{'action': 'verify_result', 'status': 'FAILED',
                          'started_at': '2026-09-07T00:00:00Z', 'completed_at': '2026-09-07T00:00:02Z',
                          'reason_codes': ['no_result']}]}]
    result = project(CATALOG, data, {}, NOW)
    assert result.events[0]['timestamp'] == '2026-09-07T00:00:02Z'
    assert result.events[0]['state'] == 'FAILED'
    assert result.services[0]['recovery']['duration_ms'] is None


def test_api_partial_reader_failure_preserves_catalog_and_other_sources():
    async def failing():
        raise RuntimeError('do not expose raw upstream detail')
    async def devices():
        return []
    app = FastAPI()
    app.include_router(create_operations_router(CATALOG, {'demo': failing, 'devices': devices}))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            response = await client.get('/state/operations')
            assert response.status_code == 200
            data = response.json()
            assert data['services'][0]['observation_state'] == 'Unknown'
            assert data['sources']['devices']['status'] == 'observed'
            assert 'raw upstream' not in response.text
    asyncio.run(run())


def test_input_failure_never_inherits_ai_processing_state():
    data = fixture()
    svc = project(CATALOG, data, {'devices': 'EdgeX unavailable'}, NOW).services[0]
    assert svc['stages'][0]['state'] == 'UNKNOWN'
    assert svc['stages'][1]['state'] == 'STANDBY'


def test_expired_ownership_observation_cannot_confirm_processing():
    data = fixture()
    data['demo']['execution_ownership'] = {'effective_mode': 'ACTIVE', 'enabled': True, 'lease_valid': True,
                                         'observed_at': '2026-08-01T00:00:00Z'}
    data['demo']['performance'].update(metrics_valid=True, sample_count=10, throughput_per_second=2)
    svc = project(CATALOG, data, {}, NOW).services[0]
    assert all(s['state'] != 'PROCESSING_OBSERVED' for s in svc['stages'])
