import asyncio
import ssl
import time
import httpx
import pytest

from telemetry_plane.config import (
    DEFAULT_OUTBOX_MAX_BYTES,
    MAX_OUTBOX_BYTES,
    MAX_LOCAL_MQTT_SESSION_EXPIRY_SECONDS,
    ConfigurationError,
    EdgeSettings,
    GatewaySettings,
)
from telemetry_plane.edge import EdgeAgent, uvicorn_kwargs as edge_uvicorn_kwargs
from telemetry_plane.gateway import HTTPXCoreDataAdapter
from telemetry_plane import main as runtime_main


def tls_env(prefix="TELEMETRY_TLS_"):
    return {f"{prefix}CA_FILE": "/tls/ca.pem", f"{prefix}CERT_FILE": "/tls/client.pem", f"{prefix}KEY_FILE": "/tls/client.key"}


def gateway_env(**overrides):
    env = {
        "TELEMETRY_DATABASE_URL": "postgresql://db/telemetry",
        "CORE_DATA_URL": "http://core-data",
        "CORE_DATA_SERVICE_NAME": "gateway",
        "TELEMETRY_EDGE_AUTH_SECRETS_JSON": '{"etri-dev0001-jetorn":"edge-secret"}',
        "COMMAND_ENABLED": "true",
        "COMMAND_EDGE_ENDPOINTS_JSON": '{"etri-dev0001-jetorn":"https://edge-one:8443"}',
        "COMMAND_AUTH_TOKEN": "command-token",
        **tls_env(),
    }
    env.update(overrides)
    return env
def edge_event(identifier="11111111-1111-4111-8111-111111111111"):
    return {
        "apiVersion": "v3",
        "id": identifier,
        "deviceName": "device",
        "profileName": "profile",
        "sourceName": "source",
        "origin": 100,
        "readings": [{
            "id": "22222222-2222-4222-8222-222222222222",
            "deviceName": "device",
            "profileName": "profile",
            "resourceName": "value",
            "valueType": "Int64",
            "value": 1,
            "origin": 100,
        }],
    }




def test_gateway_runtime_configuration_requires_strict_auth_and_https_command_mappings():
    settings = GatewaySettings.from_env(gateway_env())
    assert settings.port == 8443
    assert settings.command_endpoints == {"etri-dev0001-jetorn": "https://edge-one:8443"}
    assert settings.command_auth_token == "command-token"
    assert settings.edge_auth_secrets == {"etri-dev0001-jetorn": "edge-secret"}
    assert settings.command_max_ttl_seconds == 30

    with pytest.raises(ConfigurationError, match="TELEMETRY_EDGE_AUTH_SECRETS_JSON"):
        GatewaySettings.from_env(gateway_env(TELEMETRY_EDGE_AUTH_SECRETS_JSON=""))
    with pytest.raises(ConfigurationError, match="JSON object"):
        GatewaySettings.from_env(gateway_env(COMMAND_EDGE_ENDPOINTS_JSON="edge=https://edge-one:8443"))
    with pytest.raises(ConfigurationError, match="HTTPS"):
        GatewaySettings.from_env(gateway_env(COMMAND_EDGE_ENDPOINTS_JSON='{"etri-dev0001-jetorn":"http://edge-one:8443"}'))
    with pytest.raises(ConfigurationError, match="explicit valid port"):
        GatewaySettings.from_env(gateway_env(COMMAND_EDGE_ENDPOINTS_JSON='{"etri-dev0001-jetorn":"https://edge-one"}'))

