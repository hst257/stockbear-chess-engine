"""Paired position-grouped analysis from frozen measurements; no new searches."""
import collections
import csv
import math
import random
import statistics as s
import experiment as p


def describe(values):
    values=list(values)
    q=s.quantiles(values,n=4,method='inclusive')
    return dict(median=s.median(values),q1=q[0],q3=q[2],minimum=min(values),maximum=max(values))


def interval(groups):
    rng=random.Random(20261017)
    draws=[]
    for _ in range(10000):
        draws.append(math.exp(s.mean(s.median(rng.choices(g,k=len(g))) for g in rng.choices(groups,k=len(groups)))))
    draws.sort()
    return [draws[250],draws[9750]]


def main():
    data=p.common.load(p.ROOT/'primary.json')
    records=data['records']
    index={(r['position'],r['mode'],r['budget'],r['build'],r['repeat']):r for r in records}
    assert len(index)==len(records)
    repeats=1+max(r['repeat'] for r in records)
    assert 7<=repeats<=10
    frozen=p.common.load(p.ROOT/'positions.json')
    supplementary=p.common.load(p.ROOT/'supplementary-positions.json')
    assert len(records)==len(frozen+supplementary)*5*3*repeats
    micro=p.common.load(p.ROOT/'micro.json')
    result=dict(repeats=repeats,search_records=len(records),runtime_seconds=data['runtime_seconds'],candidates={},
        method='exp(mean(per-position median(log(paired wall NPS ratio)))); hierarchical 10,000-draw bootstrap, '
        'positions as groups then paired repetitions within position, seed 20261017. Frozen 12 and supplementary 4 analyzed separately. '
        'No temporal autocorrelation model or multiplicity adjustment; these are fixture-suite throughput intervals, not Elo.')
    for label in ['sort','selective']:
        out=dict(suites={},per_position=[],micro=[],sort_micro=[])
        for suite,rows in [('frozen12',frozen),('supplementary4',supplementary)]:
            summaries=[]
            for mode,budget in p.common.load(p.ROOT/'plan.json')['budgets']:
                groups=[];order=collections.defaultdict(list)
                for row in rows:
                    ratios=[]
                    pairs={b:[index[(row['id'],mode,budget,b,rep)] for rep in range(repeats)] for b in ['baseline',label]}
                    for a,b in zip(pairs['baseline'],pairs[label]):
                        if mode=='nodes':
                            assert p.canonical(a)==p.canonical(b) and a['nodes']==b['nodes']==budget
                        ratio=(b['nodes']/b['wall_seconds'])/(a['nodes']/a['wall_seconds'])
                        ratios.append(ratio)
                        order['baseline_before' if a['order'].index('baseline')<a['order'].index(label) else 'candidate_before'].append(ratio)
                    groups.append([math.log(v) for v in ratios])
                    entry=dict(suite=suite,position=row['id'],mode=mode,budget=budget,paired_speedup=describe(ratios))
                    for b,values in pairs.items():
                        entry[b]={key:describe(v[key] for v in values) for key in ['wall_seconds','nodes','depth','seldepth']}
                        entry[b]['wall_nps']=describe(v['nodes']/v['wall_seconds'] for v in values)
                        entry[b]['eval_calls']=describe(v['counters']['eval_calls'] for v in values)
                        entry[b]['qnodes']=describe(v['counters']['qnodes'] for v in values)
                        speeds=[v['nodes']/v['wall_seconds'] for v in values]
                        entry[b]['repeat_cv']=s.stdev(speeds)/s.mean(speeds)
                    out['per_position'].append(entry)
                summaries.append(dict(mode=mode,budget=budget,positions=len(rows),pairs=len(rows)*repeats,
                    geomean_paired_speedup=math.exp(s.mean(s.median(g) for g in groups)),
                    grouped_bootstrap95=interval(groups),order_medians={k:s.median(v) for k,v in order.items()}))
            out['suites'][suite]=summaries
        for kind in [r['kind'] for r in micro['records'][0]['cases']]:
            groups={b:[next(c for c in r['cases'] if c['kind']==kind) for r in micro['records'] if r['build']==b] for b in ['baseline',label]}
            entry=dict(kind=kind,edges=groups['baseline'][0]['edges'])
            for key in ['update_ns','total_ns','prepared_update_ns','state_ns']:
                entry[key]={b:describe(v[key] for v in values) for b,values in groups.items()}
                entry[key]['paired_speedup']=describe(a[key]/b[key] for a,b in zip(groups['baseline'],groups[label]))
            out['micro'].append(entry)
        for length in range(17):
            for type_ in [0,1]:
                values={b:[next(c for c in r['cases'] if c['length']==length and c['type']==type_) for r in micro['sort_records'] if r['build']==b] for b in ['baseline',label]}
                out['sort_micro'].append(dict(length=length,type=type_,
                    baseline=describe(v['copy_plus_sort_ns'] for v in values['baseline']),
                    candidate=describe(v['copy_plus_sort_ns'] for v in values[label]),
                    paired_speedup=describe(a['copy_plus_sort_ns']/b['copy_plus_sort_ns'] for a,b in zip(values['baseline'],values[label]))))
        out['material_regressions']=[dict(suite=r['suite'],position=r['position'],mode=r['mode'],budget=r['budget'],speedup=r['paired_speedup']['median']) for r in out['per_position'] if r['paired_speedup']['median']<1/1.03]
        positive=all(r['grouped_bootstrap95'][0]>1 for r in out['suites']['frozen12'])
        corroborates=all(r['grouped_bootstrap95'][0]>1 for r in out['suites']['supplementary4'] if r['budget'] in [1000000,1000])
        # Order subsets are sensitivity checks, not independent observations.
        order_ok=all(min(r['order_medians'].values())>1 for r in out['suites']['frozen12'] if r['budget'] in [1000000,1000])
        if positive and corroborates and order_ok and not out['material_regressions']:
            out['status']='ACCEPTED'
        elif all(r['geomean_paired_speedup']<1 for r in out['suites']['frozen12']):
            out['status']='REJECTED'
        else:
            out['status']='INCONCLUSIVE'
        out['gate_checks']=dict(all_frozen_control_intervals_positive=positive,supplementary_long_controls_positive=corroborates,
            long_control_order_subsets_positive=order_ok,no_material_regressions=not out['material_regressions'])
        result['candidates'][label]=out
        with (p.ROOT/('per-position-'+label+'.csv')).open('w',newline='',encoding='utf-8') as handle:
            rows=[dict(suite=r['suite'],position=r['position'],mode=r['mode'],budget=r['budget'],speedup=r['paired_speedup']['median'],
                **{b+'_'+key:r[b][key]['median'] for b in ['baseline',label] for key in ['wall_seconds','wall_nps','nodes','depth','seldepth','eval_calls','qnodes']}) for r in out['per_position']]
            writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    # A direct new-versus-full-sort contrast shares exactly the same blocks.
    direct=[]
    for mode,budget in p.common.load(p.ROOT/'plan.json')['budgets']:
        groups=[]
        for row in frozen:
            group=[]
            for rep in range(repeats):
                a=index[(row['id'],mode,budget,'sort',rep)];b=index[(row['id'],mode,budget,'selective',rep)]
                group.append(math.log((b['nodes']/b['wall_seconds'])/(a['nodes']/a['wall_seconds'])))
            groups.append(group)
        direct.append(dict(mode=mode,budget=budget,factor=math.exp(s.mean(s.median(g) for g in groups)),grouped95=interval(groups)))
    result['selective_vs_stage2_sort']=direct
    drift=[]
    for mode,budget in p.common.load(p.ROOT/'plan.json')['budgets']:
        centers={row['id']:s.median(index[(row['id'],mode,budget,'baseline',rep)]['nodes']/index[(row['id'],mode,budget,'baseline',rep)]['wall_seconds'] for rep in range(repeats)) for row in frozen}
        passes=[]
        for rep in range(repeats):
            normalized=[]
            for row in frozen:
                record=index[(row['id'],mode,budget,'baseline',rep)]
                normalized.append(math.log((record['nodes']/record['wall_seconds'])/centers[row['id']]))
            passes.append(math.exp(s.mean(normalized)))
        drift.append(dict(mode=mode,budget=budget,normalized_baseline_nps_by_pass=passes,
            minimum=min(passes),maximum=max(passes)))
    result['baseline_drift']=drift
    result['background_load']={key:describe(r[key] for r in data['environment_segments']) for key in ['system_cpu_percent','benchmark_process_cpu_percent','other_cpu_percent_estimate']}
    result['acceptance_note']='Require all exact gates, positive frozen-suite intervals, long-control supplementary and order corroboration, and no unexplained >3% elapsed median regression. No minimum 3% gain cutoff. No acceptance from microbenchmarks alone.'
    p.save('analysis.json',result)
    print({b:dict(status=v['status'],frozen=v['suites']['frozen12'],regressions=v['material_regressions']) for b,v in result['candidates'].items()})


if __name__=='__main__':main()
