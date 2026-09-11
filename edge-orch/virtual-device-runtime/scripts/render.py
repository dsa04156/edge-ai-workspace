"""Render a reviewable test manifest and matching file registry; never applies."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--image", required=True, help="Built image; use registry/name@sha256:digest for cluster tests")
parser.add_argument("--node-selector", action="append", required=True, metavar="KEY=VALUE")
parser.add_argument("--cpu-request", default="100m")
parser.add_argument("--cpu-limit", default="1")
parser.add_argument("--memory-request", default="64Mi")
parser.add_argument("--memory-limit", default="256Mi")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
# kubectl is used only as a local Kustomize renderer.
import yaml
objects = list(yaml.safe_load_all(subprocess.check_output(
    ["rtk", "proxy", "kubectl", "kustomize", str(ROOT / "k8s")], text=True)))
selector = dict(item.split("=", 1) for item in args.node_selector)
if not selector or any(not key or not value for key, value in selector.items()):
    parser.error("explicit nonempty node selectors required")
deployment = next(item for item in objects if item["kind"] == "Deployment")
spec = deployment["spec"]["template"]["spec"]
spec["nodeSelector"] = selector
container = spec["containers"][0]
container["image"] = args.image
container["resources"] = {"requests": {"cpu": args.cpu_request, "memory": args.memory_request},
                          "limits": {"cpu": args.cpu_limit, "memory": args.memory_limit}}
registry_path = ROOT.parent / "state-aggregator/app/config/virtual_devices.json"
registry = json.loads(registry_path.read_text())
registry["resources"][0]["spec"]["nodeSelector"] = selector
args.output.mkdir(parents=True, exist_ok=True)
registry_json = json.dumps(registry, ensure_ascii=False, indent=2)
objects.append({"apiVersion": "v1", "kind": "ConfigMap",
                "metadata": {"name": "virtual-device-registry", "namespace": "virtual-device-test"},
                "data": {"virtual_devices.json": registry_json}})
(args.output / "manifest.json").write_text(json.dumps(
    {"apiVersion": "v1", "kind": "List", "items": objects}, ensure_ascii=False, indent=2) + "\n")
(args.output / "virtual_devices.json").write_text(registry_json + "\n")
print(args.output / "manifest.json")
