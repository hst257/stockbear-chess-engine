"""Summarize counter-only workload; no production timing attribution."""
import collections
import json
import statistics as s
import experiment as p

records=[json.loads(line) for line in (p.ROOT/'workload-raw.jsonl').read_text().splitlines()]
selected=[r for r in records if r['nodes']==200000]
assert len(selected)==45
aggregate=collections.defaultdict(collections.Counter)
lengths=collections.defaultdict(collections.Counter)
phases=collections.defaultdict(collections.Counter)
classes=collections.defaultdict(collections.Counter)
bins=collections.defaultdict(collections.Counter)
names=['quiet','capture','promotion','castling','en_passant','king','rights_changing_quiet','null']
for r in selected:
    for b in r['buckets']:
        kind=['state','rows'][b['type']]
        lengths[kind][b['length']]+=b['calls']
        phases[kind][['ordinary_parent','quiescence_parent'][b['phase']]]+=b['calls']
        classes[kind][names[b['kind']]]+=b['calls']
        for key in ['calls','sorted','reverse','equal','comparisons','shadow_insertion_comparisons','shadow_insertion_moves']:
            aggregate[kind][key]+=b[key]
        for i,v in enumerate(b['key_bins']):bins[kind][i]+=v
data=p.common.load(p.ROOT/'observer.json')
ratios=[]
for row in p.common.load(p.ROOT/'positions.json')+p.common.load(p.ROOT/'diagnostic-positions.json')[1:]:
    for repeat in range(3):
        pair=[r for r in data['records'] if r['position']==row['id'] and r['repeat']==repeat]
        a=next(r for r in pair if r['build']=='baseline');b=next(r for r in pair if r['build']=='observer')
        assert p.canonical(a)==p.canonical(b)
        ratios.append(b['wall_seconds']/a['wall_seconds'])
out=dict(searches=45,nodes=9000000,raw_records=len(records),warmup_records_excluded=len(records)-45,
    aggregate=aggregate,lengths=lengths,phase=phases,move_class=classes,key_bins_49_wide=bins,
    observer_elapsed_multiplier=dict(median=s.median(ratios),minimum=min(ratios),maximum=max(ratios)),
    note='Counts only, no operation timer percentages. Reference comparisons counted; insertion comparisons/shifts are a shadow model, not production instructions. '
    'Classification follows the parent search routine. Already-sorted and reverse overlap for zero/one/equal lists. Warmup excluded.')
p.save('workload.json',out)
print(json.dumps(out,indent=2))
