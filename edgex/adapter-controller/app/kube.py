from __future__ import annotations

import json
import os
from typing import Any

from kubernetes import client, config
from kubernetes.client import ApiException

from .renderer import MANAGED_BY


GROUP = "edgeai.etri.re.kr"
VERSION = "v1alpha1"
PLURAL = "adapterruntimes"
CANDIDATE_REGISTRY_NAME = "edgex-device-discovery-registry"
CANDIDATE_REGISTRY_KEY = "registry.json"
CANDIDATE_REGISTRY_LABELS = {
    "app.kubernetes.io/name": "edgex-device-discovery-registry",
    "app.kubernetes.io/part-of": "edgex-system",
    "app.kubernetes.io/managed-by": "edgex-adapter-controller",
}


class KubernetesGateway:
    def __init__(
        self,
        *,
        namespace: str,
        core_api: Any | None = None,
        apps_api: Any | None = None,
        networking_api: Any | None = None,
        custom_api: Any | None = None,
    ) -> None:
        if namespace != "edgex-edge":
            raise ValueError("Adapter Controller namespace must be edgex-edge")
        self.namespace = namespace
        if all(
            api is not None
            for api in (core_api, apps_api, networking_api, custom_api)
        ):
            self.core = core_api
            self.apps = apps_api
            self.networking = networking_api
            self.custom = custom_api
            self.api_client = client.ApiClient()
            return
        if os.getenv("KUBERNETES_SERVICE_HOST"):
            config.load_incluster_config()
        else:
            config.load_kube_config()
        self.api_client = client.ApiClient()
        self.core = core_api or client.CoreV1Api()
        self.apps = apps_api or client.AppsV1Api()
        self.networking = networking_api or client.NetworkingV1Api()
        self.custom = custom_api or client.CustomObjectsApi()

    def list_runtimes(self) -> list[dict[str, Any]]:
        payload = self.custom.list_namespaced_custom_object(
            GROUP,
            VERSION,
            self.namespace,
            PLURAL,
        )
        items = payload.get("items") if isinstance(payload, dict) else None
        return list(items) if isinstance(items, list) else []

    def get_runtime(self, name: str) -> dict[str, Any] | None:
        try:
            return self.custom.get_namespaced_custom_object(
                GROUP,
                VERSION,
                self.namespace,
                PLURAL,
                name,
            )
        except ApiException as exc:
            if exc.status == 404:
                return None
            raise

    def apply_runtime(self, resource: dict[str, Any]) -> dict[str, Any]:
        name = resource["metadata"]["name"]
        current = self.get_runtime(name)
        if current is None:
            return self.custom.create_namespaced_custom_object(
                GROUP,
                VERSION,
                self.namespace,
                PLURAL,
                resource,
            )
        return self.custom.patch_namespaced_custom_object(
            GROUP,
            VERSION,
            self.namespace,
            PLURAL,
            name,
            resource,
        )

    def patch_runtime_spec(self, name: str, patch: dict[str, Any]) -> dict[str, Any]:
        return self.custom.patch_namespaced_custom_object(
            GROUP,
            VERSION,
            self.namespace,
            PLURAL,
            name,
            {"spec": patch},
        )

    def patch_runtime_status(
        self,
        namespace: str,
        name: str,
        status: dict[str, Any],
    ) -> None:
        self._require_namespace(namespace)
        self.custom.patch_namespaced_custom_object_status(
            GROUP,
            VERSION,
            self.namespace,
            PLURAL,
            name,
            {"status": status},
        )

    def read_candidate_registry(self) -> tuple[dict[str, Any], str | None]:
        try:
            config_map = self.core.read_namespaced_config_map(
                CANDIDATE_REGISTRY_NAME,
                self.namespace,
            )
        except ApiException as exc:
            if exc.status == 404:
                return {"version": 1, "nodes": [], "candidates": []}, None
            raise
        serialized = self.api_client.sanitize_for_serialization(config_map)
        metadata = serialized.get("metadata") or {}
        labels = metadata.get("labels") or {}
        if any(labels.get(key) != value for key, value in CANDIDATE_REGISTRY_LABELS.items()):
            raise ValueError("candidate registry ConfigMap has unexpected ownership labels")
        raw = (serialized.get("data") or {}).get(CANDIDATE_REGISTRY_KEY, "")
        if not raw:
            return (
                {"version": 1, "nodes": [], "candidates": []},
                str(metadata.get("resourceVersion") or "") or None,
            )
        document = json.loads(raw)
        if not isinstance(document, dict):
            raise ValueError("candidate registry document must be an object")
        return (
            document,
            str(metadata.get("resourceVersion") or "") or None,
        )

    def write_candidate_registry(
        self,
        document: dict[str, Any],
        *,
        resource_version: str | None,
    ) -> None:
        payload = json.dumps(
            document,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if len(payload.encode("utf-8")) > 900_000:
            raise ValueError("candidate registry exceeds the ConfigMap safety limit")
        body: dict[str, Any] = {
            "apiVersion": "v1",
            "kind": "ConfigMap",
            "metadata": {
                "name": CANDIDATE_REGISTRY_NAME,
                "namespace": self.namespace,
                "labels": dict(CANDIDATE_REGISTRY_LABELS),
            },
            "data": {CANDIDATE_REGISTRY_KEY: payload},
        }
        if resource_version is None:
            try:
                self.core.create_namespaced_config_map(self.namespace, body)
                return
            except ApiException as exc:
                if exc.status != 409:
                    raise
                raise ValueError(
                    "candidate registry was created concurrently; retry the request"
                ) from exc
        body["metadata"]["resourceVersion"] = resource_version
        self.core.replace_namespaced_config_map(
            CANDIDATE_REGISTRY_NAME,
            self.namespace,
            body,
        )

    def apply_resource(self, resource: dict[str, Any]) -> None:
        metadata = resource.get("metadata") or {}
        self._require_namespace(str(metadata.get("namespace") or ""))
        name = str(metadata.get("name") or "")
        kind = resource.get("kind")
        if not name:
            raise ValueError("managed resource name is required")
        labels = metadata.get("labels") or {}
        if labels.get("app.kubernetes.io/managed-by") != MANAGED_BY:
            raise ValueError("managed resource label is required")
        owner_uid = next(
            (
                str(item.get("uid") or "")
                for item in metadata.get("ownerReferences") or []
                if isinstance(item, dict)
                and item.get("kind") == "AdapterRuntime"
                and item.get("controller") is True
            ),
            "",
        )
        if not owner_uid:
            raise ValueError("managed resource controller owner is required")
        if kind == "Deployment":
            self._create_or_patch(
                read=lambda: self.apps.read_namespaced_deployment(name, self.namespace),
                create=lambda: self.apps.create_namespaced_deployment(
                    self.namespace, resource
                ),
                patch=lambda: self.apps.patch_namespaced_deployment(
                    name, self.namespace, resource
                ),
                owner_uid=owner_uid,
            )
        elif kind == "Service":
            self._create_or_patch(
                read=lambda: self.core.read_namespaced_service(name, self.namespace),
                create=lambda: self.core.create_namespaced_service(
                    self.namespace, resource
                ),
                patch=lambda: self.core.patch_namespaced_service(
                    name, self.namespace, resource
                ),
                owner_uid=owner_uid,
            )
        elif kind == "ConfigMap":
            self._create_or_patch(
                read=lambda: self.core.read_namespaced_config_map(name, self.namespace),
                create=lambda: self.core.create_namespaced_config_map(
                    self.namespace, resource
                ),
                patch=lambda: self.core.patch_namespaced_config_map(
                    name, self.namespace, resource
                ),
                owner_uid=owner_uid,
            )
        elif kind == "NetworkPolicy":
            self._create_or_patch(
                read=lambda: self.networking.read_namespaced_network_policy(
                    name, self.namespace
                ),
                create=lambda: self.networking.create_namespaced_network_policy(
                    self.namespace, resource
                ),
                patch=lambda: self.networking.patch_namespaced_network_policy(
                    name, self.namespace, resource
                ),
                owner_uid=owner_uid,
            )
        else:
            raise ValueError(f"resource kind {kind!r} is not controller-allowlisted")

    def _create_or_patch(
        self,
        *,
        read: Any,
        create: Any,
        patch: Any,
        owner_uid: str,
    ) -> None:
        try:
            current = read()
        except ApiException as exc:
            if exc.status == 404:
                create()
                return
            raise
        serialized = self.api_client.sanitize_for_serialization(current)
        self._assert_owned_resource(serialized, owner_uid=owner_uid)
        patch()

    def is_deployment_ready(self, namespace: str, name: str) -> bool:
        self._require_namespace(namespace)
        try:
            deployment = self.apps.read_namespaced_deployment(name, self.namespace)
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise
        status = deployment.status
        spec = deployment.spec
        desired = int(spec.replicas or 0)
        available = int(status.available_replicas or 0)
        observed = int(status.observed_generation or 0)
        generation = int(deployment.metadata.generation or 0)
        return desired > 0 and available >= desired and observed >= generation

    def delete_owned_resource(
        self,
        *,
        namespace: str,
        kind: str,
        name: str,
        owner_uid: str,
    ) -> None:
        self._require_namespace(namespace)
        api, read_method, delete_method = self._resource_methods(kind)
        try:
            resource = getattr(api, read_method)(name, self.namespace)
        except ApiException as exc:
            if exc.status == 404:
                return
            raise
        serialized = self.api_client.sanitize_for_serialization(resource)
        self._assert_owned_resource(serialized, owner_uid=owner_uid)
        getattr(api, delete_method)(
            name,
            self.namespace,
            body=client.V1DeleteOptions(
                propagation_policy="Background",
            ),
        )

    def _resource_methods(self, kind: str) -> tuple[Any, str, str]:
        methods = {
            "Deployment": (
                self.apps,
                "read_namespaced_deployment",
                "delete_namespaced_deployment",
            ),
            "Service": (
                self.core,
                "read_namespaced_service",
                "delete_namespaced_service",
            ),
            "ConfigMap": (
                self.core,
                "read_namespaced_config_map",
                "delete_namespaced_config_map",
            ),
            "NetworkPolicy": (
                self.networking,
                "read_namespaced_network_policy",
                "delete_namespaced_network_policy",
            ),
        }
        try:
            return methods[kind]
        except KeyError as exc:
            raise ValueError(f"resource kind {kind!r} is not deletion-allowlisted") from exc

    @staticmethod
    def _assert_owned_resource(
        resource: dict[str, Any],
        *,
        owner_uid: str,
    ) -> None:
        metadata = resource.get("metadata") or {}
        labels = metadata.get("labels") or {}
        if labels.get("app.kubernetes.io/managed-by") != MANAGED_BY:
            raise ValueError("refusing to delete a resource not managed by the controller")
        owners = metadata.get("ownerReferences") or metadata.get(
            "owner_references"
        ) or []
        if not any(
            str(item.get("uid") or "") == owner_uid
            and item.get("kind") == "AdapterRuntime"
            for item in owners
            if isinstance(item, dict)
        ):
            raise ValueError("refusing to delete a resource with a different owner")

    def node_exists(self, name: str) -> bool:
        try:
            self.core.read_node(name)
            return True
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise

    def node_ready(self, name: str) -> bool:
        try:
            node = self.core.read_node(name)
        except ApiException as exc:
            if exc.status == 404:
                return False
            raise
        conditions = getattr(getattr(node, "status", None), "conditions", None) or []
        return any(
            getattr(condition, "type", None) == "Ready"
            and getattr(condition, "status", None) == "True"
            for condition in conditions
        )

    def _require_namespace(self, namespace: str) -> None:
        if namespace != self.namespace:
            raise ValueError("controller access outside edgex-edge is forbidden")
