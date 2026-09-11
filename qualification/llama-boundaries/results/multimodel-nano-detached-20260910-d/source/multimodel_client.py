"""Device-local fixed-token workloads, using the original benchmark protocol."""
import argparse
import concurrent.futures
import json
from pathlib import Path
import random
import time
import bench

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
        f.write(json.dumps({'wait_s':time.monotonic()-started,'readings':readings})+'\n')
    return _dataset_without_cooling(*args, **kwargs)
bench.dataset = _cooled_dataset


def run(output, node, block):
    output.mkdir(parents=True, exist_ok=False)
    base = "http://127.0.0.1:18200"
    props = bench.api(base, "/props")
    assert props["default_generation_settings"]["n_ctx"] == 4096
    (output / "props.json").write_text(json.dumps(props, indent=2))
    cases = [(512, 128, c) for c in (1, 2, 4, 8)]
    # Additional original request-length cases are repeated once in every block.
    cases += [(128, 64, 1), (2048, 128, 1), (512, 256, 1)]
    random.Random(20260910 + block).shuffle(cases)
    (output / "plan.json").write_text(json.dumps({"cases": cases, "block": block,
        "request_timeout_s": 180, "workload_seed": 20260908, "ignore_eos": True,
        "quality_evaluation": False, "production_enabled": False}, indent=2))
    journal = bench.Journal(output / "requests.jsonl")
    fixtures, rows = {}, []
    try:
        warm = bench.dataset(base, 1, {"input_tokens": 512, "output_tokens": 128, "seed": 20260908})[0]
        r = bench.stream(base, warm, run_id=output.name, request_id="warmup", phase="warmup",
                         node=node, planned_at=time.time(), timeout=180)
        journal.write(r)
        if r["status"] != "ok" or not r["zero_prefix_reuse_verified"]:
            raise RuntimeError("Warmup token/cache validation failed")
        for inp, out, concurrency in cases:
            name = f"i{inp}-o{out}-c{concurrency}"
            data = bench.dataset(base, concurrency, {"input_tokens": inp, "output_tokens": out, "seed": 20260908})
            fixtures[name] = data
            (output / "fixtures.json").write_text(json.dumps(fixtures))
            planned = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(bench.stream, base, body, run_id=output.name,
                    request_id=f"{name}-{i}", phase="measure", node=node, planned_at=planned, timeout=180)
                    for i, body in enumerate(data)]
                stage = []
                for future in concurrent.futures.as_completed(futures):
                    row = future.result()
                    row.update(case=name, concurrency=concurrency, block=block)
                    journal.write(row)
                    stage.append(row)
                    rows.append(row)
            print(json.dumps({"node": node, "block": block, "case": name, "summary": bench.summarize(stage)}), flush=True)
            if any(r["status"] != "ok" or not r["zero_prefix_reuse_verified"] for r in stage):
                raise RuntimeError("Request failure: later cases cancelled, no retry")
        (output / "complete.json").write_text(json.dumps({"measured": len(rows), "success": len(rows), "completed_at": time.time()}))
    finally:
        journal.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--node", required=True)
    p.add_argument("--block", type=int, required=True)
    a = p.parse_args()
    run(a.output, a.node, a.block)
