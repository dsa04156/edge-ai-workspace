from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

PROFILED_NAMESPACES = {"default", "offload-test", "kubeedge", "telemetry"}
INFRA_NAMESPACES = {"kube-system", "argocd", "traefik", "local-path-storage"}


def build_service_resource_profiles(
    pods: list[dict[str, Any]],
    usage_samples: list[dict[str, Any]] | None = None,
    profile_window: str | None = None,
) -> list[dict[str, Any]]:
    """Build resource profiles for running services.

    The profile combines two different signals:
    - declared requirements: Kubernetes requests/limits from Pod specs
    - current usage: Prometheus/cAdvisor CPU and memory samples
    """

    generated_at = datetime.now(timezone.utc).isoformat()
    usage_by_container = {
        (sample.get("namespace"), sample.get("pod"), sample.get("container")): sample
        for sample in usage_samples or []
    }
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for pod in pods:
        if pod.get("phase") != "Running":
            continue
        namespace = pod.get("namespace") or "default"
        if namespace in INFRA_NAMESPACES:
            continue
        service = pod.get("workload") or _service_from_pod_name(pod.get("name") or "unknown")
        grouped[(namespace, service)].append(pod)

    profiles: list[dict[str, Any]] = []
    for (namespace, service), items in sorted(grouped.items()):
        container_count = 0
        declared_request_cpu_cores = 0.0
        declared_request_memory_mib = 0.0
        declared_limit_cpu_cores = 0.0
        declared_limit_memory_mib = 0.0
        declared_gpu = 0.0
        missing_cpu_request = 0
        missing_memory_request = 0
        missing_cpu_limit = 0
        missing_memory_limit = 0
        current_cpu_usage_cores = 0.0
        current_memory_working_set_mib = 0.0
        usage_profile_totals = {
            "avg_cpu_usage_cores": 0.0,
            "max_cpu_usage_cores": 0.0,
            "p95_cpu_usage_cores": 0.0,
            "avg_memory_working_set_mib": 0.0,
            "max_memory_working_set_mib": 0.0,
            "p95_memory_working_set_mib": 0.0,
        }
        usage_sample_count = 0
        profile_sample_count = 0
        container_rows: list[dict[str, Any]] = []

        for pod in items:
            for container in pod.get("containers") or []:
                container_count += 1
                requests = container.get("requests") or {}
                limits = container.get("limits") or {}
                cpu_request = parse_cpu_cores(requests.get("cpu"))
                memory_request = parse_memory_mib(requests.get("memory"))
                cpu_limit = parse_cpu_cores(limits.get("cpu"))
                memory_limit = parse_memory_mib(limits.get("memory"))
                gpu_limit = parse_gpu_units(
                    limits.get("nvidia.com/gpu")
                    or limits.get("nvidia.com/vgpu")
                    or limits.get("hami.io/vgpu-devices")
                    or limits.get("k8s.v1.cni.cncf.io/resourceName")
                )

                if cpu_request is None:
                    missing_cpu_request += 1
                else:
                    declared_request_cpu_cores += cpu_request
                if memory_request is None:
                    missing_memory_request += 1
                else:
                    declared_request_memory_mib += memory_request
                if cpu_limit is None:
                    missing_cpu_limit += 1
                else:
                    declared_limit_cpu_cores += cpu_limit
                if memory_limit is None:
                    missing_memory_limit += 1
                else:
                    declared_limit_memory_mib += memory_limit
                declared_gpu += gpu_limit or 0.0
                usage = usage_by_container.get((namespace, pod.get("name"), container.get("name"))) or {}
                cpu_usage = _float_or_none(usage.get("cpu_usage_cores"))
                memory_usage = _float_or_none(usage.get("memory_working_set_mib"))
                profile_values = {
                    key: _float_or_none(usage.get(key))
                    for key in usage_profile_totals
                }
                if cpu_usage is not None or memory_usage is not None:
                    usage_sample_count += 1
                if any(value is not None for value in profile_values.values()):
                    profile_sample_count += 1
                if cpu_usage is not None:
                    current_cpu_usage_cores += cpu_usage
                if memory_usage is not None:
                    current_memory_working_set_mib += memory_usage
                for key, value in profile_values.items():
                    if value is not None:
                        usage_profile_totals[key] += value

                container_rows.append(
                    {
                        "namespace": namespace,
                        "pod": pod.get("name"),
                        "container": container.get("name"),
                        "node": pod.get("node"),
                        "labels": dict(pod.get("labels") or {}),
                        "pod_ready": bool(pod.get("ready")),
                        "endpoint_ready": bool(pod.get("endpoint_ready")),
                        "requests": {
                            "cpu_cores": _round_or_none(cpu_request),
                            "memory_mib": _round_or_none(memory_request),
                        },
                        "limits": {
                            "cpu_cores": _round_or_none(cpu_limit),
                            "memory_mib": _round_or_none(memory_limit),
                            "gpu_units": _round_or_none(gpu_limit),
                        },
                        "current_usage": {
                            "cpu_cores": _round_or_none(cpu_usage),
                            "memory_working_set_mib": _round_or_none(memory_usage),
                        },
                        "usage_profile": {
                            "avg_cpu_usage_cores": _round_or_none(profile_values["avg_cpu_usage_cores"]),
                            "max_cpu_usage_cores": _round_or_none(profile_values["max_cpu_usage_cores"]),
                            "p95_cpu_usage_cores": _round_or_none(profile_values["p95_cpu_usage_cores"]),
                            "avg_memory_working_set_mib": _round_or_none(profile_values["avg_memory_working_set_mib"]),
                            "max_memory_working_set_mib": _round_or_none(profile_values["max_memory_working_set_mib"]),
                            "p95_memory_working_set_mib": _round_or_none(profile_values["p95_memory_working_set_mib"]),
                        },
                    }
                )

        pods_by_node: dict[str, int] = defaultdict(int)
        for pod in items:
            pods_by_node[pod.get("node") or "unknown"] += 1

        requirements_declared = (
            missing_cpu_request == 0
            and missing_memory_request == 0
            and missing_cpu_limit == 0
            and missing_memory_limit == 0
        )
        request_coverage = _ratio(
            (container_count - missing_cpu_request) + (container_count - missing_memory_request),
            container_count * 2,
        )
        limit_coverage = _ratio(
            (container_count - missing_cpu_limit) + (container_count - missing_memory_limit),
            container_count * 2,
        )

        profiles.append(
            {
                "namespace": namespace,
                "service": service,
                "profile_type": "running_service_resource_requirements",
                "generated_at": generated_at,
                "pod_count": len(items),
                "container_count": container_count,
                "nodes": sorted(pods_by_node),
                "pods_by_node": dict(sorted(pods_by_node.items())),
                "requirements_declared": requirements_declared,
                "request_coverage_ratio": request_coverage,
                "limit_coverage_ratio": limit_coverage,
                "resource_requirements": {
                    "requests": {
                        "cpu_cores": round(declared_request_cpu_cores, 3),
                        "memory_mib": round(declared_request_memory_mib, 3),
                    },
                    "limits": {
                        "cpu_cores": round(declared_limit_cpu_cores, 3),
                        "memory_mib": round(declared_limit_memory_mib, 3),
                        "gpu_units": round(declared_gpu, 3),
                    },
                    "missing": {
                        "cpu_request_containers": missing_cpu_request,
                        "memory_request_containers": missing_memory_request,
                        "cpu_limit_containers": missing_cpu_limit,
                        "memory_limit_containers": missing_memory_limit,
                    },
                },
                "current_usage": {
                    "cpu_cores": round(current_cpu_usage_cores, 3),
                    "memory_working_set_mib": round(current_memory_working_set_mib, 3),
                    "sampled_container_count": usage_sample_count,
                    "usage_coverage_ratio": _ratio(usage_sample_count, container_count),
                },
                "usage_profile": {
                    "window": profile_window,
                    **{key: round(value, 3) for key, value in usage_profile_totals.items()},
                    "sampled_container_count": profile_sample_count,
                    "usage_coverage_ratio": _ratio(profile_sample_count, container_count),
                },
                "containers": container_rows,
                "interpretation": _interpret_profile(
                    requirements_declared=requirements_declared,
                    request_coverage=request_coverage,
                    limit_coverage=limit_coverage,
                    gpu_units=declared_gpu,
                ),
            }
        )
    return profiles


