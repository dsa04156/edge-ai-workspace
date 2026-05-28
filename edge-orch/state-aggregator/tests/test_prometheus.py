import asyncio

from app.prometheus import PrometheusClient, SERVICE_USAGE_QUERIES


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
        if query == "DCGM_FI_DEV_GPU_UTIL":
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
        if query == "DCGM_FI_DEV_GPU_TEMP":
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
            if query == "DCGM_FI_DEV_GPU_UTIL":
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
