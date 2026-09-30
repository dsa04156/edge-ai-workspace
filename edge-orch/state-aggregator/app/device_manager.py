"""Device Manager: source-owned inventory plus local, immutable profile bindings.

Only profile definitions and UID-bound references are written here. No device,
workload, EdgeX object or runtime lifecycle is created or changed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import sqlite3
import time
from datetime import datetime, timezone
from contextlib import contextmanager, nullcontext
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .common_runtime import RuntimeState, read_runtime_state
from .models import DeviceState, NodeSchedulingResource
from .profile_spec import observation, read_document, validate_document

logger = logging.getLogger(__name__)
NAME = r"^[a-z0-9][a-z0-9.-]{0,127}$"


def timestamp():
    return datetime.now(timezone.utc).isoformat()


class ProfileRef(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=NAME)
    version: str = Field(pattern=r"^[0-9]+\.[0-9]+$")


class BindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    nodeUid: str = Field(pattern=r"^[A-Za-z0-9-]{1,128}$")
    expectedRevision: int = Field(ge=0)
    profileRef: ProfileRef | None


class ProfileEditRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    nodeUid: str = Field(pattern=r"^[A-Za-z0-9-]{1,128}$")
    expectedRevision: int = Field(ge=0)
    document: dict


class ProfileBindings:
    """Not an inventory: only immutable definitions and references to source UIDs."""
    def __init__(self, path):
        self.path = Path(path)

    @contextmanager
    def connect(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript("""
            CREATE TABLE IF NOT EXISTS profiles (
                name TEXT, version TEXT, payload TEXT NOT NULL, digest TEXT NOT NULL,
                created_at TEXT NOT NULL, PRIMARY KEY(name,version));
            CREATE TABLE IF NOT EXISTS bindings (
                node_uid TEXT PRIMARY KEY, node_name TEXT NOT NULL,
                profile_name TEXT, profile_version TEXT, revision INTEGER NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(profile_name,profile_version) REFERENCES profiles(name,version));
        """)
        try:
            with db:
                yield db
        finally:
            db.close()

    def profiles(self):
        with self.connect() as db:
            return [{"document": json.loads(row["payload"]), "digest": row["digest"],
                     "createdAt": row["created_at"], "evidence": "operator-declared"}
                    for row in db.execute("SELECT * FROM profiles ORDER BY name,version")]

    def bindings(self):
        with self.connect() as db:
            return [{"nodeUid": r["node_uid"], "nodeName": r["node_name"], "revision": r["revision"],
                     "profileRef": {"name": r["profile_name"], "version": r["profile_version"]}
                     if r["profile_name"] else None, "updatedAt": r["updated_at"]}
                    for r in db.execute("SELECT * FROM bindings ORDER BY node_name,node_uid")]

    def save(self, document, connection=None):
        errors = validate_document(document)
        if errors or document.get("kind") != "DeviceProfile":
            raise HTTPException(422, errors or "DeviceProfile이 필요합니다.")
        payload = json.dumps(document, sort_keys=True, separators=(",", ":"), allow_nan=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        name, version = document["metadata"]["name"], document["metadata"]["version"]
        with (nullcontext(connection) if connection is not None else self.connect()) as db:
            if connection is None:
                db.execute("BEGIN IMMEDIATE")
            prior = db.execute("SELECT digest FROM profiles WHERE name=? AND version=?", (name, version)).fetchone()
            if prior and prior[0] != digest:
                raise HTTPException(409, "같은 버전의 내용은 변경할 수 없습니다. 새 버전으로 등록하세요.")
            if not prior:
                db.execute("INSERT INTO profiles VALUES(?,?,?,?,?)", (name, version, payload, digest, timestamp()))
        return {"profileRef": {"name": name, "version": version}, "digest": digest}

    def remove(self, name, version):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM bindings WHERE profile_name=? AND profile_version=?", (name, version)).fetchone():
                raise HTTPException(409, "장비에 연결된 Profile은 삭제할 수 없습니다. 먼저 연결을 해제하세요.")
            if not db.execute("DELETE FROM profiles WHERE name=? AND version=?", (name, version)).rowcount:
                raise HTTPException(404, "Profile 버전을 찾을 수 없습니다.")

    def bind(self, name, request, architecture=None, connection=None):
        ref = request.profileRef
        with (nullcontext(connection) if connection is not None else self.connect()) as db:
            if connection is None:
                db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM bindings WHERE node_uid=?", (request.nodeUid,)).fetchone()
            if (row["revision"] if row else 0) != request.expectedRevision or (row and row["node_name"] != name):
                raise HTTPException(409, "연결 정보가 변경되었습니다. 새로고침 후 다시 시도하세요.")
            if ref:
                profile = db.execute("SELECT payload FROM profiles WHERE name=? AND version=?", (ref.name, ref.version)).fetchone()
                if not profile:
                    raise HTTPException(404, "Profile 버전을 찾을 수 없습니다.")
                profile_arch = json.loads(profile[0])["spec"]["hardware"]["architecture"]
                if architecture and profile_arch and architecture != profile_arch:
                    raise HTTPException(409, "장비와 Profile의 architecture가 다릅니다.")
            db.execute("INSERT INTO bindings VALUES(?,?,?,?,?,?) ON CONFLICT(node_uid) DO UPDATE SET "
                       "profile_name=excluded.profile_name, profile_version=excluded.profile_version, "
                       "revision=excluded.revision, updated_at=excluded.updated_at",
                       (request.nodeUid, name, ref.name if ref else None, ref.version if ref else None,
                        request.expectedRevision + 1, timestamp()))
        return {"nodeUid": request.nodeUid, "revision": request.expectedRevision + 1,
                "profileRef": ref.model_dump() if ref else None}


class DeviceSources:
    def __init__(self, settings, service):
        self.settings, self.service = settings, service

    async def nodes(self):
        if not self.service.kube.enabled:
            raise RuntimeError("kubernetes_unavailable")
        raw = await asyncio.to_thread(self.service.kube.v1.list_node, _request_timeout=8)
        rows = []
        for node in raw.items:
            labels = node.metadata.labels or {}
            ready_status = next((c.status for c in node.status.conditions or [] if c.type == "Ready"), None)
            ready = {"True": True, "False": False}.get(ready_status)
            rows.append({"name": node.metadata.name, "uid": node.metadata.uid,
                         "architecture": labels.get("kubernetes.io/arch"), "ready": ready,
                         "nodeType": self.service.kube._determine_node_type(node),
                         "observedAt": timestamp(), "capacity": {
                             k: v for k, v in (node.status.capacity or {}).items() if k in {"cpu", "memory"}}})
        if any(not n["name"] or not n["uid"] for n in rows):
            raise ValueError("node_identity_missing")
        return sorted(rows, key=lambda r: r["name"])

    async def _remote(self, path):
        # Optional, explicit preview reader of the deployed aggregator. No proxy
        # path or origin is accepted from user input, no fallback/discovery.
        async with httpx.AsyncClient(timeout=18, trust_env=False, follow_redirects=False) as client:
            response = await client.get(self.settings.device_manager_read_base_url.rstrip("/") + path)
            response.raise_for_status()
            return response.json()

    async def resources(self):
        if self.settings.device_manager_read_base_url:
            return [NodeSchedulingResource.model_validate(r) for r in await self._remote("/api/resources")]
        return await self.service.get_scheduling_resources()

    async def sensors(self):
        if self.settings.device_manager_read_base_url:
            return [DeviceState.model_validate(r) for r in await self._remote("/state/devices")]
        return await self.service.get_devices()

    async def runtime(self):
        state = (RuntimeState.model_validate(await self._remote("/state/runtime-services"))
                 if self.settings.device_manager_read_base_url else await read_runtime_state(self.settings))
        if (state.observation_error or state.snapshot_age_seconds is None
                or not 0 <= state.snapshot_age_seconds < 15 or not 0 <= time.time() - state.observed_at < 15):
            raise ValueError("runtime_observation_unavailable")
        return state


def service_locations(runtime, now):
    locations = {}
    for item in runtime.services:
        if item.phase in {"Deleted", "Missing"}:
            continue
        current = (not item.observation_error and item.checkedAt is not None and 0 <= now - item.checkedAt < 15)
        for role, target in [("active", item.active), ("preparing", item.target), *[("retiring", r) for r in item.retiring]]:
            if target is None:
                continue
            locations.setdefault(target.node, []).append({"name": item.name, "uid": item.uid,
                "kind": item.serviceKind, "role": role, "phase": item.phase,
                "serving": bool(current and item.serving and role == "active"),
                "current": current, "observedAt": item.checkedAt})
    return locations


def create_device_manager_router(settings, service, *, store=None, sources=None):
    store = store or ProfileBindings(Path(settings.data_dir) / "device-profile-bindings.sqlite3")
    sources = sources or DeviceSources(settings, service)
    router = APIRouter(prefix="/api/v1/device-manager", tags=["Device Manager"])

    def mutation(request):
        if not settings.device_manager_enabled:
            raise HTTPException(403, "Profile 등록·연결 쓰기가 비활성입니다.")
        if (request.headers.get("origin") != str(request.base_url).rstrip("/")
                or request.headers.get("x-device-manager") != "1"
                or request.headers.get("content-type", "").split(";")[0] != "application/json"):
            raise HTTPException(403, "동일한 웹 화면에서 등록·연결 요청을 실행하세요.")

    @router.get("")
    async def inventory(response: Response):
        response.headers["Cache-Control"] = "no-store"
        async def collect(name, reader):
            try:
                return name, await asyncio.wait_for(reader(), timeout=20), None
            except Exception:
                logger.warning("Device Manager source unavailable: %s", name, exc_info=True)
                return name, None, "source_unavailable"
        results = await asyncio.gather(*(collect(k, getattr(sources, k)) for k in ("nodes", "resources", "sensors", "runtime")))
        values = {name: value for name, value, _ in results}
        errors = {name: error for name, _, error in results if error}
        states = {s["metadata"]["deviceId"]: s["status"] for s in observation(values["resources"] or [])["states"]}
        bindings = store.bindings()
        by_uid = {b["nodeUid"]: b for b in bindings}
        locations = service_locations(values["runtime"], time.time()) if values["runtime"] else {}
        nodes = [{**n, "binding": by_uid.get(n["uid"]), "runtimeState": states.get(n["name"]),
                  "services": locations.get(n["name"], []) if values["runtime"] else None}
                 for n in values["nodes"] or []]
        uids = {n["uid"] for n in nodes}
        return {"observedAt": timestamp(), "maxAgeSeconds": 60, "writable": settings.device_manager_enabled,
                "sourceErrors": errors, "nodes": nodes,
                "sensors": [s.model_dump(mode="json") for s in values["sensors"] or []],
                "profiles": store.profiles(),
                "detachedBindings": [{**b, "reason": "source_unavailable" if "nodes" in errors else "source_uid_missing"}
                                     for b in bindings if b["profileRef"] and b["nodeUid"] not in uids],
                "readMode": "deployed-aggregator-projection" if settings.device_manager_read_base_url else "direct-readers"}

    @router.post("/profiles")
    async def register_profile(request: Request):
        mutation(request)
        return store.save(await read_document(request))

    @router.delete("/profiles/{name}/{version}")
    async def delete_profile(name: str, version: str, request: Request):
        mutation(request)
        store.remove(name, version)
        return {"deleted": True}

    @router.put("/nodes/{name}/profile")
    async def bind_profile(name: str, request: Request):
        mutation(request)
        try:
            body = BindingRequest.model_validate(await read_document(request))
        except ValidationError:
            raise HTTPException(422, "nodeUid·profileRef·expectedRevision을 확인하세요.") from None
        architecture = None
        if body.profileRef is not None:
            try:
                nodes = await sources.nodes()
            except Exception:
                raise HTTPException(503, "현재 장비 원본을 확인할 수 없어 연결하지 않았습니다.") from None
            node = next((n for n in nodes if n["name"] == name and n["uid"] == body.nodeUid), None)
            if not node:
                raise HTTPException(409, "장비가 삭제·교체되었습니다. 새로고침 후 확인하세요.")
            architecture = node["architecture"]
        else:
            # Local reference removal is permitted even when the source is down.
            if not any(b["nodeUid"] == body.nodeUid and b["nodeName"] == name for b in store.bindings()):
                raise HTTPException(404, "해제할 Profile 연결이 없습니다.")
        return store.bind(name, body, architecture)

    @router.put("/nodes/{name}/profile-document")
    async def edit_profile(name: str, request: Request):
        mutation(request)
        try:
            body = ProfileEditRequest.model_validate(await read_document(request))
        except ValidationError:
            raise HTTPException(422, "장비와 Profile 수정 내용을 확인하세요.") from None
        try:
            nodes = await sources.nodes()
        except Exception:
            raise HTTPException(503, "현재 장비 원본을 확인할 수 없어 저장하지 않았습니다.") from None
        node = next((n for n in nodes if n["name"] == name and n["uid"] == body.nodeUid), None)
        if not node:
            raise HTTPException(409, "장비가 삭제·교체되었습니다. 새로고침 후 확인하세요.")
        with store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            saved = store.save(body.document, connection=db)
            binding = BindingRequest(nodeUid=body.nodeUid, expectedRevision=body.expectedRevision,
                                     profileRef=saved["profileRef"])
            result = store.bind(name, binding, node["architecture"], connection=db)
        return {**saved, **result}

    return router
