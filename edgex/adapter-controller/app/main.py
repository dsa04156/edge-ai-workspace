from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from typing import Any

from fastapi import FastAPI

from .api import create_controller_router
from .auth import build_auth_provider
from .catalog import RuntimeTemplateCatalog
from .config import Settings
from .device_catalog import DeviceBindingCatalog
from .discovery import DeviceCandidateRegistry
from .discovery_store import SQLiteDiscoveryStore
from .edgex import EdgeXRegistrationClient, EdgeXServiceProbe
from .kube import KubernetesGateway
from .registration import RegistrationCoordinator
from .reconciler import RuntimeReconciler
from .service import AdapterControllerService


logger = logging.getLogger(__name__)


def build_service(settings: Settings) -> AdapterControllerService:
    catalog = RuntimeTemplateCatalog.load(settings.catalog_path)
    device_catalog = DeviceBindingCatalog.load(settings.device_catalog_path)
    kube = KubernetesGateway(namespace=settings.namespace)
    store = SQLiteDiscoveryStore(settings.discovery_database_path)
    edgex_probe = EdgeXServiceProbe(
        settings.core_metadata_url,
        settings.edgex_timeout_seconds,
    )
    reconciler = RuntimeReconciler(
        kube,
        edgex_probe,
        namespace=settings.namespace,
    )
    candidate_registry = (
        DeviceCandidateRegistry(
            catalog,
            kube,
            stale_after_seconds=settings.discovery_stale_after_seconds,
            candidate_limit=settings.discovery_candidate_limit,
            store=store,
            device_catalog=device_catalog,
            plans_path=settings.discovery_plans_path,
        )
        if settings.device_discovery_enabled
        else None
    )
    service = AdapterControllerService(
        catalog,
        kube,
        edgex_probe,
        reconciler,
        namespace=settings.namespace,
        candidate_registry=candidate_registry,
        device_catalog=device_catalog,
    )
    if settings.device_discovery_enabled:
        coordinator = RegistrationCoordinator(
            registry=candidate_registry,
            store=store,
            device_catalog=device_catalog,
            auth_provider=build_auth_provider(
                mode=settings.auth_mode,
                endpoint=settings.auth_endpoint,
                token=settings.auth_token,
                timeout_seconds=settings.auth_timeout_seconds,
            ),
            edge_x=EdgeXRegistrationClient(
                settings.core_metadata_url,
                settings.core_data_url,
                settings.edgex_timeout_seconds,
            ),
            kube=kube,
            runtime_service=service,
            event_timeout_seconds=(
                settings.registration_event_timeout_seconds
            ),
        )
        service.attach_registration_coordinator(coordinator)
    return service


class ServiceHolder:
    def __init__(self, service: Any | None = None) -> None:
        self.service = service

    def bind(self, service: Any) -> None:
        self.service = service

    def _require(self) -> Any:
        if self.service is None:
            raise RuntimeError("Adapter Controller service is not initialized")
        return self.service

    def list_runtimes(self):
        return self._require().list_runtimes()

    def plan(self, request):
        return self._require().plan(request)

    def apply_runtime(self, name, request):
        return self._require().apply_runtime(name, request)

    def restart_runtime(self, name, request):
        return self._require().restart_runtime(name, request)

    def retire_runtime(self, name, request):
        return self._require().retire_runtime(name, request)

    def list_discovery_inventory(self):
        return self._require().list_discovery_inventory()

    def ingest_discovery_report(self, report):
        return self._require().ingest_discovery_report(report)

    def create_manual_candidate(self, request):
        return self._require().create_manual_candidate(request)

    def update_candidate_decision(self, candidate_id, request):
        return self._require().update_candidate_decision(candidate_id, request)

    def delete_candidate(self, candidate_id, request):
        return self._require().delete_candidate(candidate_id, request)

    def get_candidate(self, candidate_id):
        return self._require().get_candidate(candidate_id)

    def approve_candidate(self, candidate_id, request):
        return self._require().approve_candidate(candidate_id, request)

    def reject_candidate(self, candidate_id, request):
        return self._require().reject_candidate(candidate_id, request)

    def retry_candidate(self, candidate_id, request):
        return self._require().retry_candidate(candidate_id, request)

    def reconcile_discovery(self, request):
        return self._require().reconcile_discovery(request)

    def get_discovery_plan(self, node_id):
        return self._require().get_discovery_plan(node_id)

    def put_discovery_plan(self, node_id, plan):
        return self._require().put_discovery_plan(node_id, plan)

    def get_registration(self, candidate_id):
        return self._require().get_registration(candidate_id)

    def list_discovery_events(self, candidate_id=None, limit=200):
        return self._require().list_discovery_events(
            candidate_id=candidate_id,
            limit=limit,
        )

    def list_device_bindings(self):
        return self._require().list_device_bindings()

    def discovery_metrics(self):
        return self._require().discovery_metrics()


def create_app(
    settings: Settings | None = None,
    service: Any | None = None,
) -> FastAPI:
    active_settings = settings or Settings()
    holder = ServiceHolder(service)
    stop_event = asyncio.Event()

    async def reconcile_loop() -> None:
        while not stop_event.is_set():
            try:
                await asyncio.to_thread(holder._require().reconcile_all)
            except Exception:
                logger.exception("AdapterRuntime reconciliation cycle failed")
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=active_settings.reconcile_interval_seconds,
                )
            except TimeoutError:
                continue

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if holder.service is None:
            holder.bind(await asyncio.to_thread(build_service, active_settings))
        task = asyncio.create_task(reconcile_loop())
        try:
            yield
        finally:
            stop_event.set()
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

    application = FastAPI(
        title="edge-adapter-controller",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.include_router(
        create_controller_router(active_settings, holder)
    )
    return application


app = create_app()
