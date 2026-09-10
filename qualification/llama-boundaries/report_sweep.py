"""Build descriptive comparison assets; incomplete runs fail closed."""
import json
from pathlib import Path
import csv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from analyze_sweep import summarize

ROOT=Path(__file__).resolve().parents[2]
RUNS={'Nano':'sweep-nano-session-a/benchmark/sweep','AGX Orin':'sweep-agx-a/sweep',
      'RTX 5060 Ti':'sweep-rtx5060ti-a/sweep','RTX 5080':'sweep-rtx5080-c/sweep',
      'DGX Spark':'sweep-spark-20260910-b/sweep'}


def main():
    output=ROOT/'docs/assets/llama-sweep-20260908'
    output.mkdir(parents=True,exist_ok=True)
    data={}
    raw=[]
    for name, run in RUNS.items():
        path=ROOT/'qualification/llama-boundaries/results'/run
        if not (path/'complete.json').exists():
            raise RuntimeError(f'{name}: incomplete run')
        rows=[json.loads(line) for line in (path/'requests.jsonl').read_text().splitlines()]
        data[name]={'run':run,'complete':json.loads((path/'complete.json').read_text()),'cases':summarize(rows)}
        raw.extend(dict(row,device=name,source_run=run) for row in rows)
    (output/'results.json').write_text(json.dumps(data,indent=2))
    with (output/'requests.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=sorted(set().union(*(r.keys() for r in raw))))
        w.writeheader();w.writerows(raw)
    fig,axes=plt.subplots(1,3,figsize=(14,4),layout='constrained')
    for (name, report),color,marker in zip(data.items(),['#0072B2','#D55E00','#009E73','#000000','#CC79A7'],['o','s','^','D','P']):
        cases=report['cases']
        keys=[f'i512-o128-c{c}' for c in [1,2,4,8]]
        axes[0].plot([1,2,4,8],[cases[k]['p95_latency_ms']/1000 for k in keys],marker=marker,color=color,label=name)
        keys=[f'i{i}-o128-c1' for i in [128,512,2048]]
        axes[1].plot([128,512,2048],[cases[k]['mean_latency_ms']/1000 for k in keys],marker=marker,color=color)
        keys=[f'i512-o{o}-c1' for o in [64,128,256]]
        axes[2].plot([64,128,256],[cases[k]['mean_latency_ms']/1000 for k in keys],marker=marker,color=color)
    for ax,xlabel,ylabel in zip(axes,['Concurrency (512 / 128)','Input tokens (output 128, C1)','Output tokens (input 512, C1)'],
                                ['Empirical p95 latency (s)','Single-request latency (s)','Single-request latency (s)']):
        ax.set(xlabel=xlabel,ylabel=ylabel,ylim=(0,None))
        ax.grid(alpha=.2)
    axes[0].set_xticks([1,2,4,8]);axes[1].set_xticks([128,512,2048]);axes[2].set_xticks([64,128,256])
    axes[0].legend()
    fig.suptitle('GPU local screening: one pass, context 4096 / slot 1; not validated thresholds',fontsize=12)
    fig.savefig(output/'screening.png',dpi=160,facecolor='white')
    plt.close(fig)
    (output/'figure-provenance.json').write_text(json.dumps({'raw':'requests.csv','matplotlib':matplotlib.__version__,
        'n':'Concurrency panel n=1,2,4,8; length panels n=1 per cell',
        'uncertainty':'not estimated; no independent repeats', 'smoothing':None,
        'lines':'connect observed conditions only, not a fitted model','destination':'repository exploratory report'},indent=2))
    for name,d in data.items():
        print(name,d['complete'])
        for k,c in d['cases'].items():
            print(k,round(c['p95_latency_ms']/1000,3),round(c['p95_ttft_ms']/1000,3),round(c['complete_rps_including_drain'],3))


if __name__=='__main__':
    main()
