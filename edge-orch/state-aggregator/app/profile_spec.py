"""Draft Profile v1 validation and read-only observation. No registry or executor."""
from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response
from jsonschema import Draft202012Validator, FormatChecker

BUNDLE = json.loads((Path(__file__).parent / "config/profile_spec_v1.json").read_text())
VALIDATORS = {kind: Draft202012Validator(schema, format_checker=FormatChecker())
              for kind, schema in BUNDLE["schemas"].items()}
MAX_BODY = 64 * 1024
MAX_AGE_SECONDS = 60
logger = logging.getLogger(__name__)


def quantity(value):
    return Decimal(value[:-2]) * (1024 ** (1 + ["Ki", "Mi", "Gi", "Ti"].index(value[-2:])))


def validate_document(document):
    kind = document.get("kind") if isinstance(document, dict) else None
    if not isinstance(kind, str) or kind not in VALIDATORS:
        return [{"path": "/kind", "message": "지원하는 네 가지 kind 중 하나를 지정하세요."}]
    errors = [{"path": "/" + "/".join(map(str, e.absolute_path)), "message": e.message}
              for e in VALIDATORS[kind].iter_errors(document)]
    if errors:
        return errors[:50]
    spec = document.get("spec", {})
    levels = spec.get("resources", {})
    available = [(name, levels[name]) for name in ("minimum", "recommended", "maximum")
                 if levels.get(name) is not None]
    for (low_name, low), (high_name, high) in zip(available, available[1:]):
        for group, field, parse in [("cpu", "cores", Decimal), ("memory", "capacity", quantity),
                                    ("accelerator", "memory", quantity), ("network", "bandwidthMbps", Decimal)]:
            left, right = low.get(group, {}).get(field), high.get(group, {}).get(field)
            if left is not None and right is None:
                errors.append({"path": f"/spec/resources/{high_name}/{group}/{field}",
                               "message": f"{low_name}에 정의한 자원은 {high_name}에도 명시하세요."})
            if left is not None and right is not None and parse(left) > parse(right):
                errors.append({"path": f"/spec/resources/{high_name}/{group}/{field}",
                               "message": f"{high_name}은 {low_name}보다 작을 수 없습니다."})
    for level, value in available:
        for group, field in [("memory", "capacity"), ("accelerator", "memory")]:
            raw = value.get(group, {}).get(field)
            if raw is not None and quantity(raw) <= 0:
                errors.append({"path": f"/spec/resources/{level}/{group}/{field}",
                               "message": "요구 메모리는 0보다 커야 합니다."})
    latency = spec.get("qos", {}).get("latency")
    if latency and latency["targetMs"] > latency["maximumMs"]:
        errors.append({"path": "/spec/qos/latency", "message": "목표 지연은 최대 지연 이하여야 합니다."})
    variants = spec.get("runtime", {}).get("variants", [])
    if len({v["name"] for v in variants}) != len(variants):
        errors.append({"path": "/spec/runtime/variants", "message": "variant 이름이 중복됩니다."})
    if levels.get("minimum", {}).get("accelerator") and any(v["accelerator"] is None for v in variants):
        errors.append({"path": "/spec/runtime/variants", "message": "가속기 최소 요구량이 있으면 각 variant에 가속기 조건이 필요합니다."})
    return errors


def observation(resources, *, now=None):
    """Allocatable is NOT physical capacity; missing hardware remains unknown."""
    now = now or datetime.now(timezone.utc)
    profiles, devices, states = {}, [], []
    for resource in resources:
        architecture = resource.architecture if resource.architecture in ("arm64", "amd64") else None
        spec = {"deviceClass": "compute-node", "type": "unknown",
                "hardware": {"architecture": architecture, "cpu": {"cores": None},
                             "memory": {"capacity": None}, "accelerators": None},
                "runtime": {"frameworks": None, "backends": None},
                "capabilities": None, "communication": {"protocols": None}}
        # Shared observed capability shape, not a new named profile per instance.
        name = "observed-" + hashlib.sha256(json.dumps(spec, sort_keys=True).encode()).hexdigest()[:16]
        ref = {"name": name, "version": "1.0"}
        profiles[name] = {"apiVersion": "edgeai.etri/v1", "kind": "DeviceProfile",
                          "metadata": ref, "spec": spec}
        devices.append({"id": resource.node, "profileRef": ref, "registered": False,
                        "source": "kubernetes", "unknown": ["hardware_capacity", "runtime_support", "model_qualification"]})
        u = resource.utilization
        timestamp = u.observed_at if u else None
        age = (now - timestamp).total_seconds() if timestamp and timestamp.tzinfo else None
        fresh = age is not None and 0 <= age <= MAX_AGE_SECONDS
        utilization = None
        if fresh:
            utilization = {"source": "prometheus", "observedAt": timestamp.isoformat(),
                           "cpuRatio": u.cpu_ratio, "memoryRatio": u.memory_ratio, "gpuRatio": u.gpu_ratio}
        reasons = list(resource.reason_codes)
        if not fresh:
            reasons.append("utilization_stale_or_unreported")
        states.append({"apiVersion": "edgeai.etri/v1", "kind": "RuntimeState",
                       "metadata": {"deviceId": resource.node, "profileRef": ref},
                       "status": {"phase": "Ready" if resource.kubernetes_ready is True else
                                  "NotReady" if resource.kubernetes_ready is False else "Unknown",
                                  "observedAt": now.isoformat(),
                                  "reservation": {"source": "kubernetes-pod-requests",
                                                  "capacitySource": "kubernetes-allocatable",
                                                  **{key: getattr(resource, key).model_dump(by_alias=True)
                                                     for key in ("allocatable", "requested", "available")}},
                                  "utilization": utilization, "reasonCodes": list(dict.fromkeys(reasons))}})
    return {"observedAt": now.isoformat(), "source": "kubernetes+prometheus",
            "observationError": None, "profiles": list(profiles.values()), "devices": devices,
            "states": states, "registered": False, "maxAgeSeconds": MAX_AGE_SECONDS}


