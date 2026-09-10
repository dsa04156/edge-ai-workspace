"""Read-only Kubernetes/storage gate before enabling the real AGX test Deployment."""
import json
import subprocess
import math
import re
from urllib import request
from pathlib import Path
from continuity_policy import NODES, AGX_RUNTIME_IMAGE, AGX_IMAGE_COMPRESSED_BYTES, AGX_IMAGE_UNPACKED_BYTES


SD_MOUNT = "/srv/agx-model-cache"
SD_DEVICE = "/dev/mmcblk1p1"
SD_UUID = "c6889d5e-37bb-4b07-8e0b-757d3de8c877"


def parse_sd_metrics(metrics):
    """Read the dedicated filesystem, never substitute root for a missing SD."""
    wanted = {"node_filesystem_avail_bytes": "availableBytes",
              "node_filesystem_size_bytes": "capacityBytes",
              "node_filesystem_readonly": "readonly",
              "node_filesystem_device_error": "deviceError"}
    result = {"mountpoint": SD_MOUNT, "device": SD_DEVICE, "fstype": "ext4"}
    for line in metrics.splitlines():
        match = re.fullmatch(r'(node_filesystem_\w+)\{(.*)\} (\S+)', line)
        if not match or match[1] not in wanted:
            continue
        labels = dict(re.findall(r'(\w+)="([^"\\]*)"', match[2]))
        if not all(labels.get(k) == result[k] for k in ("mountpoint", "device", "fstype")):
            continue
        key = wanted[match[1]]
        if key in result:
            raise ValueError("ambiguous SD filesystem metrics")
        value = float(match[3])
        if not math.isfinite(value):
            raise ValueError("invalid SD filesystem metric")
        result[key] = value
    return result


def read_sd_storage(node):
    address = next(a["address"] for a in node["status"]["addresses"] if a["type"] == "InternalIP")
    # Existing read-only node exporter; no probe Pods or host mutation in startup gate.
    with request.urlopen(f"http://{address}:9100/metrics", timeout=5) as response:
        return parse_sd_metrics(response.read().decode())


def assess(node, summary, runtime_pods=(), model_fs=None):
    conditions = {c["type"]: c["status"] for c in node["status"].get("conditions", [])}
    fs = summary.get("node", {}).get("fs", {})
    available, total = fs.get("availableBytes"), fs.get("capacityBytes")
    # Development headroom for a 1.3GB model plus partial-download scratch space.
    reserve = 3 * 1024**3
    # Streamed OCI import: compressed content + upper bound of unpacked regular
    # files, 25% overhead and 256MiB scratch. No second archive copy on the eMMC.
    runtime_present = any(
        p.get("spec", {}).get("nodeName") == NODES["agx"]
        and any(c.get("name") == "inference-runtime" and c.get("image") == AGX_RUNTIME_IMAGE
                for c in p.get("spec", {}).get("containers", []))
        and any(c.get("name") == "inference-runtime" and c.get("ready") is True
                and c.get("state", {}).get("running")
                for c in p.get("status", {}).get("containerStatuses", []))
        for p in runtime_pods)
    image_reserve = (math.ceil((AGX_IMAGE_COMPRESSED_BYTES + AGX_IMAGE_UNPACKED_BYTES)*1.25)
                     + 256*1024**2) if node["metadata"]["name"] == NODES["agx"] and not runtime_present else 0
    model_available = available if model_fs is None else model_fs.get("availableBytes")
    model_total = total if model_fs is None else model_fs.get("capacityBytes")
    def headroom(free, size, extra):
        return (isinstance(free, (int, float)) and isinstance(size, (int, float))
                and math.isfinite(free) and math.isfinite(size) and size > 0
                and free-extra >= size*.20)
    storage_ok = headroom(model_available, model_total, reserve)
    if model_fs is not None:
        storage_ok = storage_ok and (model_fs.get("readonly") == 0 and model_fs.get("deviceError") == 0
                                     and model_fs.get("device") == SD_DEVICE
                                     and model_fs.get("mountpoint") == SD_MOUNT
                                     and model_fs.get("fstype") == "ext4")
    root_model_reserve = reserve if model_fs is None else 0
    checks = {"ready": conditions.get("Ready") == "True",
              "no_pressure": all(conditions.get(k) == "False" for k in ["DiskPressure", "MemoryPressure", "PIDPressure"]),
              "model_storage_headroom": storage_ok,
              "cold_runtime_headroom": headroom(available, total, root_model_reserve+image_reserve)}
    return {"node": node["metadata"]["name"], "passed": all(checks.values()), "checks": checks,
            "available_bytes": available, "capacity_bytes": total, "model_scratch_reserve_bytes": reserve,
            "cold_image_reserve_bytes": image_reserve,
            "root_model_scratch_reserve_bytes": root_model_reserve,
            "model_storage": model_fs if model_fs is not None else fs,
            "budgeted_runtime_image": AGX_RUNTIME_IMAGE if node["metadata"]["name"] == NODES["agx"] else None,
            "exact_runtime_running": runtime_present if node["metadata"]["name"] == NODES["agx"] else None,
            "minimum_remaining_fraction": .20, "observed_at": fs.get("time")}


