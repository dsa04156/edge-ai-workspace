import asyncio
import hashlib
from types import SimpleNamespace as NS
import uuid
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from app.virtual_device_control import Action, Controller, Journal, create_virtual_device_control_router

def key(): return str(uuid.uuid4())

class Apps:
    def __init__(self): self.updates=[]; self.fail=False
    def read_namespaced_deployment_scale(self, **kwargs):
        return NS(metadata=NS(uid='deployment-1',resource_version='7'))
    def replace_namespaced_deployment_scale(self, **kwargs):
        self.updates.append(kwargs)
        if self.fail: raise TimeoutError()

class FakeController(Controller):
    def __init__(self,path):
        self.apps=Apps()
        super().__init__(NS(enabled=True,apps=self.apps),Journal(path/'journal.db'))
        self.desired=0;self.ready=False;self.inferences=0;self.bad_identity=False;self.gate=None
    def definition(self): return NS()
    async def deployment(self,definition):
        if self.gate: await self.gate.wait()
        return NS(metadata=NS(uid='deployment-1',resource_version='7'))
    async def observe(self,definition):
        return {'observationError':None,'workloadUid':'other' if self.bad_identity else 'deployment-1',
                'desiredReplicas':self.desired,'instances':[{}] if self.ready else [],
                'executionState':'ready' if self.ready else 'no_instance'}
    async def infer(self,definition,row,operation_id,features):
        self.inferences+=1
        return {'requestId':operation_id,'result':{'label':'setosa'}}

def test_scale_approved_target_and_cas(tmp_path):
    c=FakeController(tmp_path)
    result=asyncio.run(c.execute(Action(action='start'),key()))
    assert result['state']=='accepted' and result['evidence']['desiredReplicas']==1
    change=c.apps.updates[0]
    assert (change['namespace'],change['name'])==('virtual-device-test','vd-demo-001')
    assert change['body']['metadata']['resourceVersion']=='7'
    assert change['body']['metadata']['uid']=='deployment-1'
    assert change['body']['spec']=={'replicas':1}

def test_duplicate_survives_restart_and_conflicting_payload_is_denied(tmp_path):
    c=FakeController(tmp_path);k=key();a=asyncio.run(c.execute(Action(action='start'),k))
    other=FakeController(tmp_path);assert asyncio.run(other.execute(Action(action='start'),k))==a
    assert len(c.apps.updates)==1 and not other.apps.updates
    with pytest.raises(HTTPException) as exc: asyncio.run(other.execute(Action(action='stop'),k))
    assert exc.value.status_code==409

def test_model_not_ready_does_not_dispatch(tmp_path):
    c=FakeController(tmp_path)
    result=asyncio.run(c.execute(Action(action='infer',features=[5.1,3.5,1.4,0.2]),key()))
    assert result['state']=='rejected' and c.inferences==0

def test_result_persists_after_stop_without_duplicate_inference(tmp_path):
    c=FakeController(tmp_path);c.ready=True;c.desired=1;k=key();a=Action(action='infer',features=[5.1,3.5,1.4,0.2])
    first=asyncio.run(c.execute(a,k));assert first['state']=='succeeded'
    asyncio.run(c.execute(Action(action='stop'),key()))
    assert asyncio.run(c.execute(a,k))==first and c.inferences==1
    assert c.journal.history()[1]['evidence']['result']['result']['label']=='setosa'
    assert c.apps.updates[-1]['body']['spec']['replicas']==0

def test_replaced_workload_blocks_mutation(tmp_path):
    c=FakeController(tmp_path);c.bad_identity=True
    assert asyncio.run(c.execute(Action(action='start'),key()))['state']=='rejected'
    assert not c.apps.updates

def test_timeout_after_dispatch_is_unknown_and_not_retried(tmp_path):
    c=FakeController(tmp_path);c.apps.fail=True;k=key();a=Action(action='start')
    first=asyncio.run(c.execute(a,k));assert first['state']=='unknown'
    assert asyncio.run(c.execute(a,k))==first and len(c.apps.updates)==1

def test_interrupted_request_is_never_replayed(tmp_path):
    c=FakeController(tmp_path);k=key();a=Action(action='start')
    c.journal.create(k,hashlib.sha256(a.model_dump_json().encode()).hexdigest(),'start')
    assert asyncio.run(c.execute(a,k))['state']=='unknown' and not c.apps.updates

def test_concurrent_different_actions_are_rejected(tmp_path):
    async def run():
        c=FakeController(tmp_path);c.gate=asyncio.Event()
        task=asyncio.create_task(c.execute(Action(action='start'),key()));await asyncio.sleep(0)
        with pytest.raises(HTTPException) as exc: await c.execute(Action(action='stop'),key())
        assert exc.value.status_code==409
        c.gate.set();await task
    asyncio.run(run())

def api(path,enabled=True):
    c=FakeController(path);settings=NS(virtual_device_control_enabled=enabled,execution_management_token='test-token',data_dir=path)
    app=FastAPI();app.include_router(create_virtual_device_control_router(None,settings,c));return TestClient(app),c

