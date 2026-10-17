"""Final preservation, exact-work, provenance and artifact inventory checks."""
import hashlib
import sys
import experiment as p

label = sys.argv[1]
p.preserve()
plan = p.common.load(p.ROOT/'plan.json')
a = p.common.load(p.ROOT/('analysis-'+label+'.json'))
assert plan['options']['NNUEKernel']=='clip' and plan['options']['Hash']==16
assert p.common.sha(p.ART/'baseline/engine.exe')==plan['baseline_binary_sha256']
assert p.common.sha(p.ART/label/'engine.exe')==p.common.load(p.ROOT/('build-'+label+'-engine.json'))['sha256']
for name in ['search.cpp','evaluation.cpp','main.cpp','nnue.hpp','nnue_v3.cpp','stage1_head.hpp']:
    assert p.common.sha(p.ART/(label+'-source')/name)==p.common.sha(p.ART/'baseline-source'/name),name
assert p.common.sha(p.ART/'baseline-source/stage1_head.hpp')==p.common.sha(p.OLD/'stage1_head.hpp')
c = p.common.load(p.ROOT/('correctness-'+label+'.json'))
assert c['passed'] and c['oracle']['bitwise_exact'] and c['head']['passed']
assert len(c['fixed_work'])==36 and c['targeted']['digest']==c['baseline_targeted']['digest']
reg = p.common.load(p.ROOT/('regressions-'+label+'.json'))
assert reg['passed'] and len(reg['interrupted'])==24 and len(reg['classical'])==12
for r in c['fixed_work']:
    assert p.canonical(r['baseline'])==p.canonical(r['variant'])
    # Completed iteration snapshots must also match except elapsed time/NPS.
    clean = lambda v: [{k:x for k,x in step.items() if k not in ['seconds','nps']} for step in v['iterations']]
    assert clean(r['baseline'])==clean(r['variant'])
data = p.common.load(p.ROOT/('search-'+label+'.json'))
records = data['records']
assert len(records)==12*5*2*p.repeats(label)
keys = {(r['position'],r['mode'],r['budget'],r['build'],r['repeat']):r for r in records}
assert len(keys)==len(records), 'Duplicate searches'
fixed_pairs = 0
for r in records:
    if r['build']=='baseline' and r['mode']=='nodes':
        v = keys[(r['position'],r['mode'],r['budget'],label,r['repeat'])]
        assert p.canonical(r)==p.canonical(v)
        assert r['nodes']==v['nodes']==r['budget']
        fixed_pairs += 1
assert a['search_records']==len(records)
assert len(a['per_position'])==60 and len(a['search'])==5
trials = {}
for name in ['sort','fused','small']:
    found = p.ROOT/('analysis-'+name+'.json')
    if not found.exists():
        continue
    trial = p.common.load(found)
    receipt = p.common.load(p.ROOT/('build-'+name+'-engine.json'))
    assert p.common.sha(p.ART/name/'engine.exe')==receipt['sha256']
    assert '-ffp-contract=off' in receipt['command']
    assert not any(flag.startswith('-ffast-math') for flag in receipt['command'])
    for source, digest in receipt['sources'].items():
        assert p.common.sha(p.ART/(name+'-source')/source)==digest, (name,source)
    raw = p.common.load(p.ROOT/('search-'+name+'.json'))['records']
    indexed = {(r['position'],r['mode'],r['budget'],r['build'],r['repeat']):r for r in raw}
    assert len(indexed)==len(raw)==12*5*2*p.repeats(name)
    assert p.common.load(p.ROOT/('correctness-'+name+'.json'))['passed']
    assert p.common.load(p.ROOT/('regressions-'+name+'.json'))['passed']
    assert p.common.load(p.ROOT/('final-harness-parity-'+name+'.json'))['passed']
    candidate_micro = p.common.load(p.ROOT/('micro-'+name+'.json'))['records']
    assert len(candidate_micro)==14 and len({r['digest'] for r in candidate_micro})==1
    for r in raw:
        if r['build']=='baseline' and r['mode']=='nodes':
            assert p.canonical(r)==p.canonical(indexed[(r['position'],r['mode'],r['budget'],name,r['repeat'])])
    if trial['status']=='ACCEPTED':
        assert all(r['grouped_bootstrap95'][0]>1 for r in trial['search'])
        assert not trial['material_regressions']
    trials[name]=dict(status=trial['status'],repeats=p.repeats(name),records=len(raw))
