from __future__ import annotations

from copy import deepcopy
from typing import Any

from .models import RuntimeApplyRequest, RuntimePlan, RuntimeTemplate


API_VERSION = "edgeai.etri.re.kr/v1alpha1"
MANAGED_BY = "edge-adapter-controller"
FINALIZER = "edgeai.etri.re.kr/runtime-cleanup"
MESSAGEBUS_HOST = "edgex-messagebus.edgex-system.svc.cluster.local"
CORE_KEEPER_HOST = "edgex-core-keeper.edgex-system.svc.cluster.local"
CORE_METADATA_HOST = "edgex-core-metadata.edgex-system.svc.cluster.local"


def render_adapter_runtime(
    plan: RuntimePlan,
    template: RuntimeTemplate,
    request: RuntimeApplyRequest,
    *,
    namespace: str,
) -> dict[str, Any]:
    if namespace != "edgex-edge":
        raise ValueError("AdapterRuntime namespace must be edgex-edge")
    if plan.action != "DEPLOY" or not plan.allowed:
        raise ValueError("only an allowed DEPLOY plan can create AdapterRuntime")
    if request.plan_hash != plan.plan_hash:
        raise ValueError("runtime plan hash does not match the apply request")
    if plan.template_id != template.template_id:
        raise ValueError("runtime plan template does not match the catalog")
    if plan.adapter_id != template.adapter_id:
        raise ValueError("runtime plan adapter does not match the catalog")
    if not plan.runtime_name or not plan.service_name:
        raise ValueError("DEPLOY plan requires runtime and service identity")
    if not template.deployment_enabled:
        raise ValueError("runtime template is not deployment-enabled")

    labels = _labels(plan.runtime_name, template.adapter_id)
    return {
        "apiVersion": API_VERSION,
        "kind": "AdapterRuntime",
        "metadata": {
            "name": plan.runtime_name,
            "namespace": namespace,
            "labels": labels,
            "finalizers": [FINALIZER],
        },
        "spec": {
            "templateId": template.template_id,
            "adapterId": template.adapter_id,
            "targetNode": plan.target_node,
            "hardwareBindingId": plan.hardware_binding_id,
            "edgeX": {
                "serviceName": plan.service_name,
                "messageBusHost": MESSAGEBUS_HOST,
                "messageBusPort": 1883,
            },
            "desiredState": "Running",
            "restartNonce": "",
            "requestRef": {
                "requestId": request.request_id,
                "payloadHash": request.payload_hash,
                "planHash": request.plan_hash,
            },
        },
    }


