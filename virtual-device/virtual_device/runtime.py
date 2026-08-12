from __future__ import annotations

import threading
import time
from collections.abc import Callable

from .adapters.base import Adapter, AdapterConnectionError, InvalidSampleError
from .config import DeviceProfile
from .models import TelemetryEnvelope
from .normalizer import Normalizer, SampleDecision, SampleGuard
from .publisher import Publisher
from .status import RuntimeStatusTracker


class VirtualDeviceRuntime:
    def __init__(
        self,
        profile: DeviceProfile,
        *,
        adapter: Adapter,
        publisher: Publisher,
        clock: Callable[[], float] = time.time,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        self.profile = profile
        self.adapter = adapter
        self.publisher = publisher
        self._clock = clock
        self._sleeper = sleeper
        self._stop_event = threading.Event()
        self._normalizer = Normalizer(profile)
        self._sample_guard = SampleGuard()
        self._status = RuntimeStatusTracker(profile)
        self._sequence = 0
        self._adapter_started = False
        self._publisher_started = False
        self._connected_since: float | None = None
        self._last_status_published_at: float | None = None

    def request_stop(self) -> None:
        self._stop_event.set()

    def run(self, *, max_iterations: int | None = None) -> None:
        if max_iterations is not None and max_iterations < 0:
            raise ValueError("max_iterations must be non-negative")

        reconnect_backoff = self.profile.runtime.reconnect_backoff_seconds
        iterations = 0
        try:
            self.publisher.start()
            self._publisher_started = True
            self._publish_status()

            while not self._stop_event.is_set():
                if max_iterations is not None and iterations >= max_iterations:
                    break
                iterations += 1

                if not self._adapter_started:
                    try:
                        self.adapter.start()
                    except AdapterConnectionError as exc:
                        self._status.mark_disconnected(str(exc))
                        self._publish_status()
                        self._wait(reconnect_backoff)
                        reconnect_backoff = min(
                            reconnect_backoff * 2,
                            self.profile.runtime.reconnect_backoff_max_seconds,
                        )
                        continue
                    except Exception as exc:
                        self._status.mark_disconnected(str(exc))
                        self._publish_status()
                        self._wait(reconnect_backoff)
                        reconnect_backoff = min(
                            reconnect_backoff * 2,
                            self.profile.runtime.reconnect_backoff_max_seconds,
                        )
                        continue

                    self._adapter_started = True
                    self._connected_since = self._clock()
                    reconnect_backoff = self.profile.runtime.reconnect_backoff_seconds
                    self._status.mark_connected()
                    self._publish_status()

                try:
                    raw_sample = self.adapter.read()
                except InvalidSampleError as exc:
                    self._status.mark_invalid_sample(str(exc))
                    self._publish_status()
                    continue
                except AdapterConnectionError as exc:
                    self._handle_disconnect(str(exc))
                    self._wait(reconnect_backoff)
                    reconnect_backoff = min(
                        reconnect_backoff * 2,
                        self.profile.runtime.reconnect_backoff_max_seconds,
                    )
                    continue
                except Exception as exc:
                    self._handle_disconnect(str(exc))
                    self._wait(reconnect_backoff)
                    reconnect_backoff = min(
                        reconnect_backoff * 2,
                        self.profile.runtime.reconnect_backoff_max_seconds,
                    )
                    continue

                if raw_sample is None:
                    now = self._clock()
                    changed = self._status.refresh_freshness(
                        now=now,
                        connected_since=self._connected_since,
                        offline_after_seconds=self.profile.runtime.offline_after_seconds,
                    )
                    if changed:
                        self._publish_status()
                    else:
                        self._publish_heartbeat_if_due()
                    self._wait(self.profile.runtime.idle_sleep_seconds)
                    continue

                collected_at = int(self._clock())
                normalized = self._normalizer.normalize(raw_sample, collected_at=collected_at)
                decision = self._sample_guard.check(
                    normalized.source_timestamp,
                    {
                        "data": normalized.fingerprint_data(),
                        "quality": normalized.quality.to_dict(),
                    },
                )
                if decision is not SampleDecision.NEW:
                    self._publish_heartbeat_if_due()
                    continue

                self._sequence += 1
                telemetry = TelemetryEnvelope.from_sample(
                    self.profile,
                    normalized,
                    sequence=self._sequence,
                )
                self.publisher.publish(
                    self.profile.output.mqtt.telemetry_topic,
                    telemetry.to_json(),
                    qos=self.profile.output.mqtt.qos,
                )
                changed = self._status.mark_sample(
                    collected_at=collected_at,
                    valid=normalized.quality.valid,
                    errors=normalized.quality.errors,
                )
                if changed:
                    self._publish_status()
                else:
                    self._publish_heartbeat_if_due()
        except Exception as exc:
            self._status.mark_failed(str(exc))
            self._try_publish_status()
            raise
        finally:
            self._shutdown()

    def _handle_disconnect(self, error: str) -> None:
        self._status.mark_disconnected(error)
        self._publish_status()
        self._stop_adapter()
        self._connected_since = None

    def _publish_heartbeat_if_due(self) -> None:
        now = self._clock()
        if (
            self._last_status_published_at is None
            or now - self._last_status_published_at >= self.profile.runtime.heartbeat_seconds
        ):
            self._publish_status(now=now)

    def _publish_status(self, *, now: float | None = None) -> None:
        self.publisher.publish(
            self.profile.output.mqtt.status_topic,
            self._status.status.to_json(),
            qos=self.profile.output.mqtt.qos,
        )
        self._last_status_published_at = self._clock() if now is None else now

    def _try_publish_status(self) -> None:
        if not self._publisher_started:
            return
        try:
            self._publish_status()
        except Exception:
            pass

    def _wait(self, seconds: float) -> None:
        if self._stop_event.is_set():
            return
        if self._sleeper is not None:
            self._sleeper(seconds)
            return
        self._stop_event.wait(seconds)

    def _stop_adapter(self) -> None:
        try:
            self.adapter.stop()
        finally:
            self._adapter_started = False

    def _shutdown(self) -> None:
        self._stop_adapter()
        self._status.mark_stopped()
        self._try_publish_status()
        if self._publisher_started:
            try:
                self.publisher.stop()
            finally:
                self._publisher_started = False
