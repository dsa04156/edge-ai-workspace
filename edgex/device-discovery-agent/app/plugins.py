from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class PluginResult:
    observations: list[dict[str, Any]]
    errors: list[str]
    implementation_state: str


class DiscoveryPlugin(Protocol):
    protocol: str

    def discover(self, plan: dict[str, Any]) -> PluginResult: ...


class UnsupportedDiscoveryPlugin:
    """Explicit placeholder for protocols that have no verified scanner yet."""

    def __init__(self, protocol: str) -> None:
        self.protocol = protocol

    def discover(self, plan: dict[str, Any]) -> PluginResult:
        if not plan.get("enabled"):
            return PluginResult([], [], "disabled")
        return PluginResult(
            [],
            [
                f"{self.protocol} discovery is not implemented; "
                "manual allowlisted endpoint declaration is required"
            ],
            "not-implemented",
        )


EXTENSION_PLUGINS = {
    protocol: UnsupportedDiscoveryPlugin(protocol)
    for protocol in ("modbus", "opcua", "onvif")
}
