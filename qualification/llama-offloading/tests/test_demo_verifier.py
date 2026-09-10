import importlib.util
from pathlib import Path
import sys
import unittest

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root))
spec=importlib.util.spec_from_file_location('verify_demo_run',root/'verify_demo_run.py')
audit=importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)
sys.path.pop(0)


class VerifierTests(unittest.TestCase):
    def gpu_record(self):
        return {'method':'nano_only', 'workload_started':5, 'finished':6,
                'gpu_session_id':'session', 'gpu_session':{
                    'id':'session', 'phase':'restored', 'sensor_ready':True,
                    'worker_replicas':0, 'restored_at':9,
                    'events':[{'phase':p,'timestamp':i} for i,p in zip([0,1,2,3,7,8],[
                        'reserving','sensor_stopping','worker_starting','prepared',
                        'restoring','sensor_restoring'])]}}

    def test_gpu_return_requires_matching_session_and_zero_reservation(self):
        self.assertTrue(audit.verify_gpu_return(self.gpu_record()))
        record=self.gpu_record();record['gpu_session']['worker_replicas']=1
        with self.assertRaisesRegex(AssertionError,'reservation'):
            audit.verify_gpu_return(record)
        record=self.gpu_record();record['gpu_session']['id']='another'
        with self.assertRaisesRegex(AssertionError,'session'):
            audit.verify_gpu_return(record)

    def test_unrestored_sensor_is_rejected(self):
        record=self.gpu_record();record['gpu_session']['sensor_ready']=False
        with self.assertRaisesRegex(AssertionError,'sensor'):
            audit.verify_gpu_return(record)

    def record(self):
        return {'status':'completed','method':'nano_only','started':1,'planned':1,
                'events':[{'event':'dispatch','request_id':'one','node':'nano','ready':True}],
                'requests':[{'request_id':'one','status':'ok','selected_node':'nano',
                             'actual_node':audit.NODES['nano']['physical'],'model_digest':audit.DIGEST,
                             'identity_verified':True,'timestamp':1,'ready_observed_at':1,
                             'dispatched_timestamp':1.1,'completed_timestamp':1.2,
                             'latency_ms':200,'ttft_ms':150}]}

    def test_valid_record(self):
        self.assertEqual(audit.verify(self.record())['completed'],1)

    def test_wrong_identity_rejected_even_if_badge_is_true(self):
        record=self.record();record['requests'][0]['actual_node']='another-node'
        with self.assertRaisesRegex(AssertionError,'physical node'):
            audit.verify(record)

    def test_duplicate_dispatch_rejected(self):
        record=self.record();record['events']*=2
        with self.assertRaisesRegex(AssertionError,'duplicate dispatch'):
            audit.verify(record)

    def test_stale_readiness_rejected(self):
        record=self.record();record['requests'][0]['ready_observed_at']=-10
        with self.assertRaisesRegex(AssertionError,'stale READY'):
            audit.verify(record)
