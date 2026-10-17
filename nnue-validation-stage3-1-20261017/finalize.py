"""Final immutable-plan, dataset consistency and preservation audit; no searches."""
import csv
import hashlib
import math
import platform
import subprocess
import validate as v


def main():
    plan=v.check_plan()
    assert v.snapshot()==v.load('preservation-before.json')
    pairs=v.read_lines('pairs.jsonl')
    raw=v.load('raw-searches.json')['records']
    assert len(raw)==len(pairs)*2==plan['expected_searches']
    assert len({p['pair_id'] for p in pairs})==len(pairs)
    assert {p['pair_id'] for p in pairs}=={f'{b["block_id"]}:{i}' for b in v.load('schedule.json') for i,_ in enumerate(b['pairs'])}
    identities=v.load('binary-identities.json')['files']
    for r in raw:
        assert r['binary_sha256']==identities[v.BINARIES[r['binary']].relative_to(v.REPO).as_posix()]
        assert r['wall_seconds']>0 and r['process_cpu_seconds']>=0
        assert math.isclose(r['wall_nps'],r['nodes']/r['wall_seconds'],rel_tol=1e-14)
    with (v.ROOT/'raw-searches.csv').open(newline='',encoding='utf-8') as f:
        assert sum(1 for _ in csv.DictReader(f))==len(raw)
    assert v.load('correctness.json')['passed'] and v.load('preservation-after.json')['passed']
    assert v.common.sha(v.ROOT/'NNUE_STAGE3_1_VALIDATION_REPORT.md')==v.common.sha(v.REPO/'NNUE_STAGE3_1_VALIDATION_REPORT.md')
    changed=subprocess.check_output(['git','diff','--name-only'],cwd=v.REPO,text=True).splitlines()
    assert all(x.startswith(v.ROOT.name+'/') or x=='NNUE_STAGE3_1_VALIDATION_REPORT.md' for x in changed),changed
    v.save('validation.json',dict(passed=True,timestamp=v.stamp(),searches=len(raw),
        unique_pairs=len(pairs),blocks=len(v.read_lines('blocks.jsonl')),protected_files=len(v.snapshot()),
        plan_sha256=v.common.sha(v.ROOT/'validation-plan.json'),discarded=v.read_lines('discarded.jsonl'),
        baseline_model_and_binaries_exact=True,production_unchanged=True,
        python=platform.python_version(),platform=platform.platform()))
    files={}
    for path in sorted(v.ROOT.rglob('*'))+[v.REPO/'NNUE_STAGE3_1_VALIDATION_REPORT.md']:
        if not path.is_file() or '__pycache__' in path.parts or path.name=='manifest.json':
            continue
        data=path.read_bytes()
        entry=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        if path.suffix in ['.json','.jsonl','.csv','.py','.ps1','.md'] or path.name=='.gitattributes':
            entry['lf_normalized_sha256']=hashlib.sha256(data.replace(b'\r\n',b'\n')).hexdigest()
        files[path.relative_to(v.REPO).as_posix()]=entry
    v.save('manifest.json',dict(timestamp=v.stamp(),files=files,original_stage3_manifest_sha256=v.load('binary-identities.json')['manifest_sha256'],
                              exact_binary_files=v.load('binary-identities.json')['files']))
    print(f'Final audit passed: {len(raw)} searches, {len(v.snapshot())} protected files, {len(files)} delivery artifacts')


if __name__=='__main__':
    main()
