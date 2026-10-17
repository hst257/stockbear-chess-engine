"""Validate frozen work, source boundaries and the completed experiment inventory."""
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import experiment as p

p.preserve()
correctness=p.common.load(p.ROOT/'correctness.json')
assert correctness['passed'] and correctness['head_parity']['head_bit_comparisons']>=160000
assert len(correctness['fixed_work'])==24
assert p.common.load(p.ROOT/'regressions.json')['passed']
for name in ['baseline_transition_oracle','variant_transition_oracle']:
    assert correctness[name]=={'transitions':31876,'nulls':26908,'bitwise_exact':True}
for path in (p.ART/'baseline-source').glob('*'):
    assert p.common.sha(path)==p.common.sha(p.REPO/'engine/src'/path.name),path
changed=[]
for path in (p.ART/'variant-source').glob('*'):
    original=p.ART/'baseline-source'/path.name
    if not original.exists() or p.common.sha(path)!=p.common.sha(original):changed.append(path.name)
assert set(changed)=={'nnue.cpp','main.cpp','stage1_head.hpp'},changed
for label in ['baseline','variant']:
    for target in ['engine','micro','oracle']:
        meta=p.common.load(p.ROOT/f'build-{label}-{target}.json')
        assert p.common.sha(p.ART/label/(target+'.exe'))==meta['sha256']
        assert '-ffp-contract=off' in meta['command']
        assert not any(flag in meta['command'] for flag in ['-ffast-math','-fassociative-math','-Ofast'])
        if label=='variant':assert p.common.sha(p.ROOT/'stage1_head.hpp')==meta['head_sha256']
        for name,expected in meta['source_sha256'].items():
            path=p.ROOT/name if name=='head_harness.cpp' else p.REPO/'engine/tests'/name if name=='benchmark_nnue.cpp' else p.ART/(label+'-source')/name
            assert p.common.sha(path)==expected,path
assert p.common.sha(p.ART/'variant-source/stage1_head.hpp')==p.common.sha(p.ROOT/'stage1_head.hpp')
data=p.common.load(p.ROOT/'search.json')
assert len(data['records'])==840 and len(data['environment_segments'])==84
for row in p.common.load(p.ROOT/'positions.json'):
    for mode,budget in [('nodes',200000),('nodes',1000000)]:
        group=[r for r in data['records'] if r['position']==row['id'] and r['mode']==mode and r['budget']==budget]
        assert len(group)==14
        assert all(r['nodes']==budget and p.canonical(r)==p.canonical(group[0]) for r in group)
micro=p.common.load(p.ROOT/'micro.json')
assert len(micro['records'])==56 and len(micro['fen_records'])==168
assert len(p.common.load(p.ROOT/'analysis.json')['search'])==5
assert p.common.load(p.ROOT/'assembly-audit.json')['avx2_codegen_enabled']
assert '147 passed' in (p.ROOT/'pytest.log').read_text()
native=p.common.load(p.ROOT/'native-samples.json')
assert len(native['records'])==24
assert all(v['symbol']!='mapped.exe!unresolved' for v in p.common.load(p.ROOT/'native-symbols.json').values())
assert p.common.load(p.ROOT/'native-sampling-identity.json')['engine_sha256']==p.common.sha(p.ART/'variant/engine.exe')
for envname in ['environment-before.json','environment-after.json']:
    env=p.common.load(p.ROOT/envname)
    assert env['battery']['PowerOnline']
root_report=p.REPO/'NNUE_STAGE1_OPTIMIZATION_REPORT.md'
assert root_report.read_bytes().replace(b'\r\n',b'\n')==(p.ROOT/root_report.name).read_bytes().replace(b'\r\n',b'\n')
save_data={'passed':True,'protected_files':len(p.common.load(p.ROOT/'preservation-before.json')),
    'production_sources_changed':[],'experimental_source_changes':changed,
    'head_bit_comparisons':correctness['head_parity']['head_bit_comparisons'],
    'fixed_work_preflight_groups':24,'full_search_records':840,'fixed_node_benchmark_pairs':168,
    'micro_working_set_records':56,'micro_fen_records':168,
    'active_engine_promoted':False,'tournaments':0,'training':False,'sealed_test_access':False}
p.save('validation.json',save_data)
inventory=[]
for path in sorted(p.ROOT.rglob('*')):
    if not path.is_file() or {'zig-cache','__pycache__','pytest-temp'}.intersection(path.parts) or path.name=='manifest.json':continue
    if path.suffix.lower() in ['.obj','.o','.lib','.tmp']:continue
    raw=path.read_bytes();record={'path':path.relative_to(p.ROOT).as_posix(),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    if path.suffix.lower() in ['.py','.cpp','.hpp','.json','.txt','.log','.md','.csv','.s','.patch','.ps1']:
        record['lf_normalized_sha256']=hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()
    inventory.append(record)
p.save('manifest.json',{'created_utc':datetime.now(timezone.utc).isoformat(),
    'note':'Local profiling/optimization artifacts only. Compiler cache, bytecode, pytest temp and compiler objects/libraries excluded. Raw hashes describe local bytes; LF hashes allow Git text normalization. No dataset inventory.',
    'network_sha256':p.common.load(p.ROOT/'plan.json')['network_sha256'],
    'report_sha256':p.common.sha(root_report),
    'report_lf_normalized_sha256':hashlib.sha256(root_report.read_bytes().replace(b'\r\n',b'\n')).hexdigest(),
    'files':inventory})
print('All Stage 1 integrity checks passed; inventoried files:',len(inventory))
