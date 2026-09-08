"""One approved virtual-device lifecycle, with durable request receipts and no replay."""
from __future__ import annotations

import asyncio
import fcntl
import hashlib
import hmac
import ipaddress
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from .virtual_resource_registry import ID_LABEL, VirtualDeviceRegistry
from .virtual_device_test_access import verify as verify_test_access
from .virtual_resources import KubernetesVirtualDeviceReader, VirtualDeviceObserver, utcnow

DEVICE_ID = "vd-demo-001"
NAMESPACE = "virtual-device-test"
IMAGE = "192.168.0.56:5000/virtual-device-runtime@sha256:e752b4e791796e908ba892572cf901aff5cf8646b6e075b6cb6a1971e2704315"


class Action(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["start", "stop", "infer"]
    features: list[Annotated[float, Field(strict=True, ge=0, le=30, allow_inf_nan=False)]] | None = Field(default=None, min_length=4, max_length=4)


class ControlError(Exception):
    pass


class Journal:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS operations (
                id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, action TEXT NOT NULL,
                state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                evidence TEXT NOT NULL)""")

    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        return db

    @staticmethod
    def decode(row):
        if row is None:
            return None
        return {"id": row["id"], "action": row["action"], "state": row["state"],
                "createdAt": row["created_at"], "updatedAt": row["updated_at"],
                "evidence": json.loads(row["evidence"]), "fingerprint": row["fingerprint"]}

    def get(self, key):
        with self.connect() as db:
            return self.decode(db.execute("SELECT * FROM operations WHERE id=?", (key,)).fetchone())

    def history(self):
        with self.connect() as db:
            return [self.decode(r) for r in db.execute("SELECT * FROM operations ORDER BY rowid DESC LIMIT 30")]

    def create(self, key, fingerprint, action):
        with self.connect() as db:
            db.execute("INSERT INTO operations VALUES (?,?,?,?,?,?,?)", (key, fingerprint, action, "running", utcnow(), utcnow(), "{}"))

    def finish(self, key, state, evidence):
        with self.connect() as db:
            db.execute("UPDATE operations SET state=?,updated_at=?,evidence=? WHERE id=?", (state, utcnow(), json.dumps(evidence, allow_nan=False), key))
        return self.get(key)

    def recover_interrupted(self):
        # Called only while holding the process-shared action lock. Never replay requests.
        with self.connect() as db:
            db.execute("UPDATE operations SET state='unknown',updated_at=?,evidence=? WHERE state='running'",
                       (utcnow(), json.dumps({"reason": "worker_interrupted_no_automatic_replay"})))


class Controller:
    def __init__(self, kube, journal: Journal):
        self.reader = KubernetesVirtualDeviceReader(kube)
        self.observer = VirtualDeviceObserver(self.reader)
        self.journal = journal

    def history(self):
        with open(str(self.journal.path) + ".lock", "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return self.journal.history()
            self.journal.recover_interrupted()
            return self.journal.history()

    def definition(self):
        item = next((r for r in VirtualDeviceRegistry.load().resources if r.metadata.name == DEVICE_ID), None)
        if not item or item.spec.runtimeRef.namespace != NAMESPACE or not item.spec.runtimeRef.workloadRef or item.spec.runtimeRef.workloadRef.name != DEVICE_ID or item.spec.runtimeRef.port != 8080:
            raise ControlError("approved_definition_missing")
        if item.spec.model != {"id": "iris-centroid", "version": "1.0.0"}:
            raise ControlError("approved_model_mismatch")
        return item

    async def deployment(self, definition):
        d = await self.reader.read(self.reader.kube.apps.read_namespaced_deployment, namespace=NAMESPACE, name=DEVICE_ID)
        if d.metadata.deletion_timestamp or (d.metadata.labels or {}).get(ID_LABEL) != DEVICE_ID:
            raise ControlError("workload_identity_mismatch")
        template = d.spec.template
        if (template.metadata.labels or {}).get(ID_LABEL) != DEVICE_ID or len(template.spec.containers) != 1 or template.spec.containers[0].image != IMAGE:
            raise ControlError("workload_contract_changed")
        if template.spec.node_selector != definition.spec.nodeSelector or d.spec.replicas not in (0, 1):
            raise ControlError("workload_placement_or_replica_changed")
        return d

    async def observe(self, definition):
        return await self.observer.observe_one(definition, [])

    async def infer(self, definition, row, operation_id, features):
        if row["executionState"] != "ready" or len(row["instances"]) != 1 or row["desiredReplicas"] != 1:
            raise ControlError("model_not_ready")
        pod = row["instances"][0]
        address = ipaddress.ip_address(pod["podIp"])
        host = f"[{address}]" if address.version == 6 else str(address)
        request_id = "nexus-" + operation_id
        body = {"requestId": request_id, "clientId": "nexus-dashboard", "features": features}
        async with httpx.AsyncClient(timeout=10, trust_env=False, follow_redirects=False) as client:
            response = await client.post(f"http://{host}:8080/infer", json=body)
            response.raise_for_status()
            result = response.json()
        expected = {"virtualDeviceId": DEVICE_ID, "podUid": pod["podUid"], "bootId": pod["runtime"]["bootId"],
                    "requestId": request_id, "clientId": "nexus-dashboard", "model": pod["runtime"]["model"],
                    "inputSha256": hashlib.sha256(json.dumps(features, separators=(",", ":")).encode()).hexdigest()}
        if any(result.get(k) != v for k, v in expected.items()) or not isinstance(result.get("result"), dict) or not result.get("completedAt"):
            raise ControlError("inference_receipt_identity_mismatch")
        return result

    async def execute(self, action: Action, key: str):
        fingerprint = hashlib.sha256(action.model_dump_json().encode()).hexdigest()
        # Cross-process lock also protects a request that outlives its browser connection.
        with open(str(self.journal.path) + ".lock", "a") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                old = self.journal.get(key)
                if old and old["fingerprint"] == fingerprint:
                    return old
                raise HTTPException(409, "virtual_device_action_in_progress")
            self.journal.recover_interrupted()
            old = self.journal.get(key)
            if old:
                if old["fingerprint"] != fingerprint:
                    raise HTTPException(409, "idempotency_key_payload_conflict")
                return old
            self.journal.create(key, fingerprint, action.action)
            sent = False
            try:
                definition = self.definition()
                deployment = await self.deployment(definition)
                row = await self.observe(definition)
                if row["observationError"] or row.get("workloadUid") != deployment.metadata.uid:
                    raise ControlError("workload_observation_unavailable")
                if action.action == "infer":
                    if row["executionState"] != "ready" or len(row["instances"]) != 1:
                        raise ControlError("model_not_ready")
                    sent = True
                    result = await self.infer(definition, row, key, action.features)
                    return self.journal.finish(key, "succeeded", {"result": result})
                desired = 1 if action.action == "start" else 0
                if row["desiredReplicas"] != desired:
                    scale = await self.reader.read(self.reader.kube.apps.read_namespaced_deployment_scale, namespace=NAMESPACE, name=DEVICE_ID)
                    if scale.metadata.uid != deployment.metadata.uid or scale.metadata.resource_version != deployment.metadata.resource_version:
                        raise ControlError("workload_replaced")
                    sent = True
                    await self.reader.read(self.reader.kube.apps.replace_namespaced_deployment_scale,
                        namespace=NAMESPACE, name=DEVICE_ID, body={"apiVersion": "autoscaling/v1", "kind": "Scale",
                        "metadata": {"name": DEVICE_ID, "namespace": NAMESPACE, "uid": scale.metadata.uid,
                                     "resourceVersion": scale.metadata.resource_version}, "spec": {"replicas": desired}})
                return self.journal.finish(key, "accepted", {"desiredReplicas": desired, "workloadUid": deployment.metadata.uid,
                    "message": "요청 접수 · 실제 준비/종료는 관측 상태를 확인하세요."})
            except asyncio.CancelledError:
                self.journal.finish(key, "unknown", {"reason": "request_interrupted_no_automatic_replay"})
                raise
            except Exception as exc:
                # A timeout after dispatch may have executed; never claim failure or replay it.
                return self.journal.finish(key, "unknown" if sent else "rejected", {"reason": str(exc)[:200] if isinstance(exc, ControlError) else type(exc).__name__})


def create_virtual_device_control_router(kube, settings, controller=None):
    router = APIRouter(prefix="/api/virtual-devices", tags=["virtual-device-control"])
    enabled = settings.virtual_device_control_enabled
    # Do not create a database on a disabled read-only deployment.
    instance = controller
    if enabled and instance is None:
        instance = Controller(kube, Journal(Path(settings.data_dir) / "virtual-device-operations.sqlite3"))

    def target(device_id):
        if device_id != DEVICE_ID:
            raise HTTPException(404, "virtual_device_control_target_not_found")

    @router.get("/{device_id}/control")
    async def control(device_id: str):
        target(device_id)
        return {"enabled": bool(enabled and settings.execution_management_token), "requiresToken": True,
                "actions": ["start", "infer", "stop"], "clientId": "nexus-dashboard",
                "registration": "git", "history": instance.history() if instance else []}

    @router.post("/{device_id}/actions")
    async def perform(device_id: str, body: Action, request: Request,
                      token: str | None = Header(default=None, alias="X-Execution-Token"),
                      key: str | None = Header(default=None, alias="Idempotency-Key")):
        target(device_id)
        if not enabled or not settings.execution_management_token:
            raise HTTPException(404, "virtual_device_control_disabled")
        if not token or not (hmac.compare_digest(token.encode(), settings.execution_management_token.encode())
                             or verify_test_access(token, settings.execution_management_token)):
            raise HTTPException(403, "execution_authentication_failed")
        origin = request.headers.get("origin")
        if origin and origin != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "cross_origin_action_denied")
        try:
            key = str(uuid.UUID(key or ""))
        except ValueError:
            raise HTTPException(400, "UUID Idempotency-Key required")
        if (body.action == "infer") != (body.features is not None):
            raise HTTPException(422, "four_features_required_only_for_infer")
        return await instance.execute(body, key)

    return router
