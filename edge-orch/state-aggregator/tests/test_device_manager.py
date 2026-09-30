import asyncio
import copy
import time
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.common_runtime import RuntimeState
from app.device_manager import BindingRequest, DeviceSources, ProfileBindings, create_device_manager_router, service_locations
from app.profile_spec import BUNDLE
from app.models import DeviceState, NodeSchedulingResource, SchedulingResourceAmounts


class Sources:
    uid = "node-uid-one"
    node_error = False
    sensor_error = False
    runtime_error = False

    async def nodes(self):
        if self.node_error: raise RuntimeError("node reader failed")
        return [{"name":"edge-001", "uid":self.uid, "architecture":"arm64", "nodeType":"edge_ai_device",
                 "ready":True, "capacity":{"cpu":"6","memory":"8Gi"}, "observedAt":datetime.now(timezone.utc).isoformat()}]

    async def resources(self):
        amount = SchedulingResourceAmounts(cpu_cores=4, memory_bytes=4*1024**3)
        return [NodeSchedulingResource(node="edge-001",kubernetes_ready=True,cpu_available=4,memoryAvailableGB=4,
            health="healthy",schedulable=True,architecture="arm64",allocatable=amount,available=amount,
            requested=SchedulingResourceAmounts(cpu_cores=0,memory_bytes=0))]

    async def sensors(self):
        if self.sensor_error: raise RuntimeError("sensor reader failed")
        return [DeviceState(name="sensor-001-temperature",profile_name="edgex-temperature-v1",device_service_name="serial",
            physical_device_id="sensor-001",admin_state="UNLOCKED",operating_state="UP")]

    async def runtime(self):
        if self.runtime_error: raise RuntimeError("runtime reader failed")
        return RuntimeState(observed_at=time.time(),snapshot_age_seconds=0,services=[])


@pytest.fixture
def context(tmp_path):
    store = ProfileBindings(tmp_path / "manager.sqlite3")
    sources = Sources()
    settings = SimpleNamespace(device_manager_enabled=True,device_manager_read_base_url="",data_dir=tmp_path)
    app = FastAPI()
    app.include_router(create_device_manager_router(settings,None,store=store,sources=sources))
    return TestClient(app),store,sources,settings


HEADERS={"Origin":"http://testserver","X-Device-Manager":"1","Content-Type":"application/json"}
BASE="/api/v1/device-manager"


def test_unknown_node_ready_is_not_reported_as_false():
    nodes = [SimpleNamespace(metadata=SimpleNamespace(name=f"node-{status}", uid=status,
             labels={"kubernetes.io/arch":"arm64"}), status=SimpleNamespace(capacity={},
             conditions=[SimpleNamespace(type="Ready",status=status)])) for status in ["True","False","Unknown"]]
    kube = SimpleNamespace(enabled=True,v1=SimpleNamespace(list_node=lambda **kwargs:SimpleNamespace(items=nodes)),
                           _determine_node_type=lambda node:"edge_ai_device")
    rows = asyncio.run(DeviceSources(None,SimpleNamespace(kube=kube)).nodes())
    assert {row["uid"]:row["ready"] for row in rows} == {"True":True,"False":False,"Unknown":None}


def profile():
    doc=copy.deepcopy(BUNDLE["examples"]["DeviceProfile"])
    doc["metadata"]["name"]="test-arm64"
    return doc


def put(client, ref, revision=0, uid="node-uid-one"):
    return client.put(BASE+"/nodes/edge-001/profile",json={"nodeUid":uid,"expectedRevision":revision,"profileRef":ref},headers=HEADERS)


def test_profiles_are_immutable_and_persist_across_store_instances(context):
    client,store,_,_=context
    doc=profile()
    assert client.post(BASE+"/profiles",json=doc,headers=HEADERS).status_code==200
    assert client.post(BASE+"/profiles",json=doc,headers=HEADERS).status_code==200
    doc["spec"]["hardware"]["cpu"]["cores"]=4
    assert client.post(BASE+"/profiles",json=doc,headers=HEADERS).status_code==409
    doc["metadata"]["version"]="1.1"
    assert client.post(BASE+"/profiles",json=doc,headers=HEADERS).status_code==200
    reopened=ProfileBindings(store.path)
    assert len(reopened.profiles())==2
    assert reopened.profiles()[0]["document"]["spec"]["hardware"]["cpu"]["cores"]==6


def test_bind_unbind_and_referenced_version_deletion(context):
    client,store,_,_=context
    doc=profile();store.save(doc)
    assert put(client,doc["metadata"]).status_code==200
    assert client.delete(BASE+"/profiles/test-arm64/1.0",headers=HEADERS).status_code==409
    row=client.get(BASE).json()["nodes"][0]
    assert row["binding"]["profileRef"]==doc["metadata"]
    assert row["services"]==[]
    assert put(client,None,1).status_code==200
    assert client.delete(BASE+"/profiles/test-arm64/1.0",headers=HEADERS).status_code==200
    assert not store.profiles()


