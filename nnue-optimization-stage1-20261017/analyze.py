"""Position-grouped paired analysis; consumes saved measurements only."""
import collections
import csv
import math
import random
import statistics as s
import experiment as p

def describe(values):
    values=list(values);q=s.quantiles(values,n=4,method='inclusive')
    return {'median':s.median(values),'q1':q[0],'q3':q[2],'minimum':min(values),'maximum':max(values)}

def geometric(values):
    return math.exp(s.mean(math.log(v) for v in values))

def group_interval(groups,seed=20261017,iterations=10000):
    """Resample positions, then paired repetitions within each selected position."""
    rng=random.Random(seed);samples=[]
    groups=list(groups)
    for _ in range(iterations):
        means=[]
        for group in rng.choices(groups,k=len(groups)):
            # Log median per fixture gives every chess fixture equal weight.
            means.append(s.median(rng.choices(group,k=len(group))))
        samples.append(math.exp(s.mean(means)))
    samples.sort()
    return [samples[int(.025*iterations)],samples[int(.975*iterations)]]

micro=p.common.load(p.ROOT/'micro.json')
out={'method':'Paired repetitions within each FEN/control. Primary search statistic: geometric mean of per-position median paired wall-NPS ratios. Hierarchical 95% bootstrap resamples 12 positions and paired repeats within each sampled position, 10,000 draws, fixed seed; descriptive for this fixed fixture suite. Repetitions are not independent chess positions.','micro':[], 'micro_fens':[], 'search':[], 'per_position':[]}
for size in [1,32,128,512]:
    records=[r for r in micro['records'] if r['frames']==size]
    pairs=[]
    for repeat in range(7):
        a=next(r for r in records if r['repeat']==repeat and r['build']=='baseline')
        b=next(r for r in records if r['repeat']==repeat and r['build']=='variant')
        assert a['checksum']==b['checksum']
        pairs.append(a['ns']/b['ns'])
    out['micro'].append({'frames':size,**{label:describe(r['ns'] for r in records if r['build']==label) for label in ['baseline','variant']},'paired_speedup':describe(pairs)})
for row in p.common.load(p.ROOT/'positions.json'):
    records=[r for r in micro['fen_records'] if r['position']==row['id']]
    pairs=[]
    for repeat in range(7):
        a=next(r for r in records if r['repeat']==repeat and r['build']=='baseline')
        b=next(r for r in records if r['repeat']==repeat and r['build']=='variant')
        assert a['checksum']==b['checksum'];pairs.append(a['ns']/b['ns'])
    out['micro_fens'].append({'position':row['id'],**{label:describe(r['ns'] for r in records if r['build']==label) for label in ['baseline','variant']},'paired_speedup':describe(pairs)})

