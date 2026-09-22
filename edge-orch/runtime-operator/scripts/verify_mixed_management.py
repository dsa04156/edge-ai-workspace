"""Local qualification only. Never connects to Kubernetes or a real EdgeX server.

Reuses production API/SQLite/controller paths with explicit test adapters, then runs
four real vd_runtime processes separately. Run with the aggregator test venv.
"""
import argparse
import asyncio
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import uuid

import httpx
from fastapi import FastAPI

REPO = Path(__file__).resolve().parents[3]
for path in [REPO/'edge-orch/runtime-operator', REPO/'edge-orch/runtime-operator/tests',
             REPO/'edge-orch/state-aggregator', REPO/'edge-orch/state-aggregator/tests']:
    sys.path.insert(0, str(path))
from test_logical_devices import rig, profile
from test_device_management import AdapterCatalog, CATALOG_PATH, FakeMetadata, FakeEvents, service_for, onboarding_request, DevicePatchRequest
from runtime_operator.api import create_app
from app.managed_devices import create_managed_device_router, physical_rows
from types import SimpleNamespace


async def management(directory):
    os.environ['LOGICAL_DEVICE_MANAGEMENT_ENABLED']='true'
    r,c,k,now=rig(directory/'engine.sqlite3')
    metadata=FakeMetadata();events=FakeEvents()
    physical=service_for(AdapterCatalog.load(CATALOG_PATH),metadata,events)
    operation=await physical.create_device(onboarding_request(device_name='qualification-sensor'),
                                           idempotency_key='qualification-register',actor='local-qualification')
    assert operation.metadata_applied and not operation.first_event_verified
    for i,admin in enumerate(['LOCKED','UNLOCKED','LOCKED']):
        await physical.patch_device('qualification-sensor',DevicePatchRequest.model_validate({'adminState':admin}),
                                    idempotency_key=f'qualification-control-{i}',actor='local-qualification')
        assert (await metadata.get_device('qualification-sensor'))['adminState']==admin
    failed=[False]
    async def sensors():
        if failed[0]:raise ConnectionError('injected EdgeX outage')
        devices=await metadata.list_devices()
        rows=physical_rows([{'name':d['name'],'admin_state':d['adminState'],
                            'operating_state':d.get('operatingState','UNKNOWN'),'telemetry_freshness':'unknown',
                            'profile_name':d['profileName'],'physical_device_id':d['tags']['physicalDeviceId']} for d in devices],[])
        return {'observedAt':now[0],'devices':rows}
    async def logical():
        value=r.list()
        for d in value['devices']:
            d.update(sourceId=d['id'],id='virtual:'+d['id'],type='logical')
        return value
    owner=create_app(c);owner.state.logical_registry=r
    app=FastAPI();app.include_router(create_managed_device_router(
        SimpleNamespace(logical_device_management_enabled=True,common_runtime_url='http://engine'),
        providers={'edgex':sensors,'logical':logical},transport=httpx.ASGITransport(app=owner),clock=lambda:now[0]))
    headers={'Origin':'http://dashboard','X-Runtime-Demo':'1','Content-Type':'application/json'}
    started=time.monotonic();latencies=[];identities={}
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://dashboard',headers=headers) as client:
            response=await client.post('/api/managed-devices/profiles',json=profile(False).model_dump());assert response.status_code==201,response.text
            for i in range(99):
                begin=time.monotonic();id=f'qualification-vd-{i:03}';base='/api/managed-devices/virtual'
                body={'id':id,'name':id,'profileId':'cpu-small'}
                response=await client.post(base,json=body);assert response.status_code==201,response.text
                identities[id]=response.json()['uid']
                assert (await client.post(base,json=body)).json()['uid']==identities[id]
                response=await client.patch(base+'/'+id,json={'expectedRevision':1,'name':id,
                    'connections':[{'kind':'EdgeXDevice','targetId':'qualification-sensor','resource':'temperature_raw'}]})
                assert response.status_code==200,response.text
                action={'action':'stop','expectedRevision':2};key=str(uuid.uuid4())
                response=await client.post(base+'/'+id+'/actions',json=action,headers={'Idempotency-Key':key})
                assert response.json()['status']=='accepted',response.text
                assert (await client.post(base+'/'+id+'/actions',json=action,headers={'Idempotency-Key':key})).json()==response.json()
                assert (await client.get(base+'/'+id)).json()['state']=='stopped'
                assert len((await client.get(base+'/'+id+'/history')).json()['events'])>=4
                latencies.append((time.monotonic()-begin)*1000)
            snapshot=(await client.get('/api/managed-devices')).json()
            assert snapshot['summary']['registered']==100 and snapshot['summary']['stopped']==100,snapshot['summary']
            assert not k.allocations and not k.data['pods']
            failed[0]=True;degraded=(await client.get('/api/managed-devices')).json()
            assert degraded['summary']['registered'] is None
            assert degraded['summary']['knownRegistered']==100 and degraded['summary']['unknown']==1 and degraded['summary']['stopped']==99
            failed[0]=False;assert (await client.get('/api/managed-devices')).json()['summary']==snapshot['summary']
        c.journal.close();await c.transport.aclose()
        restored,c2,k2,_=rig(directory/'engine.sqlite3')
        assert all(restored.get(id)['uid']==uid and restored.get(id)['connections'] for id,uid in identities.items())
        assert restored.list()['summary']['stopped']==99 and len(restored.history('qualification-vd-098'))>=4
        await c2.transport.aclose();c2.journal.close()
        return {'result':'passed','engineProcesses':1,'journalWriters':1,'registeredPhysical':1,'registeredVirtual':99,
                'physicalBackend':'simulated EdgeX Metadata/Core Data; real DeviceManagementService; no first telemetry event',
                'virtualBackend':'real FastAPI proxy + runtime owner + SQLite; simulated Kubernetes adapter',
                'physicalIndividualReadback':1,'physicalAdminTransitionsVerified':3,'virtualIndividualReadAndControl':99,
                'virtualIdempotentRegistrationAndControl':99,'virtualHistoryVerified':99,'virtualRestartPersistenceVerified':99,
                'allocatedRuntimeServicesDuringRegistration':0,'createdPodsDuringRegistration':0,
                'summary':snapshot['summary'],'sourceFailureSummary':degraded['summary'],
                'elapsedSeconds':round(time.monotonic()-started,3),
                'perVirtualApiCycleP95Ms':round(sorted(latencies)[int(len(latencies)*.95)],3),
                'countingConditions':{'includesStopped':True,'physicalUnit':'one EdgeX registered endpoint',
                                      'observationTwinsCounted':False,'podsCounted':False,'targetAchievedClaim':False}},snapshot
    finally:
        if not c.transport.is_closed:await c.transport.aclose()


