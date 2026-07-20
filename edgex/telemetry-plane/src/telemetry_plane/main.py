"""Runnable central HTTPS gateway with PostgreSQL inbox and HTTPS edge command routing."""

from __future__ import annotations
import asyncio

import ssl

import uvicorn

from .commands import HTTPSCommandBridge
from .config import GatewaySettings
from .gateway import HTTPXCoreDataAdapter, PostgreSQLInbox, PostgreSQLReplayGuard, close_owned_resources, create_app


def build_app(settings: GatewaySettings):
    resources: list[object] = []
    try:
        inbox = PostgreSQLInbox(settings.database_url)
        resources.append(inbox)
        core_data = HTTPXCoreDataAdapter(settings.core_data_url, settings.core_data_service_name)
        resources.append(core_data)
        replay_guard = PostgreSQLReplayGuard(settings.database_url)
        resources.append(replay_guard)
        app_kwargs = {
            "inbox": inbox,
            "core_data": core_data,
            "edge_auth_secrets": settings.edge_auth_secrets,
            "replay_guard": replay_guard,
        }
        if settings.command_enabled:
            command_bridge = HTTPSCommandBridge(
                settings.command_endpoints,
                settings.tls,
                command_timeout_seconds=settings.command_timeout_seconds,
                max_ttl_seconds=settings.command_max_ttl_seconds,
            )
            resources.append(command_bridge)
            app_kwargs.update(
                command_bridge=command_bridge,
                command_auth_token=settings.command_auth_token,
                command_targets=set(settings.command_endpoints),
            )
        return create_app(**app_kwargs, owned_resources=tuple(resources))
    except BaseException:
        asyncio.run(close_owned_resources(tuple(resources)))
        raise


def uvicorn_kwargs(settings: GatewaySettings) -> dict[str, object]:
    return {"host": "0.0.0.0", "port": settings.port, "ssl_certfile": settings.tls.cert_file,
            "ssl_keyfile": settings.tls.key_file, "ssl_ca_certs": settings.tls.ca_file,
            "ssl_cert_reqs": ssl.CERT_REQUIRED}


def main() -> None:
    settings = GatewaySettings.from_env()
    uvicorn.run(build_app(settings), **uvicorn_kwargs(settings))


if __name__ == "__main__":
    main()
