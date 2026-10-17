"""One bounded replacement measurement after benchmark-validity corrections.

Keep all superseded measurements; require per-iteration consumption and identical
fixture storage/stride for all variants. Full-search engines are never rebuilt.
"""
import json
import shutil
import experiment as p

method = p.common.load(p.ROOT/'micro-method-correction.json')
method['previous_harness_sha256'] = method['final_harness_sha256']
method['final_harness_sha256'] = p.common.sha(p.ROOT/'update_harness.cpp')
method['corpus_correction'] = 'Use a fixed 152-byte union slot for states in Edge. '
method['corpus_correction'] += 'Strategy 5 must not gain from a smaller stored benchmark corpus. Active return type remains 24 bytes.'
method['final_paired_repetitions'] = 7
method['full_search_binaries_unchanged'] = True
p.save('micro-method-correction.json',method)
for label in ['sort','fused','small']:
    path = p.ROOT/('micro-'+label+'.json')
    shutil.copy2(path,p.ROOT/('micro-'+label+'-before-padding.json'))
    p.build(label,'micro')
    check = json.loads(p.command([str(p.ART/label/'micro.exe'),'--verify'],'final-harness-parity-'+label))
    assert check['digest']==p.common.load(p.ROOT/('correctness-'+label+'.json'))['targeted']['digest']
    p.save('final-harness-parity-'+label+'.json',check)
    p.micro(label)
records = [r for label in ['sort','fused','small'] for r in p.common.load(p.ROOT/('micro-'+label+'.json'))['records']]
assert len({r['edge_bytes'] for r in records})==1
assert all(r['state_slot_bytes']==152 for r in records)
p.save('micro-validity.json',dict(passed=True,records=len(records),
       edge_bytes=records[0]['edge_bytes'],fixed_state_slot_bytes=152,
       explicit_per_iteration_memory_operands=True,harness_sha256=p.common.sha(p.ROOT/'update_harness.cpp'),
       initial_measurements_retained=True,full_searches_repeated=0))
print('Final micro footprint and consumption gates passed',flush=True)
