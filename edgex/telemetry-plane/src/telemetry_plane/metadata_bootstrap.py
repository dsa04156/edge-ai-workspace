"""Idempotently register the logical telemetry service, profiles, and devices."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse

import httpx

from .metadata_validation import MetadataValidationResponder


class MetadataBootstrapError(RuntimeError):
    """The desired EdgeX Metadata contract could not be safely established."""


def _strict_json(path: Path) -> Any:
    try:
        return json.loads(
            path.read_text(),
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise MetadataBootstrapError(f"{path} must contain valid JSON") from error


def _named_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise MetadataBootstrapError(f"metadata contract {field} must be an object")
    name = value.get("name")
    if not isinstance(name, str) or not name.strip():
        raise MetadataBootstrapError(f"metadata contract {field} requires a non-empty name")
    return value


def validate_contract(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {"service", "profiles", "devices"}:
        raise MetadataBootstrapError("metadata contract requires only service, profiles, and devices")
    service = _named_object(value["service"], "service")
    profiles = value["profiles"]
    devices = value["devices"]
    if not isinstance(profiles, list) or not profiles:
        raise MetadataBootstrapError("metadata contract profiles must be a non-empty array")
    if not isinstance(devices, list) or not devices:
        raise MetadataBootstrapError("metadata contract devices must be a non-empty array")
    profile_objects = [_named_object(profile, "profile") for profile in profiles]
    device_objects = [_named_object(device, "device") for device in devices]
    profile_names = {profile["name"] for profile in profile_objects}
    device_names = {device["name"] for device in device_objects}
    if len(profile_names) != len(profile_objects):
        raise MetadataBootstrapError("metadata contract profile names must be unique")
    if len(device_names) != len(device_objects):
        raise MetadataBootstrapError("metadata contract device names must be unique")
    for profile in profile_objects:
        if profile.get("apiVersion") != "v3":
            raise MetadataBootstrapError(f"profile {profile['name']} must use apiVersion v3")
    for device in device_objects:
        if device.get("serviceName") != service["name"]:
            raise MetadataBootstrapError(f"device {device['name']} references an unknown service")
        if device.get("profileName") not in profile_names:
            raise MetadataBootstrapError(f"device {device['name']} references an unknown profile")
    return value


def load_contract(path: str | Path) -> dict[str, Any]:
    return validate_contract(_strict_json(Path(path)))


class MetadataBootstrap:
    def __init__(
        self,
        metadata_url: str,
        contract: dict[str, Any],
        *,
        client: Any | None = None,
    ) -> None:
        parsed = urlparse(metadata_url)
        try:
            port = parsed.port
        except ValueError as error:
            raise MetadataBootstrapError("metadata URL has an invalid port") from error
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or port is None
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise MetadataBootstrapError("metadata URL must be HTTP(S) with an explicit port")
        self.metadata_url = metadata_url.rstrip("/")
        self.contract = validate_contract(contract)
        self.client = client or httpx.Client(timeout=10.0)

    def close(self) -> None:
        self.client.close()

    def _exists(self, kind: str, response_key: str, name: str) -> bool:
        encoded = quote(name, safe="")
        response = self.client.get(f"{self.metadata_url}/api/v3/{kind}/name/{encoded}")
        if response.status_code == 404:
            return False
        if response.status_code != 200:
            raise MetadataBootstrapError(f"EdgeX {kind}/{name} lookup returned status {response.status_code}")
        try:
            body = response.json()
        except ValueError as error:
            raise MetadataBootstrapError(f"EdgeX {kind}/{name} lookup returned invalid JSON") from error
        entity = body.get(response_key) if isinstance(body, dict) else None
        if not isinstance(entity, dict) or entity.get("name") != name:
            raise MetadataBootstrapError(f"EdgeX {kind}/{name} lookup returned the wrong object")
        return True

    def _ensure(self, kind: str, response_key: str, entity: dict[str, Any]) -> bool:
        name = entity["name"]
        if self._exists(kind, response_key, name):
            return False
        request = [{
            "apiVersion": "v3",
            "requestId": str(uuid.uuid4()),
            response_key: entity,
        }]
        response = self.client.post(f"{self.metadata_url}/api/v3/{kind}", json=request)
        if response.status_code != 207:
            raise MetadataBootstrapError(f"EdgeX {kind}/{name} create returned HTTP {response.status_code}")
        try:
            body = response.json()
        except ValueError as error:
            raise MetadataBootstrapError(f"EdgeX {kind}/{name} create returned invalid JSON") from error
        if not isinstance(body, list) or len(body) != 1 or not isinstance(body[0], dict):
            raise MetadataBootstrapError(f"EdgeX {kind}/{name} create returned invalid multi-status")
        status = body[0].get("statusCode")
        if status == 201:
            return True
        if status == 409 and self._exists(kind, response_key, name):
            return False
        raise MetadataBootstrapError(f"EdgeX {kind}/{name} create returned status {status}")

    def run(self) -> list[str]:
        created: list[str] = []
        objects = [
            ("deviceservice", "service", self.contract["service"]),
            *(("deviceprofile", "profile", profile) for profile in self.contract["profiles"]),
            *(("device", "device", device) for device in self.contract["devices"]),
        ]
        for kind, response_key, entity in objects:
            if self._ensure(kind, response_key, entity):
                created.append(f"{kind}/{entity['name']}")
        return created


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Register the EdgeX telemetry Metadata contract")
    parser.add_argument("--metadata-url", required=True)
    parser.add_argument("--contract", required=True)
    parser.add_argument("--messagebus-host", required=True)
    parser.add_argument("--messagebus-port", type=_messagebus_port, default=1883)
    return parser


def _messagebus_port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("MessageBus port must be an integer") from error
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("MessageBus port must be between 1 and 65535")
    return port


def main() -> None:
    args = build_parser().parse_args()
    contract = load_contract(args.contract)
    service_name = contract["service"]["name"]
    responder = MetadataValidationResponder(
        args.messagebus_host,
        args.messagebus_port,
        service_name,
        contract["devices"],
    )
    bootstrap: MetadataBootstrap | None = None
    try:
        bootstrap = MetadataBootstrap(args.metadata_url, contract)
        responder.start()
        for item in bootstrap.run():
            print(f"created {item}")
    finally:
        try:
            if bootstrap is not None:
                bootstrap.close()
        finally:
            responder.close()


if __name__ == "__main__":
    main()
