"""Runnable edge telemetry agent and synchronous HTTPS/mTLS command endpoint."""

from __future__ import annotations

import asyncio
import json
import ssl
import threading
import time
from datetime import UTC, datetime
from typing import Any, Awaitable, Callable
from urllib.parse import quote, urlparse

import httpx
import uvicorn
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from .clients import EdgeGatewayClient
from .commands import (
    CommandError,
    CommandExpiredError,
    TerminalCommandCache,
    TerminalCommandResult,
    _authorize_command_execution,
    command_fingerprint,
    command_from_payload,
    _strict_json_bytes,
)
from .config import EdgeSettings
from .mqtt import EdgeMQTTConsumer
from .outbox import EventConflict, EventValidationError, EdgeOutbox, OutboxCapacityExceeded


MAX_DIRECT_EVENT_BYTES = 1024 * 1024


class EdgeCommandExecutor:
    """Posts commands to the explicitly configured local EdgeX command URL template."""

    def __init__(self, url_template: str) -> None:
        parsed = urlparse(url_template.replace("{device_name}", "device"))
        original_segments = urlparse(url_template).path.split("/")
        try:
            port = parsed.port
        except ValueError as error:
            raise ValueError("EDGE_COMMAND_URL_TEMPLATE has an invalid port") from error
        if (url_template.count("{device_name}") != 1 or original_segments.count("{device_name}") != 1
                or "{" in url_template.replace("{device_name}", "") or "}" in url_template.replace("{device_name}", "")
                or parsed.scheme not in {"http", "https"} or not parsed.hostname
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or (port is not None and not 1 <= port <= 65535)):
            raise ValueError("EDGE_COMMAND_URL_TEMPLATE must use exactly one {device_name} path segment")
        self.url_template = url_template
        self.client = httpx.AsyncClient(timeout=10.0)

    async def __call__(self, device_name: str, command: dict[str, Any], expires_at: float) -> dict[str, Any]:
        remaining = expires_at - time.time()
        if remaining <= 0:
            raise CommandExpiredError("command TTL has expired")
        response = await self.client.post(
            self.url_template.format(device_name=quote(device_name, safe="")), json=command, timeout=remaining
        )
        response.raise_for_status()
        try:
            content = response.json() if response.content else {}
        except ValueError as error:
            raise CommandError("local command response is not JSON") from error
        if not isinstance(content, dict):
            raise CommandError("local command response is not an object")
        _strict_json_bytes(content)
        return content

    async def close(self) -> None:
        await self.client.aclose()


CommandExecutor = Callable[[str, dict[str, Any], float], Awaitable[dict[str, Any]]]


