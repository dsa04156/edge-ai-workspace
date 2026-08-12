from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from typing import Any
from urllib.parse import urlsplit


_SECRET_NAME = re.compile(
    r"(?:password|passwd|token|secret|credential|privatekey)",
    re.IGNORECASE,
)


def normalize_runtime_setting_value(definition: Any, value: Any) -> str | int | float | bool:
    if _SECRET_NAME.search(definition.name):
        raise ValueError("runtime settings cannot contain credentials")
    if definition.type == "integer":
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{definition.name} must be an integer")
    elif definition.type in {"string", "url"}:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{definition.name} must be a non-empty string")
        value = value.strip()
    elif definition.type == "enum" and (
        value is None or isinstance(value, (dict, list))
    ):
        raise ValueError(f"{definition.name} must be a scalar value")
    if definition.options and value not in definition.options:
        raise ValueError(f"{definition.name} is not an allowed option")
    if definition.pattern and (
        not isinstance(value, str)
        or re.fullmatch(definition.pattern, value) is None
    ):
        raise ValueError(f"{definition.name} has an invalid format")
    if definition.type == "url":
        value = _normalize_url(definition, str(value))
    return value


def normalize_runtime_settings(
    template: Any,
    values: dict[str, Any],
) -> dict[str, str | int | float | bool]:
    definitions = {item.name: item for item in template.runtime_settings}
    unknown = sorted(set(values) - set(definitions))
    if unknown:
        raise ValueError(
            f"runtime settings are not allowlisted: {', '.join(unknown)}"
        )
    normalized: dict[str, str | int | float | bool] = {}
    for name, definition in definitions.items():
        if name in values:
            raw = values[name]
        elif definition.default is not None:
            raw = definition.default
        elif definition.required:
            raise ValueError(f"runtime setting {name} is required")
        else:
            continue
        normalized[name] = normalize_runtime_setting_value(definition, raw)
    if not definitions and values:
        raise ValueError("runtime template does not accept settings")
    return normalized


def runtime_settings_hash(values: dict[str, Any]) -> str | None:
    if not values:
        return None
    canonical = json.dumps(
        values,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def render_runtime_environment(
    template: Any,
    values: dict[str, Any],
    *,
    service_name: str,
) -> list[dict[str, str]]:
    normalized = normalize_runtime_settings(template, values)
    if template.runtime_config_renderer == "none":
        return []
    if template.runtime_config_renderer != "mqtt-broker-v1":
        raise ValueError("runtime config renderer is not implemented")
    broker = urlsplit(str(normalized["Broker"]))
    port = broker.port or 1883
    return [
        {"name": "MQTTBROKERINFO_SCHEMA", "value": "tcp"},
        {"name": "MQTTBROKERINFO_HOST", "value": str(broker.hostname)},
        {"name": "MQTTBROKERINFO_PORT", "value": str(port)},
        {"name": "MQTTBROKERINFO_CLIENTID", "value": service_name},
        {
            "name": "MQTTBROKERINFO_INCOMINGTOPIC",
            "value": str(normalized["IncomingTopic"]),
        },
        {"name": "MQTTBROKERINFO_QOS", "value": str(normalized["Qos"])},
        {"name": "MQTTBROKERINFO_AUTHMODE", "value": "none"},
    ]


def _normalize_url(definition: Any, value: str) -> str:
    parsed = urlsplit(value)
    scheme = parsed.scheme.casefold()
    if scheme not in set(definition.allowed_schemes):
        raise ValueError(f"{definition.name} uses an unsupported URL scheme")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("runtime setting URL cannot contain credentials")
    if not parsed.hostname:
        raise ValueError(f"{definition.name} URL requires a host")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise ValueError(
            f"{definition.name} URL cannot contain path, query, or fragment"
        )
    try:
        port = parsed.port or definition.default_port
    except ValueError as exc:
        raise ValueError(f"{definition.name} URL port is invalid") from exc
    if port is None:
        raise ValueError(f"{definition.name} URL requires a port")
    host = parsed.hostname.casefold()
    allowed = host in set(definition.allowed_hosts)
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        allowed = allowed or any(
            address in ipaddress.ip_network(cidr, strict=False)
            for cidr in definition.allowed_cidrs
        )
    if not allowed:
        raise ValueError(f"{definition.name} host is outside the allowlist")
    rendered_host = f"[{host}]" if address is not None and address.version == 6 else host
    return f"{scheme}://{rendered_host}:{port}"
