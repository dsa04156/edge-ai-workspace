from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from .models import PlacementSelectionRequest
from .placement import select_placement
from .runtime_recommendation import (
    RuntimeRecommendationEngine,
    RuntimeRecommendationSignals,
    RuntimeRecommendationStore,
)
from .runtime_recommendation_models import (
    RuntimeRecommendationDecision,
    RuntimeRecommendationHistoryEntry,
    RuntimeRecommendationPolicy,
)


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeServiceObservation:
    input_state: str
    input_valid: bool
    model_state: str
    model_ready: bool
    performance_valid: bool
    resource_valid: bool
    cpu_ratio: float | None
    memory_ratio: float | None
    latency_p95_ms: float | None
    backlog: int | None
    throughput_per_second: float | None
    source: str
    scope: str


class RuntimeServiceObservationAdapter(Protocol):
    async def observe(
        self,
        descriptor: Any,
        resource_profile: dict[str, Any] | None,
        policy: RuntimeRecommendationPolicy,
        *,
        now: datetime,
    ) -> RuntimeServiceObservation: ...


class SensorAnomalyRuntimeAdapter:
    def __init__(self, client: Any) -> None:
        self.client = client

    async def observe(
        self,
        descriptor: Any,
        resource_profile: dict[str, Any] | None,
        policy: RuntimeRecommendationPolicy,
        *,
        now: datetime,
    ) -> RuntimeServiceObservation:
        demo = await self.client.get_state()
        profile = resource_profile or {}
        current = _mapping(profile.get("current_usage"))
        limits = _mapping(_mapping(profile.get("resource_requirements")).get("limits"))
        cpu_usage: float | None = None
        memory_usage: float | None = None
        source = "unavailable"
        scope = "unknown"
        if (
            _number(current.get("usage_coverage_ratio")) > 0
            and _fresh(profile.get("generated_at"), now, policy.metric_fresh_seconds)
            and _optional_number(current.get("cpu_cores")) is not None
            and _optional_number(current.get("memory_working_set_mib")) is not None
        ):
            cpu_usage = _optional_number(current.get("cpu_cores"))
            memory_usage = _optional_number(current.get("memory_working_set_mib"))
            source = "container-cadvisor"
            scope = "container"
        else:
            process = demo.process_resources
            if (
                process is not None
                and process.metrics_valid
                and _fresh(process.observed_at, now, policy.metric_fresh_seconds)
            ):
                cpu_usage = process.cpu_cores
                memory_usage = process.memory_rss_mib
                source = process.source
                scope = process.scope

        cpu_ratio = _ratio(cpu_usage, _optional_number(limits.get("cpu_cores")))
        memory_ratio = _ratio(
            memory_usage,
            _optional_number(limits.get("memory_mib")),
        )
        performance = demo.performance
        performance_valid = bool(
            performance is not None
            and performance.metrics_valid
            and _fresh(
                performance.observed_at,
                now,
                policy.metric_fresh_seconds,
            )
        )
        latest_contract = demo.latest.input_contract if demo.latest is not None else None
        return RuntimeServiceObservation(
            input_state=demo.input_state,
            input_valid=bool(
                demo.mode == "live"
                and demo.input_state == "fresh"
                and latest_contract == descriptor.input_contract.schema_name
            ),
            model_state=demo.model_state,
            model_ready=demo.model_state == "ready",
            performance_valid=performance_valid,
            resource_valid=cpu_ratio is not None and memory_ratio is not None,
            cpu_ratio=cpu_ratio,
            memory_ratio=memory_ratio,
            latency_p95_ms=(
                performance.processing_latency_p95_ms
                if performance is not None
                else None
            ),
            backlog=performance.backlog if performance is not None else None,
            throughput_per_second=(
                performance.throughput_per_second
                if performance is not None
                else None
            ),
            source=source,
            scope=scope,
        )