class EdgeAgent:
    def __init__(self, settings: EdgeSettings, executor: CommandExecutor | None = None) -> None:
        self.settings = settings
        self.outbox = EdgeOutbox(settings.outbox_path, max_bytes=settings.outbox_max_bytes)
        self.gateway = EdgeGatewayClient(settings.gateway_url, settings.edge_id, settings.auth_secret, settings.tls)
        self.executor = (
            executor or EdgeCommandExecutor(settings.edge_command_url_template)
            if settings.command_enabled
            else None
        )
        self.command_results = TerminalCommandCache(settings.command_dedupe_capacity)
        self._command_lock = asyncio.Lock()
        self._inflight_commands: dict[str, tuple[bytes, asyncio.Future[TerminalCommandResult]]] = {}
        self.last_source_at: float | None = None
        self.last_heartbeat_success_at: float | None = None
        self.last_heartbeat_failure_at: float | None = None
        self.last_heartbeat_error: str | None = None
        self.running = False
        self._lifecycle_lock = threading.RLock()
        self._accepting_events = True
        self._resources_closed = False
        self._consumer_closed = False
        self._outbox_closed = False
        self._gateway_closed = False
        self._executor_closed = False
        self.last_cleanup_error: str | None = None
        self.consumer: EdgeMQTTConsumer | None = None
        if settings.source_mode == "mqtt":
            if (
                settings.local_mqtt_host is None
                or settings.local_mqtt_port is None
                or settings.telemetry_topic is None
                or settings.local_mqtt_session_expiry_seconds is None
            ):
                raise ValueError("MQTT source configuration is incomplete")
            self.consumer = EdgeMQTTConsumer(
                settings.local_mqtt_host,
                settings.local_mqtt_port,
                settings.local_mqtt_tls,
                settings.telemetry_topic,
                self.enqueue_event,
                client_id=f"telemetry-plane-{settings.edge_id}",
                session_expiry_seconds=settings.local_mqtt_session_expiry_seconds,
            )

    def enqueue_event(self, event: dict[str, Any]) -> bool:
        """Commit before source ACK and report whether a new row was inserted."""
        with self._lifecycle_lock:
            if not self._accepting_events:
                raise RuntimeError("edge agent is closing and cannot admit telemetry")
            inserted = self.outbox.enqueue(event)
            self.last_source_at = time.time()
            return inserted

    def _source_age(self, now: float) -> float | None:
        with self._lifecycle_lock:
            return None if self.last_source_at is None else max(0.0, now - self.last_source_at)

    async def aclose(self) -> None:
        """Stop callbacks before closing durable resources; incomplete cleanup is retryable."""
        with self._lifecycle_lock:
            self._accepting_events = False
            self.running = False
            if self._resources_closed:
                return
        errors: list[BaseException] = []
        if not self._consumer_closed:
            try:
                if self.consumer is not None:
                    self.consumer.close()
            except BaseException as error:
                errors.append(error)
            else:
                self._consumer_closed = True
        if not self._outbox_closed:
            try:
                self.outbox.close()
            except BaseException as error:
                errors.append(error)
            else:
                self._outbox_closed = True
        if not self._gateway_closed:
            try:
                await self.gateway.close()
            except BaseException as error:
                errors.append(error)
            else:
                self._gateway_closed = True
        close = getattr(self.executor, "close", None) if self.executor is not None else None
        if close is not None and not self._executor_closed:
            try:
                await close()
            except BaseException as error:
                errors.append(error)
            else:
                self._executor_closed = True
        with self._lifecycle_lock:
            self._resources_closed = not errors
            self.last_cleanup_error = None if not errors else str(errors[0])
        if errors:
            raise errors[0]

    def app(self) -> FastAPI:
        app = FastAPI()

        @app.get("/healthz")
        async def healthz() -> dict[str, str]:
            return {"status": "ok"}

        @app.get("/readyz")
        async def readyz(response: Response) -> dict[str, str]:
            if not self.running:
                response.status_code = 503
                return {"status": "not-ready"}
            return {"status": "ready"}

        @app.get("/metrics")
        async def metrics() -> Response:
            diagnostics = self.outbox.diagnostics()
            oldest = diagnostics.oldest_pending_age or 0.0
            source_age = self._source_age(time.time())
            source_metric = "NaN" if source_age is None else str(source_age)
            heartbeat_success = "NaN" if self.last_heartbeat_success_at is None else str(self.last_heartbeat_success_at)
            heartbeat_failure = "NaN" if self.last_heartbeat_failure_at is None else str(self.last_heartbeat_failure_at)
            heartbeat_healthy = int(self.last_heartbeat_error is None and self.last_heartbeat_success_at is not None)
            return Response("# TYPE telemetry_outbox_oldest_seconds gauge\n"
                            f"telemetry_outbox_oldest_seconds {oldest}\n"
                            "# TYPE telemetry_outbox_pending_events gauge\n"
                            f"telemetry_outbox_pending_events {diagnostics.pending_count}\n"
                            "# TYPE telemetry_outbox_pending_bytes gauge\n"
                            f"telemetry_outbox_pending_bytes {diagnostics.pending_bytes}\n"
                            "# TYPE telemetry_outbox_rejected_events gauge\n"
                            f"telemetry_outbox_rejected_events {diagnostics.rejected_count}\n"
                            "# TYPE telemetry_source_freshness_seconds gauge\n"
                            f"telemetry_source_freshness_seconds {source_metric}\n"
                            "# TYPE telemetry_source_seen gauge\n"
                            f"telemetry_source_seen {int(source_age is not None)}\n"
                            "# TYPE telemetry_heartbeat_transport_healthy gauge\n"
                            f"telemetry_heartbeat_transport_healthy {heartbeat_healthy}\n"
                            "# TYPE telemetry_cleanup_healthy gauge\n"
                            f"telemetry_cleanup_healthy {int(self.last_cleanup_error is None)}\n"
                            "# TYPE telemetry_heartbeat_last_success_timestamp_seconds gauge\n"
                            f"telemetry_heartbeat_last_success_timestamp_seconds {heartbeat_success}\n"
                            "# TYPE telemetry_heartbeat_last_failure_timestamp_seconds gauge\n"
                            f"telemetry_heartbeat_last_failure_timestamp_seconds {heartbeat_failure}\n",
                            media_type="text/plain; version=0.0.4")

        @app.post("/v1/commands/{device_name:path}")
        async def command(device_name: str, request: Request) -> JSONResponse:
            if not self.settings.command_enabled:
                return JSONResponse(
                    {"edge_id": self.settings.edge_id, "command_id": "", "status": "failed",
                     "error": {"code": "commands_disabled", "message": "commands are disabled"}},
                    status_code=503,
                )
            try:
                payload = await request.json()
            except ValueError:
                return JSONResponse(
                    {"edge_id": self.settings.edge_id, "command_id": "", "status": "failed",
                     "error": {"code": "invalid_command", "message": "command payload must be JSON"}},
                    status_code=400,
                )
            if not isinstance(payload, dict):
                return JSONResponse(
                    {"edge_id": self.settings.edge_id, "command_id": "", "status": "failed",
                     "error": {"code": "invalid_command", "message": "command payload must be an object"}},
                    status_code=400,
                )
            command_id = payload.get("command_id")
            command_id = command_id if isinstance(command_id, str) else ""
            failure = lambda code, message, status: JSONResponse(
                {"edge_id": self.settings.edge_id, "command_id": command_id, "status": "failed",
                 "error": {"code": code, "message": message}}, status_code=status)
            if payload.get("edge_id") != self.settings.edge_id:
                return failure("wrong_edge", "command is not addressed to this edge", 403)
            if payload.get("device_name") != device_name:
                return failure("wrong_device", "command device_name does not match URL", 400)
            if not command_id:
                return failure("invalid_command", "command_id must be a non-empty string", 400)
            try:
                command_request = command_from_payload(
                    self.settings.edge_id,
                    device_name,
                    payload,
                    max_ttl_seconds=self.settings.command_max_ttl_seconds,
                    authorize=False,
                )
            except CommandExpiredError as error:
                return failure("command_expired", str(error), 504)
            except CommandError as error:
                return failure("invalid_command", str(error), 400)
            fingerprint = command_fingerprint(command_request)
            async with self._command_lock:
                cached = self.command_results.get(command_request.command_id)
                if cached is not None:
                    if cached.fingerprint != fingerprint:
                        return failure("command_id_conflict", "command_id was already used for different content", 409)
                    return JSONResponse(cached.body, status_code=cached.status_code)
                try:
                    _authorize_command_execution(
                        command_request,
                        max_ttl_seconds=self.settings.command_max_ttl_seconds,
                    )
                except CommandExpiredError as error:
                    return failure("command_expired", str(error), 504)
                inflight = self._inflight_commands.get(command_request.command_id)
                if inflight is not None:
                    if inflight[0] != fingerprint:
                        return failure("command_id_conflict", "command_id is already in use for different content", 409)
                    future = inflight[1]
                    owner = False
                else:
                    future = asyncio.get_running_loop().create_future()
                    future.add_done_callback(lambda completed: completed.exception())
                    self._inflight_commands[command_request.command_id] = (fingerprint, future)
                    owner = True
            if not owner:
                outcome = await asyncio.shield(future)
                return JSONResponse(outcome.body, status_code=outcome.status_code)
            executor = self.executor
            if executor is None:
                outcome = TerminalCommandResult(
                    fingerprint, 503,
                    {"edge_id": self.settings.edge_id, "command_id": command_request.command_id, "status": "failed",
                     "error": {"code": "commands_disabled", "message": "commands are disabled"}},
                )
            else:
                try:
                    remaining = command_request.expires_at - time.time()
                    if remaining <= 0:
                        raise CommandExpiredError("command TTL has expired")
                    async with asyncio.timeout(remaining):
                        result = await executor(device_name, command_request.command, command_request.expires_at)
                    if command_request.expires_at <= time.time():
                        raise CommandExpiredError("command TTL has expired")
                    if not isinstance(result, dict):
                        raise CommandError("local command response is not an object")
                    _strict_json_bytes(result)
                except TimeoutError:
                    outcome = TerminalCommandResult(
                        fingerprint, 504,
                        {"edge_id": self.settings.edge_id, "command_id": command_request.command_id,
                         "status": "failed",
                         "error": {"code": "command_expired", "message": "command TTL expired during local execution"}},
                    )
                except CommandExpiredError as error:
                    outcome = TerminalCommandResult(
                        fingerprint, 504,
                        {"edge_id": self.settings.edge_id, "command_id": command_request.command_id,
                         "status": "failed", "error": {"code": "command_expired", "message": str(error)}},
                    )
                except (httpx.HTTPError, CommandError) as error:
                    outcome = TerminalCommandResult(
                        fingerprint, 502,
                        {"edge_id": self.settings.edge_id, "command_id": command_request.command_id,
                         "status": "failed", "error": {"code": "local_command_failed", "message": str(error) or "local command failed"}},
                    )
                except BaseException as error:
                    async with self._command_lock:
                        self._inflight_commands.pop(command_request.command_id, None)
                        if not future.done():
                            future.set_exception(error)
                    raise
                else:
                    outcome = TerminalCommandResult(
                        fingerprint, 200,
                        {"edge_id": self.settings.edge_id, "command_id": command_request.command_id,
                         "status": "succeeded", "result": result},
                    )
            async with self._command_lock:
                self._inflight_commands.pop(command_request.command_id, None)
                self.command_results.put(command_request.command_id, outcome)
                if not future.done():
                    future.set_result(outcome)
            return JSONResponse(outcome.body, status_code=outcome.status_code)
        return app

    def adapter_app(self) -> FastAPI:
        """Loopback-only ingress used by direct protocol adapters on the edge host."""
        app = FastAPI()

        @app.post("/v1/events")
        async def enqueue(request: Request) -> JSONResponse:
            body = await request.body()
            if len(body) > MAX_DIRECT_EVENT_BYTES:
                return JSONResponse(
                    {"error": {"code": "event_too_large", "message": "event exceeds 1 MiB"}},
                    status_code=413,
                )
            try:
                event = json.loads(body)
            except (UnicodeDecodeError, json.JSONDecodeError):
                return JSONResponse(
                    {"error": {"code": "invalid_json", "message": "event body must be JSON"}},
                    status_code=400,
                )
            try:
                inserted = self.enqueue_event(event)
            except EventConflict as error:
                return JSONResponse(
                    {"error": {"code": "event_id_conflict", "message": str(error)}},
                    status_code=409,
                )
            except EventValidationError as error:
                return JSONResponse(
                    {"error": {"code": "invalid_event", "message": str(error)}},
                    status_code=422,
                )
            except OutboxCapacityExceeded as error:
                return JSONResponse(
                    {"error": {"code": "outbox_full", "message": str(error)}},
                    status_code=507,
                )
            except RuntimeError as error:
                return JSONResponse(
                    {"error": {"code": "agent_unavailable", "message": str(error)}},
                    status_code=503,
                )
            return JSONResponse(
                {
                    "status": "queued",
                    "edge_id": self.settings.edge_id,
                    "event_id": event["id"],
                    "deduplicated": not inserted,
                },
                status_code=202,
            )

        return app

    async def run(self) -> None:
        next_heartbeat = 0.0
        try:
            with self._lifecycle_lock:
                if self._resources_closed:
                    return
                self.running = True
                if self.consumer is not None:
                    self.consumer.start()
            while True:
                sent = await self.gateway.flush_one(self.outbox)
                now = time.time()
                if now >= next_heartbeat:
                    diagnostics = self.outbox.diagnostics(now)
                    oldest = diagnostics.oldest_pending_age or 0.0
                    source_age = self._source_age(now)
                    heartbeat = {
                        "edge_id": self.settings.edge_id,
                        "source_seen": source_age is not None,
                        "export_lag_seconds": oldest,
                        "outbox_oldest_seconds": oldest,
                        "observed_at": datetime.now(UTC).isoformat(),
                    }
                    if source_age is not None:
                        heartbeat["source_freshness_seconds"] = source_age
                    try:
                        await self.gateway.heartbeat(heartbeat)
                    except httpx.HTTPError as error:
                        self.last_heartbeat_failure_at = time.time()
                        self.last_heartbeat_error = str(error)
                    else:
                        self.last_heartbeat_success_at = time.time()
                        self.last_heartbeat_error = None
                    next_heartbeat = now + 30
                if not sent:
                    await asyncio.sleep(1)
        finally:
            await self.aclose()