micro = p.common.load(p.ROOT/('micro-'+label+'.json'))['records']
assert len(micro)==14 and len({r['digest'] for r in micro})==1
valid_micro = p.common.load(p.ROOT/'micro-validity.json')
assert valid_micro['passed'] and valid_micro['harness_sha256']==p.common.sha(p.ROOT/'update_harness.cpp')
for b in ['baseline',label]:
    assert len([r for r in micro if r['build']==b])==7
    assert all(len(r['cases'])==10 for r in micro)
assembly = p.common.load(p.ROOT/('assembly-audit-'+label+'.json'))
assert assembly['identical_head_instruction_counts']
for b in ['baseline',label]:
    assert assembly[b]['updater']['fma']==assembly[b]['head']['fma']==0
restore = p.common.load(p.ROOT/'regressions-restore-sort.json')
assert restore['passed'] and len(restore['interrupted'])==24 and len(restore['classical'])==12
legacy = p.common.load(p.ROOT/'legacy-compatibility.json')
assert legacy['passed'] and '147 passed, 13 deselected' in legacy['summary']
assert p.common.sha(p.Path(legacy['binary']))==legacy['binary_sha256']
gap = p.common.load(p.ROOT/'classical-gap.json')
gap_keys = {(r['position'],r['repeat'],r['build']) for r in gap['records']}
assert len(gap_keys)==len(gap['records'])==12*3*3
assert all(r['mode']=='time' and r['budget']==1000 for r in gap['records'])
assert gap['summary']['secondary_direct_speedup_joint_grouped95'][0]<1
assert gap['summary']['secondary_direct_speedup_joint_grouped95'][1]>1
report = p.REPO/'NNUE_STAGE2_OPTIMIZATION_REPORT.md'
mirror = p.ROOT/report.name
assert report.read_text()==mirror.read_text()
assert a['status'] in report.read_text()
out = dict(passed=True,protected_files=p.common.load(p.ROOT/'preservation-after.json')['checked_files'],
           primary_records=len(records),unique_primary_keys=len(keys),fixed_node_pairs_exact=fixed_pairs,
           initial_fixed_work_comparisons=len(c['fixed_work']),micro_records=len(micro),status=a['status'],
           independent_trials=trials,total_primary_search_records=sum(v['records'] for v in trials.values()),
           internal_restoration_observer_passed=True,legacy_pytest_passed=147,
           legacy_pytest_deselected=13,secondary_classical_records=len(gap_keys),
           retained_baseline='Stage 1' if not any(v['status']=='ACCEPTED' for v in trials.values()) else label,
           report_mirror_lf_exact=True,active_engine_unchanged=True,
           note='No new GUI/full pytest suite; isolated native correctness and search gates above.')
p.save('validation.json',out)
files = {}
for path in p.ROOT.rglob('*'):
    if not path.is_file() or {'__pycache__','zig-cache','.zig-cache'}.intersection(path.parts) or path.name=='manifest.json':
        continue
    key = path.relative_to(p.REPO).as_posix()
    item = dict(bytes=path.stat().st_size,sha256=p.common.sha(path))
    if path.suffix in ['.md','.py','.hpp','.cpp','.json','.csv','.txt','.patch','.ps1','.s']:
        item['lf_normalized_sha256']=hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    files[key]=item
files[report.name]=dict(bytes=report.stat().st_size,sha256=p.common.sha(report),
    lf_normalized_sha256=hashlib.sha256(report.read_bytes().replace(b'\r\n',b'\n')).hexdigest())
p.save('manifest.json',dict(baseline_commit=plan['baseline_commit'],candidate=label,files=files,
    note='Ignored local artifacts include EXE/PDB/generated headers/source snapshots/full assembly. '
    'Text normalized hashes survive Git LF conversion; binaries use raw hashes. Reproduction requires the preserved local model/toolchain.'))
print(out,flush=True)
