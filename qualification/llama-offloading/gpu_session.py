"""Fixed-target GPU borrowing saga. Persistent intent precedes every external mutation.

Only the approved RTX5080 worker and sensor candidate are writable. No kubectl,
arbitrary manifests, node changes, or production traffic switching are accepted.
"""
from copy import deepcopy
from pathlib import Path
from urllib import request, parse
import fcntl
import json
import sqlite3
import ssl
import threading
import time
import uuid

APP = '/apis/argoproj.io/v1alpha1/namespaces/argocd/applications/edge-orch-sensor-anomaly-demo'
WORKER = '/apis/apps/v1/namespaces/llama-offload-eval/deployments/llama-worker-spark'
SENSOR = '/apis/apps/v1/namespaces/edgex-edge/deployments/sensor-anomaly-inference-server1'
NODE = '/api/v1/nodes/etri-ser0002-cgnmsb'
OWNER = 'llama-demo.edge-ai.io/session'
OWNER_PATH = '/metadata/annotations/llama-demo.edge-ai.io~1session'
OVERRIDE = [{'name': 'sensor-anomaly-inference-server1', 'count': 0}]
HEALTH = 'http://sensor-anomaly-inference-server1.edgex-edge.svc:8080/healthz'


class KubeAPI:
    def __init__(self):
        self.root = Path('/var/run/secrets/kubernetes.io/serviceaccount')
        self.context = ssl.create_default_context(cafile=str(self.root / 'ca.crt'))

    def __call__(self, path, patch=None):
        headers = {'Authorization': 'Bearer ' + (self.root / 'token').read_text().strip()}
        data = None
        if patch is not None:
            headers['Content-Type'] = 'application/json-patch+json'
            data = json.dumps(patch).encode()
        req = request.Request('https://kubernetes.default.svc' + path, data=data,
                              headers=headers, method='GET' if patch is None else 'PATCH')
        with request.urlopen(req, context=self.context, timeout=8) as response:
            return json.load(response)


def tests(obj):
    return [{'op': 'test', 'path': '/metadata/uid', 'value': obj['metadata']['uid']},
            {'op': 'test', 'path': '/metadata/resourceVersion', 'value': obj['metadata']['resourceVersion']}]


