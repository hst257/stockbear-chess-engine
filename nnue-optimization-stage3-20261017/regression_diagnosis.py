"""Read-only investigation of the hiddenclip short-control endgame anomaly."""
import random
import statistics as s
import experiment as p

data=p.common.load(p.ROOT/'search-hiddenclip.json')
records=data['records'];rows=[]
for repeat in range(7):
    a=next(r for r in records if r['position']=='piece_endgame' and r['budget']==100 and r['build']=='baseline' and r['repeat']==repeat)
    b=next(r for r in records if r['position']=='piece_endgame' and r['budget']==100 and r['build']=='hiddenclip' and r['repeat']==repeat)
    load=next(r for r in data['environment_segments'] if r['position']=='piece_endgame' and r['repeat']==repeat)
    rows.append(dict(repeat=repeat,order=a['order'],factor=(b['nodes']/b['wall_seconds'])/(a['nodes']/a['wall_seconds']),
        baseline_nodes=a['nodes'],candidate_nodes=b['nodes'],baseline_wall=a['wall_seconds'],candidate_wall=b['wall_seconds'],
        baseline_engine_seconds=a['seconds'],candidate_engine_seconds=b['seconds'],baseline_depth=a['depth'],candidate_depth=b['depth'],
        other_cpu=load['other_cpu_percent_estimate']))
rng=random.Random(20261017)
boot=sorted(s.median(rng.choices([r['factor'] for r in rows],k=7)) for _ in range(10000))
summary=dict(rows=rows,median=s.median(r['factor'] for r in rows),repeat_only95=[boot[250],boot[9750]],
    speedup_load_correlation=s.correlation([r['factor'] for r in rows],[r['other_cpu'] for r in rows]),
    baseline_first_median=s.median(r['factor'] for r in rows if r['order'][0]=='baseline'),
    candidate_first_median=s.median(r['factor'] for r in rows if r['order'][0]=='hiddenclip'),
    candidate_wins=sum(r['factor']>1 for r in rows),candidate_losses=sum(r['factor']<1 for r in rows),new_searches=0,
    conclusion='All reported engine times are 100 ms; protocol wall overhead is small. Rate variation, order subsets, load and depth-boundary crossings do not establish a cause. Repeat-only interval crosses one. Material median remains an unexplained gate failure. No pairs removed or extra searches; no waiver.')
p.save('regression-diagnosis.json',summary)
print(summary)
