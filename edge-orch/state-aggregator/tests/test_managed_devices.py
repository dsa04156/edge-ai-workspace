import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from app.managed_devices import MixedInventory, physical_rows, create_managed_device_router


def test_mixed_100_counts_exclude_twins_keep_stopped_and_fail_independently():
    async def run():
        fail=[False];now=[100.]
        sensors=[{'name':f'sensor-{i}','profile_name':'temperature','admin_state':'UNLOCKED',
                  'operating_state':'UP','telemetry_freshness':'fresh'} for i in range(20)]
        async def physical():
            if fail[0]:raise RuntimeError('EdgeX unavailable')
            return {'observedAt':now[0],'devices':physical_rows(sensors,[])}
        async def virtual():return {'observedAt':now[0],'devices':[{'id':f'virtual:{i}','kind':'virtual','state':'stopped'} for i in range(80)]}
        async def twins():return {'observedAt':now[0],'devices':[{'id':f'twin:{i}','kind':'observation_twin','state':'running'} for i in range(20)]}
        engine=MixedInventory({'edgex':physical,'virtual':virtual,'twins':twins},lambda:now[0])
        v=await engine.snapshot();assert v['summary']=={'registered':100,'knownRegistered':100,'stateQueryable':100,'running':20,'stopped':80,'unknown':0,'other':0,'inventoryComplete':True}
        sensors[0]['admin_state']='LOCKED';sensors[1]['operating_state']='DOWN';sensors[2]['telemetry_freshness']='stale'
        v=await engine.snapshot();assert v['summary']['stopped']==81 and v['summary']['unknown']==1 and v['summary']['other']==1
        fail[0]=True;v=await engine.snapshot();assert v['summary']['registered'] is None and v['summary']['knownRegistered']==100
        assert v['summary']['unknown']==20 and v['summary']['stopped']==80
        assert all(d['state']=='unknown' for d in v['devices'] if d['kind']=='physical')
        fail[0]=False;sensors.pop();v=await engine.snapshot();assert v['summary']['registered']==99
    asyncio.run(run())


def test_proxy_scopes_mutations_and_preserves_idempotency_key():
    async def run():
        requests=[]
        def upstream(request):requests.append(request);return httpx.Response(200,json={'id':'one','status':'accepted'})
        async def empty():return {'devices':[],'observedAt':100}
        app=FastAPI();app.include_router(create_managed_device_router(SimpleNamespace(common_runtime_url='http://runtime',logical_device_management_enabled=True),
            providers={'virtual':empty},transport=httpx.MockTransport(upstream),clock=lambda:100))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://app') as client:
            url='/api/managed-devices/virtual/one/actions';body={'action':'stop','expectedRevision':1}
            assert (await client.post(url,json=body)).status_code==403
            headers={'Origin':'http://app','X-Runtime-Demo':'1','Idempotency-Key':'unique-key'}
            assert (await client.post(url,json=body,headers=headers)).status_code==200
            assert requests[0].url.path=='/logical-devices/one/actions' and requests[0].headers['Idempotency-Key']=='unique-key'
            assert (await client.get('/api/managed-devices')).headers['cache-control']=='no-store'
    asyncio.run(run())