class GPUSession:
    def __init__(self, data_dir, api=None, probe=None, drain=None):
        self.lock = threading.RLock()
        self.api = api or KubeAPI()
        self.probe = probe or self.health
        self.drain = drain or self.drain_worker
        root = Path(data_dir)
        root.mkdir(parents=True, exist_ok=True)
        # Recreate + local-path PVC + advisory lock prevents overlapping controllers.
        self.file_lock = (root / 'gpu-session.lock').open('a')
        try:
            fcntl.flock(self.file_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file_lock.close()
            raise
        self.db = sqlite3.connect(str(root / 'gpu-session.sqlite'), check_same_thread=False)
        self.db.execute('CREATE TABLE IF NOT EXISTS sessions (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        row = self.db.execute('SELECT body FROM sessions ORDER BY rowid DESC LIMIT 1').fetchone()
        self.current = json.loads(row[0]) if row else None

    @staticmethod
    def health():
        for url in (HEALTH, HEALTH.removesuffix('/healthz') + '/api/v1/augmentation-readyz'):
            with request.urlopen(url, timeout=5) as response:
                if response.status != 200:
                    return False
        return True

    @staticmethod
    def drain_worker():
        with request.urlopen('http://192.168.0.5:18100/metrics', timeout=5) as response:
            metrics = json.load(response)
        if metrics.get('active_requests', 0) or metrics.get('queue_length', 0):
            return False
        # Lifecycle lock in worker serializes this behind an in-flight activation.
        req = request.Request('http://192.168.0.5:18100/deactivate',
                              data=json.dumps({'target_state':'CACHED', 'reason':'gpu_session_restore'}).encode(),
                              headers={'Content-Type':'application/json'})
        with request.urlopen(req, timeout=180) as response:
            json.load(response)
        return True

    def view(self):
        with self.lock:
            value = deepcopy(self.current) if self.current else {'phase': 'idle', 'events': []}
            value.pop('original_source', None)
            return value

    def active(self):
        return bool(self.current and self.current['phase'] != 'restored')

    def mark(self, phase, **fields):
        with self.lock:
            self.current.update(phase=phase, updated=time.time(), **fields)
            self.current.setdefault('events', []).append({'timestamp': time.time(), 'phase': phase, **fields})
            self.db.execute('INSERT OR REPLACE INTO sessions VALUES (?, ?)',
                            (self.current['id'], json.dumps(self.current)))
            self.db.commit()

    def wait(self, check, stop=None, seconds=180):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if stop is not None and stop.is_set():
                raise RuntimeError('시연 중단 요청: 준비 중단 후 복원합니다')
            if check():
                return
            time.sleep(1)
        raise TimeoutError('GPU 준비/복원 대기시간 초과')

    def pods(self, namespace, label):
        path = '/api/v1/namespaces/' + namespace + '/pods?labelSelector=' + parse.quote(label)
        return [p for p in self.api(path)['items'] if p['status'].get('phase') not in ('Succeeded', 'Failed')]

    def sensor_ready(self):
        d = self.api(SENSOR)
        if d['metadata']['uid'] != self.current['sensor_uid']:
            raise RuntimeError('센서 Deployment UID 변경: 운영자 확인 필요')
        return (d['spec']['replicas'] == 1 and d.get('status', {}).get('readyReplicas') == 1
                and d.get('status', {}).get('observedGeneration', 0) >= d['metadata']['generation']
                and self.probe())

    def acquire(self, stop):
        if self.active():
            raise RuntimeError('미복원 GPU 세션이 있습니다')
        app, worker, sensor, node = (self.api(p) for p in (APP, WORKER, SENSOR, NODE))
        source = app['spec']['source']
        if app['metadata'].get('annotations', {}).get(OWNER) or source.get('kustomize', {}).get('replicas') is not None:
            raise RuntimeError('기존 GPU 소유권 또는 replica override: 자동 변경하지 않습니다')
        if worker['spec']['replicas'] != 0 or sensor['spec']['replicas'] != 1 or sensor.get('status', {}).get('readyReplicas') != 1:
            raise RuntimeError('시작 조건 불일치: 원격 0 / 센서 1 Ready 필요')
        if source.get('path') != 'edge-orch/sensor-anomaly-demo/k8s' or not app['spec'].get('syncPolicy', {}).get('automated', {}).get('selfHeal'):
            raise RuntimeError('승인된 센서 GitOps 계약 불일치')
        conditions = {c['type']: c['status'] for c in node['status']['conditions']}
        if conditions.get('Ready') != 'True' or conditions.get('DiskPressure') != 'False' or node.get('spec', {}).get('unschedulable'):
            raise RuntimeError('RTX 서버 Ready/디스크/scheduling 조건 불충족')
        for d in (worker, sensor):
            if d['spec']['template']['spec'].get('nodeSelector', {}).get('kubernetes.io/hostname') != 'etri-ser0002-cgnmsb':
                raise RuntimeError('승인된 GPU 노드 placement 불일치')
        if self.pods('llama-offload-eval', 'edge-ai.io/qualification-role=spark'):
            raise RuntimeError('이전 원격 Pod 종료를 기다려 주세요')
        if not self.probe():
            raise RuntimeError('원 서비스 health 확인 실패')
        self.current = {'id': uuid.uuid4().hex, 'started': time.time(), 'events': [],
                        'original_source': deepcopy(source), 'app_uid': app['metadata']['uid'],
                        'worker_uid': worker['metadata']['uid'], 'sensor_uid': sensor['metadata']['uid']}
        self.mark('reserving')
        updated = deepcopy(source)
        updated.setdefault('kustomize', {})['replicas'] = OVERRIDE
        patch = tests(app)
        if 'annotations' not in app['metadata']:
            patch.append({'op': 'add', 'path': '/metadata/annotations', 'value': {}})
        patch += [{'op': 'add', 'path': OWNER_PATH, 'value': self.current['id']},
                  {'op': 'replace', 'path': '/spec/source', 'value': updated}]
        self.api(APP, patch)
        self.mark('sensor_stopping')
        self.wait(lambda: self.api(SENSOR)['spec']['replicas'] == 0 and not self.pods(
            'edgex-edge', 'app.kubernetes.io/name=sensor-anomaly-inference-server1'), stop)
        self.mark('worker_starting', worker_started=True)
        self.scale(1)
        self.wait(lambda: self.api(WORKER).get('status', {}).get('readyReplicas') == 1, stop)
        self.mark('prepared', preparation_ms=round((time.time()-self.current['started'])*1000, 1))

    def scale(self, count):
        obj = self.api(WORKER + '/scale')
        replicas = obj.get('spec', {}).get('replicas', 0)
        if obj['metadata']['uid'] != self.current['worker_uid'] or replicas not in (0, 1):
            raise RuntimeError('원격 worker 소유권/replica 변경: 자동 덮어쓰기 금지')
        if replicas != count:
            self.api(WORKER + '/scale', tests(obj) + [{'op': 'add', 'path': '/spec/replicas', 'value': count}])

    def restore(self):
        if not self.active():
            return
        self.mark('restoring')
        try:
            app = self.api(APP)
            if app['metadata']['uid'] != self.current['app_uid']:
                raise RuntimeError('Argo Application UID 변경: 운영자 확인 필요')
            owner = app['metadata'].get('annotations', {}).get(OWNER)
            # Lost acquire acknowledgement is safe: ownership is re-read, not assumed.
            if owner != self.current['id']:
                if owner or not self.current.get('override_removed'):
                    # An unacknowledged failed acquisition did not mutate anything.
                    if owner is None and not self.current.get('worker_started') and app['spec']['source'] == self.current['original_source']:
                        self.mark('restored', restoration='acquire_not_applied')
                        return
                    raise RuntimeError('GPU 소유권 충돌: 다른 세션을 변경하지 않습니다')
            else:
                if self.api(WORKER).get('status', {}).get('readyReplicas') == 1:
                    self.wait(self.drain)
                self.scale(0)
                self.wait(lambda: self.api(WORKER)['spec']['replicas'] == 0 and not self.pods(
                    'llama-offload-eval', 'edge-ai.io/qualification-role=spark'))
                # Re-read after waiting; preserve concurrent unrelated source edits.
                app = self.api(APP)
                source = deepcopy(app['spec']['source'])
                replicas = source.get('kustomize', {}).get('replicas')
                if replicas is None and self.current.get('override_removed'):
                    pass  # Previous restore already removed it, then crashed/health timed out.
                elif replicas != OVERRIDE:
                    raise RuntimeError('임시 replica override 변경: 운영자 확인 필요')
                else:
                    del source['kustomize']['replicas']
                    if not source['kustomize'] and 'kustomize' not in self.current['original_source']:
                        del source['kustomize']
                    # Persist removal intent before mutation; retain owner until Ready.
                    self.mark('sensor_restoring', override_removed=True)
                    self.api(APP, tests(app) + [{'op': 'test', 'path': OWNER_PATH, 'value': self.current['id']},
                                               {'op': 'replace', 'path': '/spec/source', 'value': source}])
            self.wait(self.sensor_ready)
            if self.api(WORKER)['spec']['replicas'] != 0 or self.pods('llama-offload-eval', 'edge-ai.io/qualification-role=spark'):
                raise RuntimeError('원격 GPU 반환 상태 변경: 복원 완료로 표시하지 않습니다')
            app = self.api(APP)
            if app['metadata'].get('annotations', {}).get(OWNER) == self.current['id']:
                self.api(APP, tests(app) + [{'op': 'test', 'path': OWNER_PATH, 'value': self.current['id']},
                                           {'op': 'remove', 'path': OWNER_PATH}])
            self.mark('restored', restored_at=time.time(), sensor_ready=True, worker_replicas=0)
        except Exception as exc:
            self.mark('recovery_failed', error=str(exc))
            raise
