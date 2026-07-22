"""Strict environment configuration for the central gateway and edge agent."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import urlparse


class ConfigurationError(ValueError):
    pass


MAX_COMMAND_TTL_SECONDS = 300
MAX_COMMAND_TIMEOUT_SECONDS = 60
MAX_COMMAND_DEDUPE_CAPACITY = 100_000
MAX_OUTBOX_BYTES = 16 * 1024 * 1024 * 1024
DEFAULT_OUTBOX_MAX_BYTES = 1024 * 1024 * 1024
MAX_LOCAL_MQTT_SESSION_EXPIRY_SECONDS = 86_400
EDGE_SOURCE_MODES = {"direct", "mqtt"}


def _required(name: str, source: dict[str, str] | None = None) -> str:
    value = (os.environ if source is None else source).get(name, "")
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{name} is required")
    return value


def _bounded_int(name: str, default: int, maximum: int, source: dict[str, str] | None = None) -> int:
    value = (os.environ if source is None else source).get(name, str(default))
    try:
        parsed = int(value)
    except (TypeError, ValueError) as error:
        raise ConfigurationError(f"{name} must be an integer") from error
    if not 1 <= parsed <= maximum:
        raise ConfigurationError(f"{name} must be between 1 and {maximum}")
    return parsed

def _strict_bool(name: str, default: bool, source: dict[str, str] | None = None) -> bool:
    value = (os.environ if source is None else source).get(name)
    if value is None:
        return default
    if value == "true":
        return True
    if value == "false":
        return False
    raise ConfigurationError(f"{name} must be exactly true or false")


def _port(name: str, default: int, source: dict[str, str] | None = None) -> int:
    return _bounded_int(name, default, 65535, source)


def _edge_source_mode(source: dict[str, str]) -> str:
    raw = source.get("TELEMETRY_SOURCE_MODE")
    if raw is None:
        # Preserve existing MQTT deployments while making a broker-free agent
        # the default for new configurations.
        return "mqtt" if source.get("LOCAL_MQTT_HOST", "").strip() else "direct"
    if not isinstance(raw, str) or raw not in EDGE_SOURCE_MODES:
        allowed = ", ".join(sorted(EDGE_SOURCE_MODES))
        raise ConfigurationError(f"TELEMETRY_SOURCE_MODE must be one of: {allowed}")
    return raw


def _loopback_host(source: dict[str, str]) -> str:
    host = source.get("DIRECT_ADAPTER_HOST", "127.0.0.1")
    if host not in {"127.0.0.1", "::1", "localhost"}:
        raise ConfigurationError("DIRECT_ADAPTER_HOST must be a loopback address")
    return host


def _json_mapping(name: str, source: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ if source is None else source
    raw = env.get(name)
    if not isinstance(raw, str) or not raw.strip():
        raise ConfigurationError(f"{name} is required")
    try:
        mapping = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ConfigurationError(f"{name} must be a JSON object") from error
    if not isinstance(mapping, dict) or not mapping:
        raise ConfigurationError(f"{name} must be a non-empty JSON object")
    if any(not isinstance(key, str) or not key.strip() or not isinstance(value, str) or not value.strip()
           for key, value in mapping.items()):
        raise ConfigurationError(f"{name} must map non-empty strings to non-empty strings")
    return mapping


def _command_endpoints(source: dict[str, str] | None = None) -> dict[str, str]:
    endpoints = _json_mapping("COMMAND_EDGE_ENDPOINTS_JSON", source)
    for edge_id, endpoint in endpoints.items():
        parsed = urlparse(endpoint)
        try:
            port = parsed.port
        except ValueError as error:
            raise ConfigurationError(f"command endpoint for {edge_id} has an invalid port") from error
        if (parsed.scheme != "https" or not parsed.hostname or port is None or not 1 <= port <= 65535
                or parsed.username or parsed.password or parsed.query or parsed.fragment):
            raise ConfigurationError(f"command endpoint for {edge_id} must be an HTTPS URL with an explicit valid port")
    return endpoints

def _command_url_template(source: dict[str, str] | None = None) -> str:
    template = _required("EDGE_COMMAND_URL_TEMPLATE", source)
    if template.count("{device_name}") != 1:
        raise ConfigurationError("EDGE_COMMAND_URL_TEMPLATE must contain exactly one {device_name}")
    parsed = urlparse(template.replace("{device_name}", "device"))
    original_segments = urlparse(template).path.split("/")
    try:
        port = parsed.port
    except ValueError as error:
        raise ConfigurationError("EDGE_COMMAND_URL_TEMPLATE has an invalid port") from error
    if original_segments.count("{device_name}") != 1:
        raise ConfigurationError("EDGE_COMMAND_URL_TEMPLATE must use {device_name} as exactly one path segment")
    if ("{" in template.replace("{device_name}", "") or "}" in template.replace("{device_name}", "")
            or parsed.scheme not in {"http", "https"} or not parsed.hostname
            or (port is not None and not 1 <= port <= 65535)
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ConfigurationError("EDGE_COMMAND_URL_TEMPLATE must be an HTTP(S) URL without credentials")
    return template

def _gateway_url(source: dict[str, str] | None = None) -> str:
    url = _required("GATEWAY_URL", source)
    parsed = urlparse(url)
    try:
        port = parsed.port
    except ValueError as error:
        raise ConfigurationError("GATEWAY_URL has an invalid port") from error
    if (parsed.scheme != "https" or not parsed.hostname or port is None or not 1 <= port <= 65535
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ConfigurationError("GATEWAY_URL must be an HTTPS URL with a hostname and explicit valid port")
    return url



@dataclass(frozen=True)
class TLSSettings:
    ca_file: str
    cert_file: str
    key_file: str

    @classmethod
    def from_env(cls, source: dict[str, str] | None = None, prefix: str = "TELEMETRY_TLS_") -> "TLSSettings":
        return cls(_required(f"{prefix}CA_FILE", source), _required(f"{prefix}CERT_FILE", source),
                   _required(f"{prefix}KEY_FILE", source))


@dataclass(frozen=True)
class GatewaySettings:
    database_url: str
    core_data_url: str
    core_data_service_name: str
    edge_auth_secrets: dict[str, str]
    tls: TLSSettings
    command_enabled: bool
    command_endpoints: dict[str, str]
    command_auth_token: str | None
    port: int
    command_max_ttl_seconds: int
    command_timeout_seconds: int

    @classmethod
    def from_env(cls, source: dict[str, str] | None = None) -> "GatewaySettings":
        env = os.environ if source is None else source
        command_enabled = _strict_bool("COMMAND_ENABLED", False, env)
        return cls(
            _required("TELEMETRY_DATABASE_URL", env),
            _required("CORE_DATA_URL", env),
            _required("CORE_DATA_SERVICE_NAME", env),
            _json_mapping("TELEMETRY_EDGE_AUTH_SECRETS_JSON", env),
            TLSSettings.from_env(env),
            command_enabled,
            _command_endpoints(env) if command_enabled else {},
            _required("COMMAND_AUTH_TOKEN", env) if command_enabled else None,
            _port("TELEMETRY_PORT", 8443, env),
            _bounded_int("COMMAND_MAX_TTL_SECONDS", 30, MAX_COMMAND_TTL_SECONDS, env),
            _bounded_int("COMMAND_TIMEOUT_SECONDS", 10, MAX_COMMAND_TIMEOUT_SECONDS, env),
        )


@dataclass(frozen=True)
class EdgeSettings:
    edge_id: str
    gateway_url: str
    auth_secret: str
    tls: TLSSettings
    outbox_path: str
    source_mode: str
    local_mqtt_host: str | None
    local_mqtt_port: int | None
    local_mqtt_tls: TLSSettings | None
    telemetry_topic: str | None
    local_mqtt_session_expiry_seconds: int | None
    direct_adapter_host: str
    direct_adapter_port: int
    command_enabled: bool
    edge_command_url_template: str | None
    health_port: int
    outbox_max_bytes: int
    command_max_ttl_seconds: int
    command_dedupe_capacity: int



    @classmethod
    def from_env(cls, source: dict[str, str] | None = None) -> "EdgeSettings":
        env = os.environ if source is None else source
        source_mode = _edge_source_mode(env)
        if source_mode == "mqtt":
            local_tls = (
                TLSSettings.from_env(env, "LOCAL_MQTT_TLS_")
                if env.get("LOCAL_MQTT_TLS_CA_FILE")
                or env.get("LOCAL_MQTT_TLS_CERT_FILE")
                or env.get("LOCAL_MQTT_TLS_KEY_FILE")
                else None
            )
            local_mqtt_host = _required("LOCAL_MQTT_HOST", env)
            local_mqtt_port = _port("LOCAL_MQTT_PORT", 1883, env)
            telemetry_topic = (
                _required("LOCAL_TELEMETRY_TOPIC", env)
                if "LOCAL_TELEMETRY_TOPIC" in env
                else "edgex/events/#"
            )
            session_expiry = _bounded_int(
                "LOCAL_MQTT_SESSION_EXPIRY_SECONDS",
                3600,
                MAX_LOCAL_MQTT_SESSION_EXPIRY_SECONDS,
                env,
            )
        else:
            local_tls = None
            local_mqtt_host = None
            local_mqtt_port = None
            telemetry_topic = None
            session_expiry = None
        auth_secret = _required("EDGE_AUTH_SECRET", env)
        command_enabled = _strict_bool("COMMAND_ENABLED", False, env)
        return cls(
            _required("EDGE_ID", env),
            _gateway_url(env),
            auth_secret,
            TLSSettings.from_env(env),
            _required("OUTBOX_PATH", env),
            source_mode,
            local_mqtt_host,
            local_mqtt_port,
            local_tls,
            telemetry_topic,
            session_expiry,
            _loopback_host(env),
            _port("DIRECT_ADAPTER_PORT", 18080, env),
            command_enabled,
            _command_url_template(env) if command_enabled else None,
            _port("EDGE_AGENT_PORT", 8443, env),
            _bounded_int("EDGE_OUTBOX_MAX_BYTES", DEFAULT_OUTBOX_MAX_BYTES, MAX_OUTBOX_BYTES, env),
            _bounded_int("COMMAND_MAX_TTL_SECONDS", 30, MAX_COMMAND_TTL_SECONDS, env),
            _bounded_int("COMMAND_DEDUPE_CAPACITY", 1024, MAX_COMMAND_DEDUPE_CAPACITY, env),
        )
