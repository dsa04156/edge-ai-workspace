"""Explicitly authorized live qualification; only qa-mixed100-* runtimes execute.

Physical verification temporarily changes/restores description, never admin state,
protocol bindings, sensor commands or actuators. Existing definitions stay registered.
"""
import argparse
import asyncio
import copy
import json
from pathlib import Path
import subprocess
import time
from urllib.parse import quote
import uuid

import httpx

PREFIX='qa-mixed100'
NODE='etri-ser0001-cg0msb'
IMAGE='192.168.0.56:5000/runtime-contract-demo@sha256:425836c63f64d6659892bc42d96700dc61edd55b3d8b8bfe37fcabcd52e4d558'


def kube(kind):
    return json.loads(subprocess.check_output(['kubectl','--request-timeout=10s','-n','platform-runtime','get',kind,'-o','json']))['items']


def execution_profile(gpu=False):
    requests={'cpu':'100m','memory':'64Mi'};limits={'cpu':'250m','memory':'128Mi'}
    if gpu:requests['nvidia.com/gpu']=limits['nvidia.com/gpu']='1'
    spec={'serviceKind':'test','execution':'http-json-v1','ioContract':'synthetic.mixed100.v1',
          'port':8080,'readyPath':'/ready','requestPath':'/infer','timeoutSeconds':30,'suspended':True,
          'demo':{'label':'mixed100 synthetic HTTP qualification','payload':{'delaySeconds':.15,'input':{'qualification':True}}},
          'policy':{'mode':'preferred','preferredRole':'server','allowedRoles':['server'],
                    'nodeSelector':{'kubernetes.io/hostname':NODE},'prepareTimeoutSeconds':60},
          'variants':[{'name':'cpu-amd64','image':IMAGE,'architecture':'amd64','backend':'cpu',
                       'requests':requests,'limits':limits,'maxInFlight':1,'qualification':'synthetic management test only'}]}
    return {'id':PREFIX+('-gpu' if gpu else '-cpu'),'name':'혼합100 검증 '+('GPU 할당' if gpu else 'CPU'),
            'architecture':'amd64','requests':requests,'limits':limits,'executionSpec':spec}


