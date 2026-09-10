"""Scoped Kubernetes adapter. Only UID-owned resources in the configured namespace."""
import copy

from kubernetes import client, config
from kubernetes.client.exceptions import ApiException

from .contract import ServiceSpec

GROUP = "platform.jinuk.io"
VERSION = "v1alpha1"
PLURAL = "runtimeservices"
FINALIZER = GROUP + "/drain"


def owned(obj, uid):
    return any(r.get("uid") == uid and r.get("controller") is True and r.get("kind") == "RuntimeService"
               for r in obj.get("metadata", {}).get("ownerReferences", []))


class Kube:
    def __init__(self, namespace="platform-runtime"):
        self.namespace = namespace
        config.load_incluster_config()
        self.api = client.ApiClient()
        self.core = client.CoreV1Api(self.api)
        self.apps = client.AppsV1Api(self.api)
        self.custom = client.CustomObjectsApi(self.api)
        self.node = client.NodeV1Api(self.api)

    def raw(self, obj):
        return self.api.sanitize_for_serialization(obj)

    def snapshot(self):
        # Any failed/partial API read rejects this complete snapshot.
        return {
            "services": self.custom.list_namespaced_custom_object(GROUP, VERSION, self.namespace, PLURAL,
                                                                   _request_timeout=5)["items"],
            "nodes": self.raw(self.core.list_node(_request_timeout=5))["items"],
            "pods": self.raw(self.core.list_pod_for_all_namespaces(_request_timeout=5))["items"],
            "deployments": self.raw(self.apps.list_deployment_for_all_namespaces(_request_timeout=5))["items"],
            "kubeServices": self.raw(self.core.list_service_for_all_namespaces(_request_timeout=5))["items"],
            "runtimeClasses": self.raw(self.node.list_runtime_class(_request_timeout=5))["items"],
        }

    def finalizer(self, resource, add=True):
        body = copy.deepcopy(resource)
        values = body["metadata"].get("finalizers", [])
        body["metadata"]["finalizers"] = list(set(values + [FINALIZER])) if add else [v for v in values if v != FINALIZER]
        # resourceVersion protects deletion/spec changes made by an operator concurrently.
        return self.custom.replace_namespaced_custom_object(GROUP, VERSION, self.namespace, PLURAL,
                                                            resource["metadata"]["name"], body, _request_timeout=5)

    def status(self, resource, status):
        self.custom.patch_namespaced_custom_object_status(GROUP, VERSION, self.namespace, PLURAL,
            resource["metadata"]["name"], {"metadata": {"resourceVersion": resource["metadata"]["resourceVersion"]},
                                         "status": status}, _request_timeout=5)

    def _existing(self, kind, name, uid):
        read = self.apps.read_namespaced_deployment if kind == "Deployment" else self.core.read_namespaced_service
        try:
            obj = self.raw(read(name, self.namespace, _request_timeout=5))
        except ApiException as e:
            if e.status == 404:
                return None
            raise
        if not owned(obj, uid):
            raise ValueError("ownership_conflict:" + name)
        return obj

    def ensure(self, resource, spec: ServiceSpec, candidate, name):
        uid = resource["metadata"]["uid"]
        ref = {"apiVersion": GROUP + "/" + VERSION, "kind": "RuntimeService", "name": resource["metadata"]["name"],
               "uid": uid, "controller": True, "blockOwnerDeletion": True}
        labels = {GROUP + "/service-uid": uid, GROUP + "/revision": name}
        meta = {"name": name, "namespace": self.namespace, "labels": labels, "ownerReferences": [ref]}
        v = candidate.variant
        pod_spec = {
            "automountServiceAccountToken": False,
            "terminationGracePeriodSeconds": int(spec.timeoutSeconds) + 15,
            "securityContext": {"runAsNonRoot": True, "runAsUser": 65532, "runAsGroup": 65532},
            # matchFields does not rely on hostname label matching the Node name.
            "affinity": {"nodeAffinity": {"requiredDuringSchedulingIgnoredDuringExecution": {
                "nodeSelectorTerms": [{"matchFields": [{"key": "metadata.name", "operator": "In", "values": [candidate.node]}]}]}}},
            "nodeSelector": {**spec.policy.nodeSelector, **v.nodeSelector,
                             "kubernetes.io/arch": v.architecture, "kubernetes.io/os": "linux"},
            "containers": [{"name": "runtime", "image": v.image, "imagePullPolicy": "IfNotPresent",
                "ports": [{"containerPort": spec.port, "name": "http"}],
                "env": [{"name": "PLATFORM_IO_CONTRACT", "value": spec.ioContract},
                        {"name": "PLATFORM_PORT", "value": str(spec.port)},
                        {"name": "PLATFORM_NODE", "valueFrom": {"fieldRef": {"fieldPath": "spec.nodeName"}}}],
                "resources": {"requests": v.requests, "limits": v.limits},
                "securityContext": {"allowPrivilegeEscalation": False, "readOnlyRootFilesystem": True,
                                    "capabilities": {"drop": ["ALL"]}},
                "readinessProbe": {"httpGet": {"path": spec.readyPath, "port": spec.port},
                                   "periodSeconds": 2, "timeoutSeconds": 2},
                "volumeMounts": [{"name": "scratch", "mountPath": "/tmp"}]}],
            "volumes": [{"name": "scratch", "emptyDir": {"sizeLimit": "128Mi"}}],
        }
        if v.runtimeClassName:
            pod_spec["runtimeClassName"] = v.runtimeClassName
        existing = self._existing("Deployment", name, uid)
        if existing is None:
            self.apps.create_namespaced_deployment(self.namespace, {"apiVersion": "apps/v1", "kind": "Deployment",
                "metadata": meta, "spec": {"replicas": 1, "revisionHistoryLimit": 1, "strategy": {"type": "Recreate"},
                "selector": {"matchLabels": labels}, "template": {"metadata": {"labels": labels}, "spec": pod_spec}}},
                _request_timeout=5)
        elif existing["spec"].get("replicas") != 1:
            self.scale(name, uid, 1)
        if self._existing("Service", name, uid) is None:
            self.core.create_namespaced_service(self.namespace, {"apiVersion": "v1", "kind": "Service", "metadata": meta,
                "spec": {"selector": labels, "ports": [{"port": spec.port, "targetPort": spec.port}]}}, _request_timeout=5)

    def scale(self, name, uid, replicas):
        existing = self._existing("Deployment", name, uid)
        if existing and existing["spec"].get("replicas") != replicas:
            self.apps.patch_namespaced_deployment(name, self.namespace,
                {"metadata": {"resourceVersion": existing["metadata"]["resourceVersion"]}, "spec": {"replicas": replicas}},
                _request_timeout=5)

    def remove(self, name, uid):
        for kind in ("Deployment", "Service"):
            existing = self._existing(kind, name, uid)
            if existing:
                delete = self.apps.delete_namespaced_deployment if kind == "Deployment" else self.core.delete_namespaced_service
                delete(name, self.namespace, body={"preconditions": {"uid": existing["metadata"]["uid"]}}, _request_timeout=5)
