import asyncio
import copy
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from runtime_operator.service_settings import public_settings, revision, router, updated_spec, PolicySettings
from runtime_operator.kube import Kube
from test_runtime import resource
from runtime_operator.service_settings import definition_spec
from kubernetes.client.exceptions import ApiException


def stopped_resource():
    r = resource(); r['spec'].update(serviceKind='ai', suspended=True)
    r['spec']['variants'][0]['verifiedNodes'] = ['field-any']
    return r


def test_policy_edit_preserves_other_contract_and_rejects_unregistered_nodes():
    r = stopped_resource(); state = {'phase':'Suspended','checkedAt':99}
    view = public_settings(r,state,100); assert view['editable']
    p = PolicySettings.model_validate(view['settings']); p.nodeName = 'field-any'; p.pressureSeconds = 8
    updated = updated_spec(r,p)
    assert updated['variants'] == r['spec']['variants'] and updated['suspended']
    assert updated['policy']['pressureSeconds'] == 8
    assert updated['policy']['nodeSelector']['kubernetes.io/hostname'] == 'field-any'
    p.nodeName = 'unregistered'
    with pytest.raises(ValueError): updated_spec(r,p)
    p.nodeName = None; p.lowWatermark = .9; p.highWatermark = .8
    with pytest.raises(ValueError): updated_spec(r,p)
    assert not public_settings(r,{'phase':'Serving','checkedAt':99},100)['editable']
    assert not public_settings(r,{'phase':'Suspended','checkedAt':50},100)['editable']


def test_kube_write_checks_uid_spec_and_preserves_latest_resource_version():
    r = stopped_resource(); calls=[]
    class Custom:
        def get_namespaced_custom_object(self,*a,**k): return copy.deepcopy(r)
        def replace_namespaced_custom_object(self,*a,**k): calls.append(a[5]); return a[5]
    kube = object.__new__(Kube); kube.custom=Custom(); kube.namespace='platform-runtime'
    p=PolicySettings.model_validate(public_settings(r,{'phase':'Suspended','checkedAt':99},100)['settings'])
    p.pressureSeconds=7
    result=kube.set_service_settings(r['metadata']['name'],r['metadata']['uid'],revision(r),p)
    assert result['metadata']['resourceVersion']=='1' and result['spec']['policy']['pressureSeconds']==7
    for uid,rev in [('other',revision(r)),(r['metadata']['uid'],'0'*64)]:
        with pytest.raises(ValueError): kube.set_service_settings(r['metadata']['name'],uid,rev,p)
    assert len(calls)==1


def test_routes_save_stopped_service_with_revision_and_never_start_it():
    async def run():
        r=stopped_resource(); uid=r['metadata']['uid']; writes=[]
        def write(name,identity,rev,settings):
            assert identity==uid and rev==revision(r)
            out=copy.deepcopy(r);out['spec']=updated_spec(r,settings);writes.append(out);return out
        c=SimpleNamespace(stopping=False,snapshot={'services':[r]},clock=lambda:100,last_snapshot=99,
            states={uid:{'phase':'Suspended','checkedAt':99}},reconcile_lock=asyncio.Lock(),
            kube=SimpleNamespace(set_service_settings=write))
        app=FastAPI();app.state.controller=c;app.include_router(router(app))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://app') as client:
            path='/services/'+r['metadata']['name']+'/settings'
            before=(await client.get(path,params={'serviceUid':uid})).json()
            body={'serviceUid':uid,'specRevision':before['specRevision'],'settings':before['settings']}
            body['settings']['pressureSeconds']=10
            response=await client.put(path,json=body);assert response.status_code==200
            assert response.json()['settings']['pressureSeconds']==10 and writes[0]['spec']['suspended']
            assert (await client.put(path,json=body)).status_code==409
            assert (await client.get(path,params={'serviceUid':'other'})).status_code==409
            c.states[uid]['phase']='Serving'
            assert (await client.put(path,json={**body,'specRevision':response.json()['specRevision']})).status_code==409
            assert len(writes)==1
    asyncio.run(run())


