"""Summarize every screened case, including failures; no validated policy."""
import argparse
import csv
import json
from pathlib import Path
import statistics
import bench


def summarize(rows):
    groups = {}
    for case in dict.fromkeys(r['case'] for r in rows):
        records = [r for r in rows if r['case']==case]
        good = [r for r in records if r['status']=='ok']
        latency = [r['latency_ms'] for r in good]
        ttft = [r['ttft_ms'] for r in good if r['ttft_ms'] is not None]
        span = max(r['completed_at'] for r in records) - min(r['planned_at'] for r in records)
        groups[case] = {'pattern':records[0]['pattern'], 'input_tokens':records[0]['input_tokens'],
            'output_tokens':records[0]['target_output_tokens'], 'concurrency':records[0]['concurrency'],
            'scheduled':len(records),'sent':sum(r.get('sent_at') is not None for r in records),
            'ok':len(good),'failed':sum(r['status'] not in ('ok','not_sent') for r in records),
            'not_sent':sum(r['status']=='not_sent' for r in records),
            'mean_latency_ms':statistics.mean(latency) if latency else None,
            'sd_latency_ms':statistics.stdev(latency) if len(latency)>1 else None,
            'p50_latency_ms':bench.percentile(latency,.5),'p95_latency_ms':bench.percentile(latency,.95),
            'p95_ttft_ms':bench.percentile(ttft,.95),
            'complete_rps_including_drain':len(good)/span if span>0 else None,
            'output_tokens_s':sum(r['actual_output_tokens'] for r in good)/span if span>0 else None,
            'offered_rps':records[0].get('offered_rps'),
            'generator_delay_p95_ms':bench.percentile([r['generator_delay_ms'] for r in records if r.get('generator_delay_ms') is not None],.95)}
    return groups


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('run',type=Path)
    a=p.parse_args()
    rows=[json.loads(x) for x in (a.run/'requests.jsonl').read_text().splitlines()]
    result={'cases':summarize(rows),'run':a.run.name,'raw_sha256':bench.digest(a.run/'requests.jsonl'),
            'completed_plan':(a.run/'complete.json').exists(),'production_enabled':False,
            'threshold_validated':False,'warning':'One ordered screening pass; n=1 values are single observations, not reliable p95. Finite waves and 10s arrival windows do not establish sustained capacity. No holdout or random device order.'}
    (a.run/'analysis.json').write_text(json.dumps(result,indent=2))
    with (a.run/'requests.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=sorted(set().union(*(r.keys() for r in rows))))
        w.writeheader(); w.writerows(rows)
    print(json.dumps(result))


if __name__=='__main__':
    main()
