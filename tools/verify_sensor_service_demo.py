#!/usr/bin/env python3
"""Read-only field verifier for the fixed sensor anomaly service demo."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal


Scenario = Literal["anomaly", "disconnect"]


class ObservationError(RuntimeError):
    """Raised when the state-aggregator response violates the verifier contract."""


@dataclass(frozen=True)
class Observation:
    observed_at: str
    device_operating_state: str
    device_freshness: str
    device_status: str
    demo_mode: str
    demo_status: str
    demo_input_state: str
    anomaly: bool | None
    score: float | None
    origin: int | None
    frames_processed: int | None
    observation_error: str | None

    @property
    def device_healthy(self) -> bool:
        return (
            self.device_operating_state == "UP"
            and self.device_freshness == "fresh"
            and self.device_status == "available"
        )

    @property
    def demo_healthy(self) -> bool:
        return (
            self.demo_mode == "live"
            and self.demo_input_state == "fresh"
            and self.demo_status in {"normal", "anomaly"}
            and self.observation_error is None
            and self.origin is not None
            and self.frames_processed is not None
        )

    @property
    def degraded(self) -> bool:
        return (
            not self.device_healthy
            or self.demo_mode != "live"
            or self.demo_input_state in {"stale", "error", "waiting"}
            or self.demo_status in {"degraded", "starting"}
            or self.observation_error is not None
        )


@dataclass(frozen=True)
class Transition:
    phase: str
    reason: str
    observation: Observation


class ScenarioTracker:
    """Explicit state machine for physical anomaly and disconnect field gates."""

    def __init__(self, scenario: Scenario) -> None:
        self.scenario = scenario
        self.phase = "WAITING_BASELINE"
        self.transitions: list[Transition] = []
        self.baseline_origin: int | None = None
        self.baseline_frames: int | None = None
        self.trigger_origin: int | None = None

    @property
    def complete(self) -> bool:
        return self.phase == "PASSED"

    def consume(self, observation: Observation) -> bool:
        previous = self.phase
        if self.scenario == "anomaly":
            self._consume_anomaly(observation)
        else:
            self._consume_disconnect(observation)
        return previous != self.phase

    def failure_reason(self) -> str:
        reasons = {
            "WAITING_BASELINE": "healthy_baseline_not_observed",
            "WAITING_ANOMALY": "anomaly_not_observed",
            "WAITING_CLEAR": "normal_recovery_not_observed",
            "WAITING_DISCONNECT": "disconnect_not_observed",
            "WAITING_RECOVERY": "fresh_recovery_not_observed",
        }
        return reasons.get(self.phase, "unknown_verification_failure")

    def _consume_anomaly(self, observation: Observation) -> None:
        if self.phase == "WAITING_BASELINE":
            if observation.demo_healthy and observation.anomaly is False:
                self._record_baseline(observation)
                self._transition(
                    "WAITING_ANOMALY",
                    "normal fresh baseline observed",
                    observation,
                )
            return
        if self.phase == "WAITING_ANOMALY":
            if (
                observation.demo_healthy
                and observation.anomaly is True
                and self._origin_advanced(observation, self.baseline_origin)
            ):
                self.trigger_origin = observation.origin
                self._transition(
                    "WAITING_CLEAR",
                    "anomaly observed on a newer sample",
                    observation,
                )
            return
        if self.phase == "WAITING_CLEAR":
            if (
                observation.demo_healthy
                and observation.anomaly is False
                and self._origin_advanced(observation, self.trigger_origin)
            ):
                self._transition(
                    "PASSED",
                    "normal state recovered on a newer sample",
                    observation,
                )

    def _consume_disconnect(self, observation: Observation) -> None:
        if self.phase == "WAITING_BASELINE":
            if observation.device_healthy and observation.demo_healthy:
                self._record_baseline(observation)
                self._transition(
                    "WAITING_DISCONNECT",
                    "device and service baseline are fresh",
                    observation,
                )
            return
        if self.phase == "WAITING_DISCONNECT":
            if observation.degraded:
                self._transition(
                    "WAITING_RECOVERY",
                    "device or service degradation observed",
                    observation,
                )
            return
        if self.phase == "WAITING_RECOVERY":
            if (
                observation.device_healthy
                and observation.demo_healthy
                and self._origin_advanced(observation, self.baseline_origin)
                and self._frames_advanced(observation)
            ):
                self._transition(
                    "PASSED",
                    "device, service, origin and frame processing recovered",
                    observation,
                )

    def _record_baseline(self, observation: Observation) -> None:
        self.baseline_origin = observation.origin
        self.baseline_frames = observation.frames_processed

    def _frames_advanced(self, observation: Observation) -> bool:
        return (
            observation.frames_processed is not None
            and self.baseline_frames is not None
            and observation.frames_processed > self.baseline_frames
        )

    @staticmethod
    def _origin_advanced(
        observation: Observation,
        reference: int | None,
    ) -> bool:
        return (
            observation.origin is not None
            and reference is not None
            and observation.origin > reference
        )

    def _transition(
        self,
        phase: str,
        reason: str,
        observation: Observation,
    ) -> None:
        self.phase = phase
        self.transitions.append(
            Transition(phase=phase, reason=reason, observation=observation)
        )


class StateAggregatorClient:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def observe(self, device_name: str) -> Observation:
        demo = self._get_json("/state/service-demo")
        devices = self._get_json("/state/devices")
        return observation_from_payloads(demo, devices, device_name)

    def _get_json(self, path: str) -> Any:
        request = urllib.request.Request(
            self.base_url + path,
            headers={"Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout_seconds,
            ) as response:
                return json.load(response)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            raise ObservationError(f"GET {path} failed: {exc}") from exc


def observation_from_payloads(
    demo: Any,
    devices: Any,
    device_name: str,
) -> Observation:
    if not isinstance(demo, dict):
        raise ObservationError("service-demo response must be an object")
    if not isinstance(devices, list):
        raise ObservationError("devices response must be an array")
    device = next(
        (
            item
            for item in devices
            if isinstance(item, dict) and item.get("name") == device_name
        ),
        None,
    )
    if device is None:
        raise ObservationError(f"device {device_name!r} was not found")

    latest = demo.get("latest")
    if latest is not None and not isinstance(latest, dict):
        raise ObservationError("service-demo latest must be an object or null")
    latest = latest or {}
    counters = demo.get("counters")
    if counters is not None and not isinstance(counters, dict):
        raise ObservationError("service-demo counters must be an object or null")
    counters = counters or {}

    anomaly = latest.get("anomaly")
    if anomaly is not None and not isinstance(anomaly, bool):
        raise ObservationError("latest.anomaly must be boolean or null")
    origin = _optional_int(latest.get("origin"), "latest.origin")
    frames = _optional_int(
        counters.get("frames_processed"),
        "counters.frames_processed",
    )
    score = latest.get("score")
    if score is not None and not isinstance(score, (int, float)):
        raise ObservationError("latest.score must be numeric or null")

    return Observation(
        observed_at=_utc_now(),
        device_operating_state=str(device.get("operating_state") or "unknown"),
        device_freshness=str(device.get("telemetry_freshness") or "unknown"),
        device_status=str(device.get("overall_status") or "unknown"),
        demo_mode=str(demo.get("mode") or "unknown"),
        demo_status=str(demo.get("status") or "unknown"),
        demo_input_state=str(demo.get("input_state") or "unknown"),
        anomaly=anomaly,
        score=float(score) if score is not None else None,
        origin=origin,
        frames_processed=frames,
        observation_error=(
            str(demo["observation_error"])
            if demo.get("observation_error") is not None
            else None
        ),
    )


def run_verification(args: argparse.Namespace) -> dict[str, Any]:
    client = StateAggregatorClient(args.base_url, args.http_timeout)
    tracker = ScenarioTracker(args.scenario)
    started_at = _utc_now()
    deadline = time.monotonic() + args.timeout
    errors: list[dict[str, str]] = []
    next_heartbeat = 0.0

    while time.monotonic() < deadline and not tracker.complete:
        try:
            observation = client.observe(args.device_name)
        except ObservationError as exc:
            error = {"observedAt": _utc_now(), "message": str(exc)}
            errors.append(error)
            print(f"{error['observedAt']} observation_error={exc}", flush=True)
            time.sleep(args.interval)
            continue

        changed = tracker.consume(observation)
        now = time.monotonic()
        if changed or now >= next_heartbeat:
            print(_format_observation(tracker.phase, observation), flush=True)
            next_heartbeat = now + max(args.interval, 5.0)
        if not tracker.complete:
            time.sleep(args.interval)

    result = {
        "scenario": args.scenario,
        "passed": tracker.complete,
        "phase": tracker.phase,
        "reason": "passed" if tracker.complete else tracker.failure_reason(),
        "startedAt": started_at,
        "finishedAt": _utc_now(),
        "baseUrl": args.base_url,
        "deviceName": args.device_name,
        "transitions": [
            {
                "phase": item.phase,
                "reason": item.reason,
                "observation": asdict(item.observation),
            }
            for item in tracker.transitions
        ],
        "observationErrors": errors,
    }
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    print(rendered)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    return result


def _optional_int(value: Any, field: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ObservationError(f"{field} must be an integer or null")
    return value


def _format_observation(phase: str, observation: Observation) -> str:
    return (
        f"{observation.observed_at} phase={phase} "
        f"device={observation.device_operating_state}/"
        f"{observation.device_freshness}/{observation.device_status} "
        f"demo={observation.demo_input_state}/{observation.demo_status} "
        f"anomaly={observation.anomaly} score={observation.score} "
        f"origin={observation.origin} frames={observation.frames_processed}"
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "실제 센서 움직임 또는 Serial 분리·복구를 read-only API로 판정합니다."
        )
    )
    parser.add_argument("scenario", choices=("anomaly", "disconnect"))
    parser.add_argument(
        "--base-url",
        default=os.getenv("STATE_AGGREGATOR_BASE_URL", "http://127.0.0.1:8000"),
        help="state-aggregator URL (기본: http://127.0.0.1:8000)",
    )
    parser.add_argument(
        "--device-name",
        default="virtual-acceleration-x-001",
        help="분리·복구 상태를 확인할 EdgeX Device 이름",
    )
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--http-timeout", type=float, default=3.0)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    for field in ("timeout", "interval", "http_timeout"):
        if getattr(args, field) <= 0:
            parser.error(f"--{field.replace('_', '-')} must be positive")
    return args


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    result = run_verification(args)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
