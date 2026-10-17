"""Batched component latencies and isolated symbol-build fixed-work parity."""
import json
import subprocess
from contextlib import ExitStack
import run_profile as p

p.pin()
rows=p.common.load(p.ROOT/'positions.json')
data={'method':'Seven rotated position passes; 100,000 calls per component plus 1,000 warmup calls. First legal child per FEN. Dense includes fused input clipping; standalone activation overlaps it and must not be added. Standalone output and conversion have noinline harness boundaries; production head measured independently. No alternative kernel or new quantization.','records':[]}
for repeat in range(7):
    order=rows[repeat:]+rows[:repeat]
    for row in order:
        value=json.loads(subprocess.check_output([str(p.ART/'components.exe'),row['fen'],'100000'],text=True))
        data['records'].append(dict(value,position=row['id'],repeat=repeat))
    p.save('components.json',data)
    print('Components',repeat,flush=True)
checks=[]
with ExitStack() as stack:
    engines={label:stack.enter_context(p.open_engine(path)) for label,path in {'release':p.ART/'release/engine.exe','symbols':p.ART/'mapped.exe'}.items()}
    for engine in engines.values():engine.configure(dict(p.common.load(p.ROOT/'config.json')['options'],Evaluator='nnue'))
    for row in rows:
        result={label:p.checked_capture(engine,row,'nodes',200000) for label,engine in engines.items()}
        assert p.canonical(result['release'])==p.canonical(result['symbols']),row['id']
        checks.append({'position':row['id'],**result})
p.save('symbol-build-parity.json',{'passed':True,'records':checks})