def summarize_service_resource_profiles(profiles: list[dict[str, Any]]) -> dict[str, Any]:
    total_pods = sum(int(profile.get("pod_count") or 0) for profile in profiles)
    total_containers = sum(int(profile.get("container_count") or 0) for profile in profiles)
    total_request_cpu = sum((profile.get("resource_requirements") or {}).get("requests", {}).get("cpu_cores") or 0 for profile in profiles)
    total_request_memory = sum((profile.get("resource_requirements") or {}).get("requests", {}).get("memory_mib") or 0 for profile in profiles)
    total_limit_gpu = sum((profile.get("resource_requirements") or {}).get("limits", {}).get("gpu_units") or 0 for profile in profiles)
    total_current_cpu = sum((profile.get("current_usage") or {}).get("cpu_cores") or 0 for profile in profiles)
    total_current_memory = sum((profile.get("current_usage") or {}).get("memory_working_set_mib") or 0 for profile in profiles)
    total_sampled_containers = sum((profile.get("current_usage") or {}).get("sampled_container_count") or 0 for profile in profiles)
    missing_profiles = [profile for profile in profiles if not profile.get("requirements_declared")]
    return {
        "profile_count": len(profiles),
        "running_pod_count": total_pods,
        "container_count": total_containers,
        "declared_request_cpu_cores": round(total_request_cpu, 3),
        "declared_request_memory_mib": round(total_request_memory, 3),
        "declared_limit_gpu_units": round(total_limit_gpu, 3),
        "current_cpu_usage_cores": round(total_current_cpu, 3),
        "current_memory_working_set_mib": round(total_current_memory, 3),
        "usage_sampled_container_count": total_sampled_containers,
        "usage_coverage_ratio": _ratio(total_sampled_containers, total_containers),
        "fully_declared_profile_count": len(profiles) - len(missing_profiles),
        "partially_declared_profile_count": len(missing_profiles),
    }