def test_commands_disabled_do_not_require_command_token_endpoints_or_local_command_url():
    gateway = GatewaySettings.from_env(gateway_env(
        COMMAND_ENABLED="false",
        COMMAND_EDGE_ENDPOINTS_JSON="",
        COMMAND_AUTH_TOKEN="",
    ))
    assert not gateway.command_enabled
    assert gateway.command_endpoints == {}
    assert gateway.command_auth_token is None

    edge = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": "/data/outbox.db",
        "LOCAL_MQTT_HOST": "localhost",
        **tls_env(),
    })
    assert not edge.command_enabled
    assert edge.edge_command_url_template is None
    for invalid_url in (
        "http://gateway:8443",
        "https://gateway",
        "https://user:password@gateway:8443",
        "https://gateway:8443?query=value",
        "https://gateway:8443#fragment",
        "https://gateway:not-a-port",
    ):
        with pytest.raises(ConfigurationError, match="GATEWAY_URL"):
            EdgeSettings.from_env({
                "EDGE_ID": "etri-dev0001-jetorn",
                "GATEWAY_URL": invalid_url,
                "EDGE_AUTH_SECRET": "edge-secret",
                "OUTBOX_PATH": "/data/outbox.db",
                "LOCAL_MQTT_HOST": "localhost",
                **tls_env(),
            })


    with pytest.raises(ConfigurationError, match="COMMAND_EDGE_ENDPOINTS_JSON"):
        GatewaySettings.from_env(gateway_env(COMMAND_EDGE_ENDPOINTS_JSON=""))
    with pytest.raises(ConfigurationError, match="COMMAND_AUTH_TOKEN"):
        GatewaySettings.from_env(gateway_env(COMMAND_AUTH_TOKEN=""))
    with pytest.raises(ConfigurationError, match="EDGE_COMMAND_URL_TEMPLATE"):
        EdgeSettings.from_env({
            "EDGE_ID": "etri-dev0001-jetorn",
            "GATEWAY_URL": "https://gateway:8443",
            "EDGE_AUTH_SECRET": "edge-secret",
            "OUTBOX_PATH": "/data/outbox.db",
            "LOCAL_MQTT_HOST": "localhost",
            "COMMAND_ENABLED": "true",
            **tls_env(),
        })


def test_build_app_uses_per_edge_auth_mapping_and_bounded_command_bridge(monkeypatch):
    captured = {}

    class Bridge:
        def __init__(self, *args, **kwargs):
            captured["bridge"] = (args, kwargs)

    monkeypatch.setattr(runtime_main, "PostgreSQLInbox", lambda value: ("inbox", value))
    replay_guard = object()
    monkeypatch.setattr(runtime_main, "PostgreSQLReplayGuard", lambda value: replay_guard)
    monkeypatch.setattr(runtime_main, "HTTPXCoreDataAdapter", lambda *args: ("core-data", args))
    monkeypatch.setattr(runtime_main, "HTTPSCommandBridge", Bridge)
    monkeypatch.setattr(runtime_main, "create_app", lambda **kwargs: captured.setdefault("app", kwargs))
    runtime_main.build_app(GatewaySettings.from_env(gateway_env()))

    assert captured["app"]["edge_auth_secrets"] == {"etri-dev0001-jetorn": "edge-secret"}
    assert captured["app"]["command_auth_token"] == "command-token"
    assert captured["app"]["command_targets"] == {"etri-dev0001-jetorn"}
    assert captured["bridge"][1] == {"command_timeout_seconds": 10, "max_ttl_seconds": 30}
    assert captured["app"]["replay_guard"] is replay_guard


def test_build_app_disabled_omits_command_wiring(monkeypatch):
    captured = {}
    monkeypatch.setattr(runtime_main, "PostgreSQLInbox", lambda value: ("inbox", value))
    replay_guard = object()
    monkeypatch.setattr(runtime_main, "PostgreSQLReplayGuard", lambda value: replay_guard)
    monkeypatch.setattr(runtime_main, "HTTPXCoreDataAdapter", lambda *args: ("core-data", args))
    monkeypatch.setattr(runtime_main, "create_app", lambda **kwargs: captured.setdefault("app", kwargs))

    runtime_main.build_app(GatewaySettings.from_env(gateway_env(
        COMMAND_ENABLED="false",
        COMMAND_EDGE_ENDPOINTS_JSON="",
        COMMAND_AUTH_TOKEN="",
    )))

    assert "command_bridge" not in captured["app"]
    assert "command_auth_token" not in captured["app"]
    assert "command_targets" not in captured["app"]
    assert captured["app"]["replay_guard"] is replay_guard


