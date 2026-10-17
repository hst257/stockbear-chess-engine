"""Validate completed Stage 2.1 receipts, preservation and reproducible inventory."""
import hashlib
import json
import experiment as p

p.preserve()
plan=p.common.load(p.ROOT/'plan.json')
a=p.common.load(p.ROOT/'analysis.json')
data=p.common.load(p.ROOT/'primary.json')
keys={(r['position'],r['mode'],r['budget'],r['build'],r['repeat']) for r in data['records']}
assert len(keys)==len(data['records'])==16*5*3*a['repeats']
assert a['repeats'] in range(7,11)
assert len(p.common.load(p.ROOT/'candidate-selection.json')['new_candidates'])<=2
assert p.common.sha(p.ART/'baseline/engine.exe')==plan['baseline_binary_sha256']
assert p.common.sha(p.ART/'sort/engine.exe')==plan['stage2_sort_binary_sha256']
assert plan['options']['NNUEKernel']=='clip' and plan['options']['Hash']==16


def completed_iterations(record):
    return [{k:v for k,v in step.items() if k not in ['seconds','nps']} for step in record['iterations']]


for b in ['sort','selective']:
    c=p.common.load(p.ROOT/('correctness-'+b+'.json'))
    reg=p.common.load(p.ROOT/('regressions-'+b+'.json'))
    assert c['passed'] and c['oracle']['bitwise_exact'] and c['head']['passed']
    assert c['targeted']['digest']==c['baseline_targeted']['digest']
    assert c['sorting']['passed'] and c['sorting']['tests']==272000
    if b=='selective':assert c['sorting']['equal_key_identity_mismatches']==0
    assert len(c['fixed_work'])==48 and reg['passed'] and len(reg['interrupted'])==24
    for r in c['fixed_work']:
        assert p.canonical(r['baseline'])==p.canonical(r['variant'])
        assert completed_iterations(r['baseline'])==completed_iterations(r['variant'])
    for r in data['records']:
        if r['build']==b and r['mode']=='nodes':
            baseline=next(x for x in data['records'] if x['build']=='baseline' and x['position']==r['position'] and x['mode']==r['mode'] and x['budget']==r['budget'] and x['repeat']==r['repeat'])
            assert p.canonical(baseline)==p.canonical(r) and r['nodes']==r['budget']
            assert completed_iterations(baseline)==completed_iterations(r)
    for name in ['search.cpp','evaluation.cpp','main.cpp','nnue.hpp','nnue_v3.cpp','stage1_head.hpp']:
        assert p.common.sha(p.ART/(b+'-source')/name)==p.common.sha(p.ART/'baseline-source'/name)
    for target in ['micro','sorttest']+(['engine','oracle','head'] if b=='selective' else []):
        meta=p.common.load(p.ROOT/('build-'+b+'-'+target+'.json'))
        assert p.common.sha(p.ART/b/(target+'.exe'))==meta['sha256']
        assert '-ffp-contract=off' in meta['command'] and '-ffast-math' not in meta['command']
        for name,sha in meta['sources'].items():
            assert p.common.sha(p.ART/(b+'-source')/name)==sha,(b,target,name)
    assembly=p.common.load(p.ROOT/('assembly-audit-'+b+'.json'))
    assert assembly['identical_head_instruction_counts']
    assert all(assembly[name][kind]['fma']==0 for name in ['baseline',b] for kind in ['updater','head'])
assert p.common.load(p.ROOT/'regressions-restore-selective.json')['passed']
micro=p.common.load(p.ROOT/'micro.json')
assert len(micro['records'])==len(micro['sort_records'])==21
assert len({r['digest'] for r in micro['records']})==1
assert all(r['edge_bytes']==1872 and r['state_slot_bytes']==152 for r in micro['records'])
assert p.common.load(p.ROOT/'workload.json')['searches']==45
observer=p.common.load(p.ROOT/'build-observer-engine.json')
assert p.common.sha(p.ART/'observer/engine.exe')==observer['sha256']
for name,sha in observer['sources'].items():
    assert p.common.sha(p.ART/'observer-source'/name)==sha, name
report=p.REPO/'NNUE_STAGE2_1_OPTIMIZATION_REPORT.md'
assert report.read_text()==(p.ROOT/report.name).read_text()
out=dict(passed=True,primary_search_records=len(keys),repeats=a['repeats'],new_variants=1,
    exact_fixed_work_comparisons_per_candidate=48,sorting_tests_per_implementation=272000,
    internal_restoration_passed=True,protected_files=p.common.load(p.ROOT/'preservation-after.json')['checked_files'],
    statuses={b:v['status'] for b,v in a['candidates'].items()},active_engine_unchanged=True,
    no_tournaments_training_stage3=True,report_mirror_exact=True)
p.save('validation.json',out)
files={}
for path in list(p.ROOT.rglob('*'))+[report]:
    if not path.is_file() or path.name=='manifest.json' or {'__pycache__','zig-cache','.zig-cache'}.intersection(path.parts):continue
    entry=dict(bytes=path.stat().st_size,sha256=p.common.sha(path))
    if path.suffix in ['.md','.py','.cpp','.hpp','.json','.jsonl','.csv','.txt','.patch','.ps1','.s']:
        entry['lf_normalized_sha256']=hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    files[path.relative_to(p.REPO).as_posix()]=entry
p.save('manifest.json',dict(baseline_commit=plan['baseline_commit'],stage2_commit=plan['stage2_commit'],files=files,
    note='Binaries, generated weights, source snapshots and full assembly are local ignored artifacts. Text-normalized hashes survive Git LF conversion.'))
print(out)
