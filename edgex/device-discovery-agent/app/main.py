from __future__ import annotations

import logging
import os
import random
import socket
import time
from datetime import datetime, timezone
from pathlib import Path

from .reporter import DiscoveryReportError, signed_report
from .scanner import scan_node


logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("edge-device-discovery")


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


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
    agent_id = f"edge-device-discovery/{node_name}/{socket.gethostname()}"
    heartbeat_path = Path(
        os.getenv("DISCOVERY_HEARTBEAT_PATH", "/tmp/discovery-heartbeat")
    )
    logger.info(
        "starting passive discovery node=%s interval=%ss",
        node_name,
        interval_seconds,
    )
    while True:
        started = time.monotonic()
        candidates, scan_errors = scan_node()
        payload = {
            "nodeName": node_name,
            "agentId": agent_id,
            "observedAt": datetime.now(timezone.utc).isoformat(),
            "candidates": candidates,
            "scanErrors": scan_errors,
        }
        try:
            signed_report(
                controller_url=controller_url,
                hmac_key=hmac_key,
                payload=payload,
                timeout_seconds=timeout_seconds,
            )
            logger.info(
                "reported passive discovery node=%s candidates=%d scanErrors=%d",
                node_name,
                len(candidates),
                len(scan_errors),
            )
        except DiscoveryReportError as exc:
            logger.warning("%s", exc)
        heartbeat_path.touch()
        elapsed = time.monotonic() - started
        jitter = random.uniform(0, min(3.0, interval_seconds * 0.1))
        time.sleep(max(1.0, interval_seconds + jitter - elapsed))


if __name__ == "__main__":
    run()
