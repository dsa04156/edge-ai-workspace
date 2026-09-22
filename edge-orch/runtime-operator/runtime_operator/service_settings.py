"""Bounded editing of an existing, stopped RuntimeService deployment policy."""
import asyncio
import copy
import hashlib
import json
from typing import Literal

from fastapi import APIRouter, HTTPException, Path, Query, Response
from kubernetes.client.exceptions import ApiException
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .contract import ServiceSpec


class PolicySettings(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    mode: Literal["automatic", "preferred", "approval"]
    preferredRole: Literal["edge", "server"]
    nodeName: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9.-]{0,252}$")
    highWatermark: float = Field(gt=0, le=1)
    lowWatermark: float = Field(ge=0, lt=1)
    pressureSeconds: float = Field(ge=1, le=3600)
    returnSeconds: float = Field(ge=1, le=86400)
    cooldownSeconds: float = Field(ge=1, le=86400)


class SettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serviceUid: str = Field(pattern=r"^[A-Za-z0-9-]{1,80}$")
    specRevision: str = Field(pattern=r"^[a-f0-9]{64}$")
    settings: PolicySettings


class DefinitionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    serviceUid: str = Field(pattern=r"^[A-Za-z0-9-]{1,80}$")
    specRevision: str = Field(pattern=r"^[a-f0-9]{64}$")
    spec: dict


class RegistrationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$")
    spec: dict


def git_managed(resource):
    meta = resource.get("metadata", {})
    return bool(meta.get("annotations", {}).get("argocd.argoproj.io/tracking-id")
                or meta.get("labels", {}).get("argocd.argoproj.io/instance")
                or any("argocd" in f.get("manager", "") for f in meta.get("managedFields", [])))


def definition_spec(raw, resource=None):
    """A dashboard definition is unqualified, stopped and uses managed workers."""
    ServiceSpec.model_validate(raw)
    if resource and git_managed(resource):
        raise ValueError("service_settings_owned_by_git")
    if resource and any(v.get("resident") for v in resource["spec"]["variants"]):
        raise ValueError("resident_definition_requires_deployment_contract")
    result = copy.deepcopy(raw)
    if any(v.get("resident") for v in result.get("variants", [])) or result.get("inference") or result.get("commonAI"):
        raise ValueError("resident_definition_requires_deployment_contract")
    if result.get("suspended") is not True or result.get("policy", {}).get("mode") != "preferred":
        raise ValueError("definition_requires_stopped_preferred_policy")
    if result.get("policy", {}).get("stages"):
        raise ValueError("definition_requires_stopped_preferred_policy")
    # A new artifact cannot inherit the old artifact's execution/performance evidence.
    for variant in result.get("variants", []):
        variant.update(qualification="dashboard-unqualified", verifiedNodes=[], qualifiedRps=None,
                       qualifiedP95Milliseconds=None, qualifiedInputProfile=None, maxInFlight=1)
    spec = ServiceSpec.model_validate(result)
    if not (spec.demo or spec.is_ai):
        raise ValueError("service_demo_control_not_enabled")
    return result


