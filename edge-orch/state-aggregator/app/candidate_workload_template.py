from __future__ import annotations

import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Literal

from kubernetes.utils.quantity import parse_quantity
from pydantic import Field, field_validator, model_validator

from .models import PlacementSelectionResult, SchedulingModel


StatePolicyType = Literal[
    "stateless",
    "fresh_state",
    "snapshot_restore",
    "shared_storage",
]
CandidateStorageType = Literal["none", "ephemeral", "new_pvc", "source_pvc"]
_IMMUTABLE_IMAGE = re.compile(r"^.+@sha256:[0-9a-f]{64}$")
_DNS_LABEL = re.compile(r"^[a-z0-9]([-a-z0-9]*[a-z0-9])?$")


class CandidateNamingPolicy(SchedulingModel):
    pattern: str = "{source}-{action}-{planSuffix}"
    max_length: int = Field(default=63, ge=1, le=63)

    @field_validator("pattern")
    @classmethod
    def validate_pattern(cls, value: str) -> str:
        required = {"{source}", "{action}", "{planSuffix}"}
        if not all(token in value for token in required):
            raise ValueError("candidate naming pattern must include source, action and planSuffix")
        return value


class CandidateConstraints(SchedulingModel):
    architectures: list[str] = Field(min_length=1)
    accelerator: str | None = None
    accelerator_units: dict[str, float] = Field(default_factory=dict)

    @field_validator("accelerator_units")
    @classmethod
    def validate_accelerator_units(cls, values: dict[str, float]) -> dict[str, float]:
        if any(not name or amount < 0 for name, amount in values.items()):
            raise ValueError("acceleratorUnits must be non-negative")
        return values


class CandidateStoragePolicy(SchedulingModel):
    type: CandidateStorageType
    volume_name: str | None = None
    mount_path: str | None = None
    reuse_source_pvc: bool = False
    copy_existing_data: bool = False
    size: str | None = None
    storage_class_name: str | None = None
    access_modes: list[str] = Field(default_factory=list)


class CandidateStatePolicy(SchedulingModel):
    type: StatePolicyType
    candidate_storage: CandidateStoragePolicy

    @model_validator(mode="after")
    def validate_policy(self) -> "CandidateStatePolicy":
        storage = self.candidate_storage
        if self.type == "fresh_state" and storage.type == "none":
            raise ValueError("fresh_state requires candidate storage")
        if self.type == "stateless" and storage.type != "none":
            raise ValueError("stateless requires no candidate storage")
        if storage.type in {"ephemeral", "new_pvc", "source_pvc"} and (
            not storage.volume_name or not storage.mount_path
        ):
            raise ValueError("candidate storage requires volumeName and mountPath")
        return self


class SourceStateVolumeContract(SchedulingModel):
    volume_name: str
    claim_name: str
    required_access_modes: list[str] = Field(min_length=1)
    storage_class_name: str


class CandidateSourceContract(SchedulingModel):
    namespace: str
    kind: Literal["Deployment"]
    name: str
    service_name: str
    container_name: str
    compatible_images: list[str] = Field(min_length=1)
    source_state_volume: SourceStateVolumeContract | None = None

    @field_validator("compatible_images")
    @classmethod
    def validate_images(cls, values: list[str]) -> list[str]:
        if any(not _IMMUTABLE_IMAGE.fullmatch(value) for value in values):
            raise ValueError("compatibleImages must use immutable sha256 digests")
        return values


class CandidateContainerTemplate(SchedulingModel):
    name: str
    image: str
    image_pull_policy: str = "IfNotPresent"
    env: list[dict[str, Any]] = Field(default_factory=list)
    ports: list[dict[str, Any]] = Field(default_factory=list)
    startup_probe: dict[str, Any] | None = None
    readiness_probe: dict[str, Any] | None = None
    liveness_probe: dict[str, Any] | None = None
    resources: dict[str, Any]
    security_context: dict[str, Any]
    volume_mounts: list[dict[str, Any]] = Field(default_factory=list)

    @field_validator("image")
    @classmethod
    def validate_image(cls, value: str) -> str:
        if not _IMMUTABLE_IMAGE.fullmatch(value):
            raise ValueError("candidate image must use an immutable sha256 digest")
        return value