def test_edge_runtime_configuration_requires_non_default_secret_and_bounded_command_values():
    env = {
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": "/data/outbox.db",
        "LOCAL_MQTT_HOST": "localhost",
        "EDGE_COMMAND_URL_TEMPLATE": "http://core-command/api/v3/device/{device_name}",
        "COMMAND_ENABLED": "true",
        **tls_env(),
        **tls_env("LOCAL_MQTT_TLS_"),
    }
    settings = EdgeSettings.from_env(env)
    assert settings.auth_secret == "edge-secret"
    assert settings.command_dedupe_capacity == 1024
    assert edge_uvicorn_kwargs(settings)["ssl_cert_reqs"] == ssl.CERT_REQUIRED
    assert settings.telemetry_topic == "edgex/events/#"
    assert settings.outbox_max_bytes == DEFAULT_OUTBOX_MAX_BYTES
    assert settings.local_mqtt_session_expiry_seconds == 3600

    with pytest.raises(ConfigurationError, match="EDGE_AUTH_SECRET"):
        EdgeSettings.from_env({key: value for key, value in env.items() if key != "EDGE_AUTH_SECRET"})
    with pytest.raises(ConfigurationError, match="COMMAND_MAX_TTL_SECONDS"):
        EdgeSettings.from_env({**env, "COMMAND_MAX_TTL_SECONDS": "0"})
    with pytest.raises(ConfigurationError, match="COMMAND_DEDUPE_CAPACITY"):
        EdgeSettings.from_env({**env, "COMMAND_DEDUPE_CAPACITY": "100001"})
    with pytest.raises(ConfigurationError, match="EDGE_OUTBOX_MAX_BYTES"):
        EdgeSettings.from_env({**env, "EDGE_OUTBOX_MAX_BYTES": str(MAX_OUTBOX_BYTES + 1)})
    with pytest.raises(ConfigurationError, match="LOCAL_MQTT_SESSION_EXPIRY_SECONDS"):
        EdgeSettings.from_env({**env, "LOCAL_MQTT_SESSION_EXPIRY_SECONDS": str(MAX_LOCAL_MQTT_SESSION_EXPIRY_SECONDS + 1)})


def test_edge_configuration_rejects_legacy_secret_blank_topic_and_unsafe_url_template():
    env = {
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_HEARTBEAT_SECRET": "legacy-secret",
        "OUTBOX_PATH": "/data/outbox.db",
        "LOCAL_MQTT_HOST": "localhost",
        **tls_env(),
    }
    with pytest.raises(ConfigurationError, match="EDGE_AUTH_SECRET"):
        EdgeSettings.from_env(env)
    strict_env = {**env, "EDGE_AUTH_SECRET": "edge-secret"}
    with pytest.raises(ConfigurationError, match="LOCAL_TELEMETRY_TOPIC"):
        EdgeSettings.from_env({**strict_env, "LOCAL_TELEMETRY_TOPIC": ""})
    for template in (
        "http://core-command/api/{device_name}/read/{device_name}",
        "http://core-command/api/prefix-{device_name}",
        "http://core-command/api/{other}",
    ):
        with pytest.raises(ConfigurationError, match="EDGE_COMMAND_URL_TEMPLATE"):
            EdgeSettings.from_env({**strict_env, "COMMAND_ENABLED": "true", "EDGE_COMMAND_URL_TEMPLATE": template})

def test_edge_agent_closes_callback_path_before_durable_resources(monkeypatch, tmp_path):
    consumers = []
    gateways = []

    class Consumer:
        def __init__(self, *args, **kwargs):
            self.closed = False
            consumers.append(self)

        def start(self):
            return None

        def close(self):
            self.closed = True

    class Gateway:
        def __init__(self, *args):
            self.closed = False
            gateways.append(self)

        async def close(self):
            self.closed = True

    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    env = {
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        "EDGE_COMMAND_URL_TEMPLATE": "http://core-command/api/v3/device/{device_name}",
        **tls_env(),
    }
    agent = EdgeAgent(EdgeSettings.from_env(env), executor=lambda *_: None)
    agent.enqueue_event(edge_event())

    asyncio.run(agent.aclose())

    assert consumers[0].closed
    assert gateways[0].closed
    with pytest.raises(RuntimeError, match="closing"):
        agent.enqueue_event(edge_event("33333333-3333-4333-8333-333333333333"))

def test_disabled_command_route_returns_503_without_creating_executor(monkeypatch, tmp_path):
    class Consumer:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        **tls_env(),
    })
    agent = EdgeAgent(settings, executor=lambda *_: (_ for _ in ()).throw(AssertionError("must not execute")))
    assert agent.executor is None

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent.app()), base_url="https://edge") as client:
            metrics = await client.get("/metrics")
            response = await client.post("/v1/commands/device-1", json={"command_id": "cmd-1"})
            return metrics.text, response

    initial_metrics, response = asyncio.run(run())
    assert "telemetry_source_freshness_seconds NaN" in initial_metrics
    assert "telemetry_source_seen 0" in initial_metrics
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "commands_disabled"
    agent.enqueue_event(edge_event("44444444-4444-4444-8444-444444444444"))
    item = agent.outbox.claim()
    assert item is not None
    agent.outbox.reject(item.event_id, item.claim_token, "invalid event")

    async def metrics():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent.app()), base_url="https://edge") as client:
            return await client.get("/metrics")

    assert "telemetry_outbox_rejected_events 1" in asyncio.run(metrics()).text
    asyncio.run(agent.aclose())