def revision(resource):
    return hashlib.sha256(json.dumps(resource["spec"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def settings_of(spec):
    p = spec.policy
    return PolicySettings(mode="approval" if p.approvalRequired else p.mode,
        preferredRole=p.preferredRole, nodeName=p.nodeSelector.get("kubernetes.io/hostname"),
        highWatermark=p.highWatermark, lowWatermark=p.lowWatermark,
        pressureSeconds=p.pressureSeconds, returnSeconds=p.returnSeconds, cooldownSeconds=p.cooldownSeconds)


def configured_nodes(spec):
    return sorted({n for v in spec.variants for n in [*v.verifiedNodes, v.nodeSelector.get("kubernetes.io/hostname")]
                   if n})


def updated_spec(resource, settings):
    if git_managed(resource):
        raise ValueError("service_settings_owned_by_git")
    spec = ServiceSpec.model_validate(resource["spec"])
    if settings.mode != "preferred" and any(v.qualification == "dashboard-unqualified" for v in spec.variants):
        raise ValueError("automatic_policy_requires_qualification")
    current = settings_of(spec)
    if settings.nodeName != current.nodeName:
        if spec.policy.stages or settings.nodeName and settings.nodeName not in configured_nodes(spec):
            raise ValueError("node_outside_registered_contract")
    updated = copy.deepcopy(resource["spec"])
    policy = updated.setdefault("policy", {})
    values = settings.model_dump(exclude={"mode", "nodeName"})
    policy.update(values, mode="automatic" if settings.mode == "approval" else settings.mode,
                  approvalRequired=settings.mode == "approval")
    selector = policy.setdefault("nodeSelector", {})
    if settings.nodeName: selector["kubernetes.io/hostname"] = settings.nodeName
    else: selector.pop("kubernetes.io/hostname", None)
    ServiceSpec.model_validate(updated)  # includes model qualification and commonAI/staged constraints
    return updated


def public_settings(resource, state, now):
    spec = ServiceSpec.model_validate(resource["spec"])
    editable = bool(spec.suspended and state.get("phase") == "Suspended"
                    and not state.get("active") and not state.get("target") and not state.get("retiring")
                    and 0 <= now - state.get("checkedAt", 0) < 15
                    and (spec.demo or spec.is_ai) and not git_managed(resource))
    values = settings_of(spec); modes = []
    for mode in ["preferred", "automatic", "approval"]:
        try:
            updated_spec(resource, values.model_copy(update={"mode": mode}))
            modes.append(mode)
        except ValueError:
            pass
    return {"uid": resource["metadata"]["uid"], "name": resource["metadata"]["name"],
        "specRevision": revision(resource), "observedAt": now, "editable": editable,
        "reason": None if editable else "service_settings_owned_by_git" if git_managed(resource) else "service_must_be_stopped",
        "spec": copy.deepcopy(resource["spec"]),
        "definitionEditable": editable and not any(v.resident for v in spec.variants),
        "definitionReason": "resident_definition_requires_deployment_contract" if any(v.resident for v in spec.variants) else None,
        "settings": values.model_dump(),
        "constraints": {"modes": modes, "roles": spec.policy.allowedRoles,
            "nodes": configured_nodes(spec), "nodeSelectionAllowed": not bool(spec.policy.stages)},
        "variants": [{"name": v.name, "image": v.image, "architecture": v.architecture,
                      "requests": v.requests, "limits": v.limits} for v in spec.variants]}


def router(app):
    routes = APIRouter()

    def current(name, uid):
        c = app.state.controller
        if c.stopping or not c.snapshot or not 0 <= c.clock() - c.last_snapshot < 15:
            raise HTTPException(503, "runtime_snapshot_unavailable")
        matches = [r for r in c.snapshot["services"] if r["metadata"]["name"] == name
                   and r["metadata"]["uid"] == uid and not r["metadata"].get("deletionTimestamp")]
        if len(matches) != 1: raise HTTPException(409, "service_identity_changed")
        return c, matches[0]

    @routes.post("/services/registration", status_code=201)
    async def register(body: RegistrationRequest):
        c = app.state.controller
        async with c.reconcile_lock:
            if c.stopping or not c.snapshot or not 0 <= c.clock() - c.last_snapshot < 15:
                raise HTTPException(503, "runtime_snapshot_unavailable")
            try:
                spec = definition_spec(body.spec)
                resource = await asyncio.to_thread(c.kube.register_service, body.name, spec)
            except ValidationError:
                raise HTTPException(422, "settings_violate_registered_contract") from None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from None
            except ApiException as exc:
                raise HTTPException(409 if exc.status == 409 else 503, "service_name_exists" if exc.status == 409 else "settings_not_applied") from None
            c.snapshot["services"].append(resource)
            return public_settings(resource, {}, c.clock())

    @routes.put("/services/{name}/definition")
    async def save_definition(body: DefinitionRequest, name: str = Path(pattern=r"^[a-z0-9-]{1,63}$")):
        c = app.state.controller
        async with c.reconcile_lock:
            c, resource = current(name, body.serviceUid)
            view = public_settings(resource, c.states.get(body.serviceUid, {}), c.clock())
            if not view["definitionEditable"]:
                raise HTTPException(409, view["definitionReason"] or view["reason"])
            if revision(resource) != body.specRevision:
                raise HTTPException(409, "service_settings_changed")
            try:
                definition_spec(body.spec, resource)
                resource = await asyncio.to_thread(c.kube.set_service_definition, name, body.serviceUid, body.specRevision, body.spec)
            except ValidationError:
                raise HTTPException(422, "settings_violate_registered_contract") from None
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None
            except ApiException as exc:
                raise HTTPException(409 if exc.status == 409 else 503, "settings_not_applied") from None
            c.snapshot["services"] = [resource if r["metadata"]["uid"] == body.serviceUid else r for r in c.snapshot["services"]]
            return public_settings(resource, c.states.get(body.serviceUid, {}), c.clock())

    @routes.get("/services/{name}/settings")
    async def read(response: Response, name: str = Path(pattern=r"^[a-z0-9-]{1,63}$"),
                   serviceUid: str = Query(pattern=r"^[A-Za-z0-9-]{1,80}$")):
        c, resource = current(name, serviceUid)
        response.headers["Cache-Control"] = "no-store"
        return public_settings(resource, c.states.get(serviceUid, {}), c.clock())

    @routes.put("/services/{name}/settings")
    async def save(body: SettingsRequest, name: str = Path(pattern=r"^[a-z0-9-]{1,63}$")):
        c = app.state.controller
        async with c.reconcile_lock:
            c, resource = current(name, body.serviceUid)
            if not public_settings(resource, c.states.get(body.serviceUid, {}), c.clock())["editable"]:
                raise HTTPException(409, "service_must_be_stopped")
            if revision(resource) != body.specRevision: raise HTTPException(409, "service_settings_changed")
            try:
                updated_spec(resource, body.settings)
                resource = await asyncio.to_thread(c.kube.set_service_settings, name, body.serviceUid,
                                                  body.specRevision, body.settings)
            except ValidationError:
                raise HTTPException(422, "settings_violate_registered_contract") from None
            except ValueError as exc:
                raise HTTPException(409, str(exc)) from None
            except ApiException as exc:
                raise HTTPException(409 if exc.status == 409 else 503, "settings_not_applied") from None
            c.snapshot["services"] = [resource if r["metadata"]["uid"] == body.serviceUid else r for r in c.snapshot["services"]]
            return public_settings(resource, c.states.get(body.serviceUid, {}), c.clock())

    return routes