def render_runtime_workload(
    runtime: dict[str, Any],
    template: RuntimeTemplate,
    *,
    namespace: str,
) -> list[dict[str, Any]]:
    metadata = runtime.get("metadata") or {}
    spec = runtime.get("spec") or {}
    name = str(metadata.get("name") or "")
    uid = str(metadata.get("uid") or "")
    if runtime.get("apiVersion") != API_VERSION or runtime.get("kind") != "AdapterRuntime":
        raise ValueError("invalid AdapterRuntime identity")
    if namespace != "edgex-edge" or metadata.get("namespace") != namespace:
        raise ValueError("AdapterRuntime namespace must be edgex-edge")
    if not name or not uid:
        raise ValueError("persisted AdapterRuntime name and uid are required")
    if spec.get("templateId") != template.template_id:
        raise ValueError("AdapterRuntime template is not allowlisted")
    if spec.get("adapterId") != template.adapter_id:
        raise ValueError("AdapterRuntime adapter is not allowlisted")
    binding = next(
        (
            item
            for item in template.hardware_bindings
            if item.binding_id == spec.get("hardwareBindingId")
        ),
        None,
    )
    if binding is None:
        raise ValueError("AdapterRuntime hardware binding is not allowlisted")
    if spec.get("targetNode") != binding.node_name:
        raise ValueError("AdapterRuntime node does not match hardware binding")
    if not template.deployment_enabled or template.image is None:
        raise ValueError("runtime template is not deployment-enabled")

    edge_x = spec.get("edgeX") or {}
    service_name = str(edge_x.get("serviceName") or "")
    if service_name != name:
        raise ValueError("runtime and EdgeX service identity must match")
    if edge_x.get("messageBusHost") != MESSAGEBUS_HOST:
        raise ValueError("message bus host is not the approved service DNS")
    if edge_x.get("messageBusPort") != 1883:
        raise ValueError("message bus port is not approved")

    labels = _labels(name, template.adapter_id)
    owner_references = [
        {
            "apiVersion": API_VERSION,
            "kind": "AdapterRuntime",
            "name": name,
            "uid": uid,
            "controller": True,
            "blockOwnerDeletion": True,
        }
    ]
    object_metadata = {
        "name": name,
        "namespace": namespace,
        "labels": labels,
        "ownerReferences": owner_references,
    }
    restart_nonce = str(spec.get("restartNonce") or "")
    pod_annotations = (
        {"edgeai.etri.re.kr/restart-nonce": restart_nonce}
        if restart_nonce
        else {}
    )
    configuration = _configuration_yaml(
        service_name=service_name,
        service_port=template.service_port,
    )
    config_map = {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": deepcopy(object_metadata),
        "data": {"configuration.yaml": configuration},
    }
    volume_mounts: list[dict[str, Any]] = [
        {
            "name": "runtime-config",
            "mountPath": "/res/configuration.yaml",
            "subPath": "configuration.yaml",
            "readOnly": True,
        },
        {"name": "profiles", "mountPath": "/res/profiles"},
        {"name": "devices", "mountPath": "/res/devices"},
        {"name": "tmp", "mountPath": "/tmp"},
    ]
    volumes: list[dict[str, Any]] = [
        {
            "name": "runtime-config",
            "configMap": {
                "name": name,
                "items": [
                    {
                        "key": "configuration.yaml",
                        "path": "configuration.yaml",
                    }
                ],
            },
        },
        {"name": "profiles", "emptyDir": {}},
        {"name": "devices", "emptyDir": {}},
        {"name": "tmp", "emptyDir": {}},
    ]
    if binding.host_device_path is not None:
        volume_mounts.append(
            {
                "name": "hardware-device",
                "mountPath": binding.container_device_path,
            }
        )
        volumes.append(
            {
                "name": "hardware-device",
                "hostPath": {
                    "path": binding.host_device_path,
                    "type": binding.device_type,
                },
            }
        )
    security_context: dict[str, Any]
    if binding.requires_privileged:
        security_context = {
            "privileged": True,
            "allowPrivilegeEscalation": True,
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": False,
            "runAsUser": 0,
            "runAsGroup": 0,
        }
    else:
        security_context = {
            "privileged": False,
            "allowPrivilegeEscalation": False,
            "capabilities": {"drop": ["ALL"]},
            "readOnlyRootFilesystem": True,
            "runAsNonRoot": True,
            "runAsUser": 65532,
            "runAsGroup": 65532,
        }
    container = {
        "name": "device-service",
        "image": template.image,
        "imagePullPolicy": "IfNotPresent",
        "args": [
            f"-cp=keeper.http://{CORE_KEEPER_HOST}:59890",
            "-cd=/res",
        ],
        "env": [
            {"name": "EDGEX_SERVICE_NAME", "value": service_name},
            {"name": "EDGEX_SECURITY_SECRET_STORE", "value": "false"},
            {
                "name": "SERVICE_HOST",
                "value": f"{service_name}.{namespace}.svc.cluster.local",
            },
            {"name": "SERVICE_PORT", "value": str(template.service_port)},
            {"name": "SERVICE_SERVERBINDADDR", "value": "0.0.0.0"},
            {"name": "CLIENTS_CORE_METADATA_HOST", "value": CORE_METADATA_HOST},
            {"name": "MESSAGEBUS_HOST", "value": MESSAGEBUS_HOST},
            {"name": "MESSAGEBUS_OPTIONAL_CLIENTID", "value": service_name},
        ],
        "ports": [
            {
                "name": "http",
                "containerPort": template.service_port,
                "protocol": "TCP",
            }
        ],
        "startupProbe": {
            "httpGet": {"path": "/api/v3/ping", "port": "http"},
            "periodSeconds": 2,
            "failureThreshold": 60,
        },
        "readinessProbe": {
            "httpGet": {"path": "/api/v3/ping", "port": "http"},
            "periodSeconds": 5,
            "failureThreshold": 3,
        },
        "livenessProbe": {
            "httpGet": {"path": "/api/v3/ping", "port": "http"},
            "periodSeconds": 10,
            "failureThreshold": 3,
        },
        "resources": {
            "requests": {"cpu": "25m", "memory": "64Mi"},
            "limits": {"cpu": "750m", "memory": "384Mi"},
        },
        "securityContext": security_context,
        "volumeMounts": volume_mounts,
    }
    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": deepcopy(object_metadata),
        "spec": {
            "replicas": 1,
            "revisionHistoryLimit": 2,
            "strategy": {"type": "Recreate"},
            "selector": {"matchLabels": _selector_labels(name)},
            "template": {
                "metadata": {
                    "labels": labels,
                    **({"annotations": pod_annotations} if pod_annotations else {}),
                },
                "spec": {
                    "nodeSelector": {
                        "kubernetes.io/hostname": binding.node_name,
                    },
                    "automountServiceAccountToken": False,
                    "terminationGracePeriodSeconds": 20,
                    "securityContext": {
                        "seccompProfile": {"type": "RuntimeDefault"},
                    },
                    "containers": [container],
                    "volumes": volumes,
                },
            },
        },
    }
    service = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": deepcopy(object_metadata),
        "spec": {
            "type": "ClusterIP",
            "selector": _selector_labels(name),
            "ports": [
                {
                    "name": "http",
                    "port": template.service_port,
                    "targetPort": "http",
                }
            ],
        },
    }
    network_policy = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": deepcopy(object_metadata),
        "spec": {
            "podSelector": {"matchLabels": _selector_labels(name)},
            "policyTypes": ["Ingress", "Egress"],
            "ingress": [
                {
                    "from": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": "edgex-system",
                                }
                            }
                        },
                        {
                            "namespaceSelector": {},
                            "podSelector": {
                                "matchLabels": {
                                    "edge-ai.io/local-data-client": "true",
                                }
                            },
                        },
                    ],
                    "ports": [
                        {"protocol": "TCP", "port": template.service_port},
                    ],
                }
            ],
            "egress": [
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": "kube-system",
                                }
                            }
                        }
                    ],
                    "ports": [
                        {"protocol": "UDP", "port": 53},
                        {"protocol": "TCP", "port": 53},
                    ],
                },
                {
                    "to": [
                        {
                            "namespaceSelector": {
                                "matchLabels": {
                                    "kubernetes.io/metadata.name": "edgex-system",
                                }
                            }
                        }
                    ],
                    "ports": [
                        {"protocol": "TCP", "port": 59890},
                        {"protocol": "TCP", "port": 59881},
                        {"protocol": "TCP", "port": 1883},
                    ],
                },
                *[
                    {
                        "to": [
                            (
                                {
                                    "namespaceSelector": {
                                        "matchLabels": {
                                            "kubernetes.io/metadata.name": (
                                                rule.namespace
                                            ),
                                        }
                                    },
                                    "podSelector": {
                                        "matchLabels": rule.pod_selector,
                                    },
                                }
                                if rule.cidr is None
                                else {
                                    "ipBlock": {
                                        "cidr": rule.cidr,
                                    }
                                }
                            )
                        ],
                        "ports": [
                            {"protocol": "TCP", "port": port}
                            for port in rule.ports
                        ],
                    }
                    for rule in template.network_egress
                ],
            ],
        },
    }
    return [config_map, deployment, service, network_policy]