def test_auth_target_origin_and_schema_deny_without_mutation(tmp_path):
    client,c=api(tmp_path);url='/api/virtual-devices/vd-demo-001/actions';headers={'X-Execution-Token':'test-token','Idempotency-Key':key()}
    assert client.post(url,json={'action':'start'}).status_code==403
    assert client.post(url.replace('vd-demo-001','other'),headers=headers,json={'action':'start'}).status_code==404
    assert client.post(url,headers={**headers,'Origin':'https://unrelated.invalid'},json={'action':'start'}).status_code==403
    for body in [{'action':'start','replicas':5},{'action':'infer','features':[1,2,3]},{'action':'infer','features':[1,2,3,31]},{'action':'start','features':[1,2,3,4]}]:
        assert client.post(url,headers=headers,json=body).status_code==422
    assert not c.apps.updates
    assert client.post(url,headers=headers,json={'action':'start'}).json()['state']=='accepted'
    assert client.get('/api/virtual-devices/vd-demo-001/control').json()['history'][0]['action']=='start'

def test_disabled_feature_denies(tmp_path):
    client,c=api(tmp_path,False)
    assert client.get('/api/virtual-devices/vd-demo-001/control').json()['enabled'] is False
    assert client.post('/api/virtual-devices/vd-demo-001/actions',headers={'X-Execution-Token':'test-token'},json={'action':'start'}).status_code==404
    assert not c.apps.updates

def test_read_history_recovers_abandoned_work_without_replaying(tmp_path):
    c=FakeController(tmp_path);k=key();c.journal.create(k,'fingerprint','infer')
    assert c.history()[0]['state']=='unknown' and c.inferences==0

def test_scale_fails_closed_when_template_changes_between_reads(tmp_path):
    c=FakeController(tmp_path)
    c.apps.read_namespaced_deployment_scale=lambda **kwargs:NS(metadata=NS(uid='deployment-1',resource_version='8'))
    result=asyncio.run(c.execute(Action(action='start'),key()))
    assert result['state']=='rejected' and not c.apps.updates

@pytest.mark.parametrize('changed', ['image','node','identity'])
def test_changed_deployment_contract_is_rejected(tmp_path,changed):
    from app.virtual_device_control import IMAGE, ControlError, ID_LABEL
    template=NS(metadata=NS(labels={ID_LABEL:'vd-demo-001'}),spec=NS(containers=[NS(image=IMAGE)],node_selector={'kubernetes.io/hostname':'etri-ser0002-cgnmsb'}))
    deployment=NS(metadata=NS(deletion_timestamp=None,labels={ID_LABEL:'vd-demo-001'}),spec=NS(template=template,replicas=0))
    if changed=='image': template.spec.containers[0].image='arbitrary:latest'
    elif changed=='node': template.spec.node_selector={'kubernetes.io/hostname':'another'}
    else: deployment.metadata.labels={ID_LABEL:'another'}
    apps=NS(read_namespaced_deployment=lambda **kwargs:deployment)
    c=Controller(NS(enabled=True,apps=apps),Journal(tmp_path/'contract.db'))
    with pytest.raises(ControlError): asyncio.run(c.deployment(c.definition()))

@pytest.mark.parametrize('corrupt',[False,True])
def test_inference_receipt_matches_exact_pod_boot_model_input_and_request(tmp_path,monkeypatch,corrupt):
    import httpx
    from app.virtual_device_control import ControlError
    original=httpx.AsyncClient
    features=[5.1,3.5,1.4,0.2]
    runtime={'bootId':'boot-1','model':{'id':'iris-centroid','version':'1.0.0','sha256':'artifact'}}
    row={'executionState':'ready','desiredReplicas':1,'instances':[{'podIp':'127.0.0.1','podUid':'pod-1','runtime':runtime}]}
    def handler(request):
        import json
        body=json.loads(request.content)
        assert request.url.host=='127.0.0.1' and body['clientId']=='nexus-dashboard'
        return httpx.Response(200,json={'virtualDeviceId':'vd-demo-001','podUid':'wrong' if corrupt else 'pod-1','bootId':'boot-1',
            'requestId':body['requestId'],'clientId':body['clientId'],'model':runtime['model'],
            'inputSha256':hashlib.sha256(json.dumps(features,separators=(',',':')).encode()).hexdigest(),
            'result':{'label':'setosa'},'completedAt':'2026-09-08T00:00:00Z'})
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler),**kw))
    c=Controller(None,Journal(tmp_path/'receipt.db'))
    if corrupt:
        with pytest.raises(ControlError): asyncio.run(c.infer(c.definition(),row,key(),features))
    else:
        assert asyncio.run(c.infer(c.definition(),row,key(),features))['result']['label']=='setosa'

def test_scoped_test_access_authorizes_only_this_control_target(tmp_path):
    from app.virtual_device_test_access import issue
    client,c=api(tmp_path)
    token=issue('test-token')
    headers={'X-Execution-Token':token,'Idempotency-Key':key()}
    response=client.post('/api/virtual-devices/vd-demo-001/actions',headers=headers,json={'action':'start'})
    assert response.status_code==200 and response.json()['state']=='accepted'
    assert client.post('/api/virtual-devices/other/actions',headers=headers,json={'action':'start'}).status_code==404
    assert len(c.apps.updates)==1
    headers['X-Execution-Token']=issue('test-token',now=1)
    assert client.post('/api/virtual-devices/vd-demo-001/actions',headers=headers,json={'action':'stop'}).status_code==403
