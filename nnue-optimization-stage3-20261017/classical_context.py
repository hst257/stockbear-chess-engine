"""Optional fresh descriptive context, only after a Stage 3 acceptance gate."""
from contextlib import ExitStack
import math
import statistics as s
import experiment as p
from analyze import interval

a=p.common.load(p.ROOT/'analysis.json')
if not a['accepted_candidates']:
    p.save('classical-context.json',dict(performed=False,reason='No candidate passed the primary acceptance gates; optional comparison skipped.'))
    print('Optional classical context skipped: no accepted candidate')
    raise SystemExit(0)
label=a['retained_baseline']
path=p.ROOT/'classical-context.json'
data=p.common.load(path) if path.exists() else dict(performed=True,candidate=label,records=[],repeats=3,
    purpose='Fresh matched-position descriptive throughput, not inference cost, acceptance extension, Elo or games.')
assert data.get('candidate')==label
done={(r['position'],r['build'],r['repeat']) for r in data['records']}
p.pin()
with ExitStack() as stack:
    players={b:stack.enter_context(p.player('baseline' if b=='classical' else b,
        evaluator='classical' if b=='classical' else 'nnue')) for b in ['classical','baseline',label]}
    for repeat in range(3):
        for i,row in enumerate(p.common.load(p.ROOT/'positions.json')):
            order=list(players);offset=(repeat+i)%3;order=order[offset:]+order[:offset]
            for b in order:
                if (row['id'],b,repeat) in done:continue
                data['records'].append(dict(p.capture(players[b],row,'time',1000),build=b,repeat=repeat))
                done.add((row['id'],b,repeat));p.save(path.name,data)
            print('Classical context',repeat+1,row['id'],flush=True)
groups={b:[] for b in ['baseline',label]}
for row in p.common.load(p.ROOT/'positions.json'):
    for b in groups:
        group=[]
        for rep in range(3):
            classic=next(r for r in data['records'] if r['position']==row['id'] and r['repeat']==rep and r['build']=='classical')
            nnue=next(r for r in data['records'] if r['position']==row['id'] and r['repeat']==rep and r['build']==b)
            group.append(math.log((nnue['nodes']/nnue['wall_seconds'])/(classic['nodes']/classic['wall_seconds'])))
        groups[b].append(group)
data['summary']={b:dict(nnue_classical_ratio=math.exp(s.mean(s.median(g) for g in values)),grouped95=interval(values)) for b,values in groups.items()}
p.save(path.name,data);print(data['summary'])
