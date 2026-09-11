import json, subprocess, sys, datetime
from pathlib import Path
allowed = {"benchmark-client", "inference-edge", "inference-edge-resnet18", "h6-edge-rpi5b-mobilenet", "h6-edge-rpi5b-resnet18", "inference-server", "inference-server-resnet18"}
for name in sys.argv[1:]:
    assert name in allowed
    obj = json.loads(subprocess.check_output(["kubectl", "get", "deployment", name, "-n", "ai-placement-experiment", "-o", "json"]))
    spec = obj["spec"]["template"]["spec"]
    node = spec["nodeName"]
    assert not spec.get("nodeSelector"), "Unexpected existing selector"
    replicas = obj["spec"]["replicas"]
    patch = [
        {"op": "test", "path": "/metadata/uid", "value": obj["metadata"]["uid"]},
        {"op": "test", "path": "/spec/replicas", "value": replicas},
        {"op": "test", "path": "/spec/template/spec/nodeName", "value": node},
        {"op": "remove", "path": "/spec/template/spec/nodeName"},
        {"op": "add", "path": "/spec/template/spec/nodeSelector", "value": {"kubernetes.io/hostname": node}},
    ]
    record = {"name": name, "node": node, "replicas": replicas, "patch": patch, "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}
    target = Path(__file__).parent / (name + "-selector-change.json")
    target.write_text(json.dumps(record, indent=2) + "\n")
    subprocess.run(["kubectl", "patch", "deployment", name, "-n", "ai-placement-experiment", "--type=json", "-p", json.dumps(patch)], check=True)
    after = json.loads(subprocess.check_output(["kubectl", "get", "deployment", name, "-n", "ai-placement-experiment", "-o", "json"]))
    expected = json.loads(json.dumps(obj["spec"]))
    expected["template"]["spec"].pop("nodeName")
    expected["template"]["spec"]["nodeSelector"] = {"kubernetes.io/hostname": node}
    assert after["spec"] == expected, "Unexpected additional spec change"
    record["verified_spec_only_expected_changes"] = True
    target.write_text(json.dumps(record, indent=2) + "\n")
