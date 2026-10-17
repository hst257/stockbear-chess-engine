"""Bounded own-child native sampler, reusing the frozen profiling implementation."""
import shutil
import sys
from types import SimpleNamespace
import experiment as p

label = sys.argv[1]
assert p.common.load(p.ROOT / ('analysis-'+label+'.json'))['status']=='ACCEPTED'
profile = p.REPO / 'nnue-profiling-20261017'
sys.path.insert(0,str(profile))
import run_profile as old
import sample_native as sampler

for source,dest in [('engine.exe','mapped.exe'),('engine.pdb','mapped.pdb'),('engine.pdb','engine.pdb')]:
    shutil.copy2(p.ART/label/source,p.ART/dest)
p.save('config.json',p.common.load(p.ROOT/'plan.json'))
sampler.p = SimpleNamespace(ROOT=p.ROOT,ART=p.ART,pin=old.pin,common=p.common,
        save=p.save,open_engine=p.open_engine,checked_capture=old.checked_capture)
sampler.run()
p.save('native-sampling-identity.json',dict(candidate=label,engine_sha256=p.common.sha(p.ART/'mapped.exe'),
       sampler_sha256=p.common.sha(profile/'sample_native.py'),
       baseline_reused_trace_sha256=p.common.sha(p.OLD/'native-samples.json'),
       baseline_reused_symbols_sha256=p.common.sha(p.OLD/'native-symbols.json'),
       warning='Coarse post-change shares, not matched before/after component cycle measurements.'))