def test_encoded_slash_device_command_reaches_executor_and_rejects_payload_mismatch(monkeypatch, tmp_path):
    class Consumer:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    calls = []

    async def executor(device_name, command, expires_at):
        calls.append((device_name, command))
        return {"state": "ready"}

    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        "EDGE_COMMAND_URL_TEMPLATE": "http://core-command/api/v3/device/{device_name}",
        "COMMAND_ENABLED": "true",
        **tls_env(),
    })
    agent = EdgeAgent(settings, executor=executor)
    now = time.time()
    payload = {
        "edge_id": settings.edge_id,
        "device_name": "camera/a b",
        "command_id": "encoded-device-command",
        "issued_at": now,
        "expires_at": now + 5,
        "operation": "read_status",
        "command": {},
        "authorization_version": "authz-v1",
        "policy_version": "policy-v1",
        "idempotency_classification": "idempotent",
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent.app()), base_url="https://edge") as client:
            succeeded = await client.post("/v1/commands/camera%2Fa%20b", json=payload)
            mismatched = await client.post(
                "/v1/commands/camera%2Fa%20b",
                json={**payload, "device_name": "camera/a-c", "command_id": "mismatched-device-command"},
            )
            return succeeded, mismatched

    succeeded, mismatched = asyncio.run(run())
    assert succeeded.status_code == 200
    assert calls == [("camera/a b", {})]
    assert mismatched.status_code == 400
    assert mismatched.json()["error"]["code"] == "wrong_device"
    assert calls == [("camera/a b", {})]
    asyncio.run(agent.aclose())
def test_command_api_double_encoded_device_identity_decodes_once_and_requires_exact_match(monkeypatch, tmp_path):
    class Consumer:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    calls = []

    async def executor(device_name, command, expires_at):
        calls.append((device_name, command))
        return {"state": "ready"}

    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    now = 1_700_000_000.0
    monkeypatch.setattr("telemetry_plane.edge.time.time", lambda: now)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        "EDGE_COMMAND_URL_TEMPLATE": "http://core-command/api/v3/device/{device_name}",
        "COMMAND_ENABLED": "true",
        **tls_env(),
    })
    agent = EdgeAgent(settings, executor=executor)
    payload = {
        "edge_id": settings.edge_id,
        "device_name": "camera%2Fa",
        "command_id": "double-encoded-device-command",
        "issued_at": now,
        "expires_at": now + 5,
        "operation": "read_status",
        "command": {},
        "authorization_version": "authz-v1",
        "policy_version": "policy-v1",
        "idempotency_classification": "idempotent",
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent.app()), base_url="https://edge") as client:
            succeeded = await client.post("/v1/commands/camera%252Fa", json=payload)
            mismatched = await client.post(
                "/v1/commands/camera%252Fa",
                json={**payload, "device_name": "camera/a", "command_id": "double-encoded-mismatch"},
            )
            return succeeded, mismatched

    succeeded, mismatched = asyncio.run(run())
    assert succeeded.status_code == 200
    assert succeeded.json()["status"] == "succeeded"
    assert calls == [("camera%2Fa", {})]
    assert "/" not in calls[0][0]
    assert mismatched.status_code == 400
    assert mismatched.json()["error"]["code"] == "wrong_device"
    assert calls == [("camera%2Fa", {})]
    asyncio.run(agent.aclose())


def test_command_api_empty_route_and_blank_device_identity_fail_closed(monkeypatch, tmp_path):
    class Consumer:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    calls = []

    async def executor(device_name, command, expires_at):
        calls.append((device_name, command))
        return {"state": "ready"}

    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    now = 1_700_000_000.0
    monkeypatch.setattr("telemetry_plane.edge.time.time", lambda: now)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        "EDGE_COMMAND_URL_TEMPLATE": "http://core-command/api/v3/device/{device_name}",
        "COMMAND_ENABLED": "true",
        **tls_env(),
    })
    agent = EdgeAgent(settings, executor=executor)
    payload = {
        "edge_id": settings.edge_id,
        "device_name": "",
        "command_id": "blank-device-command",
        "issued_at": now,
        "expires_at": now + 5,
        "operation": "read_status",
        "command": {},
        "authorization_version": "authz-v1",
        "policy_version": "policy-v1",
        "idempotency_classification": "idempotent",
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent.app()), base_url="https://edge") as client:
            empty_route = await client.post("/v1/commands", json=payload)
            blank_identity = await client.post("/v1/commands/", json=payload)
            return empty_route, blank_identity

    empty_route, blank_identity = asyncio.run(run())
    assert empty_route.status_code == 307
    assert blank_identity.status_code == 400
    assert blank_identity.json()["error"] == {
        "code": "invalid_command",
        "message": "device_name must be a non-empty string",
    }
    assert calls == []
    asyncio.run(agent.aclose())


