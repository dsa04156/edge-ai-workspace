import asyncio
import json
import sqlite3

import httpx
import pytest

from runtime_operator.api import create_app
from runtime_operator.diagnostics import Attempt, Recorder
from runtime_operator.journal import Journal
from test_runtime import rig, activate


async def client_for(rig):
    c,k,*_=rig
    await activate(c,k)
    return c,k,httpx.AsyncClient(transport=httpx.ASGITransport(app=create_app(c)),base_url='http://gateway')


def test_predispatch_timeout_survives_successes_and_restart(rig,tmp_path):
    async def run():
        c,k,client=await client_for(rig)
        uid,name=k.resource['metadata']['uid'],k.resource['metadata']['name']
        path=f'/services/{name}'
        try:
            c.states[uid]['active']['spec']['timeoutSeconds']=.06
            c.inflight[c.states[uid]['active']['name']]=1
            r=await client.post(path+'/invoke',json={'secret':'never copied'},headers={'X-Request-ID':'wait-expired'})
            assert r.status_code==503 and r.json()['reason']=='admission_timeout'
            assert c.journal.request(uid,'wait-expired') is None
            c.inflight.clear()
            for i in range(8):
                assert (await client.post(path+'/invoke',json={'secret':'never copied'},headers={'X-Request-ID':f'success-{i}'})).status_code==200
            value=(await client.get(path+'/request-diagnostics',params={'serviceUid':uid})).json()
            assert len(value['items'])==1
            row=value['items'][0]
            assert row['reason']=='admission_timeout' and row['gatewayQueueMilliseconds']>=60
            assert row['node'] is None and row['admittedNode']=='field-any' and row['workerRoundTripMilliseconds'] is None
            assert 'never copied' not in json.dumps(value) and 'secret' not in json.dumps(value)
            assert (await client.get(path+'/request-diagnostics',params={'serviceUid':'other'})).status_code==404
            assert (await client.get(path+'/request-diagnostics',params={'serviceUid':uid,'limit':101})).status_code==422
            backup=tmp_path/'restored.db';dest=sqlite3.connect(backup);c.journal.db.backup(dest);dest.close()
            journal=Journal(str(backup))
            try:assert Recorder(journal).list(uid)['items'][0]['reason']=='admission_timeout'
            finally:journal.close()
        finally:await client.aclose();await c.transport.aclose()
    asyncio.run(run())


@pytest.mark.parametrize('failure',['timeout','transport','invalid','http'])
def test_worker_failure_reason_and_no_second_dispatch_on_replay(rig,failure):
    async def run():
        c,k,client=await client_for(rig)
        uid,name=k.resource['metadata']['uid'],k.resource['metadata']['name'];sent=[]
        async def handler(req):
            sent.append(req)
            if failure=='timeout':raise httpx.ReadTimeout('private endpoint')
            if failure=='transport':raise httpx.ConnectError('private endpoint')
            if failure=='invalid':return httpx.Response(200,text='sensitive invalid body')
            return httpx.Response(502,json={'reason':'sensitive worker message'})
        await c.transport.aclose();c.transport=httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            path=f'/services/{name}';headers={'X-Request-ID':'failed-request'}
            result=await client.post(path+'/invoke',json={'x':1},headers=headers)
            assert result.status_code>=400
            assert (await client.post(path+'/invoke',json={'x':1},headers=headers)).status_code==result.status_code
            rows=(await client.get(path+'/request-diagnostics',params={'serviceUid':uid})).json()['items']
            assert len(sent)==1 and len(rows)==2 and rows[0]['replay']
            row=rows[1]
            assert row['reason']=={'timeout':'worker_timeout','transport':'worker_transport_error','invalid':'worker_response_invalid','http':'worker_http_error'}[failure]
            assert row['node']=='field-any' and row['workerRoundTripMilliseconds']>=0
            assert 'sensitive' not in json.dumps(rows) and 'private' not in json.dumps(rows)
        finally:await client.aclose();await c.transport.aclose()
    asyncio.run(run())


def test_pagination_uid_isolation_restart_states_and_retention(tmp_path,monkeypatch):
    import runtime_operator.diagnostics as module
    journal=Journal(str(tmp_path/'state.db'));store=Recorder(journal)
    try:
        for uid in ['u1','u2']:
            for i in range(6):
                a=Attempt(store,uid,f'r-{i}',None,{'node':'edge'});a.finish(503,'rejected','admission_timeout')
        first=store.list('u1',limit=2);second=store.list('u1',limit=2,before=first['nextBefore'])
        assert len({r['seq'] for r in first['items']+second['items']})==4
        assert all(r['uid']=='u1' for r in first['items']+second['items'])
        a=Attempt(store,'u1','queued',None,None);a.queued()
        b=Attempt(store,'u1','dispatched',None,None);b.queued();b.dispatch({'node':'gpu','name':'revision'})
        journal.close();journal=Journal(str(tmp_path/'state.db'));store=Recorder(journal)
        rows={r['requestId']:r for r in store.list('u1')['items']}
        assert rows['queued']['reason']=='controller_restarted_before_dispatch'
        assert rows['dispatched']['state']=='unknown' and rows['dispatched']['node']=='gpu'
        monkeypatch.setattr(module,'CLASS_LIMIT',2);store.last_prune=0;store.prune()
        assert journal.db.execute('SELECT count(*) FROM request_diagnostics WHERE terminal=1 AND failure=1').fetchone()[0]==2
    finally:journal.close()


def test_queue_route_change_records_actual_worker_and_gateway_wait(rig):
    async def run():
        c,k,client=await client_for(rig)
        uid,name=k.resource['metadata']['uid'],k.resource['metadata']['name']
        old=c.states[uid]['active'];c.inflight[old['name']]=1
        try:
            task=asyncio.create_task(client.post(f'/services/{name}/invoke',json={},headers={'X-Request-ID':'route-change'}))
            await asyncio.sleep(.08)
            c.states[uid]['active']={**old,'name':'new-revision','node':'new-node'}
            assert (await task).status_code==200
            rows=(await client.get(f'/services/{name}/request-diagnostics',params={'serviceUid':uid,'failuresOnly':'false'})).json()['items']
            assert rows[0]['admittedNode']=='field-any' and rows[0]['node']=='new-node'
            assert rows[0]['gatewayQueueMilliseconds']>=50 and rows[0]['workerRoundTripMilliseconds']>=0
        finally:await client.aclose();await c.transport.aclose()
    asyncio.run(run())