def compare(document, observed):
    """Explain known constraints only. Never grants execution/automatic placement."""
    spec = document["spec"]
    minimum = spec["resources"]["minimum"]
    profiles = {p["metadata"]["name"]: p for p in observed["profiles"]}
    devices = {d["id"]: d for d in observed["devices"]}
    results = []
    for state in observed["states"]:
        node = state["metadata"]["deviceId"]
        profile = profiles[devices[node]["profileRef"]["name"]]
        architecture = profile["spec"]["hardware"]["architecture"]
        reasons, unknown = [], ["runtime_model_qualification_unverified"]
        if any(v["accelerator"] is not None for v in spec["runtime"]["variants"]):
            unknown.append("accelerator_capability_unverified")
        if minimum.get("network"):
            unknown.append("network_capacity_unreported")
        if architecture is None:
            unknown.append("architecture_unreported")
        elif not any(v["architecture"] == architecture for v in spec["runtime"]["variants"]):
            reasons.append("architecture_mismatch")
        status = state["status"]
        if "node_unschedulable" in status["reasonCodes"]:
            reasons.append("node_unschedulable")
        if status["phase"] == "NotReady":
            reasons.append("node_not_ready")
        elif status["phase"] == "Unknown":
            unknown.append("node_readiness_unreported")
        available = status["reservation"]["available"]
        if available["cpuCores"] < minimum["cpu"]["cores"]:
            reasons.append("insufficient_reserved_cpu_headroom")
        if available["memoryBytes"] < quantity(minimum["memory"]["capacity"]):
            reasons.append("insufficient_reserved_memory_headroom")
        if status["utilization"] is None:
            unknown.append("utilization_stale_or_unreported")
        results.append({"deviceId": node, "status": "excluded" if reasons else "needs-verification",
                        "reasons": reasons + unknown, "executionAllowed": False})
    return results


async def read_document(request):
    data = bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data) > MAX_BODY:
            raise HTTPException(413, "Profile 입력은 64 KiB 이하여야 합니다.")
    try:
        def invalid_constant(value):
            raise ValueError(value)
        document = json.loads(data, parse_constant=invalid_constant)
        # Large exponents can become infinity without parse_constant.
        def finite(value):
            if isinstance(value, float) and not math.isfinite(value):
                raise ValueError("non-finite number")
            if isinstance(value, dict):
                for v in value.values(): finite(v)
            elif isinstance(value, list):
                for v in value: finite(v)
        finite(document)
        return document
    except (ValueError, UnicodeDecodeError, RecursionError):
        raise HTTPException(400, "올바른 JSON 객체를 입력하세요.")


def create_profile_router(resource_reader):
    router = APIRouter(prefix="/api/v1/profile-spec", tags=["Profile Spec v1 (draft)"])

    @router.get("")
    async def catalog(response: Response):
        response.headers["Cache-Control"] = "no-store"
        return BUNDLE

    async def read_observation():
        try:
            return observation(await resource_reader())
        except Exception:
            logger.exception("Profile observation unavailable")
            result = observation([])
            result["observationError"] = "node_source_unavailable"
            return result

    @router.get("/observations")
    async def observed(response: Response):
        response.headers["Cache-Control"] = "no-store"
        return await read_observation()

    @router.post("/validate")
    async def validate(request: Request):
        document = await read_document(request)
        errors = validate_document(document)
        return {"valid": not errors, "errors": errors, "persisted": False,
                "notice": "명세 형식 검증입니다. 실장비 실행·성능 검증과 다릅니다."}

    @router.post("/compare")
    async def preview(request: Request, response: Response):
        response.headers["Cache-Control"] = "no-store"
        document = await read_document(request)
        errors = validate_document(document)
        if errors or document.get("kind") != "ServiceProfile":
            raise HTTPException(422, errors or "ServiceProfile이 필요합니다.")
        observed = await read_observation()
        return {"observedAt": observed["observedAt"], "observationError": observed["observationError"],
                "candidates": compare(document, observed), "executionAllowed": False,
                "notice": "architecture·예약 여유 비교. runtime·모델·성능 자격과 전체 배치 조건은 추가 검증이 필요합니다."}

    return router
