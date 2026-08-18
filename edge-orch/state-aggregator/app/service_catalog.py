from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .service_demo_models import DeployedServiceDesignContract


_ID_PATTERN = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")
_SAFE_STATE_PATH = re.compile(r"^/state/[A-Za-z0-9._/?=&-]+$")


class CatalogModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ServiceWorkloadDescriptor(CatalogModel):
    namespace: str = Field(min_length=1)
    kind: Literal["Deployment", "StatefulSet"]
    name: str = Field(min_length=1)
    selector: dict[str, str] = Field(min_length=1)


class ServiceInputDescriptor(CatalogModel):
    authority: Literal["EdgeX"] = "EdgeX"
    schema_name: str = Field(alias="schema", serialization_alias="schema", min_length=1)
    required_resources: list[str] = Field(min_length=1)


class ServiceStageDescriptor(CatalogModel):
    stage_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    slot: Literal["Input", "Alignment", "Features", "Inference", "Result"]
    label: str = Field(min_length=1)
    kind: Literal["source", "transform", "features", "inference", "sink"]
    depends_on: list[str] = Field(default_factory=list)
    executions: list["ServiceStageExecutionDescriptor"] = Field(min_length=1)


class ServiceStageExecutionDescriptor(CatalogModel):
    target_slot: Literal["Device1", "Server1"]
    executor: str = Field(min_length=1)


class ServiceTargetDescriptor(CatalogModel):
    target_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    slot: Literal["Device1", "Server1"]
    label: str = Field(min_length=1)
    node: str = Field(min_length=1)
    mode: Literal["edge-local", "approval-gated"]
    description: str = Field(min_length=1)


class ServiceGraphDescriptor(CatalogModel):
    topology: Literal["linear-inference-split-v1"]
    title: str = Field(min_length=1)
    stages: list[ServiceStageDescriptor] = Field(min_length=1)
    targets: list[ServiceTargetDescriptor] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_graph(self) -> "ServiceGraphDescriptor":
        stage_ids = [stage.stage_id for stage in self.stages]
        if len(stage_ids) != len(set(stage_ids)):
            raise ValueError("service graph stageId values must be unique")
        slots = [stage.slot for stage in self.stages]
        expected_slots = {"Input", "Alignment", "Features", "Inference", "Result"}
        if set(slots) != expected_slots or len(slots) != len(expected_slots):
            raise ValueError("linear-inference-split-v1 requires each standard stage slot")
        stage_id_set = set(stage_ids)
        for stage in self.stages:
            unknown = set(stage.depends_on) - stage_id_set
            if unknown:
                raise ValueError(
                    f"stage {stage.stage_id!r} depends on unknown stages {sorted(unknown)!r}"
                )
            execution_slots = [execution.target_slot for execution in stage.executions]
            if len(execution_slots) != len(set(execution_slots)):
                raise ValueError(
                    f"stage {stage.stage_id!r} execution target slots must be unique"
                )
        target_ids = [target.target_id for target in self.targets]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("service graph targetId values must be unique")
        target_slots = [target.slot for target in self.targets]
        if set(target_slots) != {"Device1", "Server1"} or len(target_slots) != 2:
            raise ValueError("linear-inference-split-v1 requires Device1 and Server1 targets")
        for stage in self.stages:
            unknown_targets = {
                execution.target_slot for execution in stage.executions
            } - set(target_slots)
            if unknown_targets:
                raise ValueError(
                    f"stage {stage.stage_id!r} uses unknown targets {sorted(unknown_targets)!r}"
                )

        dependencies = {stage.stage_id: set(stage.depends_on) for stage in self.stages}
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(stage_id: str) -> None:
            if stage_id in visiting:
                raise ValueError("service graph must be acyclic")
            if stage_id in visited:
                return
            visiting.add(stage_id)
            for dependency in dependencies[stage_id]:
                visit(dependency)
            visiting.remove(stage_id)
            visited.add(stage_id)

        for stage_id in stage_ids:
            visit(stage_id)
        return self


class ServiceObservabilityDescriptor(CatalogModel):
    adapter: Literal["sensor-anomaly-v1"]
    state_path: str
    results_path: str
    alerts_path: str

    @model_validator(mode="after")
    def validate_paths(self) -> "ServiceObservabilityDescriptor":
        for field_name in (
            "state_path",
            "results_path",
            "alerts_path",
        ):
            value = getattr(self, field_name)
            if not _SAFE_STATE_PATH.fullmatch(value) or "//" in value:
                raise ValueError(f"{field_name} must be a relative /state/ path")
        return self


class ServiceAugmentationQualificationDescriptor(CatalogModel):
    status: Literal["qualified", "rejected", "pending"]
    source_model_version: str = Field(min_length=1)
    candidate_model_version: str = Field(min_length=1)
    experiment_id: str = Field(min_length=1)
    reason: str = Field(min_length=1)
    max_validated_rps: float = Field(gt=0)
    latency_p95_improvement_percent: float = Field(ge=0, le=100)
    throughput_noninferiority_percent: float = Field(ge=0, le=100)
    requires_zero_errors_and_oom: bool = True
    qualified_condition_count: int = Field(ge=0)
    validated_condition_count: int = Field(gt=0)
    evidence_document: str = Field(pattern=r"^docs/[A-Za-z0-9가-힣._/-]+\.md$")

    @model_validator(mode="after")
    def validate_condition_counts(self) -> "ServiceAugmentationQualificationDescriptor":
        if self.qualified_condition_count > self.validated_condition_count:
            raise ValueError(
                "qualified_condition_count cannot exceed validated_condition_count"
            )
        return self


class ServiceDescriptor(CatalogModel):
    service_id: str
    display_name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    category: Literal["ai_inference"] = "ai_inference"
    lifecycle: Literal["deployed"] = "deployed"
    execution_mode: Literal["fixed"] = "fixed"
    workload: ServiceWorkloadDescriptor
    input_contract: ServiceInputDescriptor
    graph: ServiceGraphDescriptor
    observability: ServiceObservabilityDescriptor
    augmentation_qualification: ServiceAugmentationQualificationDescriptor
    design_contract: DeployedServiceDesignContract

    @model_validator(mode="after")
    def validate_service_id(self) -> "ServiceDescriptor":
        if not _ID_PATTERN.fullmatch(self.service_id):
            raise ValueError("serviceId must be a DNS-compatible identifier")
        return self


class ServiceCatalogDocument(CatalogModel):
    version: Literal["edgeai.etri/service-catalog/v1"]
    services: list[ServiceDescriptor] = Field(min_length=1)


class ServiceCatalog:
    def __init__(self, document: ServiceCatalogDocument, *, source: str) -> None:
        self.version = document.version
        self.services = document.services
        self.source = source
        self._by_id = {item.service_id: item for item in self.services}
        if len(self._by_id) != len(self.services):
            raise ValueError("serviceId values must be unique")

    @classmethod
    def load(cls, path: Path) -> "ServiceCatalog":
        payload = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            ServiceCatalogDocument.model_validate(payload),
            source=f"git:{path.name}",
        )

    def require(self, service_id: str) -> ServiceDescriptor:
        try:
            return self._by_id[service_id]
        except KeyError as exc:
            raise ValueError(f"unknown service {service_id!r}") from exc