def test_definition_resets_evidence_and_rejects_unbounded_or_git_managed_contract():
    r=stopped_resource(); raw=copy.deepcopy(r['spec']); raw['policy']['mode']='preferred'
    raw['variants'][0].update(qualifiedRps=99, qualifiedP95Milliseconds=10, maxInFlight=8)
    result=definition_spec(raw,r)
    assert result['suspended'] and result['variants'][0]['maxInFlight']==1
    assert result['variants'][0]['verifiedNodes']==[] and result['variants'][0]['qualifiedRps'] is None
    assert raw['variants'][0]['qualifiedRps']==99
    with pytest.raises(ValueError): definition_spec({**raw,'command':['sh']})
    with pytest.raises(ValueError): definition_spec({**raw,'suspended':False})
    with pytest.raises(ValueError): definition_spec({**raw,'variants':['bad']})
    r['metadata']['annotations']={'argocd.argoproj.io/tracking-id':'app:service'}
    with pytest.raises(ValueError,match='owned_by_git'): definition_spec(raw,r)
    assert not public_settings(r,{'phase':'Suspended','checkedAt':99},100)['editable']
    unqualified=copy.deepcopy(r);unqualified['metadata']['annotations']={};unqualified['spec']=result
    settings=PolicySettings.model_validate(public_settings(unqualified,{'phase':'Suspended','checkedAt':99},100)['settings'])
    settings.mode='automatic'
    with pytest.raises(ValueError,match='requires_qualification'): updated_spec(unqualified,settings)
    from test_resident import setup
    resident,_=setup();resident.resource['spec']['suspended']=True
    resident.resource['spec']['policy']['mode']='preferred'
    view=public_settings(resident.resource,{'phase':'Suspended','checkedAt':99},100)
    assert view['editable'] and not view['definitionEditable']
    with pytest.raises(ValueError,match='resident_definition'):
        definition_spec(resident.resource['spec'],resident.resource)


def test_registration_and_definition_use_create_and_uid_guarded_replace_only():
    async def run():
        raw=stopped_resource()['spec'];raw['policy']['mode']='preferred'
        stored={};calls=[]
        class Custom:
            def create_namespaced_custom_object(self,*a,**k):
                body=copy.deepcopy(a[4]); name=body['metadata']['name']
                if name in stored: raise ApiException(status=409)
                body['metadata'].update(uid='new-uid',resourceVersion='1');stored[name]=body;calls.append('create');return copy.deepcopy(body)
            def get_namespaced_custom_object(self,*a,**k): return copy.deepcopy(stored[a[4]])
            def replace_namespaced_custom_object(self,*a,**k):
                body=copy.deepcopy(a[5]);stored[a[4]]=body;calls.append('replace');return body
        kube=object.__new__(Kube);kube.custom=Custom();kube.namespace='platform-runtime'
        c=SimpleNamespace(stopping=False,snapshot={'services':[]},clock=lambda:100,last_snapshot=99,
            states={},reconcile_lock=asyncio.Lock(),kube=kube)
        app=FastAPI();app.state.controller=c;app.include_router(router(app))
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://app') as client:
            registered=await client.post('/services/registration',json={'name':'new-model','spec':raw})
            assert registered.status_code==201,registered.text
            view=registered.json();assert view['spec']['suspended'] and not view['editable']
            assert (await client.post('/services/registration',json={'name':'new-model','spec':raw})).status_code==409
            body={'serviceUid':'new-uid','specRevision':view['specRevision'],'spec':view['spec']}
            body['spec']['variants'][0]['image']='example/new@sha256:'+'e'*64
            assert (await client.put('/services/new-model/definition',json=body)).status_code==409
            c.states['new-uid']={'phase':'Suspended','checkedAt':99}
            changed=await client.put('/services/new-model/definition',json=body)
            assert changed.status_code==200,changed.text
            assert changed.json()['uid']=='new-uid' and changed.json()['spec']['suspended']
            assert changed.json()['spec']['variants'][0]['image']==body['spec']['variants'][0]['image']
            assert (await client.put('/services/new-model/definition',json=body)).status_code==409
            assert calls==['create','replace']
            # Live spec mutation after the snapshot must also fail at the K8s boundary.
            rev=changed.json()['specRevision'];stored['new-model']['spec']['suspended']=False
            with pytest.raises(ValueError):kube.set_service_definition('new-model','new-uid',rev,body['spec'])
            assert calls==['create','replace']
    asyncio.run(run())
