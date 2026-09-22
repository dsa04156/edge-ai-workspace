"""Durable logical devices; RuntimeService bindings are allocated only on demand.

Shares the existing single-writer runtime journal, Kubernetes adapter and controller.
An unallocated stopped device needs no Pod and no Kubernetes observation to exist.
"""
import asyncio
import copy
import hashlib
import json
import os
import uuid
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .contract import ServiceSpec, Variant
from .service_settings import definition_spec

ID = r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Profile(Contract):
    id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=100)
    architecture: Literal["amd64", "arm64"]
    requests: dict[str, str]
    limits: dict[str, str]
    executionSpec: dict | None = None
    templateServiceUid: str | None = Field(default=None, max_length=80)

    @model_validator(mode="after")
    def resources(self):
        # Reuse the runtime's positive quantity, request<=limit and GPU integer rules.
        Variant(name="profile", image="validation@sha256:"+"0"*64, architecture=self.architecture,
                backend="http", requests=self.requests, limits=self.limits, maxInFlight=1, qualification="unqualified")
        if self.executionSpec and self.templateServiceUid:
            raise ValueError("choose_execution_spec_or_template")
        return self


class Connection(Contract):
    kind: Literal["EdgeXDevice", "Node", "VirtualDevice"]
    targetId: str = Field(min_length=1, max_length=253)
    resource: str | None = Field(default=None, max_length=128)


class DeviceInput(Contract):
    id: str = Field(pattern=ID)
    name: str = Field(min_length=1, max_length=100)
    profileId: str = Field(pattern=ID)
    connections: list[Connection] = Field(default_factory=list, max_length=100)


class DevicePatch(Contract):
    expectedRevision: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=100)
    connections: list[Connection] = Field(default_factory=list, max_length=100)


class Action(Contract):
    action: Literal["start", "stop"]
    expectedRevision: int = Field(ge=1)


def profile_spec(profile):
    if not profile["executionSpec"]:
        return None
    raw = copy.deepcopy(profile["executionSpec"])
    validated = ServiceSpec.model_validate(raw)
    if validated.inference or validated.commonAI or any(v.resident for v in validated.variants):
        raise ValueError("resident_runtime_is_not_an_independent_virtual_device")
    variants = [v for v in raw["variants"] if v["architecture"] == profile["architecture"]]
    if not variants:
        raise ValueError("profile_architecture_not_in_service")
    raw.update(variants=variants, suspended=True)
    raw["policy"] = {**raw.get("policy", {}), "mode":"preferred", "approvalRequired":False, "stages":[], "latency":None}
    for v in variants:
        v.update(requests=profile["requests"], limits=profile["limits"])
    return definition_spec(raw)


