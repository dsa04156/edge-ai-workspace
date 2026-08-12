#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from typing import TYPE_CHECKING, Any, Callable, Dict, Iterable, Tuple
from urllib.parse import urlparse
from urllib.request import Request, urlopen

if TYPE_CHECKING:
    from sense_hat import SenseHat


DEFAULT_AGENT_URL = "http://127.0.0.1:18080/v1/events"
DEFAULT_NODE = "etri-dev0003-raspi5"
DEFAULT_ALIAS = "sensehat-001"
DEFAULT_PROFILE = "etri-sensehat"


class DirectAgentPublisher:
    """Posts canonical EdgeX Events to the loopback telemetry-agent adapter."""

    def __init__(
        self,
        endpoint: str,
        *,
        edge_id: str,
        timeout: float = 5.0,
        opener: Callable[..., Any] = urlopen,
    ) -> None:
        parsed = urlparse(endpoint)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"127.0.0.1", "::1", "localhost"}
            or parsed.path != "/v1/events"
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("agent URL must be the loopback HTTP /v1/events endpoint")
        self.endpoint = endpoint
        self.edge_id = edge_id
        self.timeout = timeout
        self.opener = opener

    def publish(self, event: Dict[str, object]) -> Dict[str, object]:
        event_id = event.get("id")
        body = json.dumps(event, separators=(",", ":"), ensure_ascii=True).encode()
        request = Request(
            self.endpoint,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self.opener(request, timeout=self.timeout) as response:
                status = response.status
                ack = json.loads(response.read())
        except (OSError, ValueError) as error:
            raise RuntimeError(f"telemetry agent did not acknowledge event {event_id!r}") from error
        if (
            status != 202
            or not isinstance(ack, dict)
            or ack.get("status") != "queued"
            or ack.get("edge_id") != self.edge_id
            or ack.get("event_id") != event_id
            or not isinstance(ack.get("deduplicated"), bool)
        ):
            raise RuntimeError(f"telemetry agent returned an invalid acknowledgement for event {event_id!r}")
        return ack


def read_sensehat(sense: "SenseHat") -> Dict[str, float]:
    orientation = sense.get_orientation()
    gyro = sense.get_gyroscope_raw()
    return {
        "temp_humidity": round(float(sense.get_temperature_from_humidity()), 3),
        "temp_pressure": round(float(sense.get_temperature_from_pressure()), 3),
        "humidity": round(float(sense.get_humidity()), 3),
        "pressure": round(float(sense.get_pressure()), 3),
        "compass": round(float(sense.get_compass()), 3),
        "pitch": round(float(orientation["pitch"]), 3),
        "roll": round(float(orientation["roll"]), 3),
        "yaw": round(float(orientation["yaw"]), 3),
        "gyro_x": round(float(gyro["x"]), 6),
        "gyro_y": round(float(gyro["y"]), 6),
        "gyro_z": round(float(gyro["z"]), 6),
    }


def source_payloads(readings: Dict[str, float]) -> Iterable[Tuple[str, Dict[str, float]]]:
    yield "temperature", {
        "temp_humidity": readings["temp_humidity"],
        "temp_pressure": readings["temp_pressure"],
    }
    yield "humidity", {"humidity": readings["humidity"]}
    yield "pressure", {"pressure": readings["pressure"]}
    yield "compass", {"compass": readings["compass"]}
    yield "orientation", {
        "pitch": readings["pitch"],
        "roll": readings["roll"],
        "yaw": readings["yaw"],
    }
    yield "gyroscope", {
        "gyro_x": readings["gyro_x"],
        "gyro_y": readings["gyro_y"],
        "gyro_z": readings["gyro_z"],
    }


def build_edgex_events(
    readings: Dict[str, float],
    *,
    node: str,
    alias: str,
    profile: str = DEFAULT_PROFILE,
    origin: int | None = None,
) -> Iterable[Dict[str, object]]:
    observed_at = time.time_ns() if origin is None else origin
    for source_name, values in source_payloads(readings):
        yield {
            "apiVersion": "v3",
            "id": str(uuid.uuid4()),
            "deviceName": alias,
            "profileName": profile,
            "sourceName": source_name,
            "origin": observed_at,
            "tags": {"edge_node_id": node, "source_adapter": "i2c"},
            "readings": [
                {
                    "deviceName": alias,
                    "profileName": profile,
                    "resourceName": resource_name,
                    "valueType": "Float64",
                    "value": value,
                    "origin": observed_at,
                }
                for resource_name, value in values.items()
            ],
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Queue Sense HAT readings through the local telemetry agent")
    parser.add_argument("--agent-url", default=DEFAULT_AGENT_URL)
    parser.add_argument("--node", default=DEFAULT_NODE)
    parser.add_argument("--alias", default=DEFAULT_ALIAS)
    parser.add_argument("--profile", default=DEFAULT_PROFILE)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--once", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    from sense_hat import SenseHat

    sense = SenseHat()
    publisher = DirectAgentPublisher(
        args.agent_url,
        edge_id=args.node,
        timeout=args.timeout,
    )

    while True:
        readings = read_sensehat(sense)
        events = list(build_edgex_events(
            readings,
            node=args.node,
            alias=args.alias,
            profile=args.profile,
        ))
        for event in events:
            while True:
                try:
                    ack = publisher.publish(event)
                except Exception as error:
                    if args.once:
                        raise
                    print(f"sensehat publisher retry: {error}", file=sys.stderr, flush=True)
                    time.sleep(args.interval)
                    continue
                print(json.dumps({
                    "event_id": event["id"],
                    "source": event["sourceName"],
                    "deduplicated": ack["deduplicated"],
                }, ensure_ascii=True), flush=True)
                break
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:
        print(f"sensehat publisher error: {exc}", file=sys.stderr)
        raise SystemExit(1)
