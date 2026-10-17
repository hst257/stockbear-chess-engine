"""Position-grouped inference/search analysis; never runs an engine."""
import collections
import csv
import math
import random
import statistics as s
import experiment as p


def describe(values):
    values=list(values);q=s.quantiles(values,n=4,method='inclusive')
    return dict(median=s.median(values),q1=q[0],q3=q[2],minimum=min(values),maximum=max(values))


def interval(groups):
    rng=random.Random(20261017);draws=[]
    for _ in range(10000):
        draws.append(math.exp(s.mean(s.median(rng.choices(g,k=len(g))) for g in rng.choices(groups,k=len(groups)))))
    draws.sort();return [draws[250],draws[9750]]


def main():
    out=dict(candidates={},method='exp(mean(per-position median(log(paired wall-NPS ratio)))); '
        '10,000-draw hierarchical bootstrap: resample positions as groups then paired repetitions within group; '
        'seed 20261017. Repetitions are not independent positions. No multiplicity or temporal-autocorrelation adjustment; '
        'these are fixture-suite speed intervals, not Elo or universal workload guarantees.')
    for label in ['unroll4','hiddenclip']:
        failed=p.ROOT/('failure-'+label+'.json')
        if failed.exists():
            out['candidates'][label]=dict(status='REJECTED',failure=p.common.load(failed),search=[],per_position=[],micro=[])
            continue
        assert p.common.load(p.ROOT/('trial-'+label+'.json'))['performance_complete']
        data=p.common.load(p.ROOT/('search-'+label+'.json'))
        records=data['records']
        keys={(r['position'],r['mode'],r['budget'],r['build'],r['repeat']):r for r in records}
        count=1+max(r['repeat'] for r in records)
        assert len(keys)==len(records)==12*5*2*count and 7<=count<=10
        result=dict(micro=[],search=[],per_position=[],search_records=len(records),repeats=count,runtime_seconds=data['runtime_seconds'])
        micro=p.common.load(p.ROOT/('micro-'+label+'.json'))['records']
        for size in [1,32,128,512]:
            pairs={b:[r for r in micro if r['build']==b and r['frames']==size] for b in ['baseline',label]}
            assert len(pairs['baseline'])==len(pairs[label])==7
            ratios=[]
            for a,b in zip(pairs['baseline'],pairs[label]):
                assert a['repeat']==b['repeat'] and a['checksum']==b['checksum']
                ratios.append(a['ns']/b['ns'])
            result['micro'].append(dict(frames=size,baseline=describe(r['ns'] for r in pairs['baseline']),
                candidate=describe(r['ns'] for r in pairs[label]),paired_speedup=describe(ratios),
                repeat_only95=interval([[math.log(v) for v in ratios]]),
                frame_storage_bytes=pairs[label][0]['frame_storage_bytes']))
        for mode,budget in p.common.load(p.ROOT/'plan.json')['budgets']:
            groups=[];order=collections.defaultdict(list)
            for row in p.common.load(p.ROOT/'positions.json'):
                ratios=[];values={b:[] for b in ['baseline',label]}
                for repeat in range(count):
                    a=keys[(row['id'],mode,budget,'baseline',repeat)];b=keys[(row['id'],mode,budget,label,repeat)]
                    if mode=='nodes':assert p.canonical(a)==p.canonical(b) and a['nodes']==b['nodes']==budget
                    ratio=(b['nodes']/b['wall_seconds'])/(a['nodes']/a['wall_seconds'])
                    ratios.append(ratio)
                    order['baseline_first' if a['order'][0]=='baseline' else 'candidate_first'].append(ratio)
                    values['baseline'].append(a);values[label].append(b)
                groups.append([math.log(v) for v in ratios])
                entry=dict(position=row['id'],mode=mode,budget=budget,paired_speedup=describe(ratios))
                for b,rows in values.items():
                    entry[b]={key:describe(r[key] for r in rows) for key in ['wall_seconds','nodes','depth','seldepth']}
                    entry[b]['wall_nps']=describe(r['nodes']/r['wall_seconds'] for r in rows)
                    entry[b]['eval_calls']=describe(r['counters']['eval_calls'] for r in rows)
                    entry[b]['qnodes']=describe(r['counters']['qnodes'] for r in rows)
                    speeds=[r['nodes']/r['wall_seconds'] for r in rows]
                    entry[b]['repeat_cv']=s.stdev(speeds)/s.mean(speeds)
                result['per_position'].append(entry)
            result['search'].append(dict(mode=mode,budget=budget,pairs=12*count,
                factor=math.exp(s.mean(s.median(g) for g in groups)),grouped95=interval(groups),
                order_medians={k:s.median(v) for k,v in order.items()},
                position_range=[min(math.exp(s.median(g)) for g in groups),max(math.exp(s.median(g)) for g in groups)]))
        result['material_regressions']=[dict(position=r['position'],mode=r['mode'],budget=r['budget'],
            factor=r['paired_speedup']['median'],elapsed_percent=100*(1/r['paired_speedup']['median']-1))
            for r in result['per_position'] if r['paired_speedup']['median']<1/1.03]
        result['background_load']={key:describe(r[key] for r in data['environment_segments']) for key in ['system_cpu_percent','benchmark_process_cpu_percent','other_cpu_percent_estimate']}
        gates=dict(micro_no_material_regressions=all(r['paired_speedup']['median']>=1/1.03 for r in result['micro']),
            representative_micro_support=all(r['repeat_only95'][0]>1 for r in result['micro'] if r['frames']>=32),
            all_search_intervals_positive=all(r['grouped95'][0]>1 for r in result['search']),
            long_control_orders_positive=all(min(r['order_medians'].values())>1 for r in result['search'] if r['budget'] in [1000000,1000]),
            no_material_fixture_regressions=not result['material_regressions'])
        result['gates']=gates
        result['status']='ACCEPTED' if all(gates.values()) else 'INCONCLUSIVE'
        long_regression=all(r['grouped95'][1]<1 for r in result['search'] if r['budget'] in [1000000,1000])
        broad_head_regression=all(r['repeat_only95'][1]<1 for r in result['micro'] if r['frames']>=32)
        if long_regression or broad_head_regression:
            result['status']='REJECTED'
        out['candidates'][label]=result
        with (p.ROOT/('per-position-'+label+'.csv')).open('w',newline='',encoding='utf-8') as handle:
            rows=[dict(position=r['position'],mode=r['mode'],budget=r['budget'],speedup=r['paired_speedup']['median'],
                **{b+'_'+key:r[b][key]['median'] for b in ['baseline',label] for key in ['wall_seconds','wall_nps','nodes','depth','seldepth','eval_calls','qnodes']}) for r in result['per_position']]
            writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    accepted=[b for b,r in out['candidates'].items() if r['status']=='ACCEPTED']
    out['accepted_candidates']=accepted
    out['decision']='ACCEPTED' if accepted else ('REJECTED' if all(v['status']=='REJECTED' for v in out['candidates'].values()) else 'INCONCLUSIVE')
    out['retained_baseline']='Stage 1' if not accepted else max(accepted,key=lambda b:next(r['factor'] for r in out['candidates'][b]['search'] if r['budget']==1000000))
    out['acceptance_note']='All correctness receipts required. No arbitrary minimum 3% gain cutoff. Representative rotating-frame micro support and no common-workload loss, all search-control grouped intervals positive, long-control order support, no >3% elapsed fixture median regression. No active promotion.'
    p.save('analysis.json',out)
    print({b:dict(status=r['status'],gates=r.get('gates'),search=r['search'],micro=r['micro'],regressions=r.get('material_regressions')) for b,r in out['candidates'].items()})


if __name__=='__main__':main()