def test_command_api_wrong_edge_is_rejected_before_execution(monkeypatch, tmp_path):
    class Consumer:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    calls = []

    async def executor(device_name, command, expires_at):
        calls.append((device_name, command, expires_at))
        return {"state": "ready"}

    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    now = 1_700_000_000.0
    monkeypatch.setattr("telemetry_plane.edge.time.time", lambda: now)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        "EDGE_COMMAND_URL_TEMPLATE": "http://core-command/api/v3/device/{device_name}",
        "COMMAND_ENABLED": "true",
        **tls_env(),
    })
    agent = EdgeAgent(settings, executor=executor)
    payload = {
        "edge_id": "etri-dev0002-raspi5",
        "device_name": "camera-a",
        "command_id": "wrong-edge-command",
        "issued_at": now,
        "expires_at": now + 5,
        "operation": "read_status",
        "command": {},
        "authorization_version": "authz-v1",
        "policy_version": "policy-v1",
        "idempotency_classification": "idempotent",
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent.app()), base_url="https://edge") as client:
            return await client.post("/v1/commands/camera-a", json=payload)

    response = asyncio.run(run())

    assert response.status_code == 403
    assert response.json() == {
        "edge_id": settings.edge_id,
        "command_id": payload["command_id"],
        "status": "failed",
        "error": {"code": "wrong_edge", "message": "command is not addressed to this edge"},
    }
    assert calls == []
    asyncio.run(agent.aclose())

def test_command_api_device_mismatch_does_not_reserve_command_id(monkeypatch, tmp_path):
    class Consumer:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    calls = []

    async def executor(device_name, command, expires_at):
        calls.append((device_name, command))
        return {"state": "ready"}

    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    now = 1_700_000_000.0
    monkeypatch.setattr("telemetry_plane.edge.time.time", lambda: now)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        "EDGE_COMMAND_URL_TEMPLATE": "http://core-command/api/v3/device/{device_name}",
        "COMMAND_ENABLED": "true",
        **tls_env(),
    })
    agent = EdgeAgent(settings, executor=executor)
    payload = {
        "edge_id": settings.edge_id,
        "device_name": "camera-a",
        "command_id": "reusable-command-id",
        "issued_at": now,
        "expires_at": now + 5,
        "operation": "read_status",
        "command": {},
        "authorization_version": "authz-v1",
        "policy_version": "policy-v1",
        "idempotency_classification": "idempotent",
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent.app()), base_url="https://edge") as client:
            mismatched = await client.post(
                "/v1/commands/camera-a",
                json={**payload, "device_name": "camera-b"},
            )
            assert calls == []
            succeeded = await client.post("/v1/commands/camera-a", json=payload)
            return mismatched, succeeded

    mismatched, succeeded = asyncio.run(run())
    assert mismatched.status_code == 400
    assert mismatched.json()["error"]["code"] == "wrong_device"
    assert succeeded.status_code == 200
    assert succeeded.json()["status"] == "succeeded"
    assert calls == [("camera-a", {})]
    asyncio.run(agent.aclose())



def test_concurrent_duplicate_command_is_coalesced_conflict_rejected_and_failure_replayed(monkeypatch, tmp_path):
    class Consumer:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    calls = []
    started = asyncio.Event()
    release = asyncio.Event()

    async def executor(device_name, command, expires_at):
        calls.append((device_name, command))
        started.set()
        await release.wait()
        raise httpx.ConnectError("local EdgeX unavailable")

    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        "EDGE_COMMAND_URL_TEMPLATE": "http://core-command/api/v3/device/{device_name}",
        "COMMAND_ENABLED": "true",
        **tls_env(),
    })
    agent = EdgeAgent(settings, executor=executor)
    now = time.time()
    payload = {
        "edge_id": settings.edge_id,
        "device_name": "device-1",
        "command_id": "cmd-1",
        "issued_at": now,
        "expires_at": now + 5,
        "operation": "read_status",
        "command": {},
        "authorization_version": "authz-v1",
        "policy_version": "policy-v1",
        "idempotency_classification": "idempotent",
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent.app()), base_url="https://edge") as client:
            first = asyncio.create_task(client.post("/v1/commands/device-1", json=payload))
            await started.wait()
            duplicate = asyncio.create_task(client.post("/v1/commands/device-1", json=payload))
            await asyncio.sleep(0)
            conflict = await client.post("/v1/commands/device-1", json={**payload, "expires_at": payload["expires_at"] + 1})
            release.set()
            return await first, await duplicate, conflict, await client.post("/v1/commands/device-1", json=payload)

    first, duplicate, conflict, replay = asyncio.run(run())
    assert first.status_code == duplicate.status_code == replay.status_code == 502
    assert first.json() == duplicate.json() == replay.json()
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "command_id_conflict"
    assert len(calls) == 1
    asyncio.run(agent.aclose())

