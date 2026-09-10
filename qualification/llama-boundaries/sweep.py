"""Bounded local workload screening, not a validated saturation threshold."""
import concurrent.futures
import json
import math
from pathlib import Path
import socket
import time
import bench


def cases():
    return [(512, 128, c) for c in (1, 2, 4, 8)] + [
        (128, 128, 1), (2048, 128, 1), (512, 64, 1), (512, 256, 1),
        (128, 64, 4), (2048, 256, 1)]


def run(base, output, node, safety_check=lambda: None):
    output = Path(output)
    output.mkdir(exist_ok=False, parents=True)
    plan = {'cases': cases(), 'seed': 20260908, 'context': 4096, 'max_seconds': 240,
            'max_inflight': 8, 'rate_seconds_each': 10, 'rate_factors': [.5, 1.2],
            'rate_cap_rps': 5, 'replication': 'one screening pass; no holdout',
            'arrival': 'finite simultaneous waves then open-loop rates based on C1 measured capacity',
            'production_enabled': False}
    props = bench.api(base, '/props')
    if props['default_generation_settings']['n_ctx'] != 4096:
        raise RuntimeError('Sweep requires context4096')
    (output / 'plan.json').write_text(json.dumps(plan, indent=2))
    (output / 'provenance.json').write_text(json.dumps({'props': props, 'node': node,
        'requester': socket.gethostname(), 'scope': 'node-local HTTP, same host or Pod network',
        'control_policy': 'disabled'}, indent=2))
    journal = bench.Journal(output / 'requests.jsonl')
    rows, fixtures = [], {}
    deadline = time.monotonic() + 240
    def guard():
        safety_check()
        if time.monotonic() > deadline - 35:
            raise RuntimeError('Sweep deadline; leave time for in-flight drain')
    def body(inp, out):
        key = f'{inp}/{out}'
        if key not in fixtures:
            fixtures[key] = bench.dataset(base, 8, {'input_tokens': inp, 'output_tokens': out, 'seed': 20260908})
            (output / 'fixtures.json').write_text(json.dumps(fixtures))
        return fixtures[key]
    def send(b, case, number, phase, planned, concurrency, rate=None):
        row = bench.stream(base, b, run_id=output.name, request_id=f'{case}-{number}', phase='measure',
                           node=node, planned_at=planned, timeout=30)
        row.update(case=case, pattern=phase, concurrency=concurrency, offered_rps=rate,
                   input_tokens=len(b['prompt']), target_output_tokens=b['n_predict'])
        journal.write(row)
        return row
    def validate(stage):
        rows.extend(stage)
        if any(r['status'] != 'ok' or not r['zero_prefix_reuse_verified'] for r in stage):
            raise RuntimeError('Request failure or cache mismatch; later cases stopped')
    try:
        for inp, out, concurrency in cases():
            guard()
            data = body(inp, out)
            name = f'i{inp}-o{out}-c{concurrency}'
            planned = time.time()
            with concurrent.futures.ThreadPoolExecutor(max_workers=concurrency) as pool:
                futures = [pool.submit(send, data[i], name, i, 'wave', planned, concurrency) for i in range(concurrency)]
                validate([f.result() for f in futures])
        baseline = rows[0]['latency_ms'] / 1000
        for factor in (.5, 1.2):
            guard()
            rate = min(5, factor / baseline)
            name = f'rate-{factor}'
            start_wall, start_mono = time.time(), time.monotonic()
            pending, stage = [], []
            with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                for i in range(math.ceil(10 * rate)):
                    guard()
                    delay = start_mono + i/rate - time.monotonic()
                    if delay > 0:
                        time.sleep(delay)
                    planned = start_wall + i/rate
                    if sum(not f.done() for f in pending) >= 8:
                        row = {'run_id': output.name, 'request_id': f'{name}-{i}', 'case': name,
                               'pattern': 'open-loop', 'offered_rps': rate, 'status': 'not_sent',
                               'planned_at': planned, 'sent_at': None, 'completed_at': time.time(),
                               'latency_ms': None, 'ttft_ms': None, 'actual_output_tokens': 0,
                               'input_tokens': 512, 'target_output_tokens': 128,
                               'reason': 'bounded client inflight limit', 'phase': 'measure', 'concurrency': 8}
                        journal.write(row)
                        stage.append(row)
                    else:
                        pending.append(pool.submit(send, body(512,128)[i%8], name, i,
                                                   'open-loop', planned, 8, rate))
                stage.extend(f.result() for f in pending)
            rows.extend(stage)
            if any(r['status'] not in ('ok', 'not_sent') for r in stage):
                raise RuntimeError('Rate phase failure; no later phase')
        (output / 'complete.json').write_text(json.dumps({'requests': len(rows), 'success': sum(r['status']=='ok' for r in rows),
                                                       'measured_at': time.time(), 'threshold_validated': False}))
    finally:
        journal.close()


if __name__ == '__main__':
    import argparse, os
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base', default='http://127.0.0.1:18200')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--node', required=True)
    p.add_argument('--key-file', type=Path)
    a = p.parse_args()
    if a.key_file:
        os.environ['BOUNDARY_KEY_FILE'] = str(a.key_file)
    run(a.base, a.output, a.node)