path=p.ROOT/'search.json'
if path.exists():
    data=p.common.load(path)
    for mode,budget in p.common.load(p.ROOT/'plan.json')['budgets']:
        groups=[];positions=[];order_ratios=collections.defaultdict(list)
        for index,row in enumerate(p.common.load(p.ROOT/'positions.json')):
            records=[r for r in data['records'] if r['position']==row['id'] and r['mode']==mode and r['budget']==budget]
            if len(records)!=14:continue
            ratios=[]
            for repeat in range(7):
                a=next(r for r in records if r['repeat']==repeat and r['build']=='baseline')
                b=next(r for r in records if r['repeat']==repeat and r['build']=='variant')
                if mode=='nodes':
                    assert p.canonical(a)==p.canonical(b)
                    assert a['nodes']==b['nodes']==budget
                ratio=(b['nodes']/b['wall_seconds'])/(a['nodes']/a['wall_seconds'])
                ratios.append(ratio)
                order_ratios['baseline_first' if (repeat+index)%2 else 'variant_first'].append(ratio)
            groups.append([math.log(v) for v in ratios])
            record={'position':row['id'],'mode':mode,'budget':budget,'paired_speedup':describe(ratios)}
            for label in ['baseline','variant']:
                selected=[r for r in records if r['build']==label]
                record[label]={key:describe(r[key] for r in selected) for key in ['nodes','wall_seconds','nps','depth']}
                record[label]['wall_nps']=describe(r['nodes']/r['wall_seconds'] for r in selected)
                record[label]['eval_calls']=describe(r['counters']['eval_calls'] for r in selected)
                record[label]['qnodes']=describe(r['counters']['qnodes'] for r in selected)
                record[label]['repeat_cv']=s.stdev(r['nodes']/r['wall_seconds'] for r in selected)/s.mean(r['nodes']/r['wall_seconds'] for r in selected)
            positions.append(record);out['per_position'].append(record)
        if len(groups)==12:
            estimate=math.exp(s.mean(s.median(group) for group in groups))
            interval=group_interval(groups)
            out['search'].append({'mode':mode,'budget':budget,'positions':12,'pairs':84,
                'geomean_paired_speedup':estimate,'hierarchical_grouped_bootstrap95':interval,
                'gain_percent':100*(estimate-1),'reliable_positive_on_suite':interval[0]>1,
                'position_median_speedups':describe(math.exp(s.median(g)) for g in groups),
                'order_median_speedups':{name:s.median(values) for name,values in order_ratios.items()},
                **{label:{'wall_nps_position_medians':describe(r[label]['wall_nps']['median'] for r in positions),
                          'depth_position_medians':describe(r[label]['depth']['median'] for r in positions),
                          'repeat_cv':describe(r[label]['repeat_cv'] for r in positions)} for label in ['baseline','variant']}})
    if data['environment_segments']:
        out['background_load']={key:describe(r[key] for r in data['environment_segments']) for key in ['system_cpu_percent','benchmark_process_cpu_percent','other_cpu_percent_estimate']}
    out['search_records']=len(data['records'])
    complete=len(data['records'])==840 and len(out['search'])==5
    successful=complete and all(r['reliable_positive_on_suite'] for r in out['search']) and min(r['paired_speedup']['median'] for r in out['per_position'])>1
    out['status']='ACCEPTED' if successful else 'INCONCLUSIVE'
    out['acceptance_note']='Accepted only as an isolated experimental implementation; no promotion. All five grouped intervals and per-position medians must be positive; correctness gates are required independently.'

if (p.ROOT/'native-symbols.json').exists():
    native=p.common.load(p.ROOT/'native-samples.json')
    symbols=p.common.load(p.ROOT/'native-symbols.json')
    functions=collections.Counter();lines=collections.Counter();maintenance=0;head=0
    for record in native['records']:
        for ip,n in record['rip_counts'].items():
            value=symbols[ip];name=value['symbol'];functions[name]+=n
            if 'nnue_side_to_move' in name:head+=n
            if any(token in name for token in ['descend_nnue','nnue_update','nnue_search_states','nnue_move_delta','source/nnue.cpp','source\\nnue.cpp']):maintenance+=n
            if 'line' in value:lines[(value['file'].replace('\\','/').split('/')[-1],value['line'])]+=n
    total=functions.total()
    ratios=[]
    for pos in {r['position'] for r in native['records']}:
        a=[r for r in native['records'] if r['position']==pos and not r['sampled']]
        b=[r for r in native['records'] if r['position']==pos and r['sampled']]
        ratios.append(s.median(r['wall_nps'] for r in b)/s.median(r['wall_nps'] for r in a))
    out['native']={'samples':total,'head_fraction':head/total,'maintenance_fraction':maintenance/total,
        'other_fraction':1-(head+maintenance)/total,'functions':[{'symbol':name,'samples':n,'percent':100*n/total} for name,n in functions.most_common()],
        'lines':[{'file':file,'line':line,'samples':n,'percent':100*n/total} for (file,line),n in lines.most_common()],
        'context_failures':sum(r['failed_samples'] for r in native['records']),
        'sampled_unsampled_nps_ratios':describe(ratios),
        'suspension_ns':describe(v for r in native['records'] for v in r['suspension_ns'])}

p.save('analysis.json',out)
if out['per_position']:
    with (p.ROOT/'search-per-position.csv').open('w',newline='',encoding='utf-8') as f:
        rows=[]
        for r in out['per_position']:
            rows.append({'position':r['position'],'mode':r['mode'],'budget':r['budget'],'median_paired_speedup':r['paired_speedup']['median'],'pair_q1':r['paired_speedup']['q1'],'pair_q3':r['paired_speedup']['q3'],**{label+'_'+key:r[label][key]['median'] for label in ['baseline','variant'] for key in ['wall_nps','nodes','depth','wall_seconds','eval_calls','qnodes']}})
        writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
print({key:value for key,value in out.items() if key in ['micro','search','background_load','status','search_records']})