async def parallel_processes(directory):
    runtime=REPO/'edge-orch/virtual-device-runtime';workers=[];logs=[]
    def launch(id):
        # Pass an already-bound loopback socket, avoiding free-port races and public exposure.
        sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
        env={**os.environ,'PYTHONPATH':str(runtime),'VD_ID':id}
        env.pop('POD_UID',None)  # local processes are not Pods
        log=(directory/(id+'.log')).open('ab');logs.append(log)
        process=subprocess.Popen([sys.executable,'-m','uvicorn','vd_runtime.api:create_app','--factory',
            '--fd',str(sock.fileno()),'--log-level','warning'],env=env,pass_fds=(sock.fileno(),),stdout=log,stderr=log)
        sock.close();worker={'id':id,'process':process,'port':port};workers.append(worker);return worker
    async with httpx.AsyncClient(trust_env=False,timeout=5) as client:
        async def get(w,path):
            response=await client.get(f"http://127.0.0.1:{w['port']}"+path);response.raise_for_status();return response.json()
        async def ready(w):
            for _ in range(100):
                if w['process'].poll() is not None:raise RuntimeError('runtime process exited')
                try:
                    status=await get(w,'/status')
                    if status['modelReady']:return status
                except httpx.HTTPError:pass
                await asyncio.sleep(.1)
            raise TimeoutError('runtime readiness')
        async def infer(w,i):
            response=await client.post(f"http://127.0.0.1:{w['port']}/infer",json={
                'requestId':f'parallel-{i}','clientId':'mixed-qualification','features':[5.1,3.5,1.4,.2]})
            response.raise_for_status();body=response.json()
            assert body['virtualDeviceId']==w['id'] and body['podUid'] is None and body['result']['label']=='setosa',body
            return body
        try:
            active=[launch(f'parallel-vd-{i}') for i in range(4)]
            initial=await asyncio.gather(*(ready(w) for w in active))
            assert len({w['process'].pid for w in active})==4
            assert all(w['process'].poll() is None for w in active)
            results=[]
            for batch in range(2):
                results.extend(await asyncio.gather(*(infer(w,batch*5+i) for i in range(5) for w in active)))
            statuses=await asyncio.gather(*(get(w,'/status') for w in active))
            assert all(s['succeeded']==10 for s in statuses)
            active[0]['process'].terminate();await asyncio.to_thread(active[0]['process'].wait,10)
            survivors=await asyncio.gather(*(infer(w,100) for w in active[1:]))
            restarted=launch(active[0]['id']);after=await ready(restarted)
            assert after['virtualDeviceId']==initial[0]['virtualDeviceId'] and after['bootId']!=initial[0]['bootId']
            await infer(restarted,200)
            return {'result':'passed','sameHost':True,'parallelRuntimeProcesses':4,'concurrentRequestBatch':20,
                    'successfulRequests':len(results)+len(survivors)+1,'initialStatus':statuses,
                    'survivorsAfterIndividualStop':3,'restartPreservedLogicalId':True,'restartChangedBootId':True,
                    'runtime':'existing vd_runtime nearest-centroid Iris model; four real independent OS processes',
                    'kubernetesPodsVerified':False,'resourceQuotasEnforced':False,'gpuTested':False,
                    'limitation':'Docker socket unavailable; process parallelism is not Kubernetes Pod acceptance evidence'}
        finally:
            for w in workers:
                if w['process'].poll() is None:w['process'].terminate()
            for w in workers:
                try:await asyncio.to_thread(w['process'].wait,10)
                except subprocess.TimeoutExpired:w['process'].kill();w['process'].wait()
            for log in logs:log.close()


async def main(output):
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='mixed-device-qualification-') as scratch:
        management_result,snapshot=await management(Path(scratch))
        process_result=await parallel_processes(Path(scratch))
    report={'testedAt':datetime.now(timezone.utc).isoformat(),'operationalClusterModified':False,
            'management100':management_result,'parallelExecution':process_result,
            'remainingAcceptance':['single-node deployed engine with persistent volume','real EdgeX device observation',
                                   'parallel Kubernetes Pods with CPU/memory/GPU allocation and independent controls']}
    (output/'verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    (output/'dashboard-fixture.json').write_text(json.dumps(snapshot,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({'management':management_result['result'],'parallel':process_result['result'],
                      'registered':100,'parallelProcesses':4,'requests':process_result['successfulRequests'],
                      'output':str(output)},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    asyncio.run(main(parser.parse_args().output))
