from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from .base import Adapter, AdapterConnectionError, AdapterHealth, InvalidSampleError


class FakeAdapter(Adapter):
    """Deterministic Serial-shaped adapter for tests and local dry runs."""

    def __init__(
        self,
        samples: Iterable[dict[str, Any] | str | Exception],
        *,
        fail_start_times: int = 0,
    ) -> None:
        self._samples = iter(samples)
        self._remaining_start_failures = fail_start_times
        self._started = False
        self._health = AdapterHealth()
        self.start_calls = 0

    def start(self) -> None:
        self.start_calls += 1
        if self._remaining_start_failures > 0:
            self._remaining_start_failures -= 1
            self._health = AdapterHealth(connection="disconnected", last_error="fake start failure")
            raise AdapterConnectionError("fake start failure")
        self._started = True
        self._health = AdapterHealth(connection="connected")

    def read(self) -> dict[str, Any] | None:
        if not self._started:
            raise AdapterConnectionError("fake adapter is not started")
        try:
            item = next(self._samples)
        except StopIteration:
            return None

        if isinstance(item, InvalidSampleError):
            self._health = AdapterHealth(connection="connected", last_error=str(item))
            raise item
        if isinstance(item, Exception):
            self._started = False
            self._health = AdapterHealth(connection="disconnected", last_error=str(item))
            if isinstance(item, AdapterConnectionError):
                raise item
            raise AdapterConnectionError(str(item)) from item
        if isinstance(item, str):
            try:
                item = json.loads(item)
            except json.JSONDecodeError as exc:
                message = f"invalid JSON sample: {exc}"
                self._health = AdapterHealth(connection="connected", last_error=message)
                raise InvalidSampleError(message) from exc
        if not isinstance(item, dict):
            message = "invalid JSON sample: root must be an object"
            self._health = AdapterHealth(connection="connected", last_error=message)
            raise InvalidSampleError(message)

        self._health = AdapterHealth(connection="connected")
        return dict(item)

    def health(self) -> AdapterHealth:
        return self._health

    def stop(self) -> None:
        self._started = False
        self._health = AdapterHealth(connection="disconnected")
