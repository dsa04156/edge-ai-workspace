"""Approved Nano model pause, bounded benchmark, restore; no Pod deletion."""
import argparse
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time
import bench

BASE = 'http://127.0.0.1:18100'


def identity(pid):
    try:
        return Path(f'/proc/{pid}/stat').read_text().rsplit(')',1)[1].split()[19]
    except (OSError, IndexError):
        return None


def restore(root):
    answer = bench.api(BASE, '/activate', {'target_state':'ACTIVE','reason':'approved_local_sweep_restore'}, timeout=90)
    health = bench.api(BASE, '/health')
    loaded = bench.api('http://127.0.0.1:11435', '/api/ps')
    if answer.get('node_state') != 'ACTIVE' or not loaded.get('models'):
        raise RuntimeError('Nano original model restoration not verified')
    (root/'restored.json').write_text(json.dumps({'timestamp':time.time(),'activation':answer,'health':health,'loaded':loaded},indent=2))
    print('Nano original model restored', flush=True)


def watch(root):
    state = json.loads((root/'owner.json').read_text())
    while time.time() < state['deadline'] and identity(state['pid']) == state['identity']:
        if (root/'restored.json').exists():
            return
        time.sleep(1)
    if (root/'restored.json').exists():
        return
    if identity(state['pid']) == state['identity']:
        os.kill(state['pid'],signal.SIGTERM)
    child_path = root/'child.json'
    if child_path.exists():
        child = json.loads(child_path.read_text())
        if identity(child['pid']) == child['identity']:
            os.kill(child['pid'],signal.SIGTERM)
            limit = time.monotonic()+25
            while identity(child['pid']) == child['identity'] and time.monotonic()<limit:
                time.sleep(.5)
    if not (root/'restored.json').exists():
        restore(root)


def run(root):
    if socket.gethostname() != 'etri-dev0001-jetorn':
        raise RuntimeError('Fixed Nano only')
    root.mkdir(exist_ok=False,parents=True)
    before = bench.api(BASE,'/metrics')
    if before.get('active_requests',0) or before.get('queue_length',0):
        raise RuntimeError('Nano is busy; not pausing')
    (root/'before.json').write_text(json.dumps(before,indent=2))
    (root/'owner.json').write_text(json.dumps({'pid':os.getpid(),'identity':identity(os.getpid()),'deadline':time.time()+420}))
    with (root/'watchdog.log').open('x') as log:
        subprocess.Popen([sys.executable,__file__,'watch','--output',str(root)],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    child = None
    def interrupted(*_):
        raise KeyboardInterrupt('Restore on interruption')
    signal.signal(signal.SIGTERM,interrupted)
    signal.signal(signal.SIGHUP,interrupted)
    try:
        stopped = bench.api(BASE,'/deactivate',{'target_state':'CACHED','reason':'approved_local_sweep'},timeout=60)
        (root/'paused.json').write_text(json.dumps({'timestamp':time.time(),'result':stopped},indent=2))
        if bench.api('http://127.0.0.1:11435','/api/ps').get('models'):
            raise RuntimeError('Original GPU model still loaded')
        print('Nano original model paused',flush=True)
        child = subprocess.Popen([sys.executable,str(Path(__file__).with_name('bench.py')),'smoke',
            '--config',str(Path(__file__).with_name('nano-sweep.json')),'--output',str(root/'benchmark'),'--sweep'],start_new_session=True)
        (root/'child.json').write_text(json.dumps({'pid':child.pid,'identity':identity(child.pid)}))
        code = child.wait(timeout=330)
        if code:
            raise RuntimeError(f'Benchmark failed: {code}')
    finally:
        if child is not None and child.poll() is None:
            child.terminate()
            child.wait(timeout=25)
        restore(root)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=['run','watch','restore'])
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    {'run':run,'watch':watch,'restore':restore}[a.action](a.output.resolve())
