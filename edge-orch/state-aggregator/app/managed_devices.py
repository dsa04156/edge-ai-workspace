"""Mixed logical inventory over existing EdgeX, node and virtual-device authorities."""
import asyncio
import copy
import time
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response


def summarize(rows, complete=True):
    counts={"registered":len(rows) if complete else None,"knownRegistered":len(rows),
            "stateQueryable":sum(r["state"]!="unknown" for r in rows),"inventoryComplete":complete}
    counts.update({state:sum(r["state"]==state for r in rows) for state in ["running","stopped","unknown"]})
    counts["other"]=len(rows)-counts["running"]-counts["stopped"]-counts["unknown"]
    return counts


def physical_rows(devices,nodes):
    rows=[]
    for d in devices:
        state=("stopped" if d["admin_state"]=="LOCKED" else "running" if d["operating_state"]=="UP" and d["telemetry_freshness"]=="fresh"
               else "unavailable" if d["operating_state"]=="DOWN" else "unknown")
        rows.append({"id":"edgex:"+d["name"],"sourceId":d["name"],"name":d["name"],"kind":"physical",
                     "type":"sensor","state":state,"profileId":d["profile_name"],"node":d.get("node_name"),
                     "reason":d.get("reason"),"physicalSourceId":d.get("physical_device_id"),
                     "controls":{"owner":"edgex-management","href":"/management/devices/"+quote(d["name"],safe="")}})
    for n in nodes:
        rows.append({"id":"node:"+n["name"],"sourceId":n["name"],"name":n["name"],"kind":"physical","type":"node",
                     "state":"running" if n["ready"] is True else "unavailable" if n["ready"] is False else "unknown",
                     "controls":{"owner":"kubernetes","actions":[]}})
    return rows


def legacy_rows(snapshot):
    rows=[]
    for r in snapshot["resources"]:
        state="unknown"
        if not r["observationError"]:
            if r["executionState"] in {"ready","processing"}:state="running"
            elif r["executionState"]=="no_instance" and r.get("desiredReplicas")==0 and r.get("workloadExists"):state="stopped"
            elif r["executionState"] in {"observed","not_ready","terminating"}:state="starting" if r["executionState"]!="terminating" else "stopping"
        rows.append({"id":"legacy:"+r["id"],"sourceId":r["id"],"name":r["definition"]["spec"]["displayName"],
                     "kind":"virtual","type":"legacy","state":state,"profileId":r["definition"]["spec"].get("resourceType"),
                     "connections":r["connections"],"instances":r["instances"],"reason":r["observationError"],
                     "controls":{"owner":"virtual-device-control","actions":["start","stop","infer"] if r["id"]=="vd-demo-001" else []}})
    return rows


class MixedInventory:
    def __init__(self,providers,clock=time.time):
        self.providers=providers;self.clock=clock;self.cache={};self.lock=asyncio.Lock()

    async def snapshot(self):
        async with self.lock:
            async def fetch(name,provider):
                try:
                    value=await asyncio.wait_for(provider(),timeout=12)
                    if not isinstance(value,dict) or not isinstance(value.get("devices"),list):raise ValueError("source_contract_invalid")
                    if not 0<=self.clock()-value["observedAt"]<value.get("maxAgeSeconds",15):raise ValueError("source_stale")
                    for row in value["devices"]:
                        if not isinstance(row,dict) or not isinstance(row.get("id"),str) or row.get("state") not in {
                            "running","stopped","unknown","starting","stopping","blocked","unavailable"}:
                            raise ValueError("source_row_invalid")
                    self.cache[name]=copy.deepcopy(value)
                    return name,value,None
                except Exception as exc:
                    value=copy.deepcopy(self.cache.get(name,{"devices":[],"profiles":[]}))
                    for d in value["devices"]:d.update(state="unknown",reason="source_unavailable",locations=[],instances=[])
                    return name,value,type(exc).__name__
            sources=await asyncio.gather(*(fetch(k,v) for k,v in self.providers.items()))
            rows=[];errors={};profiles=[]
            for name,value,error in sources:
                if error:errors[name]=error
                rows.extend(value["devices"]);profiles.extend(value.get("profiles",[]))
            # Never include read-only twins or infer a logical object from a Pod/RuntimeService.
            unique={r["id"]:r for r in rows if r.get("kind") in {"physical","virtual"}}
            rows=sorted(unique.values(),key=lambda r:(r["kind"],r["id"]))
            summary=summarize(rows,not errors)
            return {"schemaVersion":"edgeai.managed-devices/v1","observedAt":self.clock(),"maxAgeSeconds":15,
                    "engineScope":"single-runtime-journal-writer","summary":summary,"sourceErrors":errors,
                    "devices":rows,"profiles":profiles,
                    "countingPolicy":{"unit":"registered-node-edgex-device-or-independent-virtual-device",
                                      "includesStopped":True,"includesObservationTwins":False,"includesPods":False}}


