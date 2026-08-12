import asyncio
from types import SimpleNamespace

from app.kube import KubeClient


def _pod(*, name: str, ready: bool):
    return SimpleNamespace(
        metadata=SimpleNamespace(
            namespace="edge-ai",
            name=name,
            labels={"edge-ai.io/augmentation-resource": "vd-x86-gpu-inference"},
            owner_references=[],
        ),
        spec=SimpleNamespace(
            node_name="gpu-node",
            containers=[
                SimpleNamespace(
                    name="runtime",
                    resources=SimpleNamespace(requests={}, limits={}),
                )
            ],
        ),
        status=SimpleNamespace(
            phase="Running",
            conditions=[SimpleNamespace(type="Ready", status="True" if ready else "False")],
        ),
    )


def test_running_service_pods_preserve_ready_endpoint_evidence():
    endpoint = SimpleNamespace(
        metadata=SimpleNamespace(namespace="edge-ai"),
        subsets=[
            SimpleNamespace(
                addresses=[
                    SimpleNamespace(target_ref=SimpleNamespace(kind="Pod", name="gpu-runtime-a"))
                ]
            )
        ],
    )
    fake_v1 = SimpleNamespace(
        list_pod_for_all_namespaces=lambda **_: SimpleNamespace(
            items=[_pod(name="gpu-runtime-a", ready=True), _pod(name="gpu-runtime-b", ready=False)]
        ),
        list_endpoints_for_all_namespaces=lambda: SimpleNamespace(items=[endpoint]),
    )
    kube = KubeClient.__new__(KubeClient)
    kube.enabled = True
    kube.v1 = fake_v1

    pods = asyncio.run(kube.get_running_service_pods())

    assert pods[0]["ready"] is True
    assert pods[0]["endpoint_ready"] is True
    assert pods[1]["ready"] is False
    assert pods[1]["endpoint_ready"] is False