def _labels(runtime_name: str, adapter_id: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": runtime_name,
        "app.kubernetes.io/part-of": "edgex-system",
        "app.kubernetes.io/managed-by": MANAGED_BY,
        "edgeai.etri.re.kr/runtime": runtime_name,
        "edgeai.etri.re.kr/adapter": adapter_id,
    }


def _selector_labels(runtime_name: str) -> dict[str, str]:
    return {
        "app.kubernetes.io/name": runtime_name,
        "edgeai.etri.re.kr/runtime": runtime_name,
    }


def _configuration_yaml(*, service_name: str, service_port: int) -> str:
    return (
        "Writable:\n"
        "  LogLevel: INFO\n"
        "  Reading:\n"
        "    ReadingUnits: true\n"
        "Service:\n"
        f"  Host: {service_name}\n"
        f"  Port: {service_port}\n"
        f"  StartupMsg: {service_name} managed Adapter runtime started\n"
        "Clients:\n"
        f"  core-metadata:\n    Host: {CORE_METADATA_HOST}\n"
        "MessageBus:\n"
        f"  Host: {MESSAGEBUS_HOST}\n"
        f"  Optional:\n    ClientId: {service_name}\n"
        "MaxConcurrentCommands: 16\n"
        "Device:\n"
        "  AsyncBufferSize: 16\n"
        "  ProfilesDir: /res/profiles\n"
        "  DevicesDir: /res/devices\n"
        "  Discovery:\n"
        "    Enabled: false\n"
        "    Interval: 30s\n"
        "  AutoEvents:\n"
        "    SendChangedReadingsOnly: false\n"
    )
