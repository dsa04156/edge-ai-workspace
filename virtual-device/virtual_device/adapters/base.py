from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


class AdapterError(RuntimeError):
    """Base error for physical-device adapter operations."""


class AdapterConnectionError(AdapterError):
    """Raised when the physical transport cannot be opened or read."""


class InvalidSampleError(AdapterError):
    """Raised for one malformed sample while keeping the transport usable."""


@dataclass(frozen=True)
class AdapterHealth:
    connection: str = "unknown"
    last_error: str | None = None


class Adapter(ABC):
    @abstractmethod
    def start(self) -> None:
        """Open the physical-device connection."""

    @abstractmethod
    def read(self) -> dict[str, Any] | None:
        """Return one decoded source sample, or None when no sample is available."""

    @abstractmethod
    def health(self) -> AdapterHealth:
        """Return the current transport-level health snapshot."""

    @abstractmethod
    def stop(self) -> None:
        """Close the physical-device connection."""