def create_managed_device_router(settings, service=None, *, providers=None, transport=None, clock=time.time):
    router=APIRouter(prefix="/api/managed-devices")
    async def owner(method,path,body=None,key=None):
        try:
            async with httpx.AsyncClient(transport=transport,timeout=15,trust_env=False,follow_redirects=False) as client:
                r=await client.request(method,settings.common_runtime_url.rstrip("/")+"/logical-devices"+path,
                                       json=body,headers={"Idempotency-Key":key} if key else {})
            if r.is_error:raise HTTPException(r.status_code if r.status_code<500 else 503,r.json().get("detail","logical_owner_unavailable"))
            r.raise_for_status();return r.json()
        except (httpx.HTTPError,ValueError):raise HTTPException(503,"logical_owner_unavailable") from None

    if providers is None:
        from .virtual_resources import KubernetesVirtualDeviceReader, VirtualDeviceObserver
        from .virtual_resource_registry import VirtualDeviceRegistry
        reader=KubernetesVirtualDeviceReader(service.kube);observer=VirtualDeviceObserver(reader)
        async def sensors():
            devices=await service.get_devices()
            return {"devices":physical_rows([d.model_dump(mode="json") for d in devices],[]),"observedAt":clock()}
        async def nodes():return {"devices":physical_rows([],await reader.nodes()),"observedAt":clock()}
        async def legacy():
            snapshot=await observer.snapshot(VirtualDeviceRegistry.load())
            return {"devices":legacy_rows(snapshot),"observedAt":clock()}
        async def logical():
            value=await owner("GET","")
            if value.get("schemaVersion")!="edgeai.logical-devices/v1":raise ValueError("logical_contract_mismatch")
            for d in value["devices"]:
                d.update(id="virtual:"+d["id"],sourceId=d["id"],type="logical",controls={"owner":"runtime-operator","actions":["start","stop"]})
            return value
        providers={"edgex":sensors,"nodes":nodes,"legacy":legacy,"logical":logical}
    inventory=MixedInventory(providers,clock)

    def mutation(request):
        if not getattr(settings,"logical_device_management_enabled",False):raise HTTPException(403,"logical_device_management_disabled")
        if (request.headers.get("origin")!=str(request.base_url).rstrip("/") or request.headers.get("x-runtime-demo")!="1"
            or request.headers.get("content-type","").split(";")[0]!="application/json"):
            raise HTTPException(403,"same_origin_action_required")

    async def payload(request):
        mutation(request)
        try:return await request.json()
        except ValueError:raise HTTPException(422,"invalid_json") from None

    @router.get("")
    async def listing(response:Response):
        response.headers["Cache-Control"]="no-store"
        value=await inventory.snapshot();value["mutationEnabled"]=bool(getattr(settings,"logical_device_management_enabled",False))
        return value
    @router.post("/profiles",status_code=201)
    async def profile(request:Request):return await owner("POST","/profiles",await payload(request))
    @router.post("/virtual",status_code=201)
    async def register(request:Request):return await owner("POST","",await payload(request))
    @router.get("/virtual/{id}")
    async def get(id:str):return await owner("GET","/"+quote(id,safe=""))
    @router.patch("/virtual/{id}")
    async def patch(id:str,request:Request):return await owner("PATCH","/"+quote(id,safe=""),await payload(request))
    @router.get("/virtual/{id}/history")
    async def history(id:str,after:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=500)):
        return await owner("GET","/"+quote(id,safe="")+f"/history?after={after}&limit={limit}")
    @router.post("/virtual/{id}/actions")
    async def action(id:str,request:Request):
        return await owner("POST","/"+quote(id,safe="")+"/actions",await payload(request),request.headers.get("idempotency-key"))
    return router
