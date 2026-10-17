"""Position-grouped paired analysis of one independently tested candidate."""
import collections
import csv
import math
import random
import statistics as s
import sys
import experiment as p


def describe(values):
    values = list(values)
    q = s.quantiles(values, n=4, method='inclusive')
    return dict(median=s.median(values), q1=q[0], q3=q[2], minimum=min(values), maximum=max(values))


def interval(groups, iterations=10000):
    rng = random.Random(20261017)
    samples = []
    for _ in range(iterations):
        samples.append(math.exp(s.mean(s.median(rng.choices(g, k=len(g)))
                       for g in rng.choices(groups, k=len(groups)))))
    samples.sort()
    return [samples[int(.025*iterations)], samples[int(.975*iterations)]]


def analyze(label):
    out = {'candidate': label, 'method': 'Geometric mean of per-position median paired '
           'wall-NPS ratios; 10,000 hierarchical bootstrap draws, resample positions then '
           'paired repetitions within positions, seed 20261017. Repeats are not independent '
           'chess fixtures; intervals describe this frozen suite, not Elo.',
           'search': [], 'per_position': [], 'micro': []}
    micro = p.common.load(p.ROOT / ('micro-' + label + '.json'))['records']
    for kind in [r['kind'] for r in micro[0]['cases']]:
        group = {b: [next(c for c in r['cases'] if c['kind'] == kind)
                     for r in micro if r['build'] == b] for b in ['baseline', label]}
        for a,b in zip([r for r in micro if r['build']=='baseline'], [r for r in micro if r['build']==label]):
            assert a['repeat']==b['repeat'] and a['digest']==b['digest']
        row = dict(kind=kind, edges=group['baseline'][0]['edges'], rows_both_perspectives=group['baseline'][0]['rows_both_perspectives'])
        for key in ['total_ns','update_ns','prepared_update_ns','state_ns','index_ns','copy_reference_ns','metadata_reference_ns']:
            row[key] = {b: describe(r[key] for r in group[b]) for b in group}
            row[key]['paired_speedup'] = describe(a[key]/b[key] for a,b in zip(group['baseline'],group[label]))
        row['ns_per_changed_row_reference'] = {b: row['prepared_update_ns'][b]['median']/max(1,row['rows_both_perspectives']) for b in group}
        out['micro'].append(row)
    data = p.common.load(p.ROOT / ('search-' + label + '.json'))
    repeats = p.repeats(label)
    for mode, budget in p.common.load(p.ROOT / 'plan.json')['budgets']:
        groups = []
        order = collections.defaultdict(list)
        for index,row in enumerate(p.common.load(p.ROOT / 'positions.json')):
            selected = [r for r in data['records'] if r['position']==row['id'] and r['mode']==mode and r['budget']==budget]
            assert len(selected)==2*repeats
            ratios = []
            for repeat in range(repeats):
                a = next(r for r in selected if r['build']=='baseline' and r['repeat']==repeat)
                b = next(r for r in selected if r['build']==label and r['repeat']==repeat)
                if mode=='nodes':
                    assert p.canonical(a)==p.canonical(b) and a['nodes']==b['nodes']==budget
                ratio = (b['nodes']/b['wall_seconds'])/(a['nodes']/a['wall_seconds'])
                ratios.append(ratio)
                order['baseline_first' if (index+repeat)%2 else 'candidate_first'].append(ratio)
            groups.append([math.log(v) for v in ratios])
            r = dict(position=row['id'],mode=mode,budget=budget,paired_speedup=describe(ratios))
            for b in ['baseline',label]:
                values = [v for v in selected if v['build']==b]
                r[b] = {k: describe(v[k] for v in values) for k in ['nodes','wall_seconds','depth','seldepth']}
                r[b]['wall_nps'] = describe(v['nodes']/v['wall_seconds'] for v in values)
                r[b]['eval_calls'] = describe(v['counters']['eval_calls'] for v in values)
                r[b]['qnodes'] = describe(v['counters']['qnodes'] for v in values)
                speeds = [v['nodes']/v['wall_seconds'] for v in values]
                r[b]['repeat_cv'] = s.stdev(speeds)/s.mean(speeds)
            out['per_position'].append(r)
        ci = interval(groups)
        out['search'].append(dict(mode=mode,budget=budget,pairs=12*repeats,
             geomean_paired_speedup=math.exp(s.mean(s.median(g) for g in groups)),
             grouped_bootstrap95=ci, positive=ci[0]>1,
             order_median_speedups={k:s.median(v) for k,v in order.items()},
             position_range=[min(math.exp(s.median(g)) for g in groups),max(math.exp(s.median(g)) for g in groups)]))
    # A resumed earlier runner could record an empty segment for a completed
    # row. Retain raw records, use only the original segment per fixture/pass.
    segments = {}
    for r in data['environment_segments']:
        segments.setdefault((r['repeat'],r['position']),r)
    out['background_segments_used'] = len(segments)
    out['duplicate_resume_segments_excluded'] = len(data['environment_segments'])-len(segments)
    out['background_load'] = {k:describe(r[k] for r in segments.values()) for k in
           ['system_cpu_percent','benchmark_process_cpu_percent','other_cpu_percent_estimate']}
    out['material_regressions'] = [dict(position=r['position'],mode=r['mode'],budget=r['budget'],
         speedup=r['paired_speedup']['median']) for r in out['per_position'] if r['paired_speedup']['median'] < 1/1.03]
    out['search_records'] = len(data['records'])
    mixed = next(r for r in out['micro'] if r['kind']=='mixed')
    correct = p.common.load(p.ROOT / ('correctness-'+label+'.json'))['passed']
    regression = p.common.load(p.ROOT / ('regressions-'+label+'.json'))['passed']
    positive = all(r['positive'] for r in out['search'])
    stable = min(r['geomean_paired_speedup'] for r in out['search']) > 1.01
    maintenance = mixed['update_ns']['paired_speedup']['median'] > 1
    out['status'] = 'ACCEPTED' if correct and regression and positive and stable and maintenance and not out['material_regressions'] else 'INCONCLUSIVE'
    if all(r['geomean_paired_speedup']<1 for r in out['search']):
        out['status'] = 'REJECTED'
    out['acceptance_note'] = ('A positive grouped interval in every control, repeatable maintenance reduction, meaningful (>1%) '
          'suite gains and no unexplained >3% fixture regression are required here. Approximately 3% remains a practical target. No promotion.')
    p.save('analysis-'+label+'.json',out)
    with (p.ROOT / ('per-position-'+label+'.csv')).open('w',newline='',encoding='utf-8') as f:
        rows = [dict(position=r['position'],mode=r['mode'],budget=r['budget'],speedup=r['paired_speedup']['median'],
              **{b+'_'+k:r[b][k]['median'] for b in ['baseline',label] for k in ['wall_seconds','wall_nps','nodes','depth','seldepth','eval_calls','qnodes']}) for r in out['per_position']]
        writer = csv.DictWriter(f,fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)
    print({k:out[k] for k in ['candidate','status','search','material_regressions','background_load']})


if __name__ == '__main__':
    analyze(sys.argv[1])
