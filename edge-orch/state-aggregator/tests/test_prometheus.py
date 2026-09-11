import asyncio

from app.prometheus import (
    PROMETHEUS_QUERIES,
    PrometheusClient,
    SERVICE_USAGE_PROFILE_QUERIES,
    SERVICE_USAGE_QUERIES,
)


class FakeResponse:
    def __init__(self, result):
        self._result = result

    def raise_for_status(self):
        return None

    def json(self):
        return {"data": {"result": self._result}}


class FakeAsyncClient:
    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def get(self, url, params):
        query = params["query"]
        if query == 'up{job="node-exporter"}':
            return FakeResponse([
                {"metric": {"instance": "192.168.0.3:9100"}, "value": [0, "1"]},
            ])
        if query == PROMETHEUS_QUERIES["cpu_logical_cores"]:
            return FakeResponse([
                {"metric": {"instance": "192.168.0.3:9100"}, "value": [0, "6"]},
            ])
        if query == PROMETHEUS_QUERIES["gpu_utilization"]:
            return FakeResponse([
                {"metric": {"instance": "192.168.0.3:9400", "gpu": "0"}, "value": [0, "47"]},
            ])
        if query == "DCGM_FI_DEV_FB_USED":
            return FakeResponse([
                {"metric": {"instance": "192.168.0.3:9400", "gpu": "0"}, "value": [0, "2048"]},
            ])
        if query == "DCGM_FI_DEV_FB_FREE":
            return FakeResponse([
                {"metric": {"instance": "192.168.0.3:9400", "gpu": "0"}, "value": [0, "6144"]},
            ])
        if query == PROMETHEUS_QUERIES["gpu_temperature_celsius"]:
            return FakeResponse([
                {"metric": {"instance": "192.168.0.3:9400", "gpu": "0"}, "value": [0, "58"]},
            ])
        if query == "DCGM_FI_DEV_POWER_USAGE":
            return FakeResponse([
                {"metric": {"instance": "192.168.0.3:9400", "gpu": "0"}, "value": [0, "72.5"]},
            ])
        return FakeResponse([])


def test_collect_node_metrics_merges_dcgm_gpu_metrics_by_node_ip(monkeypatch):
    import app.prometheus as prometheus_module

    monkeypatch.setattr(prometheus_module.httpx, "AsyncClient", FakeAsyncClient)
    client = PrometheusClient(
        "http://prometheus.example",
        {
            "192.168.0.3:9100": {"hostname": "etri-dev0001-jetorn", "node_type": "edge_ai_device"},
            "192.168.0.3": {"hostname": "etri-dev0001-jetorn", "node_type": "edge_ai_device"},
        },
    )

    items = asyncio.run(client.collect_node_metrics())

    assert len(items) == 1
    item = items[0]
    assert item.hostname == "etri-dev0001-jetorn"
    assert item.up == 1.0
    assert item.cpu_logical_cores == 6.0
    assert item.gpu_utilization == 0.47
    assert item.gpu_memory_used_mib == 2048.0
    assert item.gpu_memory_total_mib == 8192.0
    assert item.gpu_memory_usage_ratio == 0.25
    assert item.gpu_temperature_celsius == 58.0
    assert item.gpu_power_watts == 72.5


