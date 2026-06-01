from __future__ import annotations

import os
from typing import Any

from prometheus_api_client import PrometheusConnect


def query_prometheus(query: str) -> dict[str, Any]:
    prometheus_url = os.getenv(
        "PROMETHEUS_URL", "http://prometheus-server.monitoring.svc:9090"
    )
    try:
        prom = PrometheusConnect(url=prometheus_url, disable_ssl=True)
        return {"query": query, "result": prom.custom_query(query=query)}
    except Exception as exc:
        return {"query": query, "error": str(exc)}
