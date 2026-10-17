"""Reuse the bounded profiling sampler to identify the remaining hotspot.

This adapter changes only imported objects in this process. The original
profiling workspace and its result files are never written.
"""
import importlib.util
from pathlib import Path
import shutil
import sys
from types import SimpleNamespace
import experiment as p

assert p.common.load(p.ROOT/'correctness.json')['passed']
assert len(p.common.load(p.ROOT/'search.json')['records']) == 840
sys.path.insert(0, str(p.PROFILE))
import run_profile as old
import sample_native as sampler

shutil.copy2(p.ART/'variant/engine.exe', p.ART/'mapped.exe')
shutil.copy2(p.ART/'variant/engine.pdb', p.ART/'mapped.pdb')
# The PE CodeView directory names engine.pdb, even after the EXE is renamed.
# DbgHelp needs that exact local filename to match the PDB GUID.
named_pdb=p.ART/'engine.pdb'
if named_pdb.exists():assert p.common.sha(named_pdb)==p.common.sha(p.ART/'variant/engine.pdb')
else:shutil.copy2(p.ART/'variant/engine.pdb',named_pdb)
config=p.common.load(p.ROOT/'plan.json')
config['options']=dict(config['options'],NNUEKernel='clip')
p.save('config.json',config)
sampler.p=SimpleNamespace(ROOT=p.ROOT,ART=p.ART,pin=old.pin,
    common=p.common,save=p.save,open_engine=p.open_engine,checked_capture=old.checked_capture)
if '--resolve-only' in sys.argv:
    sampler.symbols(p.common.load(p.ROOT/'native-samples.json'))
else:
    sampler.run()
p.save('native-sampling-identity.json',{'engine_sha256':p.common.sha(p.ART/'mapped.exe'),
    'sampler_sha256':p.common.sha(p.PROFILE/'sample_native.py'),
    'purpose':'Coarse post-optimization hotspot estimate; same bounded four-position sampling method as profiling phase, not a matched historical share comparison or hardware counters'})