class Registry:
    def __init__(self, controller, runner):
        self.c, self.runner = controller, runner
        self.db = controller.journal.db
        self.locks = {}
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS device_profiles(id TEXT PRIMARY KEY, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS logical_devices(id TEXT PRIMARY KEY, body TEXT NOT NULL);
          CREATE TABLE IF NOT EXISTS logical_device_events(seq INTEGER PRIMARY KEY, device_id TEXT, at REAL, event TEXT, body TEXT);
          CREATE INDEX IF NOT EXISTS logical_events_device ON logical_device_events(device_id,seq);
          CREATE TABLE IF NOT EXISTS logical_device_actions(device_id TEXT, id TEXT, fingerprint TEXT, body TEXT,
            PRIMARY KEY(device_id,id));
        """)
        # An interrupted dispatch is retained for explicit review, never replayed.
        with self.db:
            for device_id, key, body in self.db.execute("SELECT device_id,id,body FROM logical_device_actions").fetchall():
                value=json.loads(body)
                if value["status"] == "pending":
                    value.update(status="unknown", reason="engine_restarted_no_automatic_replay")
                    self.db.execute("UPDATE logical_device_actions SET body=? WHERE device_id=? AND id=?",
                                    (json.dumps(value),device_id,key))

    def profiles(self):
        return [json.loads(r[0]) for r in self.db.execute("SELECT body FROM device_profiles ORDER BY id")]

    def profile(self, id):
        row=self.db.execute("SELECT body FROM device_profiles WHERE id=?",(id,)).fetchone()
        if not row: raise HTTPException(404,"profile_not_found")
        return json.loads(row[0])

    def register_profile(self, body):
        value=body.model_dump()
        if body.templateServiceUid:
            if not self.runtime_current(): raise HTTPException(503,"runtime_snapshot_unavailable")
            matches=[r for r in self.c.snapshot["services"] if r["metadata"]["uid"]==body.templateServiceUid and not r["metadata"].get("deletionTimestamp")]
            if len(matches)!=1: raise HTTPException(409,"template_identity_changed")
            value["executionSpec"]=copy.deepcopy(matches[0]["spec"])
        try: value["executionSpec"]=profile_spec(value)
        except ValueError as exc: raise HTTPException(422,str(exc)[:200]) from None
        if self.db.execute("SELECT 1 FROM device_profiles WHERE id=?",(body.id,)).fetchone():
            if self.profile(body.id)==value: return value
            raise HTTPException(409,"profile_id_exists_immutable")
        with self.db:self.db.execute("INSERT INTO device_profiles VALUES (?,?)",(body.id,json.dumps(value)))
        return value

    def get(self, id):
        row=self.db.execute("SELECT body FROM logical_devices WHERE id=?",(id,)).fetchone()
        if not row: raise HTTPException(404,"logical_device_not_found")
        return json.loads(row[0])

    def store(self, d, event, detail=None):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO logical_devices VALUES (?,?)",(d["id"],json.dumps(d)))
            self.db.execute("INSERT INTO logical_device_events(device_id,at,event,body) VALUES (?,?,?,?)",
                            (d["id"],self.c.clock(),event,json.dumps(detail if detail is not None else d)))

    def validate_connections(self, id, connections):
        for link in connections:
            if link.kind=="VirtualDevice":
                if link.targetId==id: raise HTTPException(422,"self_connection_not_allowed")
                self.get(link.targetId)
        # Physical identities remain explicit configuration, not proof of EdgeX connectivity.

    def register(self, body):
        self.profile(body.profileId);self.validate_connections(body.id,body.connections)
        if self.db.execute("SELECT 1 FROM logical_devices WHERE id=?",(body.id,)).fetchone():
            old=self.get(body.id)
            if all(old[k]==v for k,v in body.model_dump().items()): return old
            raise HTTPException(409,"logical_device_id_exists")
        value=body.model_dump()|{"uid":str(uuid.uuid4()),"revision":1,"createdAt":self.c.clock(),
                                "binding":None,"desiredState":"stopped","lastActionAt":None,"lastObservation":None}
        self.store(value,"registered")
        return value

    def runtime_current(self):
        return bool(not self.c.stopping and self.c.snapshot and not self.c.last_error
                    and 0<=self.c.clock()-self.c.last_snapshot<15)

    def view(self, d):
        d=copy.deepcopy(d);binding=d["binding"];state="unknown";reason=None;locations=[]
        if binding is None:
            state="stopped"  # authoritative: this registry has never dispatched an allocation
        elif not self.runtime_current(): reason="runtime_snapshot_unavailable"
        else:
            matches=[r for r in self.c.snapshot["services"] if r["metadata"]["name"]==binding["name"]
                     and r["metadata"].get("annotations",{}).get("platform.jinuk.io/virtual-device-uid")==d["uid"]]
            if len(matches)!=1: reason="runtime_binding_missing"
            elif binding.get("uid") and matches[0]["metadata"]["uid"]!=binding["uid"]: reason="runtime_identity_changed"
            elif matches[0]["metadata"].get("deletionTimestamp"): reason="runtime_deleting"
            else:
                uid=matches[0]["metadata"]["uid"]
                s=self.c.states.get(uid,{})
                if not 0<=self.c.clock()-s.get("checkedAt",0)<15: reason="runtime_observation_stale"
                elif d.get("lastActionAt") and s.get("checkedAt",0)<d["lastActionAt"]:
                    state="starting" if d["desiredState"]=="running" else "stopping"
                elif s.get("observationError"): reason="runtime_observation_failed"
                elif s.get("phase")=="Suspended" and not any([s.get("active"),s.get("target"),s.get("retiring")]): state="stopped"
                else:
                    a=s.get("active") or {};obs=a.get("observation") or {};health=obs.get("health") or {}
                    if s.get("serving") and health.get("ready") and 0<=self.c.clock()-obs.get("at",0)<15:state="running"
                    elif s.get("phase") in {"Preparing","Starting","Reconciling"}:state="starting"
                    elif s.get("phase")=="Draining":state="stopping"
                    elif s.get("phase")=="Blocked":state="blocked"
                    else:reason="runtime_readiness_unconfirmed"
                if state!="unknown":
                    for role, targets in [("active",[s.get("active")]),("preparing",[s.get("target")]),("retiring",s.get("retiring",[]))]:
                        locations.extend({"role":role,"node":t.get("node"),"revision":t.get("name")} for t in targets if t)
        observation={"state":state,"reason":reason,"locations":locations}
        if d.get("lastObservation")!=observation:
            d["lastObservation"]=observation;self.store(d,"observation_changed",observation)
        return d|observation|{"kind":"virtual","stateQueryable":state!="unknown","observedAt":self.c.clock(),
                             "profile":self.profile(d["profileId"]),"connectionState":"configured_unverified" if d["connections"] else "not_configured"}

    def list(self):
        rows=[self.view(json.loads(r[0])) for r in self.db.execute("SELECT body FROM logical_devices ORDER BY id").fetchall()]
        counts={"registered":len(rows),"stateQueryable":sum(r["stateQueryable"] for r in rows)}
        counts.update({k:sum(r["state"]==k for r in rows) for k in ["running","stopped","unknown"]})
        counts["other"]=len(rows)-counts["running"]-counts["stopped"]-counts["unknown"]
        return {"schemaVersion":"edgeai.logical-devices/v1","observedAt":self.c.clock(),"maxAgeSeconds":15,
                "summary":counts,"devices":rows,"profiles":self.profiles()}

    def patch(self, id, body):
        d=self.get(id)
        if d["revision"]!=body.expectedRevision:raise HTTPException(409,"logical_device_revision_changed")
        self.validate_connections(id,body.connections)
        d.update(name=body.name,connections=[x.model_dump() for x in body.connections],revision=d["revision"]+1)
        self.store(d,"configuration_changed");return self.view(d)

    def history(self,id,after=0,limit=100):
        self.get(id)
        rows=self.db.execute("SELECT seq,at,event,body FROM logical_device_events WHERE device_id=? AND seq>? ORDER BY seq LIMIT ?",(id,after,limit)).fetchall()
        return [{"seq":r[0],"at":r[1],"event":r[2],"detail":json.loads(r[3])} for r in rows]

    async def execute(self,id,body,key):
        async with self.locks.setdefault(id,asyncio.Lock()):
            fingerprint=hashlib.sha256(body.model_dump_json().encode()).hexdigest()
            old=self.db.execute("SELECT fingerprint,body FROM logical_device_actions WHERE device_id=? AND id=?",(id,key)).fetchone()
            if old:
                if old[0]!=fingerprint:raise HTTPException(409,"idempotency_key_payload_conflict")
                return json.loads(old[1])
            d=self.get(id)
            if d["revision"]!=body.expectedRevision:raise HTTPException(409,"logical_device_revision_changed")
            if body.action=="start" and not self.profile(d["profileId"])["executionSpec"]:
                raise HTTPException(409,"profile_has_no_execution_contract")
            result={"id":key,"deviceId":id,"action":body.action,"status":"pending","at":self.c.clock()}
            with self.db:self.db.execute("INSERT INTO logical_device_actions VALUES (?,?,?,?)",(id,key,fingerprint,json.dumps(result)))
            sent=False
            try:
                if d["binding"] is not None or body.action=="start":
                    async with self.c.reconcile_lock:
                        if not self.runtime_current():raise HTTPException(503,"runtime_snapshot_unavailable")
                        if d["binding"] is None:
                            d["binding"]={"name":"vd-"+uuid.UUID(d["uid"]).hex,"uid":None}
                            self.store(d,"allocation_requested")
                        ref=d["binding"]
                        if not ref["uid"]:
                            if body.action=="stop":
                                matches=[r for r in self.c.snapshot["services"] if r["metadata"]["name"]==ref["name"]
                                         and r["metadata"].get("annotations",{}).get("platform.jinuk.io/virtual-device-uid")==d["uid"]
                                         and not r["metadata"].get("deletionTimestamp")]
                                if len(matches)!=1:raise HTTPException(409,"allocation_outcome_unconfirmed")
                                resource=matches[0]
                            else:
                                sent=True
                                resource=await asyncio.to_thread(self.c.kube.register_logical_runtime,ref["name"],
                                                                self.profile(d["profileId"])["executionSpec"],d["uid"])
                            ref["uid"]=resource["metadata"]["uid"]
                            self.c.snapshot["services"]=[r for r in self.c.snapshot["services"] if r["metadata"]["name"]!=ref["name"]]+[resource]
                            self.store(d,"runtime_bound")
                        sent=True
                        resource=await asyncio.to_thread(self.c.kube.set_suspended,ref["name"],ref["uid"],body.action=="stop")
                        self.c.snapshot["services"]=[resource if r["metadata"]["uid"]==ref["uid"] else r for r in self.c.snapshot["services"]]
                        if body.action=="stop":self.runner.stop_runs(ref["uid"])
                d.update(desiredState="running" if body.action=="start" else "stopped",lastActionAt=self.c.clock(),revision=d["revision"]+1)
                self.store(d,"control_accepted",result)
                result.update(status="accepted",revision=d["revision"])
            except (Exception, asyncio.CancelledError) as exc:
                result.update(status="unknown" if sent else "rejected",reason=str(exc.detail) if isinstance(exc,HTTPException) else type(exc).__name__)
                self.store(d,"control_"+result["status"],result)
                if isinstance(exc,asyncio.CancelledError):
                    with self.db:self.db.execute("UPDATE logical_device_actions SET body=? WHERE device_id=? AND id=?",(json.dumps(result),id,key))
                    raise
            with self.db:self.db.execute("UPDATE logical_device_actions SET body=? WHERE device_id=? AND id=?",(json.dumps(result),id,key))
            return result


def router(app):
    routes=APIRouter(prefix="/logical-devices")
    def registry():
        if not hasattr(app.state,"logical_registry"):
            app.state.logical_registry=Registry(app.state.controller,app.state.demo_runner)
        return app.state.logical_registry
    def enabled():
        if os.getenv("LOGICAL_DEVICE_MANAGEMENT_ENABLED","false").lower()!="true":raise HTTPException(403,"logical_device_management_disabled")
    @routes.get("")
    async def listing():return registry().list()
    @routes.post("/profiles",status_code=201)
    async def profile(body:Profile):enabled();return registry().register_profile(body)
    @routes.post("",status_code=201)
    async def register(body:DeviceInput):enabled();return registry().view(registry().register(body))
    @routes.get("/{id}")
    async def get(id:str):return registry().view(registry().get(id))
    @routes.patch("/{id}")
    async def patch(id:str,body:DevicePatch):
        enabled();r=registry()
        async with r.locks.setdefault(id,asyncio.Lock()):return r.patch(id,body)
    @routes.get("/{id}/history")
    async def history(id:str,after:int=Query(0,ge=0),limit:int=Query(100,ge=1,le=500)):
        return {"events":registry().history(id,after,limit)}
    @routes.post("/{id}/actions")
    async def control(id:str,body:Action,idempotency_key:str=Header(alias="Idempotency-Key")):
        enabled()
        try:key=str(uuid.UUID(idempotency_key))
        except ValueError:raise HTTPException(422,"uuid_idempotency_key_required") from None
        return await registry().execute(id,body,key)
    return routes
