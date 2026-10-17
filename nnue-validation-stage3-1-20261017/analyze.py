"""Read-only analysis of the frozen Stage 3.1 observations; no engine execution."""
from __future__ import annotations

import collections
import csv
import datetime as dt
import json
import math
import os
import random
import statistics as s

import validate as v


def quantile(xs, p):
    xs = sorted(xs)
    at = (len(xs) - 1) * p
    lo = int(at)
    hi = min(len(xs) - 1, lo + 1)
    return xs[lo] + (xs[hi] - xs[lo]) * (at - lo)


def describe(xs):
    xs = [x for x in xs if x is not None and math.isfinite(x)]
    return dict(median=s.median(xs), minimum=min(xs), maximum=max(xs),
                q1=quantile(xs, .25), q3=quantile(xs, .75)) if xs else None


def factor(groups):
    return math.exp(s.mean(s.median(g) for g in groups))


def interval(groups, draws=10000, dependence=False):
    rng = random.Random(2026101731)
    values = []
    size = len(groups[0])
    for _ in range(draws):
        if dependence:
            # Whole repeat rounds shared across fixtures preserve common temporal shocks.
            indices = []
            while len(indices) < size:
                start = rng.randrange(size)
                indices.extend([start, (start + 1) % size])
            indices = indices[:size]
            sampled = [[g[i] for i in indices] for g in rng.choices(groups, k=len(groups))]
        else:
            sampled = [rng.choices(g, k=len(g)) for g in rng.choices(groups, k=len(groups))]
        values.append(factor(sampled))
    return [quantile(values, .025), quantile(values, .975)]


def correlation(xs, ys):
    if len(xs) < 3 or s.pstdev(xs) == 0 or s.pstdev(ys) == 0:
        return None
    return s.correlation(xs, ys)


