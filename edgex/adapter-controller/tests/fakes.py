from __future__ import annotations

from copy import deepcopy


class FakeKubernetesGateway:
    def __init__(
        self,
        *,
        deployment_ready: bool = False,
        target_node_ready: bool = True,
    ) -> None:
        self.deployment_ready = deployment_ready
        self.target_node_ready = target_node_ready
        self.applied: list[dict] = []
        self.deleted: list[tuple[str, str]] = []
        self.statuses: list[tuple[str, dict]] = []
        self.runtimes: dict[str, dict] = {}
        self.runtime_apply_calls: list[str] = []
        self.runtime_patches: list[tuple[str, dict]] = []
        self.nodes: set[str] = {
            "etri-dev0001-jetorn",
            "etri-dev0002-raspi5",
            "etri-dev0003-raspi5",
        }
        self.candidate_registry: dict = {
            "version": 1,
            "nodes": [],
            "candidates": [],
        }
        self.candidate_registry_version = 0

    def node_ready(self, name: str) -> bool:
        return self.target_node_ready

    def node_exists(self, name: str) -> bool:
        return name in self.nodes

    def read_candidate_registry(self):
        version = (
            str(self.candidate_registry_version)
            if self.candidate_registry_version
            else None
        )
        return deepcopy(self.candidate_registry), version

    def write_candidate_registry(self, document, *, resource_version):
        expected = (
            str(self.candidate_registry_version)
            if self.candidate_registry_version
            else None
        )
        if resource_version != expected:
            raise ValueError("candidate registry version conflict")
        self.candidate_registry = deepcopy(document)
        self.candidate_registry_version += 1

    def apply_resource(self, resource: dict) -> None:
        self.applied.append(deepcopy(resource))

    def is_deployment_ready(self, namespace: str, name: str) -> bool:
        return self.deployment_ready

    def patch_runtime_status(self, namespace: str, name: str, status: dict) -> None:
        self.statuses.append((name, deepcopy(status)))
        if name in self.runtimes:
            self.runtimes[name]["status"] = deepcopy(status)

    def delete_owned_resource(
        self,
        *,
        namespace: str,
        kind: str,
        name: str,
        owner_uid: str,
    ) -> None:
        self.deleted.append((kind, name))

    def list_runtimes(self):
        return [deepcopy(item) for item in self.runtimes.values()]

    def get_runtime(self, name):
        runtime = self.runtimes.get(name)
        return deepcopy(runtime) if runtime is not None else None

    def apply_runtime(self, resource):
        persisted = deepcopy(resource)
        persisted["metadata"].setdefault("uid", f"uid-{persisted['metadata']['name']}")
        persisted["metadata"].setdefault("generation", 1)
        self.runtimes[persisted["metadata"]["name"]] = persisted
        self.runtime_apply_calls.append(persisted["metadata"]["name"])
        return deepcopy(persisted)

    def patch_runtime_spec(self, name, patch):
        self.runtime_patches.append((name, deepcopy(patch)))
        self.runtimes[name].setdefault("spec", {}).update(deepcopy(patch))
        self.runtimes[name]["metadata"]["generation"] = (
            int(self.runtimes[name]["metadata"].get("generation") or 1) + 1
        )
        return deepcopy(self.runtimes[name])


class FakeEdgeXServiceProbe:
    def __init__(self, *, ready: bool = False, consumers: int = 0) -> None:
        self.ready = ready
        self.consumers = consumers
        self.calls: list[str] = []
        self.consumer_calls: list[str] = []

    def service_ready(self, service_name: str) -> bool:
        self.calls.append(service_name)
        return self.ready

    def consumer_count(self, service_name: str) -> int:
        self.consumer_calls.append(service_name)
        return self.consumers
