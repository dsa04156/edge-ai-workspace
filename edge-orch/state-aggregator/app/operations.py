"""Service-centred read projection. No controller calls or invented stage metrics."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field


class OperationsState(BaseModel):
    schema_version: str = "edgeai.operations/v1"
    generated_at: datetime
    mode: str = "read_only"
    sources: dict[str, dict[str, Any]]
    services: list[dict[str, Any]]
    issues: list[dict[str, Any]] = Field(default_factory=list)
    events: list[dict[str, Any]] = Field(default_factory=list)
    observation_errors: list[str] = Field(default_factory=list)


def plain(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json", by_alias=False)
    if isinstance(value, list):
        return [plain(item) for item in value]
    return value


def fresh(value, now, seconds=60):
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return -5 <= (now - timestamp).total_seconds() <= seconds
    except (ValueError, TypeError):
        return False


def project(catalog, data, errors, now=None):
    now = now or datetime.now(timezone.utc)
    origins = {
        "demo": "/state/service-demo", "devices": "/state/devices",
        "profiles": "/state/service-resource-profiles", "recommendations": "/api/runtime-recommendations",
        "executions": "/api/executions", "alerts": "/state/service-demo/alerts",
        "decisions": "/api/runtime-recommendations/{service_id}/history",
    }
    sources = {key: {"endpoint": endpoint, "status": "unknown" if key in errors else "observed",
                     "error": errors.get(key), "received_at": now.isoformat()}
               for key, endpoint in origins.items()}
    devices = {d["name"]: d for d in data.get("devices", [])}
    profiles = data.get("profiles", {}).get("service_resource_profiles", [])
    demo = data.get("demo", {})
    services, issues, events = [], [], []
    for descriptor in catalog.services:
        sid = descriptor.service_id
        observed = demo if sid == "sensor-anomaly-demo" else {}
        service_ok = bool(observed and observed.get("mode") == "live" and not observed.get("observation_error")
                          and fresh(observed.get("generated_at"), now))
        ownership = observed.get("execution_ownership") or {}
        active = service_ok and ownership.get("effective_mode") == "ACTIVE" and (
            not ownership.get("enabled") or (ownership.get("lease_valid") is True
                                            and fresh(ownership.get("observed_at"), now)))
        latest = observed.get("latest")
        perf = observed.get("performance") or {}
        perf_valid = service_ok and perf.get("metrics_valid") is True and perf.get("sample_count", 0) > 0 and fresh(perf.get("observed_at"), now)
        quality = {"scope": "service_window", "source": "/state/service-demo.performance",
                   "observed_at": perf.get("observed_at"), "valid": bool(perf_valid),
                   "sample_count": perf.get("sample_count"), "window_seconds": perf.get("window_seconds")}
        for key in ("processing_latency_p95_ms", "throughput_per_second", "backlog"):
            quality[key] = perf.get(key) if perf_valid else None
        bindings = []
        for binding in descriptor.design_contract.inputs:
            device = devices.get(binding.device_name)
            bindings.append({"stage_id": binding.stage_id, "device_name": binding.device_name,
                             "resource_name": binding.resource_name, "device": device,
                             "state": "unknown" if "devices" in errors else "missing" if device is None else device.get("overall_status", "unknown"),
                             "source": "/state/devices"})
            if "devices" in errors or device is None or device.get("overall_status") != "available":
                issues.append({"id": f"{sid}:input:{binding.stage_id}", "service_id": sid,
                               "stage_id": "collect", "device": binding.device_name,
                               "node": device.get("node_name") if device else None,
                               "state": "unknown" if "devices" in errors else "warning",
                               "reason": errors.get("devices") or (device.get("reason") if device else "missing_device"),
                               "source": "/state/devices"})
        stages = []
        for stage in descriptor.graph.stages:
            executors = []
            for execution in stage.executions:
                profile = next((p for p in profiles if p.get("namespace") == descriptor.workload.namespace
                                and p.get("service") == execution.executor), None)
                current = profile is not None and "profiles" not in errors and fresh(profile.get("generated_at"), now)
                target = next(t for t in descriptor.graph.targets if t.slot == execution.target_slot)
                executors.append({"workload": execution.executor, "namespace": descriptor.workload.namespace,
                                  "configured_node": target.node, "target_slot": execution.target_slot,
                                  "observed_nodes": profile.get("nodes", []) if current else [],
                                  "pod_ready_count": profile.get("ready_pod_count") if current else None,
                                  "pods": sorted({c["pod"] for c in profile.get("containers", []) if c.get("pod")}) if current else [],
                                  "resources": profile if current else None,
                                  "state": "Observed" if current else "Configured",
                                  "source": "/state/service-resource-profiles", "observed_at": profile.get("generated_at") if profile else None})
            # This application is streaming; a Pod does not prove a function is running.
            state = "UNKNOWN"
            evidence = "stage_instrumentation_unavailable"
            if stage.slot == "Input":
                if "devices" not in errors and bindings:
                    state = "INPUT_READY" if all(b["state"] == "available" for b in bindings) else "INPUT_ATTENTION"
                evidence = "EdgeX 입력 관측 · AI 소비 서비스의 실행 상태와 별도"
            elif service_ok:
                state = "PROCESSING_OBSERVED" if active and perf_valid and quality["throughput_per_second"] > 0 else (ownership.get("effective_mode") if ownership.get("effective_mode") in {"STANDBY", "SHADOW"} else "PROCESSING_UNCONFIRMED")
                evidence = "공유 서비스의 처리 근거 · 독립 stage 계측 없음"
                if stage.slot == "Result":
                    state = "RESULT_STORED" if latest else "NO_RESULT_OBSERVED"
                    evidence = "저장된 과거 결과 · 원 시각 확인 필요"
            stages.append({"stage_id": stage.stage_id, "label": stage.label, "kind": stage.kind,
                           "depends_on": stage.depends_on, "state": state, "evidence": evidence,
                           "executors": executors, "metrics_scope": "shared_workload; stage metrics unavailable"})
        rec = next((r for r in data.get("recommendations", []) if r.get("service_id") == sid), None)
        history = [r for r in data.get("executions", []) if r.get("service_id") == sid]
        routing = observed.get("inference_routing") or {}
        remote = service_ok and fresh(routing.get("observed_at"), now) and routing.get("inference_mode") == "REMOTE"
        # Routing mode alone is desired/configured. Require fresh remote result identity.
        applied = bool(active and remote and latest and fresh(latest.get("observed_at"), now)
                       and latest.get("execution_mode") == "remote" and latest.get("remote_node")
                       and latest.get("request_id") and not latest.get("fallback"))
        services.append({"service_id": sid, "display_name": descriptor.display_name,
                         "definition_source": catalog.source, "definition": plain(descriptor),
                         "observation_state": "Observed" if service_ok else "Unknown",
                         "status": observed.get("status") if service_ok else "unknown",
                         "input_state": observed.get("input_state") if service_ok else "unknown",
                         "model_state": observed.get("model_state") if service_ok else "unknown",
                         "execution_ownership": ownership if service_ok else None,
                         "bindings": bindings, "stages": stages, "quality": quality,
                         "model": observed.get("model") if service_ok else None,
                         "latest_result": latest, "counters": observed.get("counters") if service_ok else None,
                         "storage": observed.get("storage") if service_ok else None,
                         "recommendation": rec, "recommendation_current": bool(rec and fresh(rec.get("observed_at"), now) and "recommendations" not in errors),
                         "routing": routing if service_ok else None,
                         "application": {"state": "Applied" if applied else "NOT_APPLIED" if service_ok else "Unknown",
                                         "source": "/state/service-demo", "scope": "latest remote inference request"},
                         "executions": history,
                         "comparison": {"status": "NOT_COMPARABLE", "reason": "matched workload/input/model benchmark evidence required", "improvement_percent": None},
                         "recovery": {"t0": None, "t1": None, "t2": None, "t3": None, "t4": None,
                                      "duration_ms": None, "reason": "execution duration is not failure-detection-to-data-resumption time"}})
        reasons = []
        if not service_ok:
            reasons.append("service_observation_unavailable")
        else:
            if not active:
                reasons.append(ownership.get("reason_code") or "execution_not_active")
            if observed.get("input_state") != "fresh":
                reasons.append("service_input_" + str(observed.get("input_state")))
            if observed.get("model_state") != "ready":
                reasons.append("model_" + str(observed.get("model_state")))
        for reason in reasons:
            issues.append({"id": f"{sid}:{reason}", "service_id": sid, "stage_id": "inference",
                           "state": "warning" if service_ok else "unknown", "reason": reason,
                           "source": "/state/service-demo"})
        for record in history:
            for index, step in enumerate(record.get("steps", [])):
                timestamp = step.get("completed_at") or step.get("started_at")
                if timestamp:
                    events.append({"id": f"execution:{record['plan_id']}:{index}", "service_id": sid,
                                   "operation_id": record["plan_id"], "timestamp": timestamp,
                                   "type": step.get("action"), "state": step.get("status"),
                                   "reasons": step.get("reason_codes", []), "source": "/api/executions",
                                   "node": (record.get("candidate_workload") or {}).get("target_node")})
        for decision in data.get("decisions", {}).get(sid, []):
            events.append({"id": f"decision:{sid}:{decision['sequence']}", "service_id": sid,
                           "timestamp": decision["recorded_at"], "type": "Scheduling Decision",
                           "state": decision["state"], "reasons": decision.get("decision", {}).get("reason_codes", []),
                           "source": origins["decisions"].replace("{service_id}", sid)})
    for alert in data.get("alerts", {}).get("alerts", []):
        events.append({"id": f"alert:{alert.get('alert_id')}:{alert.get('transition')}:{alert.get('observed_at')}",
                       "service_id": "sensor-anomaly-demo", "timestamp": alert.get("observed_at"),
                       "type": "Sensor Alert", "state": alert.get("transition"), "source": origins["alerts"],
                       "reasons": [alert.get("reason_code")] if alert.get("reason_code") else []})
    events = sorted((e for e in events if e.get("timestamp")), key=lambda e: e["timestamp"], reverse=True)[:200]
    return OperationsState(generated_at=now, sources=sources, services=services, issues=issues,
                           events=events, observation_errors=[f"{k}: {v}" for k, v in errors.items()])


def create_operations_router(catalog, readers):
    router = APIRouter()

    @router.get("/state/operations", response_model=OperationsState)
    async def operations():
        async def read(key, reader):
            try:
                value = plain(await asyncio.wait_for(reader(), timeout=15))
                if isinstance(value, dict) and (value.get("observation_error") or value.get("observation_errors")):
                    return key, value, "upstream_observation_unavailable"
                return key, value, None
            except Exception as exc:
                return key, None, f"observation_unavailable:{type(exc).__name__}"
        results = await asyncio.gather(*(read(key, reader) for key, reader in readers.items()))
        return project(catalog, {k: v for k, v, _ in results if v is not None},
                       {k: e for k, _, e in results if e})

    return router
