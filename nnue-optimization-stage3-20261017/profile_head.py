"""Profile the exact copied Stage 1 binary before selecting any candidate."""
import shutil
import sys
from types import SimpleNamespace
import experiment as p

assert p.common.load(p.ROOT/'baseline-head-checks.json')['head']['passed']
assert len(p.common.load(p.ROOT/'initial-baseline.json')['records'])==180
sys.path.insert(0,str(p.PROFILE))
import run_profile as previous
import sample_native as sampler

assert not (p.ROOT/'native-samples.json').exists(), 'Do not repeat completed sampling'
for name in ['engine.exe','engine.pdb']:
    shutil.copy2(p.ART/'baseline'/name,p.ART/name)
shutil.copy2(p.ART/'baseline/engine.exe',p.ART/'mapped.exe')
shutil.copy2(p.ART/'baseline/engine.pdb',p.ART/'mapped.pdb')
sampler.p=SimpleNamespace(ROOT=p.ROOT,ART=p.ART,pin=p.pin,common=p.common,save=p.save,
    open_engine=p.open_engine,checked_capture=previous.checked_capture)
sampler.run()
p.save('sampling-identity.json',dict(engine_sha256=p.common.sha(p.ART/'mapped.exe'),
    baseline_sha256=p.common.load(p.ROOT/'plan.json')['baseline_binary_sha256'],
    sampler_sha256=p.common.sha(p.PROFILE/'sample_native.py'),
    source='Exact Stage 1 clip executable, matching local PDB; four positions, three paired sampled/unsampled passes, 1500 ms.'))
