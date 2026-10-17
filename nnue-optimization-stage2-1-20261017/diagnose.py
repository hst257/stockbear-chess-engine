"""Analyze frozen prior and fresh bounded promotion evidence, without searches."""
import json
import math
import random
import statistics as s
import experiment as p


def summarize(data, original=False):
    out=[]
    positions=list(dict.fromkeys(r['position'] for r in data['records']))
    if original: positions=['promotion']
    segments={(r['position'],r['repeat']):r for r in reversed(data['environment_segments'])}
    for pos in positions:
        rows=[r for r in data['records'] if r['position']==pos and r['mode']=='nodes' and r['budget']==1000000]
        reps=sorted({r['repeat'] for r in rows})
        pairs=[]
        for rep in reps:
            a=next(r for r in rows if r['repeat']==rep and r['build']=='baseline')
            b=next(r for r in rows if r['repeat']==rep and r['build']=='sort')
            pair=[r['build'] for r in rows if r['repeat']==rep]
            pairs.append(dict(repeat=rep,speedup=a['wall_seconds']/b['wall_seconds'],
                baseline_first=pair[0]=='baseline',background=segments[(pos,rep)]['other_cpu_percent_estimate']))
        rng=random.Random(20261017)
        boot=sorted(s.median(rng.choices([r['speedup'] for r in pairs],k=len(pairs))) for _ in range(10000))
        x=[r['speedup'] for r in pairs];y=[r['background'] for r in pairs]
        corr=s.correlation(x,y) if len(set(x))>1 and len(set(y))>1 else None
        out.append(dict(position=pos,pairs=pairs,median=s.median(x),repeat_bootstrap95=[boot[250],boot[9750]],
            speedup_background_correlation=corr,
            baseline_first_median=s.median(r['speedup'] for r in pairs if r['baseline_first']),
            candidate_first_median=s.median(r['speedup'] for r in pairs if not r['baseline_first'])))
    return out

out=dict(original=summarize(p.common.load(p.ART/'references/search-sort.json'),True),
    diagnostic=summarize(p.common.load(p.ROOT/'diagnostic.json')),
    interpretation='Five fresh 1M-node pairs at four legal promotion fixtures. Repetition-only intervals are descriptive, not independent-position evidence. '
    'A prior one-fixture regression is not a proven sorting/cache cause; order and background correlations are observational.')
p.save('promotion-diagnosis.json',out)
print({k:[(r['position'],r['median'],r['repeat_bootstrap95']) for r in out[k]] for k in ['original','diagnostic']})
