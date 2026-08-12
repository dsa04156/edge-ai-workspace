import pytest

from app.kube import KubernetesGateway


def owned_resource(*, owner_uid="runtime-uid", managed_by="edge-adapter-controller"):
    return {
        "metadata": {
            "labels": {"app.kubernetes.io/managed-by": managed_by},
            "ownerReferences": [
                {
                    "apiVersion": "edgeai.etri.re.kr/v1alpha1",
                    "kind": "AdapterRuntime",
                    "name": "runtime-01",
                    "uid": owner_uid,
                }
            ],
        }
    }


def test_owned_resource_guard_accepts_only_controller_owner():
    KubernetesGateway._assert_owned_resource(
        owned_resource(),
        owner_uid="runtime-uid",
    )

    with pytest.raises(ValueError, match="not managed"):
        KubernetesGateway._assert_owned_resource(
            owned_resource(managed_by="argocd"),
            owner_uid="runtime-uid",
        )
    with pytest.raises(ValueError, match="different owner"):
        KubernetesGateway._assert_owned_resource(
            owned_resource(owner_uid="different"),
            owner_uid="runtime-uid",
        )


def test_controller_rejects_non_edge_namespace_before_loading_client():
    with pytest.raises(ValueError, match="edgex-edge"):
        KubernetesGateway(namespace="default")


class CollisionAppsApi:
    def __init__(self):
        self.patch_calls = []

    def read_namespaced_deployment(self, name, namespace):
        return owned_resource(managed_by="argocd")

    def patch_namespaced_deployment(self, name, namespace, resource):
        self.patch_calls.append((name, namespace, resource))


def test_apply_refuses_to_take_over_same_name_external_workload():
    apps = CollisionAppsApi()
    gateway = KubernetesGateway(
        namespace="edgex-edge",
        core_api=object(),
        apps_api=apps,
        networking_api=object(),
        custom_api=object(),
    )
    desired = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": "adapter-serial-01",
            "namespace": "edgex-edge",
            "labels": {
                "app.kubernetes.io/managed-by": "edge-adapter-controller",
            },
            "ownerReferences": [
                {
                    "apiVersion": "edgeai.etri.re.kr/v1alpha1",
                    "kind": "AdapterRuntime",
                    "name": "adapter-serial-01",
                    "uid": "runtime-uid",
                    "controller": True,
                }
            ],
        },
    }

    with pytest.raises(ValueError, match="not managed"):
        gateway.apply_resource(desired)

    assert apps.patch_calls == []


class NodeApi:
    def __init__(self, status):
        self._status = status

    def read_node(self, name):
        condition = type("Condition", (), {"type": "Ready", "status": self._status})
        status = type("Status", (), {"conditions": [condition()]})
        return type("Node", (), {"status": status()})()


@pytest.mark.parametrize(("status", "expected"), [("True", True), ("False", False)])
def test_target_node_requires_kubernetes_ready_condition(status, expected):
    gateway = KubernetesGateway(
        namespace="edgex-edge",
        core_api=NodeApi(status),
        apps_api=object(),
        networking_api=object(),
        custom_api=object(),
    )

    assert gateway.node_ready("edge-node-02") is expected