class RuntimeRecommendationMonitor:
    def __init__(
        self,
        settings: Any,
        aggregator_service: Any,
        service_catalog: Any,
        adapters: dict[str, RuntimeServiceObservationAdapter],
    ) -> None:
        database_path = settings.runtime_recommendation_database_path or (
            Path(settings.data_dir) / "runtime-recommendations.sqlite3"
        )
        self.settings = settings
        self.aggregator_service = aggregator_service
        self.service_catalog = service_catalog
        self.adapters = adapters
        self.store = RuntimeRecommendationStore(
            database_path,
            history_limit=settings.runtime_recommendation_history_limit,
        )
        self.engine = RuntimeRecommendationEngine(self.store)
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if not self.settings.runtime_recommendation_enabled or self._task is not None:
            return
        self._task = asyncio.create_task(self._poll())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None

    async def _poll(self) -> None:
        while True:
            try:
                await self.evaluate_all()
            except Exception:
                logger.exception("Runtime recommendation polling failed")
            await asyncio.sleep(
                self.settings.runtime_recommendation_poll_interval_seconds
            )

    async def evaluate_all(
        self,
        *,
        now: datetime | None = None,
    ) -> list[RuntimeRecommendationDecision]:
        observed_at = _utc(now or datetime.now(timezone.utc))
        try:
            resource_state = await self.aggregator_service.get_resource_profile_state(
                refresh=True
            )
            profiles = resource_state.get("service_resource_profiles") or []
        except Exception:
            logger.exception("Failed to refresh service resource profiles")
            profiles = []
        profile_by_workload = {
            (item.get("namespace"), item.get("service")): item
            for item in profiles
            if isinstance(item, dict)
        }
        try:
            resources = await self.aggregator_service.get_scheduling_resources()
            node_observed = True
        except Exception:
            logger.exception("Failed to refresh scheduling resources")
            resources = []
            node_observed = False
        resource_by_node = {item.node: item for item in resources}

        decisions = []
        for descriptor in self.service_catalog.services:
            policy = descriptor.runtime_recommendation
            if policy is None or not policy.enabled:
                continue
            decisions.append(
                await self._evaluate_service(
                    descriptor,
                    policy,
                    profile_by_workload,
                    resources,
                    resource_by_node,
                    node_observed=node_observed,
                    now=observed_at,
                )
            )
        return decisions

    async def _evaluate_service(
        self,
        descriptor: Any,
        policy: RuntimeRecommendationPolicy,
        profile_by_workload: dict[tuple[str, str], dict[str, Any]],
        resources: list[Any],
        resource_by_node: dict[str, Any],
        *,
        node_observed: bool,
        now: datetime,
    ) -> RuntimeRecommendationDecision:
        workload_ref = descriptor.workload
        workload = await self.aggregator_service.kube.get_runtime_workload(
            namespace=workload_ref.namespace,
            kind=workload_ref.kind,
            name=workload_ref.name,
            selector=workload_ref.selector,
        )
        live_profile = profile_by_workload.get(
            (workload_ref.namespace, workload_ref.name)
        )
        metrics_profile = live_profile or workload.placement_profile
        adapter = self.adapters.get(descriptor.observability.adapter)
        if adapter is None:
            observation = _unavailable_observation("unsupported-adapter")
        else:
            try:
                observation = await adapter.observe(
                    descriptor,
                    metrics_profile,
                    policy,
                    now=now,
                )
            except Exception:
                logger.exception(
                    "Service observation failed for %s",
                    descriptor.service_id,
                )
                observation = _unavailable_observation("adapter-error")

        current_nodes = list(workload.current_nodes)
        node_failure = bool(
            current_nodes
            and any(
                node not in resource_by_node
                or not resource_by_node[node].schedulable
                or resource_by_node[node].health == "unavailable"
                for node in current_nodes
            )
        )
        placement_profile = workload.placement_profile
        profile_valid = bool(
            placement_profile
            and placement_profile.get("request_coverage_ratio") == 1
        )
        signals = RuntimeRecommendationSignals(
            service_id=descriptor.service_id,
            namespace=workload_ref.namespace,
            workload_kind=workload_ref.kind,
            workload_name=workload_ref.name,
            current_nodes=current_nodes,
            workload_observed=workload.observed,
            workload_exists=workload.exists,
            desired_replicas=workload.desired_replicas,
            ready_replicas=workload.ready_replicas,
            pod_restart_count=workload.pod_restart_count,
            pod_failure=workload.pod_failure,
            node_failure=node_failure,
            node_observed=node_observed,
            input_state=observation.input_state,
            input_valid=observation.input_valid,
            model_state=observation.model_state,
            model_ready=observation.model_ready,
            performance_valid=observation.performance_valid,
            resource_valid=observation.resource_valid and profile_valid,
            cpu_ratio=observation.cpu_ratio,
            memory_ratio=observation.memory_ratio,
            latency_p95_ms=observation.latency_p95_ms,
            backlog=observation.backlog,
            throughput_per_second=observation.throughput_per_second,
            observation_source=observation.source,
            observation_scope=observation.scope,
        )

        async def placement_provider(excluded_nodes: set[str]):
            assert placement_profile is not None
            return select_placement(
                placement_profile,
                resources,
                PlacementSelectionRequest(
                    namespace=workload_ref.namespace,
                    service=workload_ref.name,
                    architecture=policy.architecture,
                    accelerator=policy.accelerator,
                    accelerator_units=policy.accelerator_units,
                ),
                excluded_nodes=excluded_nodes,
                now=now,
            )

        return await self.engine.evaluate(
            signals,
            policy,
            placement_provider,
            now=now,
        )

    def latest(self, service_id: str) -> RuntimeRecommendationDecision | None:
        return self.store.latest(service_id)

    def latest_all(self) -> list[RuntimeRecommendationDecision]:
        return self.store.latest_all()

    def history(
        self,
        service_id: str,
        *,
        limit: int,
    ) -> list[RuntimeRecommendationHistoryEntry]:
        return self.store.history(service_id, limit=limit)


def _unavailable_observation(source: str) -> RuntimeServiceObservation:
    return RuntimeServiceObservation(
        input_state="unknown",
        input_valid=False,
        model_state="unknown",
        model_ready=False,
        performance_valid=False,
        resource_valid=False,
        cpu_ratio=None,
        memory_ratio=None,
        latency_p95_ms=None,
        backlog=None,
        throughput_per_second=None,
        source=source,
        scope="unknown",
    )


def _mapping(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: object) -> float:
    result = _optional_number(value)
    return result if result is not None else 0.0


def _optional_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _ratio(value: float | None, limit: float | None) -> float | None:
    if value is None or limit is None or limit <= 0:
        return None
    return max(0.0, value / limit)


def _fresh(value: object, now: datetime, max_age_seconds: int) -> bool:
    if isinstance(value, datetime):
        observed_at = _utc(value)
    elif isinstance(value, str):
        try:
            observed_at = _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            return False
    else:
        return False
    return 0 <= (now - observed_at).total_seconds() <= max_age_seconds


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