class CandidatePodTemplate(SchedulingModel):
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    automount_service_account_token: bool = False
    service_account_name: str | None = None
    termination_grace_period_seconds: int = Field(default=30, ge=0)
    security_context: dict[str, Any]
    container: CandidateContainerTemplate
    volumes: list[dict[str, Any]] = Field(default_factory=list)


class CandidateWorkloadTemplate(SchedulingModel):
    service_id: str
    template_version: str
    allowed_namespaces: list[str] = Field(min_length=1)
    candidate_naming: CandidateNamingPolicy
    constraints: CandidateConstraints
    state_policy: CandidateStatePolicy
    source_contract: CandidateSourceContract
    pod_template: CandidatePodTemplate

    @model_validator(mode="after")
    def validate_contract(self) -> "CandidateWorkloadTemplate":
        source = self.source_contract
        container = self.pod_template.container
        if container.name != source.container_name:
            raise ValueError("candidate and source container names must match")
        if container.image not in source.compatible_images:
            raise ValueError("candidate image must be listed in compatibleImages")
        requests = container.resources.get("requests") or {}
        if "cpu" not in requests or "memory" not in requests:
            raise ValueError("candidate resources require cpu and memory requests")
        env_names = [item.get("name") for item in container.env]
        if any(not name for name in env_names) or len(env_names) != len(set(env_names)):
            raise ValueError("candidate env names must be present and unique")
        volume_names = [item.get("name") for item in self.pod_template.volumes]
        if any(not name for name in volume_names) or len(volume_names) != len(set(volume_names)):
            raise ValueError("candidate volume names must be present and unique")
        if any("hostPath" in item for item in self.pod_template.volumes):
            raise ValueError("hostPath volumes are not allowed in candidate templates")
        if any(
            item.get("name") not in set(volume_names)
            for item in container.volume_mounts
        ):
            raise ValueError("candidate volume mounts must reference declared volumes")
        storage = self.state_policy.candidate_storage
        if storage.type == "ephemeral":
            if any("persistentVolumeClaim" in item for item in self.pod_template.volumes):
                raise ValueError("ephemeral candidate templates cannot reference PVCs")
            volumes = {item.get("name"): item for item in self.pod_template.volumes}
            volume = volumes.get(storage.volume_name)
            if volume is None or "emptyDir" not in volume:
                raise ValueError("ephemeral fresh_state volume must use emptyDir")
            mounts = {
                item.get("name"): item.get("mountPath")
                for item in container.volume_mounts
            }
            if mounts.get(storage.volume_name) != storage.mount_path:
                raise ValueError("fresh_state volume mount does not match storage policy")
        return self

    def candidate_name(self, *, source: str, action: str, plan_id: str) -> str:
        suffix = plan_id.removeprefix("runtime-plan-")[:8]
        value = self.candidate_naming.pattern.format(
            source=source,
            action=action,
            planSuffix=suffix,
        ).lower()
        value = re.sub(r"[^a-z0-9-]", "-", value).strip("-")
        value = value[: self.candidate_naming.max_length].rstrip("-")
        if not value or not _DNS_LABEL.fullmatch(value):
            raise ValueError("candidate naming policy produced an invalid DNS label")
        return value


class CandidateWorkloadTemplateCatalog(SchedulingModel):
    api_version: Literal["edge-ai.io/v1alpha1"]
    kind: Literal["CandidateWorkloadTemplateCatalog"]
    templates: list[CandidateWorkloadTemplate]


