"""One bounded real-runtime round trip; the controller alone chooses every hop."""
import asyncio,hashlib,json,subprocess,time,uuid
from pathlib import Path
import httpx
OUT=Path(__file__).parent
BASE="http://127.0.0.1:18884"
resource=json.loads((OUT.parents[1]/"examples/edgex-sensor/service.json").read_text())
uid=json.loads((OUT/"before.json").read_text())["metadata"]["uid"]
run_id="auto-common-"+uuid.uuid4().hex[:12]
async def main():
    observations=[];visited=[];receipts={};started=False; stopped=False
    async with httpx.AsyncClient(timeout=35,trust_env=False) as client:
        async def state():
            response=await client.get(BASE+"/services");response.raise_for_status()
            s=next(s for s in response.json()["services"] if s["name"]=="llama-inference")
            active=s.get("active") or {}
            row={"at":time.time(),"node":active.get("node"),"reason":s["reason"],"phase":s["phase"],
                "target":s.get("target"),"retiring":s.get("retiring"),"load":s.get("load"),
                "latency":s.get("latency"),"metrics":s.get("requestMetrics"),"returnState":s.get("returnState"),
                "lastTransition":s.get("lastTransition"),"activeObservation":active.get("observation")}
            observations.append(row)
            if active and (not visited or visited[-1]!=active["node"]):
                visited.append(active["node"]); print(json.dumps({"route":visited,"at":row["at"]}),flush=True)
            (OUT/"auto-observations.json").write_text(json.dumps(observations,indent=2))
            return s
        path=BASE+f"/demos/llama-inference/runs/{run_id}"
        try:
            deadline=time.monotonic()+180
            while time.monotonic()<deadline:
                s=await state()
                if s.get("serving") and s["active"]["node"]==resource["spec"]["commonAI"]["placement"]["default_node"] and not s.get("retiring"):break
                await asyncio.sleep(2)
            else: raise RuntimeError("baseline not ready")
            visited.clear();observations.clear();await state()
            patch=[{"op":"test","path":"/metadata/uid","value":uid},{"op":"replace","path":"/spec","value":resource["spec"]}]
            p=OUT/"automatic-patch.json";p.write_text(json.dumps(patch))
            subprocess.run(["rtk","proxy","kubectl","--context","kubernetes-admin@kubernetes","-n","platform-runtime","patch","runtimeservice","llama-inference","--type=json","--patch-file",str(p)],check=True,capture_output=True)
            await asyncio.sleep(4)
            r=await client.post(path,json={"serviceUid":uid,"mode":"service-load"});r.raise_for_status();started=True
            deadline=time.monotonic()+240
            while time.monotonic()<deadline:
                s=await state()
                r=await client.get(path,params={"serviceUid":uid});r.raise_for_status();run=r.json()
                for item in run.get("recentRequests",[]):
                    if item["state"]=="completed" and item["id"] not in receipts:
                        read=await client.get(BASE+f"/services/llama-inference/requests/{item['id']}")
                        read.raise_for_status(); receipts[item["id"]]=read.json()
                if s["active"]["node"]=="etri-ser0003-cg0ms0" and any(r["result"]["execution"]["node"]=="etri-ser0003-cg0ms0" for r in receipts.values()):break
                if run["sent"]>=700:raise RuntimeError("bounded request cap reached before Spark")
                await asyncio.sleep(3)
            else:raise RuntimeError("automatic escalation not observed")
            r=await client.post(path+"/stop",json={"serviceUid":uid});r.raise_for_status();stopped=True
            print("test input stopped; live EdgeX input continues",flush=True)
            deadline=time.monotonic()+420
            while time.monotonic()<deadline:
                s=await state()
                r=await client.get(path,params={"serviceUid":uid});r.raise_for_status();run=r.json()
                if s["active"]["node"]==resource["spec"]["commonAI"]["placement"]["default_node"] and not s.get("target") and not s.get("retiring") and run["phase"]=="Stopped":break
                await asyncio.sleep(3)
            else:raise RuntimeError("automatic low-load return not observed")
            expected=["etri-dev0001-jetorn","etri-dev0005-jetagx","etri-ser0003-cg0ms0","etri-dev0005-jetagx","etri-dev0001-jetorn"]
            assert visited==expected,visited
            assert run["failed"]==0 and run["unknown"]==0,run
            assert run["sent"]==run["succeeded"]+run["cancelled"],run
            result={"run":run,"visited":visited,"receipts":receipts,"final":s,"passed":True}
            (OUT/"automatic-verified.json").write_text(json.dumps(result,indent=2))
            print(json.dumps({"passed":True,"sent":run["sent"],"success":run["succeeded"],"cancelled":run["cancelled"],"visited":visited}),flush=True)
        finally:
            if started and not stopped:
                await client.post(path+"/stop",json={"serviceUid":uid})
            (OUT/"auto-run-id.json").write_text(json.dumps({"uid":uid,"run_id":run_id,"started":started,"stopped":stopped}))
asyncio.run(main())
