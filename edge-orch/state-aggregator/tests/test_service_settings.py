import asyncio
from types import SimpleNamespace

import httpx
from fastapi import FastAPI

from app.service_settings import create_service_settings_router


def view():
    return {'uid':'uid-1','name':'llama','specRevision':'a'*64,'observedAt':100,'editable':True,
        'settings':{'mode':'preferred','preferredRole':'edge','nodeName':None,'highWatermark':.8,
          'lowWatermark':.2,'pressureSeconds':10,'returnSeconds':60,'cooldownSeconds':30},
        'constraints':{'modes':['preferred'],'roles':['edge'],'nodes':['node-a'],'nodeSelectionAllowed':True},
        'variants':[]}


def test_settings_adapter_validates_origin_identity_and_fields_before_forwarding():
    async def run():
        requests=[]; mode='ok'
        def upstream(request):
            requests.append(request); data=view()
            if mode=='wrong': data['uid']='different'
            if mode=='conflict': return httpx.Response(409,json={'detail':'service_settings_changed'})
            return httpx.Response(200,json=data)
        app=FastAPI();app.include_router(create_service_settings_router(SimpleNamespace(
            common_runtime_demo_enabled=True,common_runtime_url='http://operator'),transport=httpx.MockTransport(upstream)))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://app') as client:
            path='/api/service-virtual-devices/llama/settings'
            response=await client.get(path,params={'serviceUid':'uid-1'});assert response.status_code==200
            assert response.headers['cache-control']=='no-store'
            body={'serviceUid':'uid-1','specRevision':'a'*64,'settings':view()['settings']}
            assert (await client.put(path,json=body)).status_code==403
            headers={'Origin':'http://app','X-Runtime-Demo':'1'}
            assert (await client.put(path,json={**body,'command':'bad'},headers=headers)).status_code==422
            assert len(requests)==1
            assert (await client.put(path,json=body,headers=headers)).status_code==200
            assert requests[-1].method=='PUT' and requests[-1].url.path=='/services/llama/settings'
            mode='conflict';assert (await client.put(path,json=body,headers=headers)).status_code==409
            mode='wrong';assert (await client.get(path,params={'serviceUid':'uid-1'})).status_code==503
    asyncio.run(run())


def test_registration_and_definition_forward_only_same_origin_and_validate_new_identity():
    async def run():
        calls=[]
        def upstream(request):
            calls.append(request);data=view();data['spec']={'suspended':True}
            return httpx.Response(201 if request.method=='POST' else 200,json=data)
        app=FastAPI();app.include_router(create_service_settings_router(SimpleNamespace(
            common_runtime_demo_enabled=True,common_runtime_url='http://operator'),transport=httpx.MockTransport(upstream)))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://app') as client:
            path='/api/service-virtual-devices/registration';body={'name':'llama','spec':{}}
            assert (await client.post(path,json=body)).status_code==403
            headers={'Origin':'http://app','X-Runtime-Demo':'1'}
            response=await client.post(path,json=body,headers=headers);assert response.status_code==201
            assert response.headers['cache-control']=='no-store' and response.json()['uid']=='uid-1'
            assert calls[-1].url.path=='/services/registration'
            assert (await client.post(path,json={**body,'name':'../invalid'},headers=headers)).status_code==422
            body={'serviceUid':'uid-1','specRevision':'a'*64,'spec':{}}
            response=await client.put('/api/service-virtual-devices/llama/definition',json=body,headers=headers)
            assert response.status_code==200 and calls[-1].url.path=='/services/llama/definition'
            assert len(calls)==2
    asyncio.run(run())
