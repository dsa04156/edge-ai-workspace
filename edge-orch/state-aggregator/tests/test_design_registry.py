import asyncio
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from pydantic import ValidationError

from app.design_registry import DesignRevision, DesignStore, create_design_router, model_contracts, validate_revision
from app.service_catalog import ServiceCatalog

CATALOG = ServiceCatalog.load(Path(__file__).parents[1] / 'app/config/service_catalog.json')


def revision(**overrides):
    return DesignRevision.model_validate({'service_id': 'test-service', 'version': '1.0',
       'design': {'nodes': [{'id': 'input', 'type': 'sensor', 'config': {'deviceName': 'sensor', 'resourceName': 'x'}},
                            {'id': 'infer', 'type': 'inference', 'config': {}}],
                  'edges': [{'from': 'input', 'to': 'infer'}]}, **overrides})


def test_revision_survives_reopen_and_retry_is_idempotent(tmp_path):
    path = tmp_path/'registry.db';store=DesignStore(path);r=revision()
    first=store.save(r);assert store.save(r)==first
    assert DesignStore(path).get(r.service_id,r.version)==first
    assert first['deployment_state']=='NOT_APPLIED'
    assert len(store.list())==1
    with pytest.raises(HTTPException) as e:
        store.save(revision(stages=[{'stage_id':'infer','cpu_request':1}]))
    assert e.value.status_code==409
    assert store.get(r.service_id,r.version)==first


def test_graph_identity_and_credentials_rejected():
    r=revision().model_dump();r['design']['nodes'][0]['config']['token']='secret'
    with pytest.raises(ValidationError): DesignRevision.model_validate(r)
    r=revision().model_dump();r['design']['edges'][0]['to']='missing'
    with pytest.raises(ValidationError): DesignRevision.model_validate(r)


def test_cycle_and_stale_input_and_architecture_block_deployment():
    r=revision(stages=[{'stage_id':'infer','preferred_node':'node','architecture':'arm64','cpu_request':2}])
    r.design['edges'].append({'from':'infer','to':'input'})
    result=validate_revision(r,[{'name':'sensor','telemetry_freshness':'stale','latest_readings':[]}],
                            [{'node':'node','schedulable':True,'architecture':'amd64','cpuAvailable':1}],model_contracts(CATALOG))
    codes={x['code'] for x in result['checks'] if x['status']=='BLOCKED'}
    assert {'dag_acyclic','input_fresh','architecture_mismatch','insufficient_cpu','model_contract_selected'}<=codes
    assert result['deployment_enabled'] is False


def test_api_auth_does_not_change_runtime_and_separates_read_validation(tmp_path):
    async def empty(): return []
    app=FastAPI();app.include_router(create_design_router(DesignStore(tmp_path/'design.db'),CATALOG,'test-token',empty,empty))
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
            payload=revision().model_dump()
            assert (await client.post('/api/service-designs',json=payload)).status_code==401
            response=await client.post('/api/service-designs',json=payload,headers={'Authorization':'Bearer test-token'})
            assert response.status_code==200
            assert response.json()['state']=='Configured'
            assert (await client.get('/api/service-designs/test-service/1.0')).json()['design']==payload['design']
            result=(await client.post('/api/service-designs/validate',json=payload)).json()
            assert result['status']=='BLOCKED'
            assert result['deployment_enabled'] is False
    asyncio.run(run())