class CandidateTemplateCatalog:
    def __init__(
        self,
        templates: dict[str, CandidateWorkloadTemplate],
        errors: dict[str, str] | None = None,
    ) -> None:
        self.templates = templates
        self.errors = errors or {}

    @classmethod
    def load(cls, path: Path) -> "CandidateTemplateCatalog":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls({}, {"*": "candidate_contract_invalid"})
        if not isinstance(payload, dict) or not isinstance(payload.get("templates"), list):
            return cls({}, {"*": "candidate_contract_invalid"})
        templates: dict[str, CandidateWorkloadTemplate] = {}
        errors: dict[str, str] = {}
        for raw in payload["templates"]:
            service_id = raw.get("serviceId") if isinstance(raw, dict) else None
            try:
                template = CandidateWorkloadTemplate.model_validate(raw)
            except Exception:
                errors[str(service_id or "*")] = "candidate_contract_invalid"
                continue
            if template.service_id in templates:
                errors[template.service_id] = "candidate_contract_invalid"
                templates.pop(template.service_id, None)
                continue
            templates[template.service_id] = template
        try:
            CandidateWorkloadTemplateCatalog.model_validate(
                {
                    **payload,
                    "templates": [
                        item.model_dump(by_alias=True) for item in templates.values()
                    ],
                }
            )
        except Exception:
            return cls({}, {"*": "candidate_contract_invalid"})
        return cls(templates, errors)

    def resolve(
        self,
        service_id: str,
    ) -> tuple[CandidateWorkloadTemplate | None, str | None]:
        if service_id in self.errors or "*" in self.errors:
            return None, "candidate_contract_invalid"
        template = self.templates.get(service_id)
        if template is None:
            return None, "candidate_template_not_found"
        return template, None


def build_candidate_deployment_manifest(
    template: CandidateWorkloadTemplate,
    placement: PlacementSelectionResult,
    *,
    namespace: str,
    name: str,
    plan_id: str,
) -> dict[str, Any]:
    if placement.selected_node is None:
        raise ValueError("placement selected node is required")
    source = template.source_contract
    identity_labels = {
        "app.kubernetes.io/name": name,
        "app.kubernetes.io/managed-by": "state-aggregator",
        "edge-ai.io/deployment": name,
        "edge-ai.io/service-id": template.service_id,
        "edge-ai.io/execution-plan-id": plan_id,
        "edge-ai.io/candidate": "true",
        "edge-ai.io/source-workload": source.name,
    }
    labels = {**deepcopy(template.pod_template.labels), **identity_labels}
    annotations = {
        **deepcopy(template.pod_template.annotations),
        "edge-ai.io/candidate-template-version": template.template_version,
        "edge-ai.io/state-policy": template.state_policy.type,
    }
    container = template.pod_template.container.model_dump(
        by_alias=True,
        exclude_none=True,
    )
    pod_spec: dict[str, Any] = {
        "automountServiceAccountToken": template.pod_template.automount_service_account_token,
        "terminationGracePeriodSeconds": template.pod_template.termination_grace_period_seconds,
        "securityContext": deepcopy(template.pod_template.security_context),
        "nodeSelector": {"kubernetes.io/hostname": placement.selected_node},
        "affinity": {
            "nodeAffinity": {
                "requiredDuringSchedulingIgnoredDuringExecution": {
                    "nodeSelectorTerms": [
                        {
                            "matchExpressions": [
                                {
                                    "key": "kubernetes.io/hostname",
                                    "operator": "In",
                                    "values": [placement.selected_node],
                                }
                            ]
                        }
                    ]
                }
            }
        },
        "containers": [container],
        "volumes": deepcopy(template.pod_template.volumes),
    }
    if template.pod_template.service_account_name is not None:
        pod_spec["serviceAccountName"] = template.pod_template.service_account_name
    return {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": identity_labels,
            "annotations": annotations,
        },
        "spec": {
            "replicas": 1,
            "revisionHistoryLimit": 1,
            "strategy": {"type": "Recreate"},
            "selector": {"matchLabels": {"edge-ai.io/deployment": name}},
            "template": {
                "metadata": {"labels": labels, "annotations": annotations},
                "spec": pod_spec,
            },
        },
    }


def quantity_matches(actual: Any, expected: Any) -> bool:
    try:
        return parse_quantity(str(actual)) == parse_quantity(str(expected))
    except Exception:
        return str(actual) == str(expected)
