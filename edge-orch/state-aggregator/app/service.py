from __future__ import annotations

import asyncio
import logging
import re
import time

import httpx
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from .config import Settings, load_instance_map
from .edgex import EdgeXClient, EdgeXError, EdgeXNotFoundError
from .models import (
    CostModelState,
    DashboardState,
    DeviceState,
    EdgeXDevice,
    NodeState,
    OperatorAssistantState,
    OperatorChatRequest,
    OperatorChatResponse,
    SummaryState,
    TelemetryPoint,
    WorkflowEvent,
    WorkflowState,
    ProjectionError,
    ProjectionObservation,
    VirtualDeviceCollection,
    VirtualDeviceView,
)
from .normalizer import build_summary, normalize_node_state, normalize_workflow_state
from .placement_recorder import InfluxResourceProfileRecorder
from .prometheus import PrometheusClient
from .resource_profile import build_service_resource_profiles, summarize_service_resource_profiles
from .storage import StateStore
from .kube import KubeClient
from .virtual_device_bindings import (
    VirtualDeviceBindingConfig,
    VirtualDeviceInstance,
    config_revision,
)
from .virtual_device_resolver import resolve_virtual_device

logger = logging.getLogger(__name__)


class StateAggregatorService:
    def __init__(
        self,
        settings: Settings,
        *,
        edgex: EdgeXClient | None = None,
        bindings: VirtualDeviceBindingConfig | None = None,
        clock: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] | None = None,
    ) -> None:
        self.settings = settings
        # Keep fallback instance map for now, but it will be overridden by KubeClient
        self.instance_map = load_instance_map(settings.instance_map_path)
        self.store = StateStore(settings.data_dir)
        self.prometheus = PrometheusClient(settings.prometheus_url, self.instance_map)
        self.edgex = edgex or EdgeXClient(
            settings.edgex_core_metadata_url,
            settings.edgex_core_data_url,
            settings.edgex_timeout_seconds,
        )
        self.resource_recorder = InfluxResourceProfileRecorder(
            settings.influxdb_url,
            settings.influxdb_org,
            settings.influxdb_bucket,
            settings.influxdb_token,
        )
        self._service_resource_profiles: list[dict[str, Any]] = []
        self._last_resource_recorded_at: datetime | None = None
        self._last_resource_record_result = "never_recorded"
        self.kube = KubeClient()
        self._poller_task: asyncio.Task | None = None
        self._resource_profile_recorder_task: asyncio.Task | None = None
        self.bindings = bindings
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._monotonic = monotonic or time.monotonic
        self._edgex_event_query_semaphore = asyncio.Semaphore(
            settings.edgex_event_query_concurrency
        )
        self._device_snapshot_lock = asyncio.Lock()
        self._device_snapshot: tuple[DeviceState, ...] | None = None
        self._device_snapshot_expires_at = 0.0
        self._device_snapshot_last_success_at: datetime | None = None
        self._device_snapshot_last_duration_seconds: float | None = None
        self._device_snapshot_refresh_count = 0
        self._device_snapshot_refresh_failure_count = 0
        self._device_snapshot_error: EdgeXError | None = None
        self._device_snapshot_error_expires_at = 0.0
        self._projection_observation: ProjectionObservation | None = None
        self._projection_observer_task: asyncio.Task | None = None

    async def start(self) -> None:
        if self._poller_task is None:
            self.invalidate_device_snapshot()
            self._poller_task = asyncio.create_task(self._poll_prometheus())
        if self.settings.resource_profile_recording_mode == "scheduled" and self._resource_profile_recorder_task is None:
            self._resource_profile_recorder_task = asyncio.create_task(self._record_resource_profiles_periodically())
        if (
            self.settings.virtual_device_projection_enabled
            and self.bindings is not None
            and self._projection_observer_task is None
        ):
            self._projection_observer_task = asyncio.create_task(
                self._observe_virtual_devices()
            )

    async def stop(self) -> None:
        tasks = [
            task
            for task in (
                self._poller_task,
                self._resource_profile_recorder_task,
                self._projection_observer_task,
            )
            if task is not None
        ]
        for task in tasks:
            task.cancel()
        for task in tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._poller_task = None
        self._resource_profile_recorder_task = None
        self._projection_observer_task = None
        self.invalidate_device_snapshot()

    def invalidate_device_snapshot(self) -> None:
        self._device_snapshot = None
        self._device_snapshot_expires_at = 0.0
        self._device_snapshot_error = None
        self._device_snapshot_error_expires_at = 0.0

    async def _poll_prometheus(self) -> None:
        while True:
            try:
                await self.refresh_nodes()
            except Exception:
                logger.exception("Failed to refresh Prometheus node metrics")
            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def _record_resource_profiles_periodically(self) -> None:
        while True:
            await asyncio.sleep(self.settings.resource_profile_record_interval_seconds)
            try:
                await self.record_service_resource_profiles(window=self.settings.resource_profile_window)
            except Exception:
                logger.exception("Failed to record scheduled service resource profile snapshot")
    async def _observe_virtual_devices(self) -> None:
        while True:
            await self.record_virtual_device_observation()
            await asyncio.sleep(self.settings.virtual_device_observer_interval_seconds)


    async def refresh_nodes(self) -> list[NodeState]:
        # Dynamically discover nodes from K8s API
        new_map = await self.kube.get_node_map()
        current_node_names = {mapping["hostname"] for mapping in new_map.values() if mapping.get("hostname")}
        if new_map:
            self.prometheus.instance_map = new_map

        raw_nodes = await self.prometheus.collect_node_metrics()
        states = [normalize_node_state(item) for item in raw_nodes]
        if current_node_names:
            states = [state for state in states if state.hostname in current_node_names]
        self.store.replace_node_states(states)
        await self.refresh_service_resource_profiles()
        return states

    def record_workflow_event(self, event: WorkflowEvent) -> WorkflowState:
        previous = self.store.workflows.get(event.workflow_id)
        workflow_state = normalize_workflow_state(event, previous)
        self.store.record_workflow_event(event, workflow_state)
        return workflow_state

    def get_nodes(self) -> list[NodeState]:
        return self.store.get_node_states()

    def get_node(self, hostname: str) -> NodeState | None:
        return self.store.nodes.get(hostname)

    def get_workflows(self) -> list[WorkflowState]:
        return self.store.get_workflow_states()

    def get_workflow(self, workflow_id: str) -> WorkflowState | None:
        return self.store.workflows.get(workflow_id)

    def get_summary(self) -> SummaryState:
        return build_summary(self.get_nodes(), self.get_workflows())

    def get_cost_model(self) -> CostModelState:
        return CostModelState(
            node_states=self.get_nodes(),
            stage_cost_stats=self.store.get_stage_cost_stats(),
            migration_cost_stats=self.store.get_migration_cost_stats(),
        )

    async def refresh_service_resource_profiles(self) -> list[dict[str, Any]]:
        pods = await self.kube.get_running_service_pods()
        usage_samples = await self.prometheus.collect_service_resource_usage()
        self._service_resource_profiles = build_service_resource_profiles(pods, usage_samples)
        if self.settings.resource_profile_recording_mode == "poll":
            recorded = await self.resource_recorder.record_snapshot(self._service_resource_profiles)
            self._last_resource_record_result = "recorded" if recorded else "failed"
            if recorded:
                self._last_resource_recorded_at = datetime.now(timezone.utc)
        return self._service_resource_profiles

    async def record_service_resource_profiles(self, window: str | None = None) -> dict[str, Any]:
        profile_window = window or self.settings.resource_profile_window
        pods = await self.kube.get_running_service_pods()
        usage_samples = await self.prometheus.collect_service_resource_profile_usage(window=profile_window)
        profiles = build_service_resource_profiles(pods, usage_samples, profile_window=profile_window)
        self._service_resource_profiles = profiles
        if self.settings.resource_profile_recording_mode == "disabled":
            self._last_resource_record_result = "disabled"
            recorded = False
        else:
            recorded = await self.resource_recorder.record_snapshot(profiles)
            self._last_resource_record_result = "recorded" if recorded else "failed"
            if recorded:
                self._last_resource_recorded_at = datetime.now(timezone.utc)
        return {
            "recorded": recorded,
            "recording_backend": "influxdb",
            "recording_mode": self.settings.resource_profile_recording_mode,
            "recording_interval_seconds": self.settings.resource_profile_record_interval_seconds,
            "last_record_result": self._last_resource_record_result,
            "recorded_at": self._last_resource_recorded_at.isoformat() if self._last_resource_recorded_at else None,
            "profile_scope": "running_service_resource_requirements",
            "profile_window": profile_window,
            "summary": summarize_service_resource_profiles(profiles),
            "service_resource_profiles": profiles,
        }

    async def get_resource_profile_state(self, refresh: bool = False) -> dict[str, Any]:
        if refresh or not self._service_resource_profiles:
            await self.refresh_service_resource_profiles()
        summary = summarize_service_resource_profiles(self._service_resource_profiles)
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "recorded_at": self._last_resource_recorded_at.isoformat() if self._last_resource_recorded_at else None,
            "recording_backend": "influxdb",
            "recording_mode": self.settings.resource_profile_recording_mode,
            "recording_interval_seconds": self.settings.resource_profile_record_interval_seconds,
            "last_record_result": self._last_resource_record_result,
            "profile_scope": "running_service_resource_requirements",
            "summary": summary,
            "service_resource_profiles": self._service_resource_profiles,
        }

    async def get_device_telemetry_history(
        self, device_id: str, window: str = "-30m", limit: int = 300
    ) -> list[TelemetryPoint]:
        match = re.fullmatch(r"-([1-9][0-9]*)([smhdw])", window)
        if match is None:
            raise ValueError("window must be a negative duration such as -30m")
        amount = int(match.group(1))
        unit = match.group(2)
        seconds = amount * {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}[unit]
        start = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        return await self.edgex.get_event_history(device_id, limit=limit, start=start)

    async def _resolve_virtual_device_instances(
        self, instances: list, *, observation_time: datetime, revision: str
    ) -> VirtualDeviceCollection:
        inventory = await self.edgex.get_devices()
        by_name = {device.name: device for device in inventory}
        configured = [
            (instance, by_name.get(instance.physical_device_ref.name))
            for instance in instances
        ]
        profile_names = sorted(
            {
                device.profile_name
                for instance, device in configured
                if device is not None
                and device.profile_name
                == instance.physical_device_ref.expected_profile_name
            }
        )
        profile_results = await asyncio.gather(
            *(self.edgex.get_device_profile(name) for name in profile_names),
            return_exceptions=True,
        )
        profiles: dict[str, object] = dict(zip(profile_names, profile_results))
        profile_failures = [
            value for value in profiles.values()
            if isinstance(value, Exception) and not isinstance(value, EdgeXNotFoundError)
        ]
        if profile_names and len(profile_failures) == len(profile_names):
            raise profile_failures[0]

        semaphore = asyncio.Semaphore(self.settings.virtual_device_observer_concurrency)

        async def event_for(device, group_instances):
            async with semaphore:
                max_freshness = max(
                    capability.freshness_seconds
                    for instance in group_instances
                    for capability in instance.capabilities
                )
                history = await self.edgex.get_bounded_event_history(
                    device.name,
                    observation_time=observation_time,
                    freshness_seconds=max_freshness,
                    page_size=min(
                        self.settings.virtual_device_event_query_page_size,
                        self.bindings.event_query.page_size,
                    ),
                    max_pages=min(
                        self.settings.virtual_device_event_query_max_pages,
                        self.bindings.event_query.max_pages,
                    ),
                    max_events_per_device=min(
                        self.settings.virtual_device_event_query_max_events_per_device,
                        self.bindings.event_query.max_events_per_device,
                    ),
                    max_prior_probe_events_per_device=min(
                        self.settings.virtual_device_event_query_max_prior_probe_events_per_device,
                        self.bindings.event_query.max_prior_probe_events_per_device,
                    ),
                )
                if history.history_truncated:
                    return {
                        instance.id: history.model_copy(
                            update={
                                "uncertain_source_resources": [
                                    (
                                        binding.source_name,
                                        binding.resource_name,
                                    )
                                    for capability in instance.capabilities
                                    for input_ in capability.inputs
                                    for binding in input_.bindings
                                ]
                            }
                        )
                        for instance in group_instances
                    }
                profile = profiles[device.profile_name]
                profile_resources = {
                    resource.name for resource in profile.device_resources
                }

                def has_matching_point(input_, points):
                    aliases = [
                        (binding.source_name, binding.resource_name)
                        for binding in input_.bindings
                        if binding.resource_name in profile_resources
                    ]
                    for point in points:
                        if (
                            point.resource_name
                            and point.resource_name not in profile_resources
                        ):
                            continue
                        if (point.source_name, point.resource_name) in aliases:
                            return True
                        possible = [
                            alias
                            for alias in aliases
                            if (
                                not point.source_name
                                or alias[0] == point.source_name
                            )
                            and (
                                not point.resource_name
                                or alias[1] == point.resource_name
                            )
                        ]
                        if len(possible) == 1:
                            return True
                    return False

                def missing_required(instance):
                    return [
                        input_
                        for capability in instance.capabilities
                        for input_ in capability.inputs
                        if input_.required
                        and not has_matching_point(input_, history.events)
                    ]

                missing_by_instance = {
                    instance.id: missing_required(instance)
                    for instance in group_instances
                }
                if not any(missing_by_instance.values()):
                    return {
                        instance.id: history for instance in group_instances
                    }
                prior_limit = min(
                    self.settings.virtual_device_event_query_max_prior_probe_events_per_device,
                    self.bindings.event_query.max_prior_probe_events_per_device,
                )
                prior_page = await self.edgex.get_prior_event_history(
                    device.name,
                    before=observation_time
                    - timedelta(seconds=max_freshness, microseconds=1),
                    limit=prior_limit,
                )
                instance_histories = {}
                for instance in group_instances:
                    missing = missing_by_instance[instance.id]
                    uncertain_bindings = [
                        (
                            binding.source_name,
                            binding.resource_name,
                        )
                        for input_ in missing
                        if prior_page.history_truncated
                        and not has_matching_point(input_, prior_page.events)
                        for binding in input_.bindings
                    ]
                    instance_histories[instance.id] = history.model_copy(
                        update={
                            "prior_probe_events": prior_page.events,
                            "history_truncated": bool(uncertain_bindings),
                            "uncertain_source_resources": uncertain_bindings,
                        }
                    )
                return instance_histories

        event_groups: dict[
            str, tuple[EdgeXDevice, list[VirtualDeviceInstance]]
        ] = {}
        for instance, device in configured:
            if (
                device is None
                or device.profile_name
                != instance.physical_device_ref.expected_profile_name
                or isinstance(profiles.get(device.profile_name), Exception)
            ):
                continue
            group = event_groups.get(device.name)
            if group is None:
                event_groups[device.name] = (device, [instance])
            else:
                group[1].append(instance)

        event_results = await asyncio.gather(
            *(
                event_for(device, group_instances)
                for device, group_instances in event_groups.values()
            ),
            return_exceptions=True,
        )
        events: dict[str, object] = {}
        for (_, group_instances), result in zip(
            event_groups.values(), event_results
        ):
            if isinstance(result, Exception):
                for instance in group_instances:
                    events[instance.id] = result
            else:
                events.update(result)
        event_failures = [
            result
            for result in event_results
            if isinstance(result, Exception)
            and not isinstance(result, EdgeXNotFoundError)
        ]
        if event_groups and len(event_failures) == len(event_groups):
            raise event_failures[0]

        items: list[VirtualDeviceView] = []
        failures = profile_failures + event_failures
        for instance, device in configured:
            if device is None:
                items.append(resolve_virtual_device(
                    instance, config_revision=revision, observation_time=observation_time,
                    device=None, profile=None, history=None,
                ))
                continue
            if device.profile_name != instance.physical_device_ref.expected_profile_name:
                items.append(
                    resolve_virtual_device(
                        instance,
                        config_revision=revision,
                        observation_time=observation_time,
                        device=device,
                        profile=None,
                        history=None,
                    )
                )
                continue
            profile_result = profiles[device.profile_name]
            if isinstance(profile_result, Exception):
                view = resolve_virtual_device(
                    instance, config_revision=revision, observation_time=observation_time,
                    device=device, profile=None, history=None,
                )
                if not isinstance(profile_result, EdgeXNotFoundError):
                    view = view.model_copy(update={
                        "binding_status": "degraded",
                        "reason_codes": ["upstream_profile_error"],
                    })
                items.append(view)
                continue
            event_result = events.get(instance.id)
            if isinstance(event_result, EdgeXNotFoundError):
                event_result = None
            if isinstance(event_result, Exception):
                view = resolve_virtual_device(
                    instance, config_revision=revision, observation_time=observation_time,
                    device=device, profile=profile_result, history=None,
                )
                items.append(view.model_copy(update={
                    "binding_status": "degraded",
                    "reason_codes": ["upstream_event_error"],
                }))
                continue
            if event_result is None:
                from .models import EventHistoryPage
                event_result = EventHistoryPage(total_count=0)
            items.append(resolve_virtual_device(
                instance, config_revision=revision, observation_time=observation_time,
                device=device, profile=profile_result, history=event_result,
            ))

        observation_error = failures[0] if failures else None
        return VirtualDeviceCollection(
            generated_at=self._clock(), observation_time=observation_time,
            config_revision=revision,
            history_truncated=any(item.history_truncated for item in items),
            items=items,
            observation_error=(
                ProjectionError(
                    code=(
                        "authority_access_denied"
                        if getattr(observation_error, "status_code", None) in {401, 403}
                        else "authority_profile_unavailable"
                        if getattr(observation_error, "operation", None) == "profile"
                        else "authority_event_unavailable"
                    ),
                    upstream="edgex", operation=getattr(observation_error, "operation", None),
                    identity=(
                        str(getattr(observation_error, "identity"))[:128]
                        if getattr(observation_error, "identity", None)
                        else None
                    ),
                    retryable=getattr(observation_error, "retryable", False),
                    status_code=getattr(observation_error, "status_code", None),
                ) if observation_error else None
            ),
        )

    async def get_virtual_devices(self) -> VirtualDeviceCollection:
        if not self.settings.virtual_device_projection_enabled or self.bindings is None:
            raise RuntimeError("projection_not_active")
        observation_time = self._clock()
        return await self._resolve_virtual_device_instances(
            self.bindings.instances, observation_time=observation_time,
            revision=config_revision(self.bindings),
        )

    async def get_virtual_device(self, virtual_device_id: str) -> VirtualDeviceView | None:
        if not self.settings.virtual_device_projection_enabled or self.bindings is None:
            raise RuntimeError("projection_not_active")
        instance = next((item for item in self.bindings.instances if item.id == virtual_device_id), None)
        if instance is None:
            return None
        observation_time = self._clock()
        collection = await self._resolve_virtual_device_instances(
            [instance], observation_time=observation_time, revision=config_revision(self.bindings),
        )
        return collection.items[0]

    async def record_virtual_device_observation(self) -> None:
        try:
            collection = await asyncio.wait_for(
                self.get_virtual_devices(),
                timeout=self.settings.virtual_device_observer_timeout_seconds,
            )
            capability_freshness = {
                (instance.id, capability.id): capability.freshness_seconds
                for instance in self.bindings.instances
                for capability in instance.capabilities
            }
            binding_ready = {
                item.id: item.binding_status == "ready" for item in collection.items
            }
            capability_ready = {
                item.id: {
                    capability.id: (
                        item.physical_device_ref.profile_resolved
                        and item.physical_device_ref.actual_profile_name
                        == item.physical_device_ref.expected_profile_name
                        and item.physical_device_ref.admin_state == "UNLOCKED"
                        and item.physical_device_ref.operating_state == "UP"
                        and all(
                            not input_.required or input_.ready
                            for input_ in capability.inputs
                        )
                    )
                    for capability in item.capabilities
                }
                for item in collection.items
            }
            input_fresh = {
                item.id: {
                    capability.id: {
                        input_.input_id: (
                            input_.original_event_ref is not None
                            and input_.observed_at is not None
                            and input_.observed_at
                            >= collection.observation_time
                            - timedelta(
                                seconds=capability_freshness[
                                    (item.id, capability.id)
                                ]
                            )
                            and input_.observed_at <= collection.observation_time
                        )
                        for input_ in capability.inputs
                    }
                    for capability in item.capabilities
                }
                for item in collection.items
            }
            self._projection_observation = ProjectionObservation(
                config_revision=collection.config_revision,
                completed_at=self._clock(),
                last_success_at=self._clock(),
                binding_ready=binding_ready,
                capability_ready=capability_ready,
                input_fresh=input_fresh,
                reason_codes=sorted(
                    {reason for item in collection.items for reason in item.reason_codes}
                ),
            )
        except Exception as exc:
            logger.exception("Virtual-device observation failed")
            previous = self._projection_observation
            self._projection_observation = ProjectionObservation(
                config_revision=config_revision(self.bindings) if self.bindings else "",
                completed_at=self._clock(),
                last_success_at=previous.last_success_at if previous else None,
                error_class=exc.__class__.__name__,
            )
    async def get_devices(self) -> list[DeviceState]:
        now = self._monotonic()
        if self._device_snapshot is not None and now < self._device_snapshot_expires_at:
            return list(self._device_snapshot)
        if self._device_snapshot_error is not None and now < self._device_snapshot_error_expires_at:
            raise self._device_snapshot_error

        async with self._device_snapshot_lock:
            now = self._monotonic()
            if self._device_snapshot is not None and now < self._device_snapshot_expires_at:
                return list(self._device_snapshot)
            if self._device_snapshot_error is not None and now < self._device_snapshot_error_expires_at:
                raise self._device_snapshot_error

            started_at = self._monotonic()
            self._device_snapshot_refresh_count += 1
            try:
                devices = await self._refresh_devices()
            except EdgeXError as exc:
                self._device_snapshot_refresh_failure_count += 1
                self._device_snapshot_error = EdgeXError(
                    str(exc),
                    operation=exc.operation,
                    identity=exc.identity,
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                )
                self._device_snapshot_error_expires_at = (
                    self._monotonic()
                    + self.settings.edgex_device_error_backoff_seconds
                )
                raise

            completed_at = self._monotonic()
            has_observation_error = any(
                device.telemetry_observation_error for device in devices
            )
            ttl = (
                self.settings.edgex_device_error_backoff_seconds
                if has_observation_error
                else self.settings.edgex_device_snapshot_ttl_seconds
            )
            self._device_snapshot = tuple(devices)
            self._device_snapshot_expires_at = completed_at + ttl
            self._device_snapshot_last_success_at = self._clock()
            self._device_snapshot_last_duration_seconds = max(
                0.0, completed_at - started_at
            )
            self._device_snapshot_error = None
            self._device_snapshot_error_expires_at = 0.0
            return list(self._device_snapshot)

    async def _refresh_devices(self) -> list[DeviceState]:
        inventory = await self.edgex.get_devices()

        async def latest_readings(device_name: str):
            async with self._edgex_event_query_semaphore:
                try:
                    return await self.edgex.get_latest_source_readings(device_name)
                except EdgeXError as exc:
                    return exc

        latest_events = await asyncio.gather(
            *(latest_readings(device.name) for device in inventory)
        )
        devices: list[DeviceState] = []
        for device, readings in zip(inventory, latest_events):
            if isinstance(readings, EdgeXError):
                state = self._normalize_edgex_device(device, [])
                devices.append(
                    state.model_copy(
                        update={
                            "telemetry_observation_error": (
                                f"{readings.__class__.__name__}"
                                + (
                                    f" (HTTP {readings.status_code})"
                                    if readings.status_code is not None
                                    else ""
                                )
                            ),
                            "overall_status": "degraded",
                            "reason": (
                                "EdgeX Core Data event observation failed: "
                                f"{readings.__class__.__name__}"
                            ),
                        }
                    )
                )
                continue
            devices.append(self._normalize_edgex_device(device, readings))
        return devices

    def device_snapshot_diagnostics(self) -> dict[str, Any]:
        age_seconds = None
        if self._device_snapshot_last_success_at is not None:
            age_seconds = max(
                0.0,
                (self._clock() - self._device_snapshot_last_success_at).total_seconds(),
            )
        devices = self._device_snapshot or ()
        return {
            "age_seconds": age_seconds,
            "last_duration_seconds": self._device_snapshot_last_duration_seconds,
            "refresh_count": self._device_snapshot_refresh_count,
            "refresh_failure_count": self._device_snapshot_refresh_failure_count,
            "event_observation_error_count": sum(
                bool(device.telemetry_observation_error) for device in devices
            ),
            "cached_device_count": len(devices),
            "refresh_in_flight": self._device_snapshot_lock.locked(),
        }

    async def get_dashboard(self) -> DashboardState:
        nodes = self.get_nodes()
        devices = await self.get_devices()
        workflows = self.get_workflows()
        summary = build_summary(nodes, workflows)
        kpis = self._build_dashboard_kpis(nodes, devices, workflows)
        resource_state = await self.get_resource_profile_state()
        kpis.update(self._build_resource_profile_kpis(resource_state))
        return DashboardState(
            generated_at=datetime.now(timezone.utc),
            nodes=nodes,
            devices=devices,
            workflows=workflows,
            summary=summary,
            kpis=kpis,
            resource_profiles=resource_state,
        )

    async def get_operator_assistant(self) -> OperatorAssistantState:
        dashboard = await self.get_dashboard()
        focus_devices = []
        for device in dashboard.devices:
            status, reason = self._device_health(device)
            if status in {"degraded", "unavailable"}:
                focus_devices.append(
                    {
                        "name": device.name,
                        "node_name": device.node_name,
                        "status": status,
                        "reason": reason,
                        "admin_state": device.admin_state,
                        "operating_state": device.operating_state,
                        "device_service_available": device.device_service_available,
                        "telemetry_freshness": device.telemetry_freshness,
                    }
                )
        kpis = dashboard.kpis
        summary = (
            "EdgeX 기반 read-only 운영 보조 요약입니다. "
            f"Core Metadata 등록 device {len(dashboard.devices)}개 중 "
            f"available device {kpis.get('available_device_count', 0)}개, "
            f"우선 점검 대상 {kpis.get('operator_focus_count', 0)}개입니다. "
            f"Core Data event freshness 비율은 {kpis.get('core_data_freshness_ratio', 0)}입니다."
        )
        return OperatorAssistantState(
            generated_at=datetime.now(timezone.utc),
            summary_ko=summary,
            focus_devices=focus_devices[:10],
            recommended_actions=self._operator_recommended_actions(focus_devices),
            guardrails=[
                "read-only endpoint: EdgeX 및 Kubernetes 리소스를 수정하지 않는다.",
                "운영자에게 점검 순서만 제안하고 명령 또는 제어를 실행하지 않는다.",
                "Kubernetes node_name은 진단 정보이며 물리 device availability 판단에 사용하지 않는다.",
            ],
            source_endpoints=[
                "/state/dashboard",
                "/state/devices",
                "/state/nodes",
                "/state/summary",
            ],
        )

    def _operator_recommended_actions(self, focus_devices: list[dict[str, Any]]) -> list[str]:
        actions: list[str] = []
        for device in focus_devices:
            name = device.get("name", "unknown-device")
            if str(device.get("admin_state", "")).upper() == "LOCKED":
                actions.append(f"{name}: Core Metadata adminState 잠금 정책을 확인한다.")
            if not device.get("device_service_available", False):
                actions.append(f"{name}: EdgeX device service와 operatingState를 확인한다.")
            if device.get("telemetry_freshness") != "fresh":
                actions.append(f"{name}: Core Data 최신 event와 device service 수집 경로를 확인한다.")
        return actions[:10] or ["현재 우선 점검 대상이 없으므로 EdgeX KPI를 확인한다."]

    async def chat_with_operator_assistant(self, request: OperatorChatRequest) -> OperatorChatResponse:
        assistant = await self.get_operator_assistant()
        system_prompt = self._operator_chat_system_prompt(assistant)
        payload = {
            "model": self.settings.qwen_model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": request.message},
            ],
            "temperature": 0.2,
            "max_tokens": 700,
        }
        endpoint = f"{self.settings.qwen_base_url.rstrip('/')}/chat/completions"
        try:
            async with httpx.AsyncClient(timeout=self.settings.qwen_timeout_seconds) as client:
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.warning("Qwen operator chat request failed: %s", exc)
            return OperatorChatResponse(
                model=self.settings.qwen_model,
                answer="로컬 Qwen 모델에 연결하지 못했습니다. 모델 서버(192.168.0.5:8080) 상태를 확인해 주세요.",
                source_endpoints=assistant.source_endpoints,
                guardrails=assistant.guardrails,
                upstream_status="unavailable",
            )

        answer = self._extract_chat_answer(data)
        return OperatorChatResponse(
            model=self.settings.qwen_model,
            answer=answer or "Qwen 응답이 비어 있습니다. 모델 서버 로그를 확인해 주세요.",
            source_endpoints=assistant.source_endpoints,
            guardrails=assistant.guardrails,
        )

    def _operator_chat_system_prompt(self, assistant: OperatorAssistantState) -> str:
        focus_lines = [
            f"- {item.get('name')}: {item.get('status')} / {item.get('reason')} / node={item.get('node_name')}"
            for item in assistant.focus_devices[:6]
        ]
        actions = "\n".join(f"- {action}" for action in assistant.recommended_actions[:6])
        focus = "\n".join(focus_lines) if focus_lines else "- 현재 우선 점검 device 없음"
        return (
            "You are a read-only Korean operator assistant for an EdgeX physical-device and Kubernetes workload dashboard. "
            "Answer in Korean unless the user asks otherwise. Do not claim you can execute commands. "
            "Do not suggest Kubernetes apply/delete/rollout, MQTT command publishing, actuator control, dynamic offloading, "
            "or agent-assisted planning as actions. Only explain current dashboard signals and safe inspection order.\n\n"
            f"Dashboard summary: {assistant.summary_ko}\n"
            f"Focus devices:\n{focus}\n"
            f"Recommended safe checks:\n{actions}\n"
            f"Guardrails: {'; '.join(assistant.guardrails)}"
        )

    def _extract_chat_answer(self, payload: dict[str, Any]) -> str:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            return ""
        first = choices[0]
        if not isinstance(first, dict):
            return ""
        message = first.get("message")
        if isinstance(message, dict):
            content = message.get("content")
            if isinstance(content, str):
                content = content.strip()
                if content:
                    return content
            reasoning = message.get("reasoning_content")
            if isinstance(reasoning, str):
                reasoning = reasoning.strip()
                if reasoning:
                    return reasoning
        text = first.get("text")
        return text.strip() if isinstance(text, str) else ""

    def _normalize_edgex_device(
        self, device: EdgeXDevice, readings: list[TelemetryPoint]
    ) -> DeviceState:
        latest_timestamp = max(
            (reading.timestamp for reading in readings), default=None
        )
        age_seconds = (
            max(0.0, (datetime.now(timezone.utc) - latest_timestamp).total_seconds())
            if latest_timestamp is not None
            else None
        )
        freshness = (
            "no_events"
            if age_seconds is None
            else "fresh"
            if age_seconds <= self.settings.edgex_event_fresh_seconds
            else "stale"
        )
        operating_state = device.operating_state.upper()
        admin_state = device.admin_state.upper()
        connection_state = (
            "disconnected"
            if admin_state == "LOCKED" or operating_state == "DOWN"
            else "connected"
            if operating_state == "UP"
            else "unknown"
        )
        state = DeviceState(
            name=device.name,
            profile_name=device.profile_name,
            device_service_name=device.device_service_name,
            protocol_names=device.protocol_names,
            admin_state=device.admin_state,
            operating_state=device.operating_state,
            connection_state=connection_state,
            device_service_available=operating_state == "UP",
            latest_event_timestamp=latest_timestamp,
            latest_readings=readings,
            telemetry_freshness=freshness,
            node_name=device.node_name,
        )
        overall_status, reason = self._device_health(state)
        return state.model_copy(
            update={"overall_status": overall_status, "reason": reason}
        )

    def _device_health(self, device: DeviceState) -> tuple[str, str]:
        if device.admin_state.upper() == "LOCKED":
            return "unavailable", "EdgeX adminState is LOCKED"
        operating_state = device.operating_state.upper()
        if operating_state == "DOWN":
            return "unavailable", "EdgeX operatingState is DOWN"
        if operating_state != "UP":
            return "degraded", f"EdgeX operatingState is {operating_state or 'UNKNOWN'}"
        if device.telemetry_freshness == "fresh":
            return "available", "EdgeX device service is UP and latest Core Data event is fresh"
        if device.telemetry_freshness == "stale":
            return "degraded", "EdgeX device service is UP but latest Core Data event is stale"
        return "degraded", "EdgeX device service is UP but no Core Data event is available"

    def _build_dashboard_kpis(
        self,
        nodes: list[NodeState],
        devices: list[DeviceState],
        workflows: list[WorkflowState],
    ) -> dict[str, Any]:
        online_nodes = [node for node in nodes if node.node_health != "unavailable"]
        health = [(device, *self._device_health(device)) for device in devices]
        available_devices = [device for device, status, _ in health if status == "available"]
        degraded_devices = [device for device, status, _ in health if status == "degraded"]
        unavailable_devices = [device for device, status, _ in health if status == "unavailable"]
        connected_devices = [
            device for device in devices if device.connection_state == "connected"
        ]
        service_available_devices = [
            device for device in devices if device.device_service_available
        ]
        event_devices = [
            device for device in devices if device.telemetry_freshness != "no_events"
        ]
        fresh_event_devices = [
            device for device in devices if device.telemetry_freshness == "fresh"
        ]
        stale_event_devices = [
            device for device in devices if device.telemetry_freshness == "stale"
        ]
        event_observation_error_devices = [
            device for device in devices if device.telemetry_observation_error
        ]
        risk_workflows = [workflow for workflow in workflows if workflow.sla_risk != "low"]
        return {
            "node_online_ratio": self._ratio(len(online_nodes), len(nodes)),
            "registered_device_count": len(devices),
            "available_device_count": len(available_devices),
            "degraded_device_count": len(degraded_devices),
            "unavailable_device_count": len(unavailable_devices),
            "edgex_connected_device_count": len(connected_devices),
            "edgex_connection_ratio": self._ratio(len(connected_devices), len(devices)),
            "edgex_operating_up_count": sum(
                device.operating_state.upper() == "UP" for device in devices
            ),
            "edgex_operating_down_count": sum(
                device.operating_state.upper() == "DOWN" for device in devices
            ),
            "edgex_operating_unknown_count": sum(
                device.operating_state.upper() not in {"UP", "DOWN"} for device in devices
            ),
            "edgex_admin_unlocked_count": sum(
                device.admin_state.upper() == "UNLOCKED" for device in devices
            ),
            "edgex_admin_locked_count": sum(
                device.admin_state.upper() == "LOCKED" for device in devices
            ),
            "device_service_available_count": len(service_available_devices),
            "device_service_availability_ratio": self._ratio(
                len(service_available_devices), len(devices)
            ),
            "core_data_event_device_count": len(event_devices),
            "fresh_core_data_event_device_count": len(fresh_event_devices),
            "stale_core_data_event_device_count": len(stale_event_devices),
            "core_data_observation_error_device_count": len(
                event_observation_error_devices
            ),
            "core_data_freshness_ratio": self._ratio(
                len(fresh_event_devices), len(devices)
            ),
            "active_node_count": len(online_nodes),
            "sla_risk_workflow_count": len(risk_workflows),
            "operator_focus_count": len(degraded_devices) + len(unavailable_devices),
        }

    def _build_resource_profile_kpis(self, resource_state: dict[str, Any]) -> dict[str, Any]:
        summary = resource_state.get("summary") or {}
        return {
            "service_resource_profile_count": summary.get("profile_count", 0),
            "service_resource_profile_pod_count": summary.get("running_pod_count", 0),
            "service_resource_profile_container_count": summary.get("container_count", 0),
            "service_resource_request_cpu_cores": summary.get("declared_request_cpu_cores", 0),
            "service_resource_request_memory_mib": summary.get("declared_request_memory_mib", 0),
            "service_resource_current_cpu_usage_cores": summary.get("current_cpu_usage_cores", 0),
            "service_resource_current_memory_working_set_mib": summary.get("current_memory_working_set_mib", 0),
            "service_resource_usage_coverage_ratio": summary.get("usage_coverage_ratio", 0),
            "service_resource_limit_gpu_units": summary.get("declared_limit_gpu_units", 0),
            "service_resource_fully_declared_profile_count": summary.get("fully_declared_profile_count", 0),
            "service_resource_partially_declared_profile_count": summary.get("partially_declared_profile_count", 0),
            "service_resource_profile_recorded": resource_state.get("recorded_at") is not None,
        }

    def _ratio(self, numerator: int, denominator: int) -> float:
        if denominator == 0:
            return 0.0
        return round(numerator / denominator, 3)
