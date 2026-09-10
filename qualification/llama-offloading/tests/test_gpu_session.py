import importlib.util
from copy import deepcopy
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch, MagicMock

spec = importlib.util.spec_from_file_location('gpu_session', Path(__file__).resolve().parents[1]/'gpu_session.py')
gpu = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gpu)


class API:
    def __init__(self):
        def obj(uid, replicas):
            return {'metadata': {'uid':uid, 'resourceVersion':'1', 'generation':1},
                    'spec': {'replicas':replicas, 'template':{'spec':{'nodeSelector':{
                        'kubernetes.io/hostname':'etri-ser0002-cgnmsb'}}}},
                    'status':{'readyReplicas':replicas, 'observedGeneration':1}}
        self.data = {gpu.WORKER:obj('worker',0), gpu.SENSOR:obj('sensor',1),
                     gpu.NODE:{'status':{'conditions':[{'type':'Ready','status':'True'},
                                                       {'type':'DiskPressure','status':'False'}]}},
                     gpu.APP:{'metadata':{'uid':'app','resourceVersion':'1','annotations':{}},
                              'spec':{'source':{'path':'edge-orch/sensor-anomaly-demo/k8s'},
                                      'syncPolicy':{'automated':{'selfHeal':True}}}}}
        self.writes = []
        self.lose_ack = False

    def __call__(self, path, patch=None):
        if '/pods?' in path:
            return {'items':[]}
        key = path.removesuffix('/scale')
        obj = self.data[key]
        if patch:
            edited = deepcopy(obj)
            for operation in patch:
                parts = [s.replace('~1','/').replace('~0','~') for s in operation['path'].split('/')[1:]]
                parent = edited
                for part in parts[:-1]:
                    parent = parent[part]
                name = parts[-1]
                if operation['op'] == 'test':
                    if parent.get(name) != operation['value']:
                        raise RuntimeError('CAS conflict')
                elif operation['op'] == 'remove':
                    del parent[name]
                else:
                    parent[name] = deepcopy(operation['value'])
            edited['metadata']['resourceVersion'] = str(int(obj['metadata']['resourceVersion'])+1)
            self.data[key] = edited
            self.writes.append((path, patch))
            if key == gpu.APP:
                n = 0 if edited['spec']['source'].get('kustomize',{}).get('replicas') else 1
                self.data[gpu.SENSOR]['spec']['replicas'] = n
                self.data[gpu.SENSOR]['status']['readyReplicas'] = n
            if key == gpu.WORKER:
                edited['status']['readyReplicas'] = edited['spec']['replicas']
            if self.lose_ack:
                self.lose_ack = False
                raise TimeoutError('response lost after commit')
        result = deepcopy(self.data[key])
        if path.endswith('/scale') and result['spec']['replicas'] == 0:
            result['spec'] = {}  # autoscaling/v1 omits the zero-valued replicas field.
        return result


class GPUSessionTests(unittest.TestCase):
    def test_health_uses_actual_sensor_api_contract(self):
        response=MagicMock()
        response.__enter__.return_value.status=200
        with patch.object(gpu.request, 'urlopen', return_value=response) as opened:
            self.assertTrue(gpu.GPUSession.health())
        self.assertEqual([c.args[0] for c in opened.call_args_list], [gpu.HEALTH,
            'http://sensor-anomaly-inference-server1.edgex-edge.svc:8080/api/v1/augmentation-readyz'])

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.api = API()
        self.session = self.open()

    def open(self):
        return gpu.GPUSession(self.tmp.name, self.api, lambda:True, lambda:True)

    def tearDown(self):
        self.session.db.close()
        self.session.file_lock.close()
        self.tmp.cleanup()

    def acquire(self):
        self.session.acquire(threading.Event())

    def assert_restored(self):
        self.assertEqual(self.session.view()['phase'],'restored')
        self.assertEqual(self.api.data[gpu.WORKER]['spec']['replicas'],0)
        self.assertEqual(self.api.data[gpu.SENSOR]['spec']['replicas'],1)
        self.assertNotIn(gpu.OWNER,self.api.data[gpu.APP]['metadata']['annotations'])
        self.assertNotIn('kustomize',self.api.data[gpu.APP]['spec']['source'])

    def test_normal_session_restores_original_state_and_preserves_other_edits(self):
        self.acquire()
        self.assertEqual(self.api.data[gpu.SENSOR]['spec']['replicas'],0)
        self.assertEqual(self.api.data[gpu.WORKER]['spec']['replicas'],1)
        self.api.data[gpu.APP]['spec']['source']['targetRevision'] = 'other-operator'
        self.session.restore()
        self.assert_restored()
        self.assertEqual(self.api.data[gpu.APP]['spec']['source']['targetRevision'],'other-operator')

    def test_existing_override_is_never_overwritten(self):
        self.api.data[gpu.APP]['spec']['source']['kustomize']={'replicas':[]}
        with self.assertRaises(RuntimeError): self.acquire()
        self.assertEqual(self.api.writes,[])

    def test_existing_worker_is_not_borrowed(self):
        self.api.data[gpu.WORKER]['spec']['replicas']=1
        with self.assertRaises(RuntimeError): self.acquire()
        self.assertEqual(self.api.writes,[])

    def test_stop_during_preparation_restores_sensor(self):
        stop=threading.Event(); stop.set()
        with self.assertRaises(RuntimeError): self.session.acquire(stop)
        self.session.restore()
        self.assert_restored()

    def test_lost_acquire_acknowledgement_is_reconciled(self):
        self.api.lose_ack=True
        with self.assertRaises(TimeoutError): self.acquire()
        self.session.restore()
        self.assert_restored()

    def test_process_restart_recovers_persisted_ownership(self):
        self.acquire()
        self.session.db.close(); self.session.file_lock.close()
        self.session=self.open()
        self.assertTrue(self.session.active())
        self.session.restore()
        self.assert_restored()

    def test_restore_retry_after_removal_ack_lost(self):
        self.acquire()
        self.session.scale(0)
        self.api.lose_ack=True
        with self.assertRaises(TimeoutError): self.session.restore()
        self.assertTrue(self.session.active())
        self.session.restore()
        self.assert_restored()

    def test_foreign_owner_blocks_all_restore_writes(self):
        self.acquire()
        self.api.data[gpu.APP]['metadata']['annotations'][gpu.OWNER]='another-session'
        before=len(self.api.writes)
        with self.assertRaises(RuntimeError): self.session.restore()
        self.assertEqual(len(self.api.writes),before)
        self.assertEqual(self.session.view()['phase'],'recovery_failed')

    def test_duplicate_controller_cannot_acquire_file_lock(self):
        with self.assertRaises(BlockingIOError): self.open()

    def test_node_pressure_blocks_mutation(self):
        self.api.data[gpu.NODE]['status']['conditions'][1]['status']='True'
        with self.assertRaises(RuntimeError): self.acquire()
        self.assertEqual(self.api.writes,[])

    def test_ready_is_not_enough_without_original_desired_replicas(self):
        self.acquire()
        self.api.data[gpu.SENSOR]['status']['readyReplicas']=1
        self.assertFalse(self.session.sensor_ready())


if __name__ == '__main__':
    unittest.main()
