"""mTLS edge clients for authenticated central telemetry and heartbeat endpoints."""

from __future__ import annotations

import json
import math
import ssl
import time
from typing import Any

import httpx

import hashlib
import hmac
from .config import TLSSettings
from .outbox import EdgeOutbox


def client_ssl_context(tls: TLSSettings) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=tls.ca_file)
    context.load_cert_chain(tls.cert_file, tls.key_file)
    return context


def canonical_json_bytes(body: dict[str, Any]) -> bytes:
    """The bytes signed and sent to the gateway; reject non-standard JSON."""
    def validate(value: Any) -> None:
        if value is None or isinstance(value, (str, bool, int)):
            return
        if isinstance(value, float):
            if math.isfinite(value):
                return
            raise ValueError("JSON numbers must be finite")
        if isinstance(value, list):
            for item in value:
                validate(item)
            return
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("JSON object keys must be strings")
                validate(item)
            return
        raise ValueError("JSON payload contains a non-JSON value")
    validate(body)
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()

def request_signature(secret: str, edge_id: str, timestamp: str, payload: bytes) -> str:
    """HMAC over the exact HTTP body bytes sent by the edge client."""
    digest = hashlib.sha256(payload).hexdigest()
    return hmac.new(secret.encode(), f"{edge_id}.{timestamp}.{digest}".encode(), hashlib.sha256).hexdigest()


class EdgeGatewayClient:
    def __init__(self, base_url: str, edge_id: str, edge_auth_secret: str, tls: TLSSettings) -> None:
        self.edge_id = edge_id
        self.edge_auth_secret = edge_auth_secret
        self.client = httpx.AsyncClient(base_url=base_url.rstrip("/"), verify=client_ssl_context(tls), timeout=10.0)

    async def close(self) -> None:
        await self.client.aclose()

    def _headers(self, raw: bytes, timestamp_header: str, signature_header: str) -> dict[str, str]:
        timestamp = str(time.time())
        return {"content-type": "application/json", "X-Edge-Id": self.edge_id,
                timestamp_header: timestamp,
                signature_header: request_signature(self.edge_auth_secret, self.edge_id, timestamp, raw)}

    async def flush_one(self, outbox: EdgeOutbox) -> bool:
        item = outbox.claim()
        if item is None:
            return False
        raw = canonical_json_bytes(item.payload)
        try:
            response = await self.client.post("/v1/ingest/events", content=raw,
                                              headers=self._headers(raw, "X-Edge-Timestamp", "X-Edge-Signature"))
            if 200 <= response.status_code < 300 and response.status_code != 201:
                outbox.failed(item.event_id, item.claim_token,
                              f"gateway protocol violation: expected 201 acknowledgement, got {response.status_code}")
                return False
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            status_code = error.response.status_code
            if 400 <= status_code < 500 and status_code not in (408, 425, 429):
                outbox.reject(item.event_id, item.claim_token, str(error))
            else:
                outbox.failed(item.event_id, item.claim_token, str(error))
            return False
        except httpx.HTTPError as error:
            outbox.failed(item.event_id, item.claim_token, str(error))
            return False
        try:
            ack = response.json()
            valid = (isinstance(ack, dict) and ack.get("edge_id") == self.edge_id and
                     ack.get("event_id") == item.event_id and ack.get("status") == "persisted" and
                     isinstance(ack.get("deduplicated"), bool))
        except (ValueError, json.JSONDecodeError):
            valid = False
        if not valid:
            outbox.failed(item.event_id, item.claim_token, "gateway returned malformed or non-persisted acknowledgement")
            return False
        outbox.delivered(item.event_id, item.claim_token)
        return True

    async def heartbeat(self, body: dict[str, Any]) -> None:
        if body.get("edge_id") != self.edge_id:
            raise ValueError("heartbeat edge_id must match client edge_id")
        raw = canonical_json_bytes(body)
        response = await self.client.post("/v1/heartbeats", content=raw,
                                          headers=self._headers(raw, "X-Heartbeat-Timestamp", "X-Heartbeat-Signature"))
        response.raise_for_status()
