from __future__ import annotations

from datetime import datetime, timezone

import httpx

from .models import NodeRawMetrics


PROMETHEUS_QUERIES = {
    "up": 'up{job="node-exporter"}',
    "cpu_utilization": '1 - avg by(instance) (rate(node_cpu_seconds_total{mode="idle"}[5m]))',
    "cpu_logical_cores": 'count by(instance) (node_cpu_seconds_total{mode="idle"})',
    "memory_usage_ratio": '1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)',
    "load_average": "node_load1",
    "network_rx_rate": 'sum by(instance) (rate(node_network_receive_bytes_total{device!="lo"}[5m]))',
    "network_tx_rate": 'sum by(instance) (rate(node_network_transmit_bytes_total{device!="lo"}[5m]))',
    "gpu_utilization": "DCGM_FI_DEV_GPU_UTIL",
    "gpu_memory_used_mib": "DCGM_FI_DEV_FB_USED",
    "gpu_memory_free_mib": "DCGM_FI_DEV_FB_FREE",
    "gpu_temperature_celsius": "DCGM_FI_DEV_GPU_TEMP",
    "gpu_power_watts": "DCGM_FI_DEV_POWER_USAGE",
}

SERVICE_USAGE_QUERIES = {
    "cpu_usage_cores": 'sum by(namespace,pod,container) (rate(container_cpu_usage_seconds_total{container!="",container!="POD",image!=""}[5m]))',
    "memory_working_set_mib": 'sum by(namespace,pod,container) (container_memory_working_set_bytes{container!="",container!="POD",image!=""}) / 1024 / 1024',
}

SERVICE_USAGE_PROFILE_QUERIES = {
    "avg_cpu_usage_cores": lambda window: f'sum by(namespace,pod,container) (avg_over_time(rate(container_cpu_usage_seconds_total{{container!="",container!="POD",image!=""}}[1m])[{window}:]))',
    "max_cpu_usage_cores": lambda window: f'sum by(namespace,pod,container) (max_over_time(rate(container_cpu_usage_seconds_total{{container!="",container!="POD",image!=""}}[1m])[{window}:]))',
    "p95_cpu_usage_cores": lambda window: f'sum by(namespace,pod,container) (quantile_over_time(0.95, rate(container_cpu_usage_seconds_total{{container!="",container!="POD",image!=""}}[1m])[{window}:]))',
    "avg_memory_working_set_mib": lambda window: f'sum by(namespace,pod,container) (avg_over_time(container_memory_working_set_bytes{{container!="",container!="POD",image!=""}}[{window}]) / 1024 / 1024)',
    "max_memory_working_set_mib": lambda window: f'sum by(namespace,pod,container) (max_over_time(container_memory_working_set_bytes{{container!="",container!="POD",image!=""}}[{window}]) / 1024 / 1024)',
    "p95_memory_working_set_mib": lambda window: f'sum by(namespace,pod,container) (quantile_over_time(0.95, container_memory_working_set_bytes{{container!="",container!="POD",image!=""}}[{window}]) / 1024 / 1024)',
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
                    node_key = self._node_key(instance)
                    results.setdefault(node_key, {})[metric_name] = float(sample["value"][1])

        collected_at = datetime.now(timezone.utc)
        items: list[NodeRawMetrics] = []
        for instance, values in results.items():
            mapping = self._instance_mapping(instance)
            gpu_memory_used_mib = values.get("gpu_memory_used_mib")
            gpu_memory_free_mib = values.get("gpu_memory_free_mib")
            gpu_memory_total_mib = None
            gpu_memory_usage_ratio = None
            if gpu_memory_used_mib is not None and gpu_memory_free_mib is not None:
                gpu_memory_total_mib = gpu_memory_used_mib + gpu_memory_free_mib
                if gpu_memory_total_mib > 0:
                    gpu_memory_usage_ratio = round(gpu_memory_used_mib / gpu_memory_total_mib, 3)
            items.append(
                NodeRawMetrics(
                    instance=instance,
                    hostname=mapping.get("hostname", instance),
                    node_type=mapping.get("node_type"),
                    up=values.get("up", 0.0),
                    cpu_utilization=values.get("cpu_utilization", 0.0),
                    cpu_logical_cores=values.get("cpu_logical_cores"),
                    memory_usage_ratio=values.get("memory_usage_ratio", 0.0),
                    load_average=values.get("load_average", 0.0),
                    network_rx_rate=values.get("network_rx_rate", 0.0),
                    network_tx_rate=values.get("network_tx_rate", 0.0),
                    gpu_utilization=self._ratio_percent(values.get("gpu_utilization")),
                    gpu_memory_used_mib=gpu_memory_used_mib,
                    gpu_memory_total_mib=gpu_memory_total_mib,
                    gpu_memory_usage_ratio=gpu_memory_usage_ratio,
                    gpu_temperature_celsius=values.get("gpu_temperature_celsius"),
                    gpu_power_watts=values.get("gpu_power_watts"),
                    collected_at=collected_at,
                )
            )
        return items

    async def collect_service_resource_usage(self) -> list[dict[str, object]]:
        """Collect current per-container service CPU/MEM usage from Prometheus/cAdvisor."""
        return await self._collect_service_usage_queries(SERVICE_USAGE_QUERIES)

    async def collect_service_resource_profile_usage(self, window: str = "10m") -> list[dict[str, object]]:
        """Collect per-container service CPU/MEM window statistics for profile evidence."""
        return await self._collect_service_usage_queries(
            {metric_name: build_query(window) for metric_name, build_query in SERVICE_USAGE_PROFILE_QUERIES.items()}
        )

    async def _collect_service_usage_queries(self, queries: dict[str, str]) -> list[dict[str, object]]:
        results: dict[tuple[str, str, str], dict[str, object]] = {}
        async with httpx.AsyncClient(timeout=10.0) as client:
            for metric_name, query in queries.items():
                response = await client.get(
                    f"{self.base_url}/api/v1/query",
                    params={"query": query},
                )
                response.raise_for_status()
                payload = response.json()
                for sample in payload.get("data", {}).get("result", []):
                    metric = sample.get("metric", {})
                    namespace = metric.get("namespace")
                    pod = metric.get("pod")
                    container = metric.get("container")
                    if not namespace or not pod or not container:
                        continue
                    key = (namespace, pod, container)
                    row = results.setdefault(
                        key,
                        {"namespace": namespace, "pod": pod, "container": container},
                    )
                    row[metric_name] = float(sample["value"][1])
        return list(results.values())

    def _node_key(self, instance: str) -> str:
        if instance in self.instance_map:
            mapped = self.instance_map[instance]
            for candidate, candidate_mapping in self.instance_map.items():
                if candidate_mapping == mapped and candidate.endswith(":9100"):
                    return candidate
            return instance
        host = instance.rsplit(":", 1)[0]
        if host in self.instance_map:
            mapped = self.instance_map[host]
            for candidate, candidate_mapping in self.instance_map.items():
                if candidate_mapping == mapped and candidate.endswith(":9100"):
                    return candidate
        return instance

    def _instance_mapping(self, instance: str) -> dict[str, str]:
        mapping = self.instance_map.get(instance)
        if mapping is not None:
            return mapping
        host = instance.rsplit(":", 1)[0]
        return self.instance_map.get(host, {})

    def _ratio_percent(self, value: float | None) -> float | None:
        if value is None:
            return None
        return round(value / 100.0, 3)
