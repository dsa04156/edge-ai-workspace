import asyncio
import copy
import json
import uuid
from types import SimpleNamespace

import httpx
import pytest

from runtime_operator.api import create_app
from runtime_operator.controller import Controller
from runtime_operator.journal import Journal
from runtime_operator.kube import FINALIZER
from runtime_operator.logical_devices import Registry, Profile, DeviceInput, DevicePatch, Action
from test_runtime import FakeKube, spec_data


class MultiKube(FakeKube):
    def __init__(self):
        super().__init__();self.data['services']=[];self.allocations=[]
    def register_logical_runtime(self,name,spec,logical_uid):
        old=next((r for r in self.data['services'] if r['metadata']['name']==name),None)
        if old:return copy.deepcopy(old)
        r={'apiVersion':'platform.jinuk.io/v1alpha1','kind':'RuntimeService',
           'metadata':{'name':name,'uid':str(uuid.uuid4()),'resourceVersion':'1','generation':1,
                       'finalizers':[], 'annotations':{'platform.jinuk.io/virtual-device-uid':logical_uid}},'spec':copy.deepcopy(spec)}
        self.data['services'].append(r);self.allocations.append(logical_uid);return copy.deepcopy(r)
    def set_suspended(self,name,uid,suspended):
        r=next(r for r in self.data['services'] if r['metadata']['uid']==uid)
        r['spec']['suspended']=suspended;r['metadata']['generation']+=1;return copy.deepcopy(r)
    def finalizer(self,resource,add=True):
        r=next(r for r in self.data['services'] if r['metadata']['uid']==resource['metadata']['uid'])
        r['metadata']['finalizers']=[FINALIZER] if add else []


def profile(execution=True):
    raw=spec_data();raw.update(serviceKind='test',demo={'label':'echo test','payload':{'value':1}})
    return Profile(id='cpu-small',name='CPU small',architecture='arm64',requests={'cpu':'100m','memory':'64Mi'},
                   limits={'cpu':'1','memory':'128Mi'},executionSpec=raw if execution else None)


def rig(path):
    k=MultiKube();now=[100.]
    transport=httpx.AsyncClient(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={
        'ready':True,'inFlight':0,'ioContract':'example.echo.v1'})))
    c=Controller(k,Journal(str(path)),transport,lambda:now[0]);c.snapshot=copy.deepcopy(k.data);c.last_snapshot=100
    runner=SimpleNamespace(stop_runs=lambda uid:None)
    return Registry(c,runner),c,k,now


def test_100_dormant_definitions_individual_control_history_and_restart(tmp_path,monkeypatch):
    async def run():
        monkeypatch.setenv('LOGICAL_DEVICE_MANAGEMENT_ENABLED','true')
        r,c,k,now=rig(tmp_path/'engine.sqlite3');app=create_app(c)
        app.state.logical_registry=r
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://engine') as client:
            assert (await client.post('/logical-devices/profiles',json=profile(False).model_dump())).status_code==201
            for i in range(100):
                d={'id':f'vd-{i:03}','name':f'device {i}','profileId':'cpu-small','connections':[]}
                response=await client.post('/logical-devices',json=d);assert response.status_code==201
                assert response.json()['state']=='stopped'
                # An exact registration retry does not grow the registry.
                assert (await client.post('/logical-devices',json=d)).json()['uid']==response.json()['uid']
                patch=await client.patch('/logical-devices/'+d['id'],json={'expectedRevision':1,'name':f'updated {i}',
                    'connections':[{'kind':'EdgeXDevice','targetId':f'sensor-{i%20:03}','resource':'temperature'}]})
                assert patch.status_code==200
                key=str(uuid.uuid4());body={'action':'stop','expectedRevision':2}
                a=await client.post('/logical-devices/'+d['id']+'/actions',json=body,headers={'Idempotency-Key':key})
                assert a.json()['status']=='accepted'
                assert (await client.post('/logical-devices/'+d['id']+'/actions',json=body,headers={'Idempotency-Key':key})).json()==a.json()
                assert len((await client.get('/logical-devices/'+d['id']+'/history')).json()['events'])>=4
            view=(await client.get('/logical-devices')).json()
            assert view['summary']=={'registered':100,'stateQueryable':100,'running':0,'stopped':100,'unknown':0,'other':0}
            assert k.allocations==[] and not k.data['pods']
            uid=r.get('vd-000')['uid'];c.journal.close()
            r2,c2,k2,_=rig(tmp_path/'engine.sqlite3')
            assert r2.list()['summary']==view['summary'] and r2.get('vd-000')['uid']==uid
            assert r2.get('vd-000')['connections'][0]['targetId']=='sensor-000'
            assert r2.history('vd-099')[-1]['event']=='control_accepted'
            await c2.transport.aclose();c2.journal.close()
        await c.transport.aclose()
    asyncio.run(run())


