"""Adapters for explicitly handed-off resident runtimes; never scales their Pods."""
import asyncio
import math

import httpx


def matching_pods(binding, pods):
    return [p for p in pods if p["metadata"].get("namespace") == binding.namespace
            and not p["metadata"].get("deletionTimestamp")
            and p.get("status", {}).get("phase") not in ("Failed", "Succeeded")
            and all(p["metadata"].get("labels", {}).get(k) == v for k, v in binding.selector.items())]


def verify_binding(binding, image, node, snapshot, port):
    pods = matching_pods(binding, snapshot["pods"])
    if len(pods) != 1:
        return "resident_pod_missing_or_ambiguous"
    pod = pods[0]
    if pod.get("spec", {}).get("nodeName") != node:
        return "resident_on_different_node"
    containers = {c["name"]: c for c in pod["spec"].get("containers", [])}
    statuses = {c["name"]: c for c in pod.get("status", {}).get("containerStatuses", [])}
    if (containers.get(binding.container, {}).get("image") != image
            or not statuses.get(binding.container, {}).get("ready")
            or not any(c["type"] == "Ready" and c["status"] == "True" for c in pod.get("status", {}).get("conditions", []))):
        return "resident_image_or_pod_not_ready"
    services = [s for s in snapshot.get("kubeServices", []) if s["metadata"].get("namespace") == binding.namespace
                and s["metadata"]["name"] == binding.service]
    if (len(services) != 1 or services[0].get("spec", {}).get("selector") != binding.selector
            or services[0].get("spec", {}).get("type", "ClusterIP") != "ClusterIP"
            or not any(p.get("port") == port for p in services[0]["spec"].get("ports", []))):
        return "resident_service_identity_mismatch"
    for ref in binding.previousControllers:
        previous = [d for d in snapshot["deployments"] if d["metadata"].get("namespace") == ref.namespace
                    and d["metadata"]["name"] == ref.name]
        if len(previous) != 1 or previous[0]["spec"].get("replicas", 1) != 0:
            return "previous_controller_not_stopped"
        selector = previous[0]["spec"].get("selector", {}).get("matchLabels", {})
        if not selector or any(p["metadata"].get("namespace") == ref.namespace
                and p.get("status", {}).get("phase") not in ("Succeeded", "Failed")
                and all(p["metadata"].get("labels", {}).get(k) == v for k, v in selector.items())
                for p in snapshot["pods"]):
            return "previous_controller_pod_still_present"
    return None


def endpoint(target):
    binding = target["resident"]
    return f"http://{binding['service']}.{binding['namespace']}.svc.cluster.local:{target['spec']['port']}"


def identity(target):
    binding = target["resident"]
    return (binding["namespace"], binding["container"], tuple(sorted(binding["selector"].items())))


async def probe(client, target):
    try:
        h, m = await asyncio.gather(client.get(endpoint(target) + "/health", timeout=3),
                                   client.get(endpoint(target) + "/metrics", timeout=3))
        h.raise_for_status()
        m.raise_for_status()
        health, metrics = h.json(), m.json()
        if (health.get("node_id") != target["node"] or metrics.get("node_id") != target["node"]
                or health.get("model_digest") != target["spec"]["inference"]["modelDigest"]
                or health.get("management_runtime_running") is not True or health.get("model_cached") is not True):
            return None
        active, queued, vram = metrics.get("active_requests"), metrics.get("queue_length"), metrics.get("model_vram_mib")
        if (type(active) is not int or type(queued) is not int or min(active, queued) < 0
                or not isinstance(vram, (float, int)) or not math.isfinite(vram) or vram < 0
                or metrics.get("max_concurrency", 0) < target["capacity"]):
            return None
        return {"ready": health.get("inference_ready") is True and health.get("model_loaded") is True and vram > 0,
                "released": health.get("node_state") == "CACHED" and health.get("model_loaded") is False and vram == 0,
                "inFlight": active + queued, "modelVramMiB": vram, "nodeState": health.get("node_state"),
                "ioContract": target["spec"]["ioContract"]}
    except (httpx.HTTPError, ValueError, TypeError):
        return None


async def lifecycle(client, target, action):
    path, desired = ("/activate", "ACTIVE") if action == "activate" else ("/deactivate", "CACHED")
    response = await client.post(endpoint(target) + path, json={"target_state": desired, "reason": "common_runtime_operator"},
                                 timeout=target["spec"]["policy"]["prepareTimeoutSeconds"])
    response.raise_for_status()
    return response.json()


def request_body(spec, body, request_id):
    contract = spec["inference"]
    if body != {"prompt": contract["prompt"], "max_tokens": contract["maxTokens"]}:
        raise ValueError("input_outside_qualified_inference_contract")
    return {**body, "request_id": request_id}


def validate_result(target, request_id, result):
    if (not isinstance(result, dict) or result.get("request_id") != request_id
            or result.get("node_id") != target["node"]
            or result.get("model_digest") != target["spec"]["inference"]["modelDigest"]
            or not result.get("response") or not 0 < result.get("eval_count", 0) <= target["spec"]["inference"]["maxTokens"]):
        raise ValueError("runtime_response_identity_or_model_mismatch")
