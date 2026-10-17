"""Verify saved Stage 3 gates, preservation, provenance and full artifact inventory."""
import hashlib
import experiment as p

p.preserve()
plan=p.common.load(p.ROOT/'plan.json');a=p.common.load(p.ROOT/'analysis.json')
assert plan['baseline_commit']=='f397a5af002900bbc15a7261dc6027c48daaeff4'
assert p.common.sha(p.ART/'baseline/engine.exe')==plan['baseline_binary_sha256']
assert len(p.common.load(p.ROOT/'candidate-selection.json')['variants'])==2
assert len(p.common.load(p.ROOT/'initial-baseline.json')['records'])==180
assert p.common.load(p.ROOT/'sampling-identity.json')['engine_sha256']==plan['baseline_binary_sha256']
selection=p.common.load(p.ROOT/'candidate-source-identity.json')
assert selection['selection_sha256']==p.common.sha(p.ROOT/'candidate-selection.json')
assert selection['profile_sha256']==p.common.sha(p.ROOT/'profile-analysis.json')
initial_bits=p.common.load(p.ROOT/'baseline-edge-bits.json')
assert initial_bits['comparisons']==4352
diagnosis=p.common.load(p.ROOT/'regression-diagnosis.json')
assert diagnosis['new_searches']==0 and len(diagnosis['rows'])==7
records_total=0;exact_pairs=0


def iterations(record):
    return [{k:v for k,v in row.items() if k not in ['seconds','nps']} for row in record['iterations']]


for label,trial in a['candidates'].items():
    assert p.common.sha(p.ROOT/(label+'_head.hpp'))==selection['candidates'][label]
    assert p.common.sha(p.ART/(label+'-source')/'stage1_head.hpp')==selection['candidates'][label]
    for name in ['nnue.cpp','main.cpp','search.cpp','evaluation.cpp','nnue.hpp','nnue_v3.cpp']:
        assert p.common.sha(p.ART/(label+'-source')/name)==p.common.sha(p.ART/'baseline-source'/name)
    for target in ['engine','micro','oracle']:
        meta=p.common.load(p.ROOT/f'build-{label}-{target}.json')
        assert p.common.sha(p.ART/label/(target+'.exe'))==meta['sha256']
        assert '-ffp-contract=off' in meta['command'] and '-ffast-math' not in meta['command']
        for name,sha in meta['sources'].items():assert p.common.sha(p.ART/(label+'-source')/name)==sha
    if 'failure' in trial:
        assert trial['status']=='REJECTED'
        assert not (p.ROOT/('search-'+label+'.json')).exists()
        continue
    c=p.common.load(p.ROOT/('correctness-'+label+'.json'))
    assert c['passed'] and c['oracle']['bitwise_exact'] and c['head']['passed']
    assert c['head']['head_bit_comparisons']>=161420 and c['extra_special_heads']==4352
    assert len(c['fixed_work'])==36
    for row in c['fixed_work']:
        assert p.canonical(row['baseline'])==p.canonical(row['variant'])
        assert iterations(row['baseline'])==iterations(row['variant'])
    reg=p.common.load(p.ROOT/('regressions-'+label+'.json'))
    assert reg['passed'] and len(reg['interrupted'])==24 and len(reg['classical'])==12
    assert p.common.load(p.ROOT/('regressions-restore-'+label+'.json'))['passed']
    data=p.common.load(p.ROOT/('search-'+label+'.json'))
    index={(r['position'],r['mode'],r['budget'],r['build'],r['repeat']):r for r in data['records']}
    assert len(index)==len(data['records'])==12*5*2*trial['repeats']
    for r in data['records']:
        if r['build']==label and r['mode']=='nodes':
            b=index[(r['position'],r['mode'],r['budget'],'baseline',r['repeat'])]
            assert p.canonical(r)==p.canonical(b) and r['nodes']==r['budget']
            assert iterations(r)==iterations(b)
            exact_pairs+=1
    micro=p.common.load(p.ROOT/('micro-'+label+'.json'))['records']
    assert len(micro)==56
    assert all(r['kernel']=='clip' for r in micro)
    inspection=p.common.load(p.ROOT/('head-inspection-'+label+'.json'))
    assert inspection['engine_sha256']==p.common.sha(p.ART/label/'engine.exe')
    assert not any(k.startswith(('vfm','vfnm')) for k in inspection['mnemonics'])
    assert inspection['isa']==p.common.load(p.ROOT/'head-inspection-baseline.json')['isa']
    if trial['status']=='ACCEPTED':assert all(trial['gates'].values())
    records_total+=len(index)
report=p.REPO/'NNUE_STAGE3_OPTIMIZATION_REPORT.md'
assert report.read_text()==(p.ROOT/report.name).read_text()
out=dict(passed=True,decision=a['decision'],retained_baseline=a['retained_baseline'],
    candidates={b:r['status'] for b,r in a['candidates'].items()},primary_search_records=records_total,
    repeated_fixed_node_pairs_exact=exact_pairs,new_variants=2,
    preserved_files=p.common.load(p.ROOT/'preservation-after.json')['checked_files'],
    active_engine_unchanged=True,report_mirror_exact=True,
    note='Isolated native head/search checks; no full GUI/desktop suite, training, tournaments or promotion.')
p.save('validation.json',out)
files={}
for path in list(p.ROOT.rglob('*'))+[report]:
    if not path.is_file() or path.name=='manifest.json' or {'__pycache__','zig-cache','.zig-cache'}.intersection(path.parts):continue
    item=dict(bytes=path.stat().st_size,sha256=p.common.sha(path))
    if path.suffix in ['.md','.py','.hpp','.cpp','.json','.csv','.txt','.patch','.ps1','.s']:
        item['lf_normalized_sha256']=hashlib.sha256(path.read_bytes().replace(b'\r\n',b'\n')).hexdigest()
    files[path.relative_to(p.REPO).as_posix()]=item
p.save('manifest.json',dict(baseline_commit=plan['baseline_commit'],files=files,
    note='Local ignored EXE/PDB/source snapshots/generated headers/complete assembly retained on Z:. '
    'Text-normalized hashes survive Git LF conversion; original model/toolchain artifacts required for reproduction.'))
print(out)
