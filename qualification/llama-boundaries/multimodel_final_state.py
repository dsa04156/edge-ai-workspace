"""Read-only final verification after all benchmark controllers have exited."""
import argparse
import datetime
import json
from pathlib import Path
import multimodel_cluster as m


def verify(root):
    before = json.loads((root / "nodes-before.json").read_text())
    original = json.loads((root / "service-before.json").read_text())
    current = m.service()
    nodes = m.pin_nodes()
    live_nodes = json.loads(m.command(m.K + ["get", "nodes", *[n["node"] for n in nodes.values()], "-o", "json"]))["items"]
    node_ready = {n["metadata"]["name"]: any(c["type"] == "Ready" and c["status"] == "True"
        for c in n["status"]["conditions"]) for n in live_nodes}
    checks = {}
    for name, node in nodes.items():
        port = json.loads(m.py(node, "import socket,json;s=socket.socket();s.settimeout(2);"
            "print(json.dumps({'closed':s.connect_ex(('127.0.0.1',18200))!=0}));s.close()"))
        # Only inspect native server command lines, not environment variables.
        processes = m.command(m.prefix(node) + ["sh", "-c",
            "for f in /proc/[0-9]*/comm; do if [ \"$(cat \"$f\" 2>/dev/null)\" = llama-server ]; then "
            "tr '\\000' ' ' < \"${f%comm}cmdline\"; echo; fi; done"])
        statuses = node["before"]["status"]["containerStatuses"]
        old = before[name]["before"]["status"]["containerStatuses"]
        identity = lambda rows: {c["name"]: [c["containerID"], c["restartCount"]] for c in rows}
        checks[name] = {"physical_node": node["node"], "pod": node["pod"], "pod_uid": node["uid"],
            "uid_preserved": node["uid"] == before[name]["uid"],
            "containers_preserved": identity(statuses) == identity(old),
            "experiment_port_closed": port["closed"],
            "experimental_native_process_absent": "18200" not in processes,
            "native_processes": processes.splitlines(), "worker_metrics": m.metrics(node)}
    result = {"observed_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "service_restored": current["metadata"]["uid"] == original["metadata"]["uid"]
            and current["spec"] == original["spec"] and current["spec"]["suspended"] is False
            and current.get("status", {}).get("phase") == "Serving",
        "service": current, "devices": checks, "node_ready": node_ready,
        "all_nodes_ready": len(node_ready) == 3 and all(node_ready.values()),
        "all_experiment_ports_closed": all(c["experiment_port_closed"] and c["experimental_native_process_absent"] for c in checks.values()),
        "pod_identity_preserved": all(c["uid_preserved"] and c["containers_preserved"] for c in checks.values())}
    (root / "final-state.json").write_text(json.dumps(result, indent=2))
    if result["service_restored"] and not (root / "service-restored.json").exists():
        (root / "service-restored.json").write_text(json.dumps(current, indent=2))
        (root / "restoration-observation.json").write_text(json.dumps({"observed_at": result["observed_at"],
            "source": "final read-only audit after continuation; parent restoration wait did not complete"}, indent=2))
    if not (root / "nodes-after.json").exists():
        (root / "nodes-after.json").write_text(json.dumps(nodes, indent=2))
    print(json.dumps({k: v for k, v in result.items() if k not in ("service", "devices")}, indent=2))
    assert result["service_restored"] and result["all_experiment_ports_closed"] and result["pod_identity_preserved"] and result["all_nodes_ready"]
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("root", type=Path)
    verify(p.parse_args().root)
