"""Joint position/triple bootstrap for the descriptive classical-gap context."""
import math
import random
import statistics as s
import experiment as p

data = p.common.load(p.ROOT/'classical-gap.json')
label = data['candidate']
assert len(data['records'])==108
index = {(r['position'],r['build'],r['repeat']):r for r in data['records']}
assert len(index)==108
groups = []
for row in p.common.load(p.ROOT/'positions.json'):
    group = []
    for repeat in range(3):
        speeds = {}
        for b in ['classical','baseline',label]:
            r = index[(row['id'],b,repeat)]
            speeds[b] = r['nodes']/r['wall_seconds']
        group.append((math.log(speeds['baseline']/speeds['classical']),
                      math.log(speeds[label]/speeds['classical']),
                      math.log(speeds[label]/speeds['baseline'])))
    groups.append(group)
rng = random.Random(20261017)
recovery, improvements = [], []
undefined = 0
for _ in range(10000):
    first, second, direct = [], [], []
    for group in rng.choices(groups,k=len(groups)):
        selected = rng.choices(group,k=3)
        first.append(s.median(v[0] for v in selected))
        second.append(s.median(v[1] for v in selected))
        direct.append(s.median(v[2] for v in selected))
    a,b = math.exp(s.mean(first)),math.exp(s.mean(second))
    improvements.append(math.exp(s.mean(direct)))
    if a<1:
        recovery.append((b-a)/(1-a))
    else:
        undefined += 1
def limits(values):
    values.sort()
    return [values[int(.025*len(values))],values[int(.975*len(values))]]
data['summary']['secondary_direct_candidate_baseline_speedup'] = math.exp(s.mean(s.median(v[2] for v in g) for g in groups))
data['summary']['secondary_direct_speedup_joint_grouped95'] = limits(improvements)
data['summary']['shortfall_recovery_joint_grouped95_conditional_on_baseline_below_classical'] = limits(recovery)
data['summary']['bootstrap_draws_without_positive_classical_gap'] = undefined
data['summary']['bootstrap_method'] = '10,000 joint draws, seed 20261017: positions as groups, then same sampled triples for all three builds. Recovery undefined when aggregate baseline reaches/exceeds classical; omitted and counted. Three triples/fixture are descriptive, not an acceptance extension.'
p.save('classical-gap.json',data)
print(data['summary'],flush=True)
