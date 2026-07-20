"""Durable edge telemetry transport for EdgeX."""

from .gateway import create_app
from .outbox import EdgeOutbox

__all__ = ["EdgeOutbox", "create_app"]