def main():
    plan = v.check_plan()
    pairs = v.read_lines('pairs.jsonl')
    assert len(pairs) * 2 == plan['expected_searches']
    assert len({p['pair_id'] for p in pairs}) == len(pairs)
    blocks = v.read_lines('blocks.jsonl')
    by_block = {b['block_id']: b for b in blocks}
    assert len(by_block) == len(v.load('schedule.json'))
    assert all(b['power_valid'] for b in blocks)
    paired = []
    records = []
    work_count = 0
    expected_pairs = {}
    for b in v.load('schedule.json'):
        for i, pair in enumerate(b['pairs']):
            expected_pairs[f'{b["block_id"]}:{i}'] = (b, pair)
    for pair in pairs:
        rows = {r['binary']: r for r in pair['records']}
        a, b = rows['baseline'], rows['hiddenclip']
        block, scheduled = expected_pairs[pair['pair_id']]
        for r in rows.values():
            assert (r['suite'], r['position'], r['repeat'], r['mode'], r['budget'], r['order']) == (
                block['suite'], block['position'], block['repeat'], scheduled['mode'], scheduled['budget'], scheduled['order'])
            assert r['affinity_mask'] == 1
        if a['mode'] == 'nodes':
            v.work_equal(a, b)
            assert a['nodes'] == b['nodes'] == a['budget']
            work_count += 1
        ratio = b['wall_nps'] / a['wall_nps']
        cpu_ratio = b['cpu_nps'] / a['cpu_nps'] if a['cpu_nps'] and b['cpu_nps'] else None
        paired.append(dict(pair_id=pair['pair_id'], suite=a['suite'], position=a['position'],
                           mode=a['mode'], budget=a['budget'], repeat=a['repeat'],
                           order=a['order'][0], block_id=a['block_id'], factor=ratio,
                           inverse_wall_factor=a['wall_seconds'] / b['wall_seconds'],
                           cpu_factor=cpu_ratio, log_ratio=math.log(ratio),
                           background_difference=b['background']['other_cpu_percent_estimate'] - a['background']['other_cpu_percent_estimate'],
                           baseline_cpu_wall=a['process_cpu_seconds'] / a['wall_seconds'],
                           candidate_cpu_wall=b['process_cpu_seconds'] / b['wall_seconds'],
                           flagged=by_block[a['block_id']]['flagged_background']))
        records.extend(pair['records'])
    cpu0 = v.read_lines('cpu0-counters.jsonl')
    cpu0_valid = [r for r in cpu0 if r.get('counter') and not r.get('error')]
    parsed_counter = [(dt.datetime.fromisoformat(r['timestamp_utc']),r) for r in cpu0_valid]
    for r in records:
        when = dt.datetime.fromisoformat(r['timestamp'])
        nearby = min(parsed_counter,key=lambda t:abs((t[0]-when).total_seconds())) if parsed_counter else None
        delta = (nearby[0]-when).total_seconds() if nearby else None
        r['cpu0_counter_snapshot'] = dict(offset_seconds=delta, sample=nearby[1],
            caveat='Nearest Windows provider snapshot within 10 seconds; not calibrated effective MHz or per-search frequency') if nearby and abs(delta)<=10 else None
    out = dict(method=plan['statistic'], uncertainty=plan['uncertainty'],
               historical_results_not_pooled=True, search_count=len(records), fixed_work_pairs=work_count,
               summaries=[], per_position=[], material_medians=[], unresolved=[], established=[],
               environment=dict(block_count=len(blocks),
                   flagged_blocks=sum(b['flagged_background'] for b in blocks),
                   flag_fraction=s.mean(b['flagged_background'] for b in blocks),
                   all_ac_and_plan_checks_pass=True, pauses=sum(x['event'] == 'background_pause' for x in v.read_lines('events.jsonl')),
                   background=describe(r['background']['other_cpu_percent_estimate'] for r in records),
                   cpu_wall_by_binary={name: describe(r['process_cpu_seconds']/r['wall_seconds'] for r in records if r['binary']==name)
                                       for name in ['baseline','hiddenclip']},
                   elapsed_seconds=v.load('progress.json')['elapsed_seconds']))
    out['environment']['cpu0_telemetry'] = dict(samples=len(cpu0_valid), errors=sum('error' in r for r in cpu0),
        search_records_with_nearby_snapshot=sum(r['cpu0_counter_snapshot'] is not None for r in records),
        query_seconds=describe(r.get('query_seconds') for r in cpu0_valid),
        reported_values={field:describe(r['counter'].get(field) for r in cpu0_valid) for field in
            ['ProcessorFrequency','PercentProcessorPerformance','PercentPerformanceLimit','PerformanceLimitFlags']},
        limitation='Counter sampling began partway through collection; no independent effective-MHz calibration or temperature measurement. Do not interpret nominal ProcessorFrequency as effective search frequency.')
    if parsed_counter:
        began=min(t for t,_ in parsed_counter)
        out['environment']['before_after_counter_start']={}
        for label, selected in [('before',[b for b in blocks if dt.datetime.fromisoformat(b['before']['timestamp'])<began]),
                                ('after',[b for b in blocks if dt.datetime.fromisoformat(b['before']['timestamp'])>=began])]:
            out['environment']['before_after_counter_start'][label]=dict(blocks=len(selected),flagged_fraction=s.mean(b['flagged_background'] for b in selected) if selected else None)
    grouped = collections.defaultdict(list)
    for p in paired:
        grouped[(p['suite'], p['mode'], p['budget'], p['position'])].append(p)
    for (suite, mode, budget, position), ps in sorted(grouped.items()):
        ps.sort(key=lambda x: x['repeat'])
        logs = [p['log_ratio'] for p in ps]
        orders = {name: math.exp(s.median(p['log_ratio'] for p in ps if p['order']==name))
                  for name in ['baseline','hiddenclip']}
        assert len(ps) == (10 if suite=='general' else 12)
        assert sum(p['order']=='baseline' for p in ps) == len(ps)//2
        result = dict(suite=suite, mode=mode, budget=budget, position=position, pairs=len(ps),
                      factor=factor([logs]), repeat95=interval([logs]), order_medians=orders,
                      ratios=[p['factor'] for p in ps], cpu_factor=math.exp(s.median(math.log(p['cpu_factor']) for p in ps if p['cpu_factor'])),
                      inverse_wall_factor=math.exp(s.median(math.log(p['inverse_wall_factor']) for p in ps)),
                      cpu_wall_baseline=describe(p['baseline_cpu_wall'] for p in ps),
                      cpu_wall_candidate=describe(p['candidate_cpu_wall'] for p in ps),
                      first_half=factor([logs[:len(logs)//2]]), second_half=factor([logs[len(logs)//2:]]),
                      lag1_log_ratio_correlation=correlation(logs[:-1], logs[1:]),
                      load_difference_log_ratio_correlation=correlation([p['background_difference'] for p in ps], logs))
        subset = [r for r in records if r['suite']==suite and r['position']==position and r['mode']==mode and r['budget']==budget]
        result['records_summary'] = {}
        for name in ['baseline','hiddenclip']:
            rs = [r for r in subset if r['binary']==name]
            result['records_summary'][name] = {key: describe(r[key] for r in rs) for key in
                ['wall_seconds','seconds','process_cpu_seconds','wall_nps','nodes','depth','seldepth']}
            result['records_summary'][name].update(
                eval_calls=describe(r['counters'].get('eval_calls') for r in rs),
                qnodes=describe(r['counters'].get('qnodes') for r in rs),
                repeat_wall_nps_cv=s.stdev(r['wall_nps'] for r in rs)/s.mean(r['wall_nps'] for r in rs))
        out['per_position'].append(result)
    for suite in ['general','endgame','sentinel']:
        for mode, budget in v.CONTROLS:
            if suite=='general' and (mode,budget)==('time',200):
                continue
            ps = [p for p in paired if (p['suite'],p['mode'],p['budget'])==(suite,mode,budget)]
            positions = sorted({p['position'] for p in ps})
            groups = [[p['log_ratio'] for p in sorted(ps,key=lambda x:x['repeat']) if p['position']==position] for position in positions]
            def subset_factor(predicate):
                selected = [[p['log_ratio'] for p in ps if p['position']==position and predicate(p)] for position in positions]
                return factor([g for g in selected if g]) if any(selected) else None
            cpu_groups = [[math.log(p['cpu_factor']) for p in ps if p['position']==position and p['cpu_factor']] for position in positions]
            round_factors = [subset_factor(lambda p, r=r: p['repeat']==r) for r in range(10 if suite=='general' else 12)]
            cpu_diag = factor([g for g in cpu_groups if g])
            result = dict(suite=suite, mode=mode, budget=budget, positions=len(groups), pairs=len(ps),
                          factor=factor(groups), ci95=interval(groups), ci_type='repeat-only' if suite=='sentinel' else 'position-grouped hierarchical',
                          circular_length2_ci95=interval(groups, dependence=True),
                          order={name:subset_factor(lambda p, name=name:p['order']==name) for name in ['baseline','hiddenclip']},
                          stable_block_factor=subset_factor(lambda p:not p['flagged']),
                          stable_block_pairs=sum(not p['flagged'] for p in ps), cpu_factor=cpu_diag,
                          stable_block_positions=sum(any(p['position']==position and not p['flagged'] for p in ps) for position in positions),
                          inverse_wall_factor=math.exp(s.mean(s.median(math.log(p['inverse_wall_factor']) for p in ps if p['position']==position) for position in positions)),
                          first_half=subset_factor(lambda p:p['repeat'] < (5 if suite=='general' else 6)),
                          second_half=subset_factor(lambda p:p['repeat'] >= (5 if suite=='general' else 6)),
                          round_factors=round_factors,
                          lag1_round_log_ratio_correlation=correlation([math.log(x) for x in round_factors[:-1]],[math.log(x) for x in round_factors[1:]]),
                          background_difference_log_ratio_correlation=correlation([p['background_difference'] for p in ps],[p['log_ratio'] for p in ps]))
            if suite!='sentinel':
                result['leave_one_position_out_range'] = [min(factor(groups[:i]+groups[i+1:]) for i in range(len(groups))),
                                                          max(factor(groups[:i]+groups[i+1:]) for i in range(len(groups)))]
            # Baseline throughput drift normalizes each position by its full-study median.
            normalized = []
            for repeat in range(10 if suite=='general' else 12):
                terms = []
                for position in positions:
                    rs = [r for r in records if (r['suite'],r['position'],r['mode'],r['budget'],r['binary'])==(suite,position,mode,budget,'baseline')]
                    current = next(r for r in rs if r['repeat']==repeat)
                    terms.append(math.log(current['wall_nps']/s.median(r['wall_nps'] for r in rs)))
                normalized.append(math.exp(s.mean(terms)))
            result['normalized_baseline_round_nps'] = normalized
            out['summaries'].append(result)
            print(suite, mode, budget, round(result['factor'],5), [round(x,5) for x in result['ci95']], flush=True)
    threshold = plan['material_factor']
    for r in out['per_position']:
        if r['factor'] >= threshold:
            continue
        entry = {k:r[k] for k in ['suite','position','mode','budget','factor','repeat95','order_medians']}
        entry['equivalent_elapsed_percent'] = 100*(1/r['factor']-1)
        same = [x for x in out['per_position'] if (x['suite'],x['position'])==(r['suite'],r['position'])]
        corroborates = any(x['factor']<threshold and (x['mode'],x['budget'])!=(r['mode'],r['budget']) for x in same)
        long_positive = all(next(x['factor'] for x in same if (x['mode'],x['budget'])==control)>1
                            for control in [('nodes',1000000),('time',1000)])
        if r['repeat95'][1]<threshold:
            entry['classification']='established material regression (unadjusted repeat interval)'
            out['established'].append(entry)
        elif r['repeat95'][1]<1 or (all(x<threshold for x in r['order_medians'].values()) and corroborates) or not (
                r['mode']=='time' and r['budget']<=200 and r['repeat95'][1]>=1 and long_positive and not corroborates):
            entry['classification']='unresolved concerning median'
            out['unresolved'].append(entry)
        else:
            entry['classification']='isolated noisy short-time median; no repeat/neighbor-control establishment'
        out['material_medians'].append(entry)
    lookup = {(x['suite'],x['mode'],x['budget']):x for x in out['summaries']}
    long = [lookup[('general',*control)] for control in [('nodes',1000000),('time',1000)]]
    eg = lookup[('endgame','time',100)]
    gates = dict(exact_identities=True, fixed_work_exact=True,
                 general_long_gain=all(x['ci95'][0]>1 for x in long),
                 general_other_no_convincing_loss=all(x['ci95'][1]>=1 for x in out['summaries'] if x['suite']=='general'),
                 long_orders_positive=all(all(y>1 for y in x['order'].values()) for x in long),
                 endgame100_noninferior=eg['ci95'][0]>threshold,
                 endgame100_no_convincing_loss=eg['ci95'][1]>=1,
                 no_established_material_loss=not out['established'] and eg['ci95'][1]>=threshold,
                 no_unresolved_material=not out['unresolved'],
                 environmental_flags_within_budget=out['environment']['flag_fraction']<=.25,
                 long_dependence_gain=all(x['circular_length2_ci95'][0]>1 for x in long),
                 long_stable_gain=all(x['stable_block_factor'] and x['stable_block_factor']>1 for x in long),
                 long_early_late_gain=all(x['first_half']>1 and x['second_half']>1 for x in long),
                 cpu_does_not_contradict=all(x['cpu_factor']>1 for x in long))
    out['gates']=gates
    if not gates['no_established_material_loss'] or all(x['ci95'][1]<=1 for x in long):
        out['decision']='REJECTED'
    elif all(gates.values()):
        out['decision']='ACCEPTED'
    else:
        out['decision']='INCONCLUSIVE'
    v.save('analysis.json',out)
    v.save('paired-analysis.json',paired)
    target=v.ROOT/'raw-searches.json'
    temporary=target.with_suffix('.tmp')
    temporary.write_text(json.dumps(dict(records=records),allow_nan=False,separators=(',',':')),encoding='utf-8')
    os.replace(temporary,target)
    fields=['pair_id','block_id','suite','position','mode','budget','repeat','binary','binary_sha256','order_index',
            'timestamp','wall_seconds','seconds','process_cpu_seconds','wall_nps','cpu_nps','nodes','depth','seldepth','move',
            'score_white','pv','counters','iterations','background','cpu0_counter_snapshot']
    with (v.ROOT/'raw-searches.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        for r in records:
            writer.writerow({k:json.dumps(r[k],sort_keys=True) if isinstance(r.get(k),(dict,list)) else r.get(k) for k in fields})
    fields=['suite','position','mode','budget','pairs','factor','repeat95','cpu_factor','inverse_wall_factor','order_medians','first_half','second_half']
    with (v.ROOT/'per-position.csv').open('w',newline='',encoding='utf-8') as f:
        writer=csv.DictWriter(f,fieldnames=fields)
        writer.writeheader()
        for r in out['per_position']:
            writer.writerow({k:json.dumps(r[k],sort_keys=True) if isinstance(r.get(k),(dict,list)) else r.get(k) for k in fields})
    print(out['decision'],gates,flush=True)


if __name__=='__main__':
    main()
