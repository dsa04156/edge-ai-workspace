"""Bounded, operator-owned measurement through the existing gateway, one pinned node at a time."""
import asyncio, copy, json, math, subprocess, sys, time
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from runtime_operator.common_ai import prepare
OUT=Path(__file__).parent
BASE="http://127.0.0.1:18881"
before=json.loads(Path("/tmp/service-auto-before.json").read_text())
(OUT/"before.json").write_text(json.dumps(before,indent=2))
config=copy.deepcopy(before["spec"]["commonAI"])
source=json.loads((OUT/"source.json").read_text())
event=source["events"]["events"][0]
reading=event["readings"][0]
body={"schema_version":"edgeai.execution/v1","request_id":"calibration-template","service_id":"llama-inference",
"source":{"type":"edgex","device_id":event["deviceName"],"event_id":event["id"],"profile_id":event["profileName"],"origin_ns":str(reading["origin"])},
"timestamp":"2026-09-14T00:00:00Z","input":{"type":"sensor","data":{"measurements":[{"name":reading["resourceName"],"value":int(reading["value"]),"unit":reading["units"]}]}}}
_,_,payload=prepare({"commonAI":config},body,body["request_id"],"llama-inference")
payload.pop("request_id")
(OUT/"calibration-input.json").write_text(json.dumps(body,indent=2))

def apply(spec):
    patch=[{"op":"test","path":"/metadata/uid","value":before["metadata"]["uid"]},{"op":"replace","path":"/spec","value":spec}]
    file=OUT/"calibration-patch.json"
    file.write_text(json.dumps(patch))
    subprocess.run(["rtk","proxy","kubectl","--context","kubernetes-admin@kubernetes","-n","platform-runtime","patch","runtimeservice","llama-inference","--type=json","--patch-file",str(file)],check=True,capture_output=True)

async def main():
    rows=[]
    async with httpx.AsyncClient(timeout=35,trust_env=False) as client:
        async def state():
            r=await client.get(BASE+"/services"); r.raise_for_status()
            return next(s for s in r.json()["services"] if s["name"]=="llama-inference")
        try:
            initial=await state()
            assert initial["load"]["inFlightAndPending"]==0 and not initial.get("target")
            for variant in before["spec"]["variants"]:
                node=variant["nodeSelector"]["kubernetes.io/hostname"]
                spec=copy.deepcopy(before["spec"])
                spec.update(commonAI=None,demo=None,ioContract="llama.edgex-sensor-summary.v1")
                spec["inference"].update(prompt=payload["prompt"],maxTokens=payload["max_tokens"])
                spec["policy"].update(mode="preferred",nodeSelector={"kubernetes.io/hostname":node},latency=None)
                apply(spec)
                deadline=time.monotonic()+150
                while time.monotonic()<deadline:
                    s=await state()
                    if (s.get("serving") and s.get("active",{}).get("node")==node
                        and s["active"]["spec"]["inference"]["prompt"]==payload["prompt"] and not s.get("target") and not s.get("retiring")):
                        break
                    await asyncio.sleep(2)
                else: raise RuntimeError("pinned runtime not ready: "+node)
                observations=[]
                for i in range(31):
                    rid="real-sensor-cal-"+variant["name"]+"-"+str(time.time_ns())
                    start=time.monotonic()
                    r=await client.post(BASE+"/services/llama-inference/invoke",json=payload,headers={"X-Request-ID":rid})
                    elapsed=(time.monotonic()-start)*1000
                    r.raise_for_status(); result=r.json()
                    assert result["node_id"]==node and result["model_digest"]==config["service"]["version"]
                    observations.append({"request_id":rid,"warmup":i==0,"client_ms":elapsed,"result":result})
                samples=sorted(r["client_ms"] for r in observations[1:])
                p95=samples[math.ceil(.95*len(samples))-1]
                row={"node":node,"variant":variant["name"],"samples":30,"p95_ms":p95,
                     "conservative_rps":math.floor(1000/p95*100)/100,"observations":observations}
                rows.append(row)
                (OUT/"calibration.json").write_text(json.dumps(rows,indent=2))
                print(json.dumps({k:v for k,v in row.items() if k!="observations"}),flush=True)
        finally:
            apply(before["spec"])
asyncio.run(main())
