#!/usr/bin/env python3
"""Read-only smoke check for the EdgeX Arduino UNO telemetry path."""

import argparse
from collections.abc import Callable
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request


PROFILE_NAME = "etri-uno-mqtt"
DEVICE_NAME = "arduino-001"
EXPECTED_RESOURCES = {
    "temperature": frozenset({"raw"}),
    "light": frozenset({"value"}),
    "magnetic": frozenset({"value"}),
    "acceleration": frozenset({"x", "y", "z"}),
}
INTEGER_VALUE_TYPES = frozenset(
    {
        "Int8",
        "Int16",
        "Int32",
        "Int64",
        "Uint8",
        "Uint16",
        "Uint32",
        "Uint64",
    }
)
EVENT_LIMIT = 20
POLL_INTERVAL_SECONDS = 1.0
HTTP_TIMEOUT_SECONDS = 3.0
DEFAULT_METADATA_URL = "http://edgex-core-metadata:59881"
DEFAULT_DATA_URL = "http://edgex-core-data:59880"
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_FRESHNESS_SECONDS = 120.0
_INTEGER_TEXT = re.compile(r"[+-]?\d+\Z")


class SmokeFailure(RuntimeError):
    """A failure whose message is safe to print to an operator."""


def build_url(base_url: str, path: str) -> str:
    """Join an EdgeX base URL and API path without changing its query."""
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}"


def profile_url(metadata_url: str) -> str:
    name = urllib.parse.quote(PROFILE_NAME, safe="")
    return build_url(metadata_url, f"/api/v3/deviceprofile/name/{name}")


def device_url(metadata_url: str) -> str:
    name = urllib.parse.quote(DEVICE_NAME, safe="")
    return build_url(metadata_url, f"/api/v3/device/name/{name}")


def events_url(data_url: str) -> str:
    name = urllib.parse.quote(DEVICE_NAME, safe="")
    return build_url(
        data_url,
        f"/api/v3/event/device/name/{name}?limit={EVENT_LIMIT}",
    )