def test_collect_node_metrics_merges_dcgm_pod_ip_with_node_exporter(monkeypatch):
    import app.prometheus as prometheus_module

    class PodIpDcgmClient(FakeAsyncClient):
        async def get(self, url, params):
            query = params["query"]
            if query == 'up{job="node-exporter"}':
                return FakeResponse([
                    {"metric": {"instance": "192.168.0.56:9100"}, "value": [0, "1"]},
                ])
            if query == PROMETHEUS_QUERIES["cpu_logical_cores"]:
                return FakeResponse([
                    {"metric": {"instance": "192.168.0.56:9100"}, "value": [0, "24"]},
                ])
            if query == PROMETHEUS_QUERIES["gpu_utilization"]:
                return FakeResponse([
                    {"metric": {"instance": "10.244.0.160:9400", "pod": "dcgm-exporter-qvf62"}, "value": [0, "33"]},
                ])
            return FakeResponse([])

    mapping = {"hostname": "etri-ser0001-cg0msb", "node_type": "cloud_server"}
    monkeypatch.setattr(prometheus_module.httpx, "AsyncClient", PodIpDcgmClient)
    client = PrometheusClient(
        "http://prometheus.example",
        {
            "192.168.0.56:9100": mapping,
            "192.168.0.56": mapping,
            "10.244.0.160:9400": mapping,
            "10.244.0.160": mapping,
        },
    )

    items = asyncio.run(client.collect_node_metrics())

    assert len(items) == 1
    item = items[0]
    assert item.instance == "192.168.0.56:9100"
    assert item.hostname == "etri-ser0001-cg0msb"
    assert item.up == 1.0
    assert item.cpu_logical_cores == 24.0
    assert item.gpu_utilization == 0.33


def test_collect_service_resource_usage_merges_container_cpu_and_memory(monkeypatch):
    import app.prometheus as prometheus_module

    class UsageClient(FakeAsyncClient):
        async def get(self, url, params):
            query = params["query"]
            if query == SERVICE_USAGE_QUERIES["cpu_usage_cores"]:
                return FakeResponse([
                    {"metric": {"namespace": "default", "pod": "redis-a", "container": "redis"}, "value": [0, "0.07"]},
                ])
            if query == SERVICE_USAGE_QUERIES["memory_working_set_mib"]:
                return FakeResponse([
                    {"metric": {"namespace": "default", "pod": "redis-a", "container": "redis"}, "value": [0, "88.5"]},
                ])
            return FakeResponse([])

    monkeypatch.setattr(prometheus_module.httpx, "AsyncClient", UsageClient)
    client = PrometheusClient("http://prometheus.example", {})

    usage = asyncio.run(client.collect_service_resource_usage())

    assert usage == [
        {
            "namespace": "default",
            "pod": "redis-a",
            "container": "redis",
            "cpu_usage_cores": 0.07,
            "memory_working_set_mib": 88.5,
        }
    ]


def test_collect_service_resource_profile_usage_returns_window_statistics(monkeypatch):
    import app.prometheus as prometheus_module

    class ProfileUsageClient(FakeAsyncClient):
        async def get(self, url, params):
            query = params["query"]
            if query == SERVICE_USAGE_PROFILE_QUERIES["avg_cpu_usage_cores"]("10m"):
                return FakeResponse([
                    {"metric": {"namespace": "default", "pod": "analyzer-a", "container": "app"}, "value": [0, "0.21"]},
                ])
            if query == SERVICE_USAGE_PROFILE_QUERIES["max_cpu_usage_cores"]("10m"):
                return FakeResponse([
                    {"metric": {"namespace": "default", "pod": "analyzer-a", "container": "app"}, "value": [0, "0.75"]},
                ])
            if query == SERVICE_USAGE_PROFILE_QUERIES["p95_cpu_usage_cores"]("10m"):
                return FakeResponse([
                    {"metric": {"namespace": "default", "pod": "analyzer-a", "container": "app"}, "value": [0, "0.62"]},
                ])
            if query == SERVICE_USAGE_PROFILE_QUERIES["avg_memory_working_set_mib"]("10m"):
                return FakeResponse([
                    {"metric": {"namespace": "default", "pod": "analyzer-a", "container": "app"}, "value": [0, "220"]},
                ])
            if query == SERVICE_USAGE_PROFILE_QUERIES["max_memory_working_set_mib"]("10m"):
                return FakeResponse([
                    {"metric": {"namespace": "default", "pod": "analyzer-a", "container": "app"}, "value": [0, "310"]},
                ])
            if query == SERVICE_USAGE_PROFILE_QUERIES["p95_memory_working_set_mib"]("10m"):
                return FakeResponse([
                    {"metric": {"namespace": "default", "pod": "analyzer-a", "container": "app"}, "value": [0, "290"]},
                ])
            return FakeResponse([])

    monkeypatch.setattr(prometheus_module.httpx, "AsyncClient", ProfileUsageClient)
    client = PrometheusClient("http://prometheus.example", {})

    usage = asyncio.run(client.collect_service_resource_profile_usage(window="10m"))

    assert usage == [
        {
            "namespace": "default",
            "pod": "analyzer-a",
            "container": "app",
            "avg_cpu_usage_cores": 0.21,
            "max_cpu_usage_cores": 0.75,
            "p95_cpu_usage_cores": 0.62,
            "avg_memory_working_set_mib": 220.0,
            "max_memory_working_set_mib": 310.0,
            "p95_memory_working_set_mib": 290.0,
        }
    ]


