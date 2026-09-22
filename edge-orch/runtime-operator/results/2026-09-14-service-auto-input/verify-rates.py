"""Validate the new bounded sensor profile at declared request rates, with routes pinned."""
import asyncio, copy, json, math, subprocess, time
from pathlib import Path
import httpx
OUT=Path(__file__).parent
SERVICE=OUT.parents[1]/"examples/edgex-sensor/service.json"
resource=json.loads(SERVICE.read_text())
uid=json.loads((OUT/"before.json").read_text())["metadata"]["uid"]
BASE="http://127.0.0.1:18884"
def apply(spec):
    patch=[{"op":"test","path":"/metadata/uid","value":uid},{"op":"replace","path":"/spec","value":spec}]
    file=OUT/"rate-patch.json"; file.write_text(json.dumps(patch))
    subprocess.run(["rtk","proxy","kubectl","--context","kubernetes-admin@kubernetes","-n","platform-runtime","patch","runtimeservice","llama-inference","--type=json","--patch-file",str(file)],check=True,capture_output=True)
async def main():
    all_rows=[]
    async with httpx.AsyncClient(timeout=35,trust_env=False) as client:
        async def state():
            r=await client.get(BASE+"/services");r.raise_for_status()
            return next(s for s in r.json()["services"] if s["name"]=="llama-inference")
        try:
            for variant in resource["spec"]["variants"]:
                node=variant["nodeSelector"]["kubernetes.io/hostname"]
                spec=copy.deepcopy(resource["spec"])
                spec["policy"]["nodeSelector"]={"kubernetes.io/hostname":node}
                apply(spec)
                deadline=time.monotonic()+180
                while time.monotonic()<deadline:
                    s=await state()
                    if s.get("serving") and s.get("active",{}).get("node")==node and s["active"]["spec"].get("commonAI",{}).get("offload",{}).get("enabled") and not s.get("target") and not s.get("retiring"): break
                    await asyncio.sleep(2)
                else: raise RuntimeError("route not ready: "+node)
                rate=variant["qualifiedRps"]
                async def request(i):
                    body=json.loads((OUT/"calibration-input.json").read_text())
                    body["request_id"]="profile-rate-"+str(time.time_ns())+"-"+str(i)
                    body["input"]["data"]["measurements"][0]["value"]=[0,329,1023][i%3]
                    start=time.monotonic()
                    r=await client.post(BASE+"/services/llama-inference/invoke",json=body,headers={"X-Request-ID":body["request_id"]})
                    elapsed=(time.monotonic()-start)*1000
                    row={"request":body,"status":r.status_code,"client_ms":elapsed,"response":r.json()}
                    return row
                tasks=[]; start=time.monotonic()
                for i in range(round(rate*30)):
                    await asyncio.sleep(max(0,start+i/rate-time.monotonic()))
                    tasks.append(asyncio.create_task(request(i)))
                rows=await asyncio.gather(*tasks)
                samples=sorted(r["client_ms"] for r in rows)
                row={"node":node,"rps":rate,"duration_seconds":30,"requests":len(rows),
                    "success":sum(r["status"]==200 for r in rows),"p95_ms":samples[math.ceil(.95*len(samples))-1],"rows":rows}
                all_rows.append(row); (OUT/"rates.json").write_text(json.dumps(all_rows,indent=2))
                assert row["success"]==len(rows), {k:v for k,v in row.items() if k!="rows"}
                assert all(r["response"]["execution"]["node"]==node for r in rows)
                variant["qualifiedP95Milliseconds"]=round(row["p95_ms"],3)
                variant["qualification"]="results/2026-09-14-service-auto-input/rates.json: 64-token cap; raw 0/329/1023; 30s fixed-rate successful requests"
                print(json.dumps({k:v for k,v in row.items() if k!="rows"}),flush=True)
            worst=max(v["qualifiedP95Milliseconds"] for v in resource["spec"]["variants"])
            return_ms=max(1000,math.ceil(worst*1.25/100)*100)
            resource["spec"]["policy"]["latency"].update(returnP95Milliseconds=return_ms,maxP95Milliseconds=math.ceil(return_ms*1.5))
            SERVICE.write_text(json.dumps(resource,ensure_ascii=False,indent=2)+"\n")
            apply(resource["spec"])
        except BaseException:
            apply(json.loads((OUT/"before.json").read_text())["spec"])
            raise
asyncio.run(main())