def get_json(
    url: str,
    timeout: float = HTTP_TIMEOUT_SECONDS,
    *,
    opener: Callable[..., object] = urllib.request.urlopen,
) -> dict[str, object]:
    """GET one JSON object while keeping transport details out of errors."""
    request = urllib.request.Request(url, method="GET")
    try:
        with opener(request, timeout=timeout) as response:  # type: ignore[attr-defined]
            payload = json.load(response)  # type: ignore[arg-type]
    except urllib.error.HTTPError as exc:
        raise SmokeFailure(f"EdgeX GET failed with HTTP status {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise SmokeFailure("EdgeX GET failed") from None
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise SmokeFailure("EdgeX GET returned invalid JSON") from None

    if not isinstance(payload, dict):
        raise SmokeFailure("EdgeX GET returned invalid JSON")
    return payload


def _validate_named_response(
    response: dict[str, object], response_key: str, expected_name: str
) -> None:
    entity = response.get(response_key)
    if not isinstance(entity, dict) or entity.get("name") != expected_name:
        raise SmokeFailure(f"Core Metadata returned an invalid {response_key}")


def _is_integer_reading(reading: object) -> bool:
    if not isinstance(reading, dict):
        return False
    if not isinstance(reading.get("resourceName"), str):
        return False
    if reading.get("valueType") not in INTEGER_VALUE_TYPES:
        return False
    value = reading.get("value")
    if isinstance(value, bool):
        return False
    if isinstance(value, int):
        return True
    return isinstance(value, str) and _INTEGER_TEXT.fullmatch(value) is not None


def _has_expected_readings(event: dict[str, object], required: frozenset[str]) -> bool:
    readings = event.get("readings")
    if not isinstance(readings, list):
        return False

    valid_names = {
        reading.get("resourceName")
        for reading in readings
        if _is_integer_reading(reading)
    }
    return required.issubset(valid_names)


def _is_fresh(origin: object, now_ns: int, freshness_seconds: float) -> bool:
    if isinstance(origin, bool) or not isinstance(origin, int) or origin < 0:
        return False
    age_ns = now_ns - origin
    return 0 <= age_ns <= int(freshness_seconds * 1_000_000_000)


def validate_events(
    response: dict[str, object],
    freshness_seconds: float,
    *,
    now_ns: int | None = None,
) -> None:
    """Validate that recent events collectively cover every UNO source."""
    events = response.get("events")
    if not isinstance(events, list):
        raise SmokeFailure("Core Data returned an invalid event collection")

    observed: set[str] = set()
    recent: set[str] = set()
    valid: set[str] = set()
    current_ns = time.time_ns() if now_ns is None else now_ns

    for event in events:
        if not isinstance(event, dict):
            continue
        source = event.get("sourceName")
        if not isinstance(source, str) or source not in EXPECTED_RESOURCES:
            continue
        source_name = str(source)
        observed.add(source_name)
        if not _is_fresh(event.get("origin"), current_ns, freshness_seconds):
            continue
        recent.add(source_name)
        if _has_expected_readings(event, EXPECTED_RESOURCES[source_name]):
            valid.add(source_name)

    expected = set(EXPECTED_RESOURCES)
    missing = sorted(expected - observed)
    stale = sorted(observed - recent)
    malformed = sorted(recent - valid)
    if missing:
        raise SmokeFailure(f"missing telemetry sources: {','.join(missing)}")
    if stale:
        raise SmokeFailure(f"stale telemetry sources: {','.join(stale)}")
    if malformed:
        raise SmokeFailure(f"malformed telemetry sources: {','.join(malformed)}")


def poll_for_telemetry(
    data_url: str,
    timeout_seconds: float,
    freshness_seconds: float,
    *,
    json_getter: Callable[[str], dict[str, object]] | None = None,
    monotonic: Callable[[], float] = time.monotonic,
    sleeper: Callable[[float], None] = time.sleep,
    wall_time_ns: Callable[[], int] = time.time_ns,
) -> None:
    """Poll the read-only Core Data device event endpoint until it validates."""
    getter = get_json if json_getter is None else json_getter
    url = events_url(data_url)
    deadline = monotonic() + timeout_seconds
    last_failure: SmokeFailure | None = None
    first_attempt = True

    while first_attempt or monotonic() < deadline:
        first_attempt = False
        try:
            response = getter(url)
            validate_events(
                response,
                freshness_seconds,
                now_ns=wall_time_ns(),
            )
            return
        except SmokeFailure as exc:
            last_failure = exc

        remaining = deadline - monotonic()
        if remaining <= 0:
            break
        sleeper(min(POLL_INTERVAL_SECONDS, remaining))

    detail = str(last_failure) if last_failure else "telemetry unavailable"
    raise SmokeFailure(f"telemetry polling timed out: {detail}")


def verify(
    metadata_url: str,
    data_url: str,
    timeout_seconds: float,
    freshness_seconds: float,
    *,
    json_getter: Callable[[str], dict[str, object]] | None = None,
) -> None:
    """Verify Metadata and the exact Core Data retrieval path without mutation."""
    getter = get_json if json_getter is None else json_getter
    profile_response = getter(profile_url(metadata_url))
    _validate_named_response(profile_response, "profile", PROFILE_NAME)
    device_response = getter(device_url(metadata_url))
    _validate_named_response(device_response, "device", DEVICE_NAME)
    poll_for_telemetry(
        data_url,
        timeout_seconds,
        freshness_seconds,
        json_getter=getter,
    )


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return parsed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only EdgeX UNO ingestion smoke check"
    )
    parser.add_argument("--metadata-url", default=DEFAULT_METADATA_URL)
    parser.add_argument("--data-url", default=DEFAULT_DATA_URL)
    parser.add_argument(
        "--timeout",
        type=_non_negative_float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="maximum polling time in seconds",
    )
    parser.add_argument(
        "--freshness-seconds",
        type=_positive_float,
        default=DEFAULT_FRESHNESS_SECONDS,
        help="maximum accepted event age in seconds",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        verify(
            args.metadata_url,
            args.data_url,
            args.timeout,
            args.freshness_seconds,
        )
    except SmokeFailure as exc:
        print(f"FAIL: {exc}")
        return 1
    except Exception:
        print("FAIL: unexpected smoke check error")
        return 1

    sources = ",".join(EXPECTED_RESOURCES)
    print(f"PASS: device={DEVICE_NAME} sources={sources}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