async def main(args):
    out=args.output;out.mkdir(parents=True,exist_ok=True)
    def save(name,value):(out/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
    headers={'Origin':args.dashboard,'X-Runtime-Demo':'1','Content-Type':'application/json'}
    async with httpx.AsyncClient(base_url=args.dashboard,headers=headers,timeout=25,trust_env=False) as client:
        async def api(method,path,body=None,key=None):
            response=await client.request(method,'/api/managed-devices'+path,json=body,
                                          headers={'Idempotency-Key':key} if key else {})
            response.raise_for_status();return response.json()
        async def get(id):return await api('GET','/virtual/'+id)
        async def action(id,what):
            assert id.startswith(PREFIX+'-')
            d=await get(id);result=await api('POST','/virtual/'+id+'/actions',
                {'action':what,'expectedRevision':d['revision']},str(uuid.uuid4()))
            if result['status']!='accepted':raise RuntimeError(json.dumps(result))
            return result
        async def wait_states(ids,state,seconds=90):
            deadline=time.monotonic()+seconds
            while True:
                rows=await asyncio.gather(*(get(id) for id in ids))
                if all(d['state']==state for d in rows):return rows
                if time.monotonic()>deadline:
                    save('last-unexpected-state.json',rows)
                    raise TimeoutError([(d['id'],d['state'],d.get('reason')) for d in rows])
                await asyncio.sleep(2)

        if args.phase=='register':
            before=await api('GET','');save('inventory-before.json',before)
            sensors=[d for d in before['devices'] if d['kind']=='physical' and d['type']=='sensor' and d['state']=='running']
            assert len(sensors)>=12 and before['summary']['inventoryComplete']
            sensors=sensors[:12];physical=[]
            # Use the existing management API and authoritative Metadata readback.
            async with httpx.AsyncClient(base_url=args.metadata,trust_env=False,timeout=15) as metadata:
                for sensor in sensors:
                    name=sensor['sourceId'];path='/api/v3/device/name/'+quote(name,safe='')
                    response=await metadata.get(path);response.raise_for_status();original=response.json()['device']
                    description=original.get('description','');marker=description+' [qa-mixed100-readback]'
                    if len(marker)>1000:raise ValueError('description exceeds reversible test bounds')
                    operation=None
                    try:
                        response=await client.patch('/management/devices/'+quote(name,safe=''),json={'description':marker},
                                                    headers={'Idempotency-Key':str(uuid.uuid4())})
                        response.raise_for_status();operation=response.json()
                        response=await metadata.get(path);response.raise_for_status();changed=response.json()['device']
                        assert changed['description']==marker and changed['adminState']==original['adminState']
                    finally:
                        response=await metadata.get(path);response.raise_for_status();current=response.json()['device']
                        if current.get('description')==marker:
                            restored=await client.patch('/management/devices/'+quote(name,safe=''),json={'description':description},
                                                        headers={'Idempotency-Key':str(uuid.uuid4())})
                            restored.raise_for_status()
                    response=await metadata.get(path);response.raise_for_status();restored=response.json()['device']
                    assert restored.get('description','')==description
                    assert restored['adminState']==original['adminState'] and restored['protocols']==original['protocols']
                    physical.append({'id':sensor['id'],'changedAndRestored':True,'adminAndProtocolsPreserved':True,
                                     'operationStatus':operation.get('status')})
            save('physical-control.json',physical);print('Physical 12 description changes/readbacks/restores passed',flush=True)
            pods_before={p['metadata']['uid'] for p in kube('pods')}
            services_before={s['metadata']['uid'] for s in kube('runtimeservices')}
            for gpu in [False,True]:await api('POST','/profiles',execution_profile(gpu))
            virtual=[]
            for i in range(88):
                id=PREFIX+f'-{i+1:03}';profile=PREFIX+('-gpu' if i==0 else '-cpu')
                body={'id':id,'name':id,'profileId':profile,'connections':[]}
                d=await api('POST','/virtual',body)
                assert (await api('POST','/virtual',body))['uid']==d['uid']
                d=await api('PATCH','/virtual/'+id,{'expectedRevision':d['revision'],'name':id,
                    'connections':[{'kind':'EdgeXDevice','targetId':sensors[i%12]['sourceId']}]})
                result=await action(id,'stop');view=await get(id)
                history=await api('GET','/virtual/'+id+'/history')
                assert view['state']=='stopped' and view['binding'] is None and len(history['events'])>=4
                virtual.append({'id':id,'uid':view['uid'],'revision':view['revision'],'profileId':profile,
                                'connections':view['connections'],'events':len(history['events'])})
                if (i+1)%10==0:print('Virtual definitions verified',i+1,flush=True)
            assert {s['metadata']['uid'] for s in kube('runtimeservices')}==services_before
            assert {p['metadata']['uid'] for p in kube('pods')}==pods_before
            after=await api('GET','');save('inventory-registered.json',after)
            cohort={d['id'] for d in sensors}|{'virtual:'+d['id'] for d in virtual}
            rows=[d for d in after['devices'] if d['id'] in cohort]
            assert len(rows)==100 and all(d['state']!='unknown' for d in rows)
            save('cohort.json',{'physical':physical,'virtual':virtual,'count':100,'podAllocationsAtRegistration':0,
                                'includesStopped':True,'excludesObservationTwins':True,'totalInventory':after['summary']})
            print('Cohort 100 verified; total inventory',after['summary'],flush=True)
        elif args.phase=='persistence':
            cohort=json.loads((out/'cohort.json').read_text());checked=[]
            for old in cohort['virtual']:
                d=await get(old['id']);h=await api('GET','/virtual/'+d['id']+'/history')
                assert all(d[k]==old[k] for k in ['uid','profileId','connections','revision'])
                assert d['state']=='stopped' and len(h['events'])>=old['events']
                checked.append(d['id'])
            save('persistence.json',{'verified':len(checked),'ids':checked,'enginePods':[
                {'uid':p['metadata']['uid'],'node':p['spec'].get('nodeName')} for p in kube('pods')
                if p['metadata'].get('labels',{}).get('app')=='runtime-operator']})
            print('Persistence verified',len(checked),flush=True)
        elif args.phase in {'parallel','gpu'}:
            ids=[PREFIX+'-001'] if args.phase=='gpu' else [PREFIX+f'-{i:03}' for i in range(2,6)]
            receipt=[];results=[];attempts=[]
            try:
                receipt=await asyncio.gather(*(action(id,'start') for id in ids))
                running=await wait_states(ids,'running');save(args.phase+'-running.json',running)
                uids={d['binding']['uid'] for d in running}
                pods=[p for p in kube('pods') if p['metadata'].get('labels',{}).get('platform.jinuk.io/service-uid') in uids]
                assert len(pods)==len(ids) and len({p['metadata']['uid'] for p in pods})==len(ids)
                pod_evidence=[]
                for p in pods:
                    container=p['spec']['containers'][0];expected=running[0]['profile']
                    assert container['resources']['requests']==expected['requests']
                    assert container['resources']['limits']==expected['limits']
                    assert p['spec']['nodeName']==NODE
                    code="import pathlib,json; names=['/sys/fs/cgroup/cpu.max','/sys/fs/cgroup/memory.max','/sys/fs/cgroup/cpu/cpu.cfs_quota_us','/sys/fs/cgroup/memory/memory.limit_in_bytes']; print(json.dumps({'cgroup':{n:pathlib.Path(n).read_text().strip() for n in names if pathlib.Path(n).exists()},'nvidiaDevicePresent':pathlib.Path('/dev/nvidia0').exists()}))"
                    measured=json.loads(subprocess.check_output(['kubectl','--request-timeout=10s','-n','platform-runtime',
                        'exec',p['metadata']['name'],'--','python','-c',code]))
                    limits=measured['cgroup']
                    assert int(limits.get('/sys/fs/cgroup/memory.max',limits.get('/sys/fs/cgroup/memory/memory.limit_in_bytes','0')))==134217728,limits
                    if '/sys/fs/cgroup/cpu.max' in limits:
                        quota,period=map(int,limits['/sys/fs/cgroup/cpu.max'].split());assert quota/period==.25,limits
                    else:assert int(limits['/sys/fs/cgroup/cpu/cpu.cfs_quota_us'])==25000,limits
                    if args.phase=='gpu':assert measured['nvidiaDevicePresent'],measured
                    pod_evidence.append({'name':p['metadata']['name'],'uid':p['metadata']['uid'],'node':p['spec']['nodeName'],
                                         'resources':container['resources'],'measured':measured})
                save(args.phase+'-pods.json',pod_evidence)
                async with httpx.AsyncClient(base_url=args.engine,timeout=15,trust_env=False) as engine:
                    async def invoke(d,index):
                        request_id='mixed100-'+uuid.uuid4().hex;payload={'delaySeconds':.15,'input':{'logicalId':d['id'],'round':index}}
                        response=await engine.post('/services/'+d['binding']['name']+'/invoke',json=payload,
                            headers={'X-Request-ID':request_id,'X-Runtime-Service-Uid':d['binding']['uid']})
                        attempts.append({'logicalId':d['id'],'round':index,'requestId':request_id,
                                         'status':response.status_code,'body':response.json()})
                        save(args.phase+'-attempts.json',attempts)
                        if response.status_code>=400:
                            observed=await engine.get('/services')
                            save(args.phase+'-failure-state.json',observed.json())
                        response.raise_for_status();value=response.json()
                        assert value['output']==payload['input'] and value['requestId']==request_id and value['node']==NODE
                        return value
                    for i in range(5):
                        batch=await asyncio.gather(*(invoke(d,i) for d in running),return_exceptions=True)
                        results.extend(x for x in batch if not isinstance(x,BaseException))
                        save(args.phase+'-requests.json',results)
                        if any(isinstance(x,BaseException) for x in batch):
                            raise RuntimeError([str(x) for x in batch if isinstance(x,BaseException)])
                    if args.phase=='parallel':
                        first=running[0];await action(first['id'],'stop');await wait_states([first['id']],'stopped')
                        survivors=await wait_states(ids[1:],'running')
                        results.extend(await asyncio.gather(*(invoke(d,10) for d in survivors)))
                        await action(first['id'],'start');again=(await wait_states([first['id']],'running'))[0]
                        assert again['uid']==first['uid'] and again['binding']['uid']==first['binding']['uid']
                        results.append(await invoke(again,20))
                        newpods=[p for p in kube('pods') if p['metadata'].get('labels',{}).get('platform.jinuk.io/service-uid')==first['binding']['uid']]
                        oldpod=next(p for p in pods if p['metadata']['labels']['platform.jinuk.io/service-uid']==first['binding']['uid'])
                        assert len(newpods)==1 and newpods[0]['metadata']['uid']!=oldpod['metadata']['uid']
                save(args.phase+'-requests.json',results)
            finally:
                cleanup=[]
                for id in ids:
                    try:cleanup.append(await action(id,'stop'))
                    except Exception as exc:cleanup.append({'id':id,'error':str(exc)})
                save(args.phase+'-cleanup.json',cleanup)
            stopped=await wait_states(ids,'stopped')
            bound={d['binding']['uid'] for d in stopped}
            assert not [p for p in kube('pods') if p['metadata'].get('labels',{}).get('platform.jinuk.io/service-uid') in bound]
            save(args.phase+'-result.json',{'passed':True,'runtimePods':len(ids),'requestsSucceeded':len(results),
                'stoppedAfterTest':len(stopped),'executionPodsRemaining':0,'gpuComputeTested':False})
            print(args.phase,'passed',len(results),'requests; runtime Pods cleaned up',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--execute',action='store_true',required=True)
    parser.add_argument('--phase',choices=['register','persistence','parallel','gpu'],required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--dashboard',default='http://aggregator.192.168.0.56.sslip.io')
    parser.add_argument('--engine',default='http://127.0.0.1:18880')
    parser.add_argument('--metadata',default='http://127.0.0.1:18927')
    asyncio.run(main(parser.parse_args()))
