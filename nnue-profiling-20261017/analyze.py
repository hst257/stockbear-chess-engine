"""Recompute report tables from raw measurements; never starts an engine."""
import collections
import csv
import json
import statistics as s
import run_profile as p

def describe(values):
    values=list(values)
    q=s.quantiles(values,n=4,method='inclusive') if len(values)>1 else [values[0]]*3
    return dict(median=s.median(values),q1=q[0],q3=q[2],minimum=min(values),maximum=max(values))

def med(rows,key):return s.median(r[key] for r in rows)
baseline=p.common.load(p.ROOT/'baseline.json')
positions=p.common.load(p.ROOT/'positions.json')
out={'method':'Ratios are matched within FEN/control; repeated measurements collapsed to a median per FEN. Cross-FEN summaries describe this fixture suite, not matched search trees or strength. Inclusive quartiles.','baseline':[],'positions':[]}
for mode,budget in [('depth',5),('nodes',200000),('time',100),('time',500),('time',1000)]:
    selected=[r for r in baseline['records'] if r['mode']==mode and r['budget']==budget]
    pair_ratios=[]
    for row in positions:
        pair={e:[r for r in selected if r['position']==row['id'] and r['evaluator']==e] for e in ['classical','nnue']}
        assert all(len(v)==3 for v in pair.values())
        record={'position':row['id'],'mode':mode,'budget':budget}
        for e,records in pair.items():
            for key in ['nps','wall_nps','depth','nodes','wall_seconds','evaluations_per_node','nodes_per_completed_depth']:
                record[e+'_'+key]=describe(r[key] for r in records)
            record[e+'_eval_calls']=med([{'x':r['counters']['eval_calls']} for r in records],'x')
            record[e+'_q_fraction']=s.median(r['counters']['qnodes']/r['nodes'] for r in records)
            record[e+'_outside_reported_seconds']=s.median(r['wall_seconds']-r['seconds'] for r in records)
        ratio=med(pair['nnue'],'wall_nps')/med(pair['classical'],'wall_nps')
        record['nnue_classical_wall_nps_ratio']=ratio;pair_ratios.append(ratio)
        out['positions'].append(record)
    summary={'mode':mode,'budget':budget,'matched_nps_ratio':describe(pair_ratios)}
    summary['repeat_cv']=describe(s.stdev(r['wall_nps'] for r in selected if r['position']==row['id'] and r['evaluator']==e)/s.mean(r['wall_nps'] for r in selected if r['position']==row['id'] and r['evaluator']==e) for row in positions for e in ['classical','nnue'])
    for e in ['classical','nnue']:
        summary[e]={key:describe(r[e+'_'+key]['median'] for r in out['positions'] if r['mode']==mode and r['budget']==budget) for key in ['wall_nps','nps','depth','nodes','evaluations_per_node','nodes_per_completed_depth']}
    out['baseline'].append(summary)
out['cold']={e:{key:describe(r[key] for r in baseline['cold'] if r['evaluator']==e) for key in ['wall_nps','startup_seconds','wall_seconds']} for e in ['classical','nnue']}
out['cold_matched_warm_ratios']={e:describe(s.median(r['wall_nps'] for r in baseline['cold'] if r['position']==pos and r['evaluator']==e)/s.median(r['wall_nps'] for r in baseline['records'] if r['position']==pos and r['evaluator']==e and r['mode']=='time' and r['budget']==100) for pos in {r['position'] for r in baseline['cold']}) for e in ['classical','nnue']}
profile=p.common.load(p.ROOT/'instrumented.json')['records']
out['observer_overhead']={}
for build in ['counters','timers']:
    ratios=[]
    for row in positions:
        found={b:[r for r in profile if r['position']==row['id'] and r['build']==b] for b in ['release',build]}
        ratios.append(med(found[build],'wall_seconds')/med(found['release'],'wall_seconds'))
    out['observer_overhead'][build]=describe(ratios)
timed=[r for r in profile if r['build']=='timers']
counts=[r for r in profile if r['build']=='counters']
total_nodes=sum(r['nodes'] for r in timed)
categories=timed[0]['profile']['categories']
total_ns=sum(v['ns'] for r in timed for v in r['profile']['categories'].values())
out['exclusive_clock_categories']={}
for key in categories:
    ns=sum(r['profile']['categories'][key]['ns'] for r in timed)
    calls=sum(r['profile']['categories'][key]['calls'] for r in timed)
    out['exclusive_clock_categories'][key]=dict(ns=ns,calls=calls,ns_per_call=ns/max(1,calls),percent=100*ns/total_ns,ns_per_node=ns/total_nodes)