def test_expired_edge_command_returns_504_without_execution(monkeypatch, tmp_path):
    class Consumer:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    calls = []

    async def executor(device_name, command, expires_at):
        calls.append((device_name, command))
        return {"state": "ready"}

    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        "EDGE_COMMAND_URL_TEMPLATE": "http://core-command/api/v3/device/{device_name}",
        "COMMAND_ENABLED": "true",
        **tls_env(),
    })
    agent = EdgeAgent(settings, executor=executor)
    payload = {
        "edge_id": settings.edge_id,
        "device_name": "device-1",
        "command_id": "expired-command",
        "issued_at": time.time() - 10,
        "expires_at": time.time() - 1,
        "operation": "read_status",
        "command": {},
        "authorization_version": "authz-v1",
        "policy_version": "policy-v1",
        "idempotency_classification": "idempotent",
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent.app()), base_url="https://edge") as client:
            return await client.post("/v1/commands/device-1", json=payload)

    response = asyncio.run(run())
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "command_expired"
    assert calls == []
    asyncio.run(agent.aclose())
def test_future_issued_edge_command_with_excess_remaining_ttl_returns_504_without_execution(monkeypatch, tmp_path):
    class Consumer:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    now = [1_000.0]
    calls = []

    async def executor(device_name, command, expires_at):
        calls.append((device_name, command, expires_at))
        return {"state": "ready"}

    monkeypatch.setattr("telemetry_plane.commands.time.time", lambda: now[0])
    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        "EDGE_COMMAND_URL_TEMPLATE": "http://core-command/api/v3/device/{device_name}",
        "COMMAND_ENABLED": "true",
        **tls_env(),
    })
    agent = EdgeAgent(settings, executor=executor)
    payload = {
        "edge_id": settings.edge_id,
        "device_name": "device-1",
        "command_id": "future-command",
        "issued_at": now[0] + 20,
        "expires_at": now[0] + 50,
        "operation": "read_status",
        "command": {},
        "authorization_version": "authz-v1",
        "policy_version": "policy-v1",
        "idempotency_classification": "idempotent",
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent.app()), base_url="https://edge") as client:
            return await client.post("/v1/commands/device-1", json=payload)

    response = asyncio.run(run())
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "command_expired"
    assert calls == []
    asyncio.run(agent.aclose())

def test_expired_terminal_duplicate_replays_without_execution_and_conflicts(monkeypatch, tmp_path):
    class Consumer:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    now = [1_000.0]
    calls = []

    async def executor(device_name, command, expires_at):
        calls.append((device_name, command, expires_at))
        return {"state": "ready"}

    monkeypatch.setattr("telemetry_plane.edge.time.time", lambda: now[0])
    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        "EDGE_COMMAND_URL_TEMPLATE": "http://core-command/api/v3/device/{device_name}",
        "COMMAND_ENABLED": "true",
        **tls_env(),
    })
    agent = EdgeAgent(settings, executor=executor)
    payload = {
        "edge_id": settings.edge_id,
        "device_name": "device-1",
        "command_id": "cached-command",
        "issued_at": now[0],
        "expires_at": now[0] + 5,
        "operation": "read_status",
        "command": {},
        "authorization_version": "authz-v1",
        "policy_version": "policy-v1",
        "idempotency_classification": "idempotent",
    }

    async def post(body):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent.app()), base_url="https://edge") as client:
            return await client.post("/v1/commands/device-1", json=body)

    first = asyncio.run(post(payload))
    now[0] += 6
    replay = asyncio.run(post(payload))
    expired_miss = asyncio.run(post({**payload, "command_id": "expired-miss"}))
    conflict = asyncio.run(post({**payload, "issued_at": payload["issued_at"] - 1}))

    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    assert expired_miss.status_code == 504
    assert expired_miss.json()["error"]["code"] == "command_expired"
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "command_id_conflict"
    assert len(calls) == 1
    asyncio.run(agent.aclose())