def test_stale_binding_revisions_do_not_overwrite(context):
    client,store,_,_=context;doc=profile();store.save(doc)
    assert put(client,doc["metadata"]).status_code==200
    assert put(client,None,0).status_code==409
    assert put(client,None,1).status_code==200
    assert put(client,doc["metadata"],0).status_code==409
    assert store.bindings()[0]["profileRef"] is None


def test_name_reuse_never_transfers_uid_binding(context):
    client,store,sources,_=context;doc=profile();store.save(doc)
    assert put(client,doc["metadata"]).status_code==200
    sources.uid="replacement-uid"
    assert put(client,doc["metadata"],1).status_code==409
    state=client.get(BASE).json()
    assert state["nodes"][0]["binding"] is None
    assert state["detachedBindings"][0]["reason"]=="source_uid_missing"
    assert put(client,None,1).status_code==200


def test_partial_failure_does_not_turn_into_empty_healthy_inventory(context):
    client,store,sources,_=context;doc=profile();store.save(doc);put(client,doc["metadata"])
    sources.sensor_error=True;sources.runtime_error=True
    state=client.get(BASE).json()
    assert set(state["sourceErrors"])=={"sensors","runtime"}
    assert state["nodes"][0]["services"] is None
    sources.node_error=True
    assert put(client,doc["metadata"],1).status_code==503
    state=client.get(BASE).json()
    assert state["detachedBindings"][0]["reason"]=="source_unavailable"
    assert put(client,None,1).status_code==200


def test_profile_and_architecture_must_exist(context):
    client,store,_,_=context
    assert put(client,{"name":"missing","version":"1.0"}).status_code==404
    doc=profile();doc["spec"]["hardware"]["architecture"]="amd64";store.save(doc)
    assert put(client,doc["metadata"]).status_code==409
    assert not store.bindings()


@pytest.mark.parametrize("bad", [None,[],{"kind":[]},BUNDLE["examples"]["ServiceProfile"]])
def test_only_valid_device_profiles_are_registered(context,bad):
    import json
    client,store,_,_=context
    assert client.post(BASE+"/profiles",content=json.dumps(bad),headers=HEADERS).status_code==422
    assert store.profiles()==[]


def test_write_gate_and_same_origin(context):
    client,_,_,settings=context
    assert client.post(BASE+"/profiles",json=profile()).status_code==403
    assert client.post(BASE+"/profiles",json=profile(),headers={**HEADERS,"Origin":"http://other"}).status_code==403
    settings.device_manager_enabled=False
    assert client.post(BASE+"/profiles",json=profile(),headers=HEADERS).status_code==403
    assert client.get(BASE).json()["writable"] is False


def test_sensors_keep_edgex_identity_and_native_profile(context):
    state=context[0].get(BASE).json()
    assert state["sensors"][0]["profile_name"]=="edgex-temperature-v1"
    assert state["sensors"][0]["physical_device_id"]=="sensor-001"
    assert len(state["nodes"])==1
    assert not state["profiles"]


def test_services_preserve_active_preparing_retiring_and_stale_roles():
    now=time.time()
    def target(node):return {"name":node,"node":node,"role":"edge","variant":"arm64","capacity":1}
    state=RuntimeState.model_validate({"observed_at":now,"snapshot_age_seconds":0,"services":[{
        "name":"model","uid":"service-uid","phase":"Running","serving":True,"checkedAt":now,
        "active":target("a"),"target":target("b"),"retiring":[target("c")]}]})
    rows=service_locations(state,now)
    assert rows["a"][0]["serving"] is True
    assert rows["b"][0]["role"]=="preparing" and rows["b"][0]["serving"] is False
    assert rows["c"][0]["role"]=="retiring"
    assert service_locations(state,now+16)["a"][0]["current"] is False


def test_inline_edit_atomically_saves_profile_and_binds(context):
    client,store,_,_=context
    doc=profile()
    payload={"nodeUid":"node-uid-one","expectedRevision":0,"document":doc}
    route=BASE+"/nodes/edge-001/profile-document"
    assert client.put(route,json=payload,headers=HEADERS).status_code==200
    assert store.bindings()[0]["profileRef"]==doc["metadata"]
    doc["metadata"]["version"]="1.1"
    # Stale revision rolls back the newly inserted profile as well.
    assert client.put(route,json=payload,headers=HEADERS).status_code==409
    assert len(store.profiles())==1
    payload["expectedRevision"]=1
    assert client.put(route,json=payload,headers=HEADERS).status_code==200
    assert store.bindings()[0]["profileRef"]["version"]=="1.1"
    assert len(store.profiles())==2


def test_inline_edit_rolls_back_architecture_mismatch_and_rejects_replaced_uid(context):
    client,store,sources,_=context
    doc=profile();doc["spec"]["hardware"]["architecture"]="amd64"
    route=BASE+"/nodes/edge-001/profile-document"
    payload={"nodeUid":"node-uid-one","expectedRevision":0,"document":doc}
    assert client.put(route,json=payload,headers=HEADERS).status_code==409
    assert store.profiles()==[]
    sources.uid="replacement"
    assert client.put(route,json=payload,headers=HEADERS).status_code==409
    assert store.profiles()==[]