out['clock_totals']={'ns':total_ns,'nodes':total_nodes,'allocations':sum(r['profile']['allocations'] for r in timed),'allocation_bytes':sum(r['profile']['bytes'] for r in timed)}
keys=[key for key,value in counts[0]['diagnostics'].items() if isinstance(value,int) and not key.startswith('maximum') and key not in ['frame_bytes','stack_bytes']]
d={key:sum(r['diagnostics'][key] for r in counts) for key in keys}
out['work_counts']=d
out['work_ratios']={key:d[a]/d[b] for key,a,b in [('updates_per_node','updates','visits'),('eval_calls_per_node','evaluation_calls','visits'),('qnode_fraction','qvisits','visits'),('unused_update_fraction','unused_updates','updates'),('unused_leaf_fraction','unused_leaf_updates','updates'),('mean_delta_rows','delta_rows','updates'),('logical_copy_bytes_per_update','copy_payload_bytes','updates'),('mean_pending_edges','pending_edges','evaluated_frames')]}
out['work_per_position']={r['id']:{key:counts_value for key,counts_value in next(v['diagnostics'] for v in counts if v['position']==r['id']).items()} for r in positions}
for name in ['micro','components']:
    values=p.common.load(p.ROOT/(name+'.json'))['records']
    out[name]={key:describe(v[key] for v in values) for key in values[0] if key.endswith('_ns')}
if (p.ROOT/'native-symbols.json').exists():
    data=p.common.load(p.ROOT/'native-samples.json');symbols=p.common.load(p.ROOT/'native-symbols.json')
    functions=collections.Counter();lines=collections.Counter();maintenance=0;head=0
    per_position={}
    for row in positions:
        selected=[r for r in data['records'] if r['position']==row['id']]
        if not selected:continue
        sampled=[r for r in selected if r['sampled']];plain=[r for r in selected if not r['sampled']]
        fn=collections.Counter()
        for r in sampled:
            for address,n in r['rip_counts'].items():
                v=symbols[address];functions[v['symbol']]+=n;fn[v['symbol']]+=n
                if 'line' in v:lines[(v['file'].replace('\\','/').split('/')[-1],v['line'])]+=n
                if 'nnue_side_to_move' in v['symbol']:head+=n
                if any(t in v['symbol'] for t in ['descend_nnue','nnue_update','nnue_search_states','nnue_move_delta','source/nnue.cpp','source\\nnue.cpp']):maintenance+=n
        per_position[row['id']]={'samples':fn.total(),'head_fraction':sum(n for name,n in fn.items() if 'nnue_side_to_move' in name)/fn.total(),'sampled_plain_nps_ratio':med(sampled,'wall_nps')/med(plain,'wall_nps')}
    total=functions.total()
    out['native']={'samples':total,'head_fraction':head/total,'maintenance_fraction':maintenance/total,'functions':[{'symbol':name,'samples':n,'percent':100*n/total} for name,n in functions.most_common()],'lines':[{'file':file,'line':line,'samples':n,'percent':100*n/total} for (file,line),n in lines.most_common()],'per_position':per_position,'suspension_ns':describe(v for r in data['records'] for v in r['suspension_ns']),'failures':sum(r['failed_samples'] for r in data['records'])}
    f=head/total
    out['amdahl_head']={str(speed):1/(1-f+f/speed) for speed in [1.1,1.2,1.5,2,1000000000]}
if (p.ROOT/'varying-head.json').exists():
    values=p.common.load(p.ROOT/'varying-head.json')['records']
    out['varying_head']={key:describe(v[key] for v in values) for key in values[0] if key.endswith('_ns')}
if (p.ROOT/'classical-timers.json').exists():
    values=p.common.load(p.ROOT/'classical-timers.json')['records']
    out['classical_clock_categories']={key:{field:sum(r['profile']['categories'][key][field] for r in values) for field in ['calls','ns']} for key in values[0]['profile']['categories']}
p.save('summary.json',out)
with (p.ROOT/'baseline-per-position.csv').open('w',newline='',encoding='utf-8') as f:
    rows=[{key:(v['median'] if isinstance(v,dict) else v) for key,v in r.items()} for r in out['positions']]
    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
with (p.ROOT/'component-clock-times.csv').open('w',newline='',encoding='utf-8') as f:
    writer=csv.DictWriter(f,fieldnames=['component','ns','calls','ns_per_call','percent','ns_per_node']);writer.writeheader()
    writer.writerows(dict(component=name,**value) for name,value in out['exclusive_clock_categories'].items())
print(json.dumps({key:out[key] for key in ['baseline','observer_overhead','work_ratios','native','amdahl_head'] if key in out},indent=2))
