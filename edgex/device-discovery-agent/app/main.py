from __future__ import annotations

import logging
import os
import random
import socket
import time
from datetime import datetime, timezone

from .health import HealthState, start_health_server
from .reporter import (
    DiscoveryReportError,
    fetch_discovery_plan,
    signed_report,
)
from .scanner import scan_node


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("edge-device-discovery")
SUPPORTED_PROTOCOLS = {
    "serial",
    "i2c",
    "mqtt",
    "modbus",
    "opcua",
    "onvif",
}


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def _configured_protocols() -> tuple[str, ...] | None:
    raw = os.getenv("DISCOVERY_PROTOCOLS", "").strip()
    if not raw:
        return None
    protocols = tuple(
        dict.fromkeys(
            item.strip().casefold()
            for item in raw.split(",")
            if item.strip()
        )
    )
    if not protocols:
        raise RuntimeError("DISCOVERY_PROTOCOLS must not be empty")
    unsupported = sorted(set(protocols) - SUPPORTED_PROTOCOLS)
    if unsupported:
        raise RuntimeError(
            "DISCOVERY_PROTOCOLS contains unsupported values: "
            + ", ".join(unsupported)
        )
    return protocols


def run() -> None:
    node_name = _required_env("NODE_NAME")
    hmac_key = _required_env("ADAPTER_CONTROLLER_INTERNAL_HMAC_KEY")
    controller_url = os.getenv(
        "ADAPTER_CONTROLLER_URL",
        "http://edgex-adapter-controller.edgex-edge.svc.cluster.local:8080",
    )
    interval_seconds = max(
        10,
        min(300, int(os.getenv("DISCOVERY_INTERVAL_SECONDS", "30"))),
    )
    timeout_seconds = max(
        1.0,
        min(30.0, float(os.getenv("DISCOVERY_TIMEOUT_SECONDS", "8"))),
    )
    health_port = max(
        1024,
        min(65535, int(os.getenv("DISCOVERY_HEALTH_PORT", "8081"))),
    )
    protocols = _configured_protocols()
    agent_id = f"edge-device-discovery/{node_name}/{socket.gethostname()}"
    health_state = HealthState(
        ready_window_seconds=max(60.0, interval_seconds * 3.0),
    )
    start_health_server(health_state, port=health_port)
    logger.info(
        "starting plan-based discovery node=%s protocols=%s "
        "interval=%ss healthPort=%s",
        node_name,
        ",".join(protocols) if protocols is not None else "all",
        interval_seconds,
        health_port,
    )
    while True:
        started = time.monotonic()
        try:
            plan = fetch_discovery_plan(
                controller_url=controller_url,
                hmac_key=hmac_key,
                node_name=node_name,
                timeout_seconds=timeout_seconds,
            )
            candidates, scan_errors = scan_node(
                plan=plan,
                protocols=None if protocols is None else set(protocols),
            )
        except DiscoveryReportError as exc:
            candidates = []
            scan_errors = [f"Discovery Plan unavailable: {exc}"]
            logger.warning("%s", exc)
        payload = {
            "nodeName": node_name,
            "agentId": agent_id,
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "candidates": candidates,
            "scanErrors": scan_errors,
        }
        if protocols is not None:
            payload["scannedProtocols"] = list(protocols)
        try:
            signed_report(
                controller_url=controller_url,
                hmac_key=hmac_key,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
            logger.info(
                "reported plan-based discovery node=%s candidates=%d scanErrors=%d",
                node_name,
                len(candidates),
                len(scan_errors),
            )
            health_state.mark_report_success()
        except DiscoveryReportError as exc:
            logger.warning("%s", exc)
        elapsed = time.monotonic() - started
        jitter = random.uniform(0, min(3.0, interval_seconds * 0.1))
        time.sleep(max(1.0, interval_seconds + jitter - elapsed))


if __name__ == "__main__":
    run()