def test_jetson_metric_joins_node_exporter_without_fabricating_gpu_memory(monkeypatch):
    import app.prometheus as mod
    class JetsonClient(FakeAsyncClient):
        async def get(self, url, params):
            if params['query'] == PROMETHEUS_QUERIES['gpu_utilization']:
                return FakeResponse([{'metric': {'instance': '192.168.0.3:9100'}, 'value': [0, '37.5']}])
            if params['query'].startswith('DCGM_') or params['query'] == PROMETHEUS_QUERIES['gpu_temperature_celsius']: return FakeResponse([])
            return await super().get(url, params)
    monkeypatch.setattr(mod.httpx, 'AsyncClient', JetsonClient)
    result=asyncio.run(PrometheusClient('http://prom',{'192.168.0.3:9100':{'hostname':'etri-dev0001-jetorn'}}).collect_node_metrics())
    assert len(result)==1 and result[0].gpu_utilization==.375
    assert result[0].gpu_memory_total_mib is None
    assert 'jetson_gpu_collector_success == 1' in PROMETHEUS_QUERIES['gpu_utilization']
    assert 'up{job="jetson-gpu-exporter"} == 1' in PROMETHEUS_QUERIES['gpu_utilization']


def test_temperature_metrics_remain_component_specific_and_missing_is_absent(monkeypatch):
    import app.prometheus as prometheus_module
    from app.normalizer import normalize_node_state

    class ThermalClient(FakeAsyncClient):
        async def get(self, url, params):
            values = {
                "up": [("agx:9100", "1"), ("spark:9100", "1")],
                "cpu_temperature_celsius": [("agx:9100", "43.5"), ("spark:9100", "NaN")],
                "gpu_temperature_celsius": [("agx:9100", "40.25"), ("agx:9400", "42")],
                "system_temperature_celsius": [("spark:9100", "39.8")],
            }
            key = next(k for k, q in PROMETHEUS_QUERIES.items() if q == params["query"])
            return FakeResponse([{"metric": {"instance": i}, "value": [0, v]} for i, v in values.get(key, [])])

    monkeypatch.setattr(prometheus_module.httpx, "AsyncClient", ThermalClient)
    agx = {"hostname": "agx"}
    client = PrometheusClient("http://prometheus.example", {"agx:9100": agx, "agx:9400": agx, "spark:9100": {"hostname": "spark"}})
    nodes = {n.hostname: normalize_node_state(n).raw_metrics for n in asyncio.run(client.collect_node_metrics())}
    assert nodes["agx"]["cpu_temperature_celsius"] == 43.5
    assert nodes["agx"]["gpu_temperature_celsius"] == 42
    assert "system_temperature_celsius" not in nodes["agx"]
    assert nodes["spark"]["system_temperature_celsius"] == 39.8
    assert "cpu_temperature_celsius" not in nodes["spark"]
    assert "gpu_temperature_celsius" not in nodes["spark"]