def test_core_data_adapter_uses_add_event_path_with_encoded_envelope_fields():
    requested = []

    async def handler(request):
        requested.append(request)
        return httpx.Response(201)

    async def run():
        adapter = HTTPXCoreDataAdapter("http://core-data", "telemetry gateway",
                                      httpx.AsyncClient(transport=httpx.MockTransport(handler)))
        await adapter.post_event({
            "apiVersion": "v3",
            "id": "55555555-5555-4555-8555-555555555555",
            "profileName": "profile/a",
            "deviceName": "device 1",
            "sourceName": "source/a",
            "origin": 100,
            "readings": [{
                "id": "66666666-6666-4666-8666-666666666666",
                "deviceName": "device 1",
                "profileName": "profile/a",
                "resourceName": "value",
                "valueType": "Int64",
                "value": 1,
                "origin": 100,
            }],
        })
        await adapter.client.aclose()

    asyncio.run(run())
    assert requested[0].url.raw_path == b"/api/v3/event/telemetry%20gateway/profile%2Fa/device%201/source%2Fa"


def test_edge_agent_heartbeat_omits_freshness_for_unknown_source(monkeypatch, tmp_path):
    heartbeats = []

    class Consumer:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            pass

        def close(self):
            pass

    class Gateway:
        def __init__(self, *args):
            pass

        async def flush_one(self, outbox):
            return False

        async def heartbeat(self, payload):
            heartbeats.append(payload)
            raise asyncio.CancelledError

        async def close(self):
            pass

    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    agent = EdgeAgent(EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        **tls_env(),
    }))
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(agent.run())
    assert heartbeats[0]["source_seen"] is False
    assert "source_freshness_seconds" not in heartbeats[0]


def test_closed_edge_agent_refuses_to_start_mqtt_callbacks(monkeypatch, tmp_path):
    starts = []

    class Consumer:
        def __init__(self, *args, **kwargs):
            pass

        def start(self):
            starts.append(True)

        def close(self):
            pass

    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    agent = EdgeAgent(EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        **tls_env(),
    }))
    asyncio.run(agent.aclose())
    asyncio.run(agent.run())
    assert starts == []


def test_unexpected_command_executor_exception_propagates_and_is_not_cached(monkeypatch, tmp_path):
    calls = []
    started = asyncio.Event()
    release = asyncio.Event()

    class Consumer:
        def __init__(self, *args, **kwargs):
            pass

        def close(self):
            pass

    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    async def executor(device_name, command, expires_at):
        calls.append((device_name, command))
        started.set()
        await release.wait()
        raise RuntimeError("executor bug")

    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        "COMMAND_ENABLED": "true",
        "EDGE_COMMAND_URL_TEMPLATE": "http://core-command/api/v3/device/{device_name}",
        **tls_env(),
    })
    agent = EdgeAgent(settings, executor=executor)
    now = time.time()
    payload = {
        "edge_id": settings.edge_id,
        "device_name": "device-1",
        "command_id": "cmd-exception",
        "issued_at": now,
        "expires_at": now + 5,
        "operation": "read_status",
        "command": {},
        "authorization_version": "authz-v1",
        "policy_version": "policy-v1",
        "idempotency_classification": "idempotent",
    }

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=agent.app()), base_url="https://edge") as client:
            first = asyncio.create_task(client.post("/v1/commands/device-1", json=payload))
            await started.wait()
            duplicate = asyncio.create_task(client.post("/v1/commands/device-1", json=payload))
            await asyncio.sleep(0)
            release.set()
            with pytest.raises(RuntimeError, match="executor bug"):
                await first
            with pytest.raises(RuntimeError, match="executor bug"):
                await duplicate
            with pytest.raises(RuntimeError, match="executor bug"):
                await client.post("/v1/commands/device-1", json=payload)

    asyncio.run(run())
    assert len(calls) == 2
    asyncio.run(agent.aclose())
def test_edge_agent_wires_stable_mqtt_client_and_bounded_session(monkeypatch, tmp_path):
    captured = {}

    class Consumer:
        def __init__(self, *args, **kwargs):
            captured["args"] = args
            captured["kwargs"] = kwargs

        def close(self):
            pass

    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", Consumer)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0001-jetorn",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "LOCAL_MQTT_HOST": "localhost",
        "LOCAL_MQTT_SESSION_EXPIRY_SECONDS": "120",
        **tls_env(),
    })
    agent = EdgeAgent(settings)
    assert captured["kwargs"] == {
        "client_id": "telemetry-plane-etri-dev0001-jetorn",
        "session_expiry_seconds": 120,
    }
    asyncio.run(agent.aclose())