def test_four_independent_runtime_bindings_and_observation_failure(tmp_path):
    async def run():
        r,c,k,now=rig(tmp_path/'engine.sqlite3');r.register_profile(profile())
        devices=[r.register(DeviceInput(id=f'vd-{i}',name=f'vd {i}',profileId='cpu-small')) for i in range(4)]
        result=await asyncio.gather(*(r.execute(d['id'],Action(action='start',expectedRevision=1),str(uuid.uuid4())) for d in devices))
        assert all(x['status']=='accepted' for x in result) and len(set(k.allocations))==4
        for resource in k.data['services']:
            variant=resource['spec']['variants'][0]
            assert variant['requests']=={'cpu':'100m','memory':'64Mi'}
            assert variant['limits']=={'cpu':'1','memory':'128Mi'}
        await c.tick();await c.tick()
        for uid,s in c.states.items():
            if s.get('target'):k.ready(s['target']['name'])
        now[0]+=1;await c.tick();now[0]+=1;await c.tick()
        running=r.list();assert running['summary']['running']==4,running
        assert len({d['binding']['uid'] for d in running['devices']})==4
        # Four bindings use the real controller's ensure path, not four counts on one service.
        assert len(k.data['pods'])==4
        d=running['devices'][0];uid=d['binding']['uid'];c.states[uid]['checkedAt']=0
        degraded=r.list()['summary'];assert degraded['registered']==4 and degraded['unknown']==1 and degraded['running']==3 and degraded['stopped']==0
        await c.tick()
        result=await asyncio.gather(*(r.execute(d['id'],Action(action='stop',expectedRevision=d['revision']),str(uuid.uuid4())) for d in r.list()['devices']))
        assert all(x['status']=='accepted' for x in result)
        for _ in range(5):now[0]+=1;await c.tick()
        assert r.list()['summary']['stopped']==4
        assert all(d['uid']==devices[i]['uid'] for i,d in enumerate(r.list()['devices']))
        await c.transport.aclose();c.journal.close()
    asyncio.run(run())


def test_profile_validation_revision_conflicts_and_disabled_mutations(tmp_path,monkeypatch):
    async def run():
        r,c,k,now=rig(tmp_path/'engine.sqlite3');r.register_profile(profile(False))
        with pytest.raises(ValueError):Profile.model_validate({**profile().model_dump(),'requests':{'cpu':'2','memory':'64Mi'}})
        gpu=Profile.model_validate({**profile().model_dump(),'id':'gpu-small',
            'requests':{'cpu':'100m','memory':'64Mi','nvidia.com/gpu':'1'},
            'limits':{'cpu':'1','memory':'128Mi','nvidia.com/gpu':'1'}})
        stored=r.register_profile(gpu)
        assert stored['executionSpec']['variants'][0]['requests']['nvidia.com/gpu']=='1'
        assert stored['executionSpec']['variants'][0]['limits']['nvidia.com/gpu']=='1'
        assert not k.allocations
        with pytest.raises(ValueError):Profile.model_validate({**gpu.model_dump(),'requests':{'cpu':'100m','memory':'64Mi','nvidia.com/gpu':'0.5'}})
        r.register(DeviceInput(id='one',name='one',profileId='cpu-small'))
        with pytest.raises(Exception,match='logical_device_revision_changed'):r.patch('one',DevicePatch(expectedRevision=2,name='changed'))
        with pytest.raises(Exception,match='execution_contract'):await r.execute('one',Action(action='start',expectedRevision=1),str(uuid.uuid4()))
        app=create_app(c);app.state.logical_registry=r;monkeypatch.delenv('LOGICAL_DEVICE_MANAGEMENT_ENABLED',raising=False)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://engine') as client:
            assert (await client.post('/logical-devices',json={'id':'other','name':'other','profileId':'cpu-small'})).status_code==403
            assert (await client.get('/logical-devices')).json()['summary']['registered']==1
        await c.transport.aclose();c.journal.close()
    asyncio.run(run())


def test_uncertain_allocation_stop_never_allocates_and_restart_never_replays(tmp_path):
    async def run():
        r,c,k,now=rig(tmp_path/'engine.sqlite3');r.register_profile(profile())
        r.register(DeviceInput(id='one',name='one',profileId='cpu-small'))
        calls=[]
        def fail(*args):calls.append(args);raise TimeoutError('allocation outcome lost')
        k.register_logical_runtime=fail
        start=Action(action='start',expectedRevision=1);key=str(uuid.uuid4())
        result=await r.execute('one',start,key)
        assert result['status']=='unknown' and r.view(r.get('one'))['state']=='unknown'
        assert (await r.execute('one',start,key))==result and len(calls)==1
        stopped=await r.execute('one',Action(action='stop',expectedRevision=1),str(uuid.uuid4()))
        assert stopped['status']=='rejected' and stopped['reason']=='allocation_outcome_unconfirmed'
        assert len(calls)==1 and not k.data['pods']
        uid=r.get('one')['uid'];c.journal.close();await c.transport.aclose()
        r,c,k,_=rig(tmp_path/'engine.sqlite3')
        assert r.get('one')['uid']==uid and r.view(r.get('one'))['state']=='unknown'
        assert (await r.execute('one',start,key))==result and k.allocations==[]
        await c.transport.aclose();c.journal.close()
    asyncio.run(run())