def parse_cpu_cores(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    try:
        if text.endswith("m"):
            return float(text[:-1]) / 1000.0
        return float(text)
    except ValueError:
        return None


def parse_memory_mib(value: Any) -> float | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    units = {
        "Ki": 1 / 1024,
        "Mi": 1,
        "Gi": 1024,
        "Ti": 1024 * 1024,
        "K": 1000 / 1024 / 1024,
        "M": 1000 * 1000 / 1024 / 1024,
        "G": 1000 * 1000 * 1000 / 1024 / 1024,
    }
    for suffix, multiplier in units.items():
        if text.endswith(suffix):
            try:
                return float(text[: -len(suffix)]) * multiplier
            except ValueError:
                return None
    try:
        return float(text) / 1024 / 1024
    except ValueError:
        return None


def parse_gpu_units(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _service_from_pod_name(name: str) -> str:
    parts = name.split("-")
    if len(parts) >= 3 and _looks_like_hash(parts[-2]) and _looks_like_suffix(parts[-1]):
        return "-".join(parts[:-2])
    if len(parts) >= 2 and _looks_like_suffix(parts[-1]):
        return "-".join(parts[:-1])
    return name


def _looks_like_hash(value: str) -> bool:
    return len(value) >= 6 and all(ch.isalnum() for ch in value)


def _looks_like_suffix(value: str) -> bool:
    return 4 <= len(value) <= 10 and all(ch.isalnum() for ch in value)


def _interpret_profile(*, requirements_declared: bool, request_coverage: float, limit_coverage: float, gpu_units: float) -> str:
    if requirements_declared:
        if gpu_units > 0:
            return "CPU/MEM 요청·제한과 GPU 요구량이 명시된 실행 서비스 프로파일입니다."
        return "CPU/MEM 요청·제한이 명시된 실행 서비스 프로파일입니다."
    if request_coverage == 0 and limit_coverage == 0:
        return "실행 중이지만 Kubernetes requests/limits가 없어 요구량 프로파일 보강이 필요합니다."
    return "일부 컨테이너만 requests/limits가 있어 요구량 프로파일이 부분 정의 상태입니다."


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round(numerator / denominator, 3)


def _round_or_none(value: float | None) -> float | None:
    if value is None:
        return None
    return round(value, 3)


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