def validate_sd_manifest(agx, storage):
    """The separately budgeted SD must be the filesystem this worker will use."""
    spec = agx["spec"]["template"]["spec"]
    pv = next(i for i in storage["items"] if i["kind"] == "PersistentVolume" and i["metadata"]["name"] == "llama-agx-sd-cache")
    pvc = next(i for i in storage["items"] if i["kind"] == "PersistentVolumeClaim" and i["metadata"]["name"] == "llama-agx-cache-sd")
    volume = next(v for v in spec["volumes"] if v["name"] == "model-cache")
    guard = next(c for c in spec["initContainers"] if c["name"] == "verify-sd-cache")
    expected_affinity = {"required": {"nodeSelectorTerms": [{"matchExpressions": [
        {"key": "kubernetes.io/hostname", "operator": "In", "values": [NODES["agx"]]}]}]}}
    if not (volume.get("persistentVolumeClaim", {}).get("claimName") == pvc["metadata"]["name"]
            and pvc["spec"].get("volumeName") == pv["metadata"]["name"]
            and pv["spec"].get("local") == {"path": SD_MOUNT+"/ollama", "fsType": "ext4"}
            and pv["spec"].get("nodeAffinity") == expected_affinity
            and pv["metadata"].get("annotations", {}).get("qualification.edge/sd-uuid") == SD_UUID
            and SD_UUID in " ".join(guard.get("command", []))
            and {"name": "model-cache", "mountPath": "/models", "readOnly": True} in guard.get("volumeMounts", [])):
        raise ValueError("manifest does not match the dedicated AGX SD storage budget")


def main():
    results = []
    manifest = json.loads((Path(__file__).parent / "nano-agx-k8s/resources.yaml").read_text())
    agx = next(i for i in manifest["items"] if i["kind"] == "Deployment" and i["metadata"]["name"] == "llama-agx")
    runtime = next(c for c in agx["spec"]["template"]["spec"]["containers"] if c["name"] == "inference-runtime")
    if runtime["image"] != AGX_RUNTIME_IMAGE or runtime.get("imagePullPolicy") != "Never":
        print(json.dumps({"passed": False, "error": "manifest does not match measured offline runtime storage budget"}))
        raise SystemExit(2)
    try:
        storage = json.loads((Path(__file__).parent / "nano-agx-k8s/sd-storage.yaml").read_text())
        validate_sd_manifest(agx, storage)
    except (KeyError, StopIteration, ValueError, OSError) as exc:
        print(json.dumps({"passed": False, "error": f"SD storage manifest: {exc}"}))
        raise SystemExit(2)
    for name in NODES.values():
        try:
            node = json.loads(subprocess.check_output(["rtk", "proxy", "kubectl", "get", "node", name, "-o", "json"], timeout=15))
            summary = json.loads(subprocess.check_output(["rtk", "proxy", "kubectl", "get", "--raw", f"/api/v1/nodes/{name}/proxy/stats/summary"], timeout=15))
            pods = json.loads(subprocess.check_output(["rtk", "proxy", "kubectl", "get", "pods", "-n", "llama-continuity-test", "-l", "app=llama-agx", "-o", "json"], timeout=15))["items"] if name == NODES["agx"] else []
            results.append(assess(node, summary, pods, read_sd_storage(node) if name == NODES["agx"] else None))
        except Exception as exc:
            results.append({"node": name, "passed": False, "error": str(exc)})
    print(json.dumps({"passed": all(r["passed"] for r in results), "nodes": results}, indent=2))
    raise SystemExit(0 if all(r["passed"] for r in results) else 2)


if __name__ == "__main__":
    main()