def test_direct_source_mode_does_not_require_or_construct_mqtt(monkeypatch, tmp_path):
    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    def unexpected_mqtt(*args, **kwargs):
        raise AssertionError("direct source mode must not construct an MQTT consumer")

    monkeypatch.setattr("telemetry_plane.edge.EdgeMQTTConsumer", unexpected_mqtt)
    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0003-raspi5",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "TELEMETRY_SOURCE_MODE": "direct",
        **tls_env(),
    })

    assert settings.source_mode == "direct"
    assert settings.local_mqtt_host is None
    assert settings.direct_adapter_host == "127.0.0.1"
    assert settings.direct_adapter_port == 18080
    agent = EdgeAgent(settings)
    assert agent.consumer is None
    asyncio.run(agent.aclose())


def test_source_mode_validation_and_mqtt_requirements(tmp_path):
    base = {
        "EDGE_ID": "etri-dev0003-raspi5",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        **tls_env(),
    }

    with pytest.raises(ConfigurationError, match="TELEMETRY_SOURCE_MODE"):
        EdgeSettings.from_env({**base, "TELEMETRY_SOURCE_MODE": "serial"})
    with pytest.raises(ConfigurationError, match="LOCAL_MQTT_HOST"):
        EdgeSettings.from_env({**base, "TELEMETRY_SOURCE_MODE": "mqtt"})
    with pytest.raises(ConfigurationError, match="loopback"):
        EdgeSettings.from_env({
            **base,
            "TELEMETRY_SOURCE_MODE": "direct",
            "DIRECT_ADAPTER_HOST": "0.0.0.0",
        })


def test_direct_adapter_commits_before_ack_and_is_idempotent(monkeypatch, tmp_path):
    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0003-raspi5",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "TELEMETRY_SOURCE_MODE": "direct",
        **tls_env(),
    })
    agent = EdgeAgent(settings)
    event = edge_event()

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=agent.adapter_app()),
            base_url="http://127.0.0.1:18080",
        ) as client:
            accepted = await client.post("/v1/events", json=event)
            duplicate = await client.post("/v1/events", json=event)
            conflicting = await client.post(
                "/v1/events",
                json={
                    **event,
                    "readings": [{**event["readings"][0], "value": 2}],
                },
            )
            invalid = await client.post("/v1/events", json={"apiVersion": "v3"})
            return accepted, duplicate, conflicting, invalid

    accepted, duplicate, conflicting, invalid = asyncio.run(run())
    assert accepted.status_code == 202
    assert accepted.json() == {
        "status": "queued",
        "edge_id": "etri-dev0003-raspi5",
        "event_id": event["id"],
        "deduplicated": False,
    }
    assert duplicate.status_code == 202
    assert duplicate.json()["deduplicated"] is True
    assert conflicting.status_code == 409
    assert conflicting.json()["error"]["code"] == "event_id_conflict"
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "invalid_event"
    assert agent.outbox.diagnostics().pending_count == 1
    asyncio.run(agent.aclose())


def test_direct_adapter_reports_full_outbox_without_ack(monkeypatch, tmp_path):
    class Gateway:
        def __init__(self, *args):
            pass

        async def close(self):
            pass

    monkeypatch.setattr("telemetry_plane.edge.EdgeGatewayClient", Gateway)
    settings = EdgeSettings.from_env({
        "EDGE_ID": "etri-dev0003-raspi5",
        "GATEWAY_URL": "https://gateway:8443",
        "EDGE_AUTH_SECRET": "edge-secret",
        "OUTBOX_PATH": str(tmp_path / "outbox.db"),
        "EDGE_OUTBOX_MAX_BYTES": "1",
        "TELEMETRY_SOURCE_MODE": "direct",
        **tls_env(),
    })
    agent = EdgeAgent(settings)

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=agent.adapter_app()),
            base_url="http://127.0.0.1:18080",
        ) as client:
            return await client.post("/v1/events", json=edge_event())

    response = asyncio.run(run())
    assert response.status_code == 507
    assert response.json()["error"]["code"] == "outbox_full"
    assert agent.outbox.diagnostics().pending_count == 0
    asyncio.run(agent.aclose())
