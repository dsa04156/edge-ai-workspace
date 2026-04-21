from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .models import NodeRawMetrics


PROMETHEUS_QUERIES = {
    "up": 'up{job="node-exporter"}',
    "cpu_utilization": '1 - avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))',
    "memory_usage_ratio": '1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)',
    "load_average": "node_load1",
    "network_rx_rate": 'sum by(instance) (rate(node_network_receive_bytes_total{device!="lo"}[5m]))',
    "network_tx_rate": 'sum by(instance) (rate(node_network_transmit_bytes_total{device!="lo"}[5m]))',
}


class PrometheusClient:
    def __init__(self, base_url: str, instance_map: dict[str, dict[str, str]]) -> None:
        self.base_url = base_url.rstrip("/")
        self.instance_map = instance_map

    async def collect_node_metrics(self) -> list[NodeRawMetrics]:
        results: dict[str, dict[str, float]] = {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            for metric_name, query in PROMETHEUS_QUERIES.items():
                response = await client.get(
                    f"{self.base_url}/api/v1/query",
                    params={"query": query},
                )
                response.raise_for_status()
                payload = response.json()
                for sample in payload.get("data", {}).get("result", []):
                    instance = sample.get("metric", {}).get("instance")
                    if not instance:
                        continue
                    results.setdefault(instance, {})[metric_name] = float(sample["value"][1])

        collected_at = datetime.now(timezone.utc)
        items: list[NodeRawMetrics] = []
        for instance, values in results.items():
            mapping = self.instance_map.get(instance, {})
            items.append(
                NodeRawMetrics(
                    instance=instance,
                    hostname=mapping.get("hostname", instance),
                    node_type=mapping.get("node_type"),
                    up=values.get("up", 0.0),
                    cpu_utilization=values.get("cpu_utilization", 0.0),
                    memory_usage_ratio=values.get("memory_usage_ratio", 0.0),
                    load_average=values.get("load_average", 0.0),
                    network_rx_rate=values.get("network_rx_rate", 0.0),
                    network_tx_rate=values.get("network_tx_rate", 0.0),
                    collected_at=collected_at,
                )
            )
        return items
