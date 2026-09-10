"""Audit downloaded real-run records independently of the UI's green badges."""
import argparse
import json
from pathlib import Path

from demo import DIGEST, NODES, summarize


def verify(run, require_release_snapshot=False):
    assert run['status']=='completed', 'run not completed'
    rows=run['requests']; events=run['events']
    assert len(rows)==run['planned'] and rows, 'missing requests'
    assert all(r['status']=='ok' for r in rows), 'request errors'
    ids=[r['request_id'] for r in rows]
    assert len(set(ids))==len(ids), 'duplicate result ids'
    dispatch={}
    for e in events:
        if e['event']=='dispatch':
            assert e['request_id'] not in dispatch, 'duplicate dispatch'
            dispatch[e['request_id']]=e
    assert set(dispatch)==set(ids), 'dispatch/result mismatch'
    remote=[]
    for row in rows:
        node=row['selected_node']
        assert row['actual_node']==NODES[node]['physical'], 'physical node mismatch'
        assert row['model_digest']==DIGEST and row['identity_verified'], 'model identity mismatch'
        assert dispatch[row['request_id']]['node']==node, 'execution node changed'
        assert 0 <= row['dispatched_timestamp']-row['ready_observed_at'] <= 3, 'stale READY witness'
        assert row['completed_timestamp']>=row['dispatched_timestamp']>=row['timestamp'], 'timestamp order'
        if node!='nano':
            remote.append(row)
    if run['method']=='nano_only':
        assert not remote, 'baseline offloaded'
    elif run['method'] in ('cached_on_demand','cold_on_demand'):
        assert remote, 'no remote responses'
        activation=next(e for e in events if e['event']=='activation_started')
        ready=next(e for e in events if e['event']=='ready')
        release=next(e for e in events if e['event']=='released')
        assert activation['timestamp']<=ready['timestamp']<=min(r['dispatched_timestamp'] for r in remote), 'not READY before offload'
        assert release['timestamp']-max(r['completed_timestamp'] for r in remote)>=30, 'early idle release'
        if require_release_snapshot:
            observation=release['observation']
            assert observation['node_state']==release['state'], 'release state mismatch'
            assert observation['model_loaded'] is False, 'runner still loaded'
            assert observation['model_vram_mib']==0, 'model VRAM not returned'
    return summarize(run)


def verify_gpu_return(run):
    session = run['gpu_session']
    assert session['id'] == run['gpu_session_id'], 'GPU session mismatch'
    assert session['phase'] == 'restored' and session['sensor_ready'], 'sensor not restored'
    assert session['worker_replicas'] == 0, 'GPU reservation not returned'
    phases = session['events']
    first = lambda name: next(e['timestamp'] for e in phases if e['phase'] == name)
    assert first('reserving') <= first('sensor_stopping') <= first('worker_starting') <= first('prepared'), 'preparation order'
    assert first('prepared') <= run['workload_started'] <= run['finished'] <= session['restored_at'], 'workload/restoration order'
    assert run['finished'] <= first('restoring') <= first('sensor_restoring') <= session['restored_at'], 'restoration order'
    if run['method'] == 'cached_on_demand':
        returned = next(e for e in run['events'] if e['event'] == 'nano_returned')
        row = next(q for q in run['requests'] if q['request_id'] == returned['request_id'])
        assert row['selected_node'] == 'nano' and row['phase'] == '부하 감소', 'Nano return not observed'
    return True


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('files',nargs='+',type=Path)
    parser.add_argument('--require-release-snapshot',action='store_true')
    parser.add_argument('--require-gpu-return',action='store_true')
    args=parser.parse_args()
    records=[json.loads(p.read_text()) for p in args.files]
    if len(records)>1:
        assert all((r['stages'],r['prompt'],r['max_tokens'])==(records[0]['stages'],records[0]['prompt'],records[0]['max_tokens']) for r in records), 'workload differs'
        offsets=lambda r: sorted(q['scheduled_offset'] for q in r['requests'])
        assert all(offsets(r)==offsets(records[0]) for r in records), 'arrival schedule differs'
    for path,record in zip(args.files,records):
        if args.require_gpu_return:
            verify_gpu_return(record)
        print(json.dumps({'file':str(path),'verified':True,'summary':verify(record,args.require_release_snapshot)},ensure_ascii=False))
