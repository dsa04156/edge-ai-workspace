"""Finish the Spark matrix with temperature conditioning outside timed waves.

Runs under the existing parent experiment's suspended service. It never changes
service state. Completed screening cells in the parent remain immutable.
"""
import argparse
import json
from pathlib import Path
import shutil
import time
import multimodel_cluster as cluster
import bench

COOLING = '''
import sys
_dataset_without_cooling = bench.dataset
def _cooled_dataset(*args, **kwargs):
    started = time.monotonic()
    readings = []
    while True:
        zones = bench.thermal_zones()
        temperatures = [z['temperature_c'] for z in zones if z['temperature_c'] is not None]
        if not temperatures:
            raise RuntimeError('Cooling requires actual thermal sensors')
        maximum = max(temperatures)
        readings.append({'at':time.time(),'maximum_temperature_c':maximum})
        if maximum <= 60:
            break
        if time.monotonic() - started > 180:
            raise RuntimeError('Pre-case cooling deadline')
        time.sleep(2)
    path = Path(sys.argv[sys.argv.index('--output')+1]) / 'cooling.jsonl'
    with path.open('a') as f:
        f.write(json.dumps({'wait_s':time.monotonic()-started,'readings':readings})+'\\n')
    return _dataset_without_cooling(*args, **kwargs)
bench.dataset = _cooled_dataset
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parent", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    parent, output = args.parent.resolve(), args.output.resolve()
    output.mkdir(exist_ok=False, parents=True)
    models = json.loads((parent / "models.json").read_text())
    plan = json.loads((parent / "plan.json").read_text())
    owner = json.loads((parent / "owner.json").read_text())
    nodes = cluster.pin_nodes()
    node = nodes["spark"]
    # Preserve the exact source used by the first run before producing the variant.
    source = output / "source"
    source.mkdir()
    for name in ("bench.py", "common-0332.json", "config.json", "multimodel_cluster.py"):
        shutil.copy2(cluster.HERE / name, source / name)
    client = (cluster.HERE / "multimodel_client.py").read_text()
    assert client.count("import bench\n") == 1
    (source / "multimodel_client.py").write_text(client.replace("import bench\n", "import bench\n" + COOLING))
    cluster.HERE = source
    (output / "models.json").write_text(json.dumps(models, indent=2))
    (output / "nodes-before.json").write_text(json.dumps(nodes, indent=2))
    (output / "plan.json").write_text(json.dumps({**plan, "nodes": ["spark"], "thermal_conditioning":
        "max observed host thermal zone <=60 C before warmup and each case; wait excluded from wave latency/throughput",
        "parent": str(parent), "selection": "only cells not completed in parent; no selection by latency"}, indent=2))
    (output / "source-hashes.json").write_text(json.dumps({p.name: bench.digest(p) for p in source.iterdir()}, indent=2))
    completed = []
    for block, order in enumerate(plan["order"]):
        for slug in order:
            prior = parent / "spark" / (slug + f"-b{block}")
            cleanup_path = prior / "cleanup.json"
            clean = json.loads(cleanup_path.read_text()) if cleanup_path.exists() else {}
            if (prior / "workload/complete.json").exists() and clean.get("process_exited") and clean.get("port_released"):
                continue
            state = cluster.service()
            if state["metadata"]["uid"] != owner["uid"] or not state["spec"]["suspended"]:
                raise RuntimeError("Parent experiment no longer holds service suspension")
            model = next(m for m in models if m["slug"] == slug)
            cluster.run_cell("spark", node, model, block, output)
            completed.append(slug + f"-b{block}")
            (output / "completed-cells.json").write_text(json.dumps(completed, indent=2))
    (output / "nodes-after.json").write_text(json.dumps(cluster.pin_nodes(), indent=2))
    print(json.dumps({"event": "spark_continuation_complete", "cells": len(completed)}), flush=True)


if __name__ == "__main__":
    main()
