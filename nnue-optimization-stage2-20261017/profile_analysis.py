"""Summarize fresh Stage 1 clip observers, including observer perturbation."""
import statistics as s
import experiment as p

records = p.common.load(p.ROOT / 'instrumented.json')['records']
assert len(records) == 108
timed = [r for r in records if r['build'] == 'timers']
counts = [r for r in records if r['build'] == 'counters']
updates = sum(r['diagnostics']['updates'] for r in timed)
nodes = sum(r['nodes'] for r in timed)
ns = sum(v['ns'] for r in timed for v in r['profile']['categories'].values())
out = {'observer_overhead': {}, 'categories': {}, 'nodes': nodes, 'updates': updates,
       'warning': 'Exclusive clock times are perturbed by per-scope steady_clock calls; '
       'do not interpret them as exact production latency or add them to native shares.'}
for label in ['counters', 'timers']:
    ratios = []
    for row in p.common.load(p.ROOT / 'positions.json'):
        group = [r for r in records if r['position'] == row['id']]
        ratios.append(s.median(r['wall_seconds'] for r in group if r['build'] == label) /
                      s.median(r['wall_seconds'] for r in group if r['build'] == 'baseline'))
    out['observer_overhead'][label] = {'median_elapsed_ratio': s.median(ratios),
                                      'min': min(ratios), 'max': max(ratios)}
for name in timed[0]['profile']['categories']:
    duration = sum(r['profile']['categories'][name]['ns'] for r in timed)
    calls = sum(r['profile']['categories'][name]['calls'] for r in timed)
    out['categories'][name] = dict(ns=duration, calls=calls, percent=100*duration/ns,
         ns_per_call=duration/max(1,calls), ns_per_update=duration/updates, ns_per_node=duration/nodes)
keys = [k for k,v in counts[0]['diagnostics'].items() if isinstance(v,int)
        and not k.startswith('maximum') and k not in ['frame_bytes', 'stack_bytes']]
out['counts'] = {k: sum(r['diagnostics'][k] for r in counts) for k in keys}
d = out['counts']
out['ratios'] = dict(updates_per_node=d['updates']/nodes, rows_per_perspective=d['delta_rows']/d['updates'],
     logical_bytes_per_copy=d['copy_payload_bytes']/d['copies'], null_fraction=d['null_updates']/d['updates'])
assert all(r['diagnostics']['refreshes'] == 1 for r in counts)
out['frame_bytes'] = counts[0]['diagnostics']['frame_bytes']
out['stack_bytes'] = counts[0]['diagnostics']['stack_bytes']
out['allocations'] = sum(r['profile']['allocations'] for r in timed)
out['allocation_bytes'] = sum(r['profile']['bytes'] for r in timed)
p.save('maintenance-profile.json', out)
print({k:out[k] for k in ['observer_overhead','ratios','frame_bytes','stack_bytes']})
for k,v in out['categories'].items():
    if k.startswith('nnue_'):
        print(k,v)
