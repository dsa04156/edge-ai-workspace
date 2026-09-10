"""Remote-only descriptive blocks; never impute a missing local baseline."""
import argparse
import csv
import json
from pathlib import Path
import platform
import bench
from analyze_paired import describe


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('run', type=Path)
    args = p.parse_args()
    rows = [json.loads(line) for line in (args.run / 'requests.jsonl').read_text().splitlines()]
    if not rows or any(r['route'] != 'remote' or r['matched_comparison'] for r in rows):
        raise ValueError('Requires explicitly remote-only records')
    groups = {str(c): describe([r for r in rows if r['concurrency'] == c]) for c in (1, 2, 4)}
    report = {'schema': 'edge-ai.llm-remote-observation/v1', 'run': args.run.name,
              'measurements': groups, 'local_baseline': None, 'paired': False,
              'production_enabled': False, 'routing_boundary': None,
              'activation_boundary': None, 'reclamation_boundary': None,
              'raw_sha256': bench.digest(args.run / 'requests.jsonl'),
              'limitations': ['Three within-session blocks, no holdout',
                              'No concurrent Nano local baseline',
                              'Finite waves, not sustained saturation',
                              'No inferential test or confidence interval']}
    (args.run / 'profile.json').write_text(json.dumps(report, indent=2))
    with (args.run / 'requests.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=sorted(set().union(*(r.keys() for r in rows))))
        writer.writeheader()
        writer.writerows(rows)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 3, figsize=(12, 4), layout='constrained')
    for ax, metric, label in zip(axes, ('p95_latency_ms', 'p95_ttft_ms', 'active_wave_completed_rps'),
                                 ('p95 latency (ms)', 'p95 TTFT (ms)', 'Active-wave requests/s')):
        for c in (1, 2, 4):
            group = groups[str(c)]
            ax.scatter(c, group[metric], color='#0072B2', marker='o')
            ax.annotate(f"n={group['requests']}", (c, group[metric]), xytext=(0, 8),
                        textcoords='offset points', ha='center')
        ax.set(xlabel='Concurrency', ylabel=label, xticks=[1, 2, 4],
               ylim=(0, max(g[metric] for g in groups.values()) * 1.2))
    fig.suptitle('Nano to AGX Orin: 3 blocks, remote ready; no matched local baseline', fontsize=11)
    fig.savefig(args.run / 'concurrency.png', dpi=160, facecolor='white')
    plt.close(fig)
    (args.run / 'figure-provenance.json').write_text(json.dumps({
        'raw': 'requests.jsonl', 'python': platform.python_version(), 'matplotlib': matplotlib.__version__,
        'estimator': 'linear empirical p95 of successful equal-length requests; throughput sums active wave durations',
        'n': '3,6,12 requests; 3 within-session blocks per condition',
        'uncertainty': 'not estimated', 'missing': 'null, not zero', 'smoothing': None,
        'destination': 'exploratory repository report; not journal submission'}, indent=2))
    print(json.dumps({c: {k: v for k, v in g.items() if k != 'blocks_raw'} for c, g in groups.items()}))


if __name__ == '__main__':
    main()
