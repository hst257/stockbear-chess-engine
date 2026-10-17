"""Secondary matched-position throughput context, not an acceptance/tournament test.

Three rotated evaluator/build triples, 12 frozen fixtures, 1000 ms, CPU 0.
Different evaluators visit different trees: NPS ratios are not equal-work cost
or Elo estimates. The primary seven-pair candidate/control test remains separate.
"""
from contextlib import ExitStack
import math
import os
import statistics as s
import sys
import experiment as p
from load_meter import Meter

label = sys.argv[1]
assert p.common.load(p.ROOT / ('correctness-'+label+'.json'))['passed']
trial_status = p.common.load(p.ROOT / ('analysis-'+label+'.json'))['status']
p.pin()
labels = ['classical','baseline',label]
data = {'records': [], 'environment_segments': [], 'repeats': 3,
        'purpose': __doc__, 'candidate': label, 'candidate_status': trial_status, 'summary': {}}
if (p.ROOT/'classical-gap.json').exists():
    data = p.common.load(p.ROOT/'classical-gap.json')
    assert data['candidate']==label and data['repeats']==3
done = {(r['position'],r['build'],r['repeat']) for r in data['records']}
with ExitStack() as stack:
    players = {b:stack.enter_context(p.player('baseline' if b=='classical' else b,
               'classical' if b=='classical' else 'nnue')) for b in labels}
    meter = Meter([os.getpid()]+[e.transport.get_pid() for e in players.values()])
    stack.callback(meter.close)
    for e in players.values():
        p.capture(e,p.common.load(p.ROOT/'positions.json')[0],'nodes',20000)
    for repeat in range(3):
        for i,row in enumerate(p.common.load(p.ROOT/'positions.json')):
            if all((row['id'],b,repeat) in done for b in labels):
                continue
            start = (i+repeat)%3
            order = labels[start:]+labels[:start]
            for b in order:
                if (row['id'],b,repeat) in done:
                    continue
                r = p.capture(players[b],row,'time',1000)
                data['records'].append(dict(r,build=b,repeat=repeat))
            data['environment_segments'].append(dict(meter.read(),repeat=repeat,position=row['id']))
            p.save('classical-gap.json',data)
            print('Matched context',repeat+1,row['id'],flush=True)
groups = {b:[] for b in ['baseline',label]}
for row in p.common.load(p.ROOT/'positions.json'):
    records = [r for r in data['records'] if r['position']==row['id']]
    for b in groups:
        ratios = []
        for repeat in range(3):
            a = next(r for r in records if r['repeat']==repeat and r['build']=='classical')
            v = next(r for r in records if r['repeat']==repeat and r['build']==b)
            ratios.append((v['nodes']/v['wall_seconds'])/(a['nodes']/a['wall_seconds']))
        groups[b].append([math.log(v) for v in ratios])
from analyze import interval
for b,g in groups.items():
    data['summary'][b] = dict(geomean_paired_nps_ratio_to_classical=math.exp(s.mean(s.median(v) for v in g)),
                            grouped_bootstrap95=interval(g))
a = data['summary']['baseline']['geomean_paired_nps_ratio_to_classical']
b = data['summary'][label]['geomean_paired_nps_ratio_to_classical']
data['summary']['aggregate_remaining_nps_shortfall_fraction_recovered']=(b-a)/(1-a) if a<1 else None
data['summary']['warning']='Descriptive ratio of geometric group summaries, three repetitions only; '
data['summary']['warning']+='not a precise recovery estimate or equal-tree/evaluation-cost/Elo comparison. No earlier-run projection used.'
p.save('classical-gap.json',data)
print(data['summary'],flush=True)