def uvicorn_kwargs(settings: EdgeSettings) -> dict[str, object]:
    return {"host": "0.0.0.0", "port": settings.health_port, "ssl_certfile": settings.tls.cert_file,
            "ssl_keyfile": settings.tls.key_file, "ssl_ca_certs": settings.tls.ca_file,
            "ssl_cert_reqs": ssl.CERT_REQUIRED}


def direct_uvicorn_kwargs(settings: EdgeSettings) -> dict[str, object]:
    return {"host": settings.direct_adapter_host, "port": settings.direct_adapter_port}


def main() -> None:
    settings = EdgeSettings.from_env()
    agent = EdgeAgent(settings)

    async def serve() -> None:
        servers = [uvicorn.Server(uvicorn.Config(agent.app(), log_level="info", **uvicorn_kwargs(settings)))]
        if settings.source_mode == "direct":
            servers.append(uvicorn.Server(uvicorn.Config(
                agent.adapter_app(), log_level="info", **direct_uvicorn_kwargs(settings)
            )))
        server_tasks = {asyncio.create_task(server.serve()) for server in servers}
        agent_task = asyncio.create_task(agent.run())
        done, pending = await asyncio.wait({*server_tasks, agent_task}, return_when=asyncio.FIRST_COMPLETED)
        for server in servers:
            server.should_exit = True
        for task in pending:
            task.cancel()
        results = await asyncio.gather(*pending, return_exceptions=True)
        try:
            for task in done:
                task.result()
            for result in results:
                if isinstance(result, BaseException) and not isinstance(result, asyncio.CancelledError):
                    raise result
        finally:
            await agent.aclose()

    asyncio.run(serve())


if __name__ == "__main__":
    main()
