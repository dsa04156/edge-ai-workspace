from datetime import datetime, timezone

from app.models import NodeState, VirtualDeviceCollection
from app.resource_pool import build_resource_pool_state
from app.virtual_resource_registry import RESOURCE_REGISTRY
from app.virtual_resources import build_virtual_resource_state


def _node() -> NodeState:
    return NodeState(
        hostname="etri-ser0002-cgnmsb",
        instance="192.168.0.5:9100",
        node_type="server",
        collected_at=datetime.now(timezone.utc),
        raw_metrics={"up": 1.0},
        compute_pressure="low",
        memory_pressure="low",
        network_pressure="low",
        node_health="healthy",
    )


def test_resource_pool_separates_node_diagnostics_from_verified_runtime_candidates():
    nodes = [_node()]
    virtual_resources = build_virtual_resource_state(
        registry=RESOURCE_REGISTRY,
        service_resource_profiles=[],
        nodes=nodes,
    )
    state = build_resource_pool_state(
        virtual_devices=VirtualDeviceCollection(
            projection_enabled=False,
            generated_at=datetime.now(timezone.utc),
            observation_time=datetime.now(timezone.utc),
            config_revision="",
        ),
        nodes=nodes,
        virtual_resources=virtual_resources,
        service_resource_profiles=[],
    )

    node = next(item for item in state.resources if item.resource_class == "node_diagnostic")
    gpu = next(item for item in state.resources if item.id == "vd-x86-gpu-inference")

    assert node.status == "verified"
    assert node.selectable is False
    assert node.authority == "Kubernetes 노드 진단"
    assert gpu.status == "declared"
    assert gpu.selectable is False
    assert [item.stage for item in gpu.evidence] == ["definition", "runtime", "endpoint", "binding"]
    assert [item.state for item in gpu.evidence] == ["verified", "missing", "missing", "missing"]
    assert state.summary.verified_candidates == 0
    assert state.summary.declared_candidates == 4


def test_resource_pool_only_counts_fully_evidenced_free_runtime_as_verified_candidate():
    nodes = [_node()]
    profiles = [
        {
            "namespace": "edge-ai",
            "service": "gpu-runtime",
            "pod_count": 1,
            "nodes": ["etri-ser0002-cgnmsb"],
            "containers": [
                {
                    "namespace": "edge-ai",
                    "pod": "gpu-runtime-a",
                    "container": "runtime",
                    "node": "etri-ser0002-cgnmsb",
                    "labels": {
                        "edge-ai.io/augmentation-resource": "vd-x86-gpu-inference",
                        "edge-ai.io/binding-state": "free",
                    },
                    "pod_ready": True,
                    "endpoint_ready": True,
                }
            ],
        }
    ]
    virtual_resources = build_virtual_resource_state(
        registry=RESOURCE_REGISTRY,
        service_resource_profiles=profiles,
        nodes=nodes,
    )
    state = build_resource_pool_state(
        virtual_devices=VirtualDeviceCollection(
            projection_enabled=False,
            generated_at=datetime.now(timezone.utc),
            observation_time=datetime.now(timezone.utc),
            config_revision="",
        ),
        nodes=nodes,
        virtual_resources=virtual_resources,
        service_resource_profiles=profiles,
    )

    gpu = next(item for item in state.resources if item.id == "vd-x86-gpu-inference")
    assert gpu.status == "verified"
    assert gpu.selectable is True
    assert [item.state for item in gpu.evidence] == ["verified", "verified", "verified", "verified"]
    assert state.summary.verified_candidates == 1
