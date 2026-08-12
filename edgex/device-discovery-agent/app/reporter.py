from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class DiscoveryReportError(RuntimeError):
    pass


def signed_report(
    *,
    controller_url: str,
    hmac_key: str,
    payload: dict[str, Any],
    timeout_seconds: float,
) -> None:
    path = "/internal/v1/discovery/reports"
    body = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    timestamp = str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{timestamp}\nPOST\n{path}\n{body_hash}".encode("utf-8")
    signature = hmac.new(
        hmac_key.encode("utf-8"),
        canonical,
        hashlib.sha256,
    ).hexdigest()
    request = Request(
        f"{controller_url.rstrip('/')}{path}",
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Controller-Timestamp": timestamp,
            "X-Controller-Signature": signature,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            response.read()
            if response.status != 202:
                raise DiscoveryReportError(
                    f"controller returned unexpected status {response.status}"
                )
    except HTTPError as exc:
        exc.read()
        raise DiscoveryReportError(
            f"controller rejected discovery report with status {exc.code}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise DiscoveryReportError(
            f"controller report failed: {exc.__class__.__name__}"
        ) from exc


def fetch_discovery_plan(
    *,
    controller_url: str,
    hmac_key: str,
    node_name: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    path = f"/internal/v1/discovery/plans/{node_name}"
    body = b""
    timestamp = str(int(time.time()))
    body_hash = hashlib.sha256(body).hexdigest()
    canonical = f"{timestamp}\nGET\n{path}\n{body_hash}".encode("utf-8")
    signature = hmac.new(
        hmac_key.encode("utf-8"),
        canonical,
        hashlib.sha256,
    ).hexdigest()
    request = Request(
        f"{controller_url.rstrip('/')}{path}",
        method="GET",
        headers={
            "Accept": "application/json",
            "X-Controller-Timestamp": timestamp,
            "X-Controller-Signature": signature,
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read()
            if response.status != 200:
                raise DiscoveryReportError(
                    f"controller returned unexpected status {response.status}"
                )
    except HTTPError as exc:
        exc.read()
        raise DiscoveryReportError(
            f"controller rejected Discovery Plan with status {exc.code}"
        ) from exc
    except (URLError, TimeoutError, OSError) as exc:
        raise DiscoveryReportError(
            f"controller plan request failed: {exc.__class__.__name__}"
        ) from exc
    try:
        parsed = json.loads(payload)
    except (ValueError, TypeError) as exc:
        raise DiscoveryReportError(
            "controller Discovery Plan response was invalid"
        ) from exc
    if not isinstance(parsed, dict) or parsed.get("nodeId") != node_name:
        raise DiscoveryReportError(
            "controller Discovery Plan did not match this node"
        )
    return parsed
