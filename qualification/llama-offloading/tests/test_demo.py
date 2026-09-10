import importlib.util
from pathlib import Path
import tempfile
import unittest
import time

spec=importlib.util.spec_from_file_location("demo",Path(__file__).resolve().parents[1]/"demo.py")
demo=importlib.util.module_from_spec(spec)
spec.loader.exec_module(demo)


class DemoTests(unittest.TestCase):
    def test_stale_nano_does_not_block_ready_remote(self):
        now=time.time()
        snapshots={"nano":{"inference_ready":True,"observed_at":now-10},
                   "spark":{"inference_ready":True,"observed_at":now}}
        self.assertEqual(demo.choose_node("cached_on_demand","spark",True,{},snapshots,200,22,now),"spark")
        self.assertIsNone(demo.choose_node("nano_only","spark",True,{},snapshots,200,22,now))
        self.assertIsNone(demo.choose_node("cached_on_demand","spark",False,{},snapshots,200,22,now))

    def test_lifecycle_events_survive_many_requests(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=demo.Demo(tmp,self.transport)
            run={"id":"fixture","started":time.time(),"method":"cached_on_demand","planned":300,
                 "requests":[],"samples":[],"events":[{"event":"ready","timestamp":time.time()}]}
            run["events"].extend({"event":"dispatch","request_id":str(i),"ready":True} for i in range(300))
            app.runs.append(run)
            self.assertIn("ready",[e["event"] for e in app.view()["runs"][0]["events"]])

    def test_schedule_is_open_loop_and_identical_across_methods(self):
        stages=[{"name":"low","seconds":2,"rps":1},{"name":"burst","seconds":1,"rps":4}]
        self.assertEqual(demo.schedule(stages),[(0.,"low"),(1.,"low"),(2.,"burst"),(2.25,"burst"),(2.5,"burst"),(2.75,"burst")])

    def transport(self, url, payload=None, timeout=4):
        node=next(n for n,c in demo.NODES.items() if url.startswith(c["url"]))
        if url.endswith("/generate"):
            return {"request_id":payload["request_id"],"node_id":demo.NODES[node]["physical"],"model_digest":demo.DIGEST,"ttft_ms":1.,"tokens_per_second":100.,"response":"fixture"}
        return {"node_id":demo.NODES[node]["physical"],"management_runtime_running":True,"inference_ready":True,"model_cached":True,"model_digest":demo.DIGEST,"active_requests":0,"queue_length":0,"node_state":"ACTIVE"}

    def test_real_runner_accounts_for_requests_and_records_single_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=demo.Demo(tmp,self.transport)
            app.snapshots={n:{**self.transport(c["url"]+"/health"),"observed_at":time.time()} for n,c in demo.NODES.items()}
            run=app.run("nano_only","spark",[{"name":"fixture","seconds":.05,"rps":20}],"fixture")
            self.assertEqual(run["status"],"completed")
            report=demo.summarize(run)
            self.assertEqual(report["completed"],1)
            self.assertTrue(report["checks"]["all_requests_accounted"])
            self.assertTrue(report["checks"]["worker_identity_verified"])
            self.assertTrue(report["checks"]["forwarded_once"])
            self.assertEqual(demo.Demo(tmp,self.transport).runs[0]["id"],run["id"])

    def test_identity_mismatch_is_error_not_confirmed_remote_processing(self):
        def bad(url,payload=None,timeout=4):
            out=self.transport(url,payload,timeout)
            if url.endswith("/generate"):
                out["node_id"]="wrong-device"
            return out
        with tempfile.TemporaryDirectory() as tmp:
            app=demo.Demo(tmp,bad)
            app.snapshots={n:{**self.transport(c["url"]+"/health"),"observed_at":time.time()} for n,c in demo.NODES.items()}
            run=app.run("nano_only","spark",[{"name":"fixture","seconds":.05,"rps":20}],"fixture")
            self.assertEqual(demo.summarize(run)["errors"],1)
            self.assertFalse(run["requests"][0]["identity_verified"])

    def test_preflight_does_not_unload_another_workload(self):
        mutations=[]
        def busy(url,payload=None,timeout=4):
            if payload:
                mutations.append(url)
            return {**self.transport(url,payload,timeout),"active_requests":1}
        with tempfile.TemporaryDirectory() as tmp:
            app=demo.Demo(tmp,busy)
            run=app.run("cached_on_demand","spark",[],"fixture")
            self.assertEqual(run["status"],"failed")
            self.assertEqual(mutations,[])

    def test_interrupted_run_not_silently_resumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            app=demo.Demo(tmp,self.transport)
            app.save({"id":"interrupted","status":"running"})
            self.assertEqual(demo.Demo(tmp,self.transport).runs[0]["status"],"interrupted")


if __name__=="__main__":
    unittest.main()
