"""Read-only measurement assertions plus a bounded artifact inventory."""
import csv
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import run_profile as p

p.verify()
baseline=p.common.load(p.ROOT/'baseline.json')
assert len(baseline['records'])==360 and len(baseline['cold'])==24
positions=p.common.load(p.ROOT/'positions.json')
for row in positions:
    for evaluator in ['classical','nnue']:
        for mode,budget in [('depth',5),('nodes',200000)]:
            records=[r for r in baseline['records'] if r['position']==row['id'] and r['evaluator']==evaluator and r['mode']==mode]
            assert len(records)==3
            assert all(p.canonical(r)==p.canonical(records[0]) for r in records)
            assert all(r['nodes']==budget for r in records) if mode=='nodes' else all(r['depth']==budget for r in records)
profile=p.common.load(p.ROOT/'instrumented.json')['records']
assert len(profile)==108
for row in positions:
    for repeat in range(3):
        group=[r for r in profile if r['position']==row['id'] and r['repeat']==repeat]
        assert len(group)==3 and all(p.canonical(r)==p.canonical(group[0]) for r in group)
        for r in group:
            if r['build']=='release':continue
            d=r['diagnostics']
            assert d['qvisits']==r['counters']['qnodes']
            assert d['updates']==d['copies']==sum(d['delta_histogram'])
            assert d['updates']==d['normal_updates']+d['q_updates']+d['unvisited_updates']
            assert d['null_updates']==r['counters']['null_attempts']
            assert d['frame_bytes']==1176 and d['stack_bytes']==76440
            assert d['refreshes']==1
assert p.common.load(p.ROOT/'symbol-build-parity.json')['passed']
transitions=p.common.load(p.ROOT/'transition-parity.json')
assert transitions['bitwise_exact'] and transitions['transitions']==31876 and transitions['nulls']==26908
assert all(c['identical'] for c in p.common.load(p.ROOT/'binary-inspection.json')['function_byte_checks'])
for name in ['components','micro']:
    records=p.common.load(p.ROOT/(name+'.json'))['records']
    assert len(records)==84
    assert all(value>0 for r in records for key,value in r.items() if key.endswith('_ns'))
assert all(r['head_parity_cases']==201 for r in p.common.load(p.ROOT/'components.json')['records'])
samples=p.common.load(p.ROOT/'native-samples.json')['records']
assert len(samples)==24 and sum(r['failed_samples'] for r in samples)==0
assert sum(sum(r['rip_counts'].values()) for r in samples)==4074
assert len(p.common.load(p.ROOT/'classical-timers.json')['records'])==24
assert len(p.common.load(p.ROOT/'varying-head.json')['records'])==7

summary=p.common.load(p.ROOT/'summary.json')
with (p.ROOT/'batched-component-times.csv').open('w',newline='',encoding='utf-8') as f:
    writer=csv.DictWriter(f,fieldnames=['harness','component','timed_calls','total_measured_ns','mean_ns_per_call','median_ns_per_batch','q1_ns','q3_ns','production_ns_per_node'])
    writer.writeheader()
    for name in ['components','micro']:
        records=p.common.load(p.ROOT/(name+'.json'))['records']
        for key,distribution in summary[name].items():
            calls=100000*len(records);total=sum(r[key]*100000 for r in records)
            writer.writerow({'harness':name,'component':key,'timed_calls':calls,'total_measured_ns':round(total),'mean_ns_per_call':total/calls,'median_ns_per_batch':distribution['median'],'q1_ns':distribution['q1'],'q3_ns':distribution['q3'],'production_ns_per_node':'not inferred from repeated-root microbenchmark'})
p.save('validation.json',{'passed':True,'protected_files':653,'warm_searches':360,'cold_searches':24,'instrumented_searches':108,'symbol_parity_pairs':12,'move_transitions':31876,'null_transitions':26908,'executed_split_head_parity_checks':84*201,'native_samples':4074,'native_context_failures':0,'notes':'Fixed-work repeat determinism and cross-build decision/counter equivalence checked. No GUI/full application suite; no production source changes.'})

inventory=[]
for path in sorted(p.ROOT.rglob('*')):
    if not path.is_file() or 'zig-cache' in path.parts or '__pycache__' in path.parts or path.name=='manifest.json':continue
    if path.suffix.lower() in ['.obj','.o','.lib','.tmp']:continue
    raw=path.read_bytes();record={'path':path.relative_to(p.ROOT).as_posix(),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    if path.suffix.lower() in ['.py','.cpp','.hpp','.json','.log','.md','.csv','.txt','.s']:
        record['lf_normalized_sha256']=hashlib.sha256(raw.replace(b'\r\n',b'\n')).hexdigest()
    inventory.append(record)
reports={name:{'sha256':p.common.sha(p.REPO/name),'lf_normalized_sha256':hashlib.sha256((p.REPO/name).read_bytes().replace(b'\r\n',b'\n')).hexdigest()} for name in ['NNUE_PROFILING_REPORT.md','NNUE_OPTIMIZATION_ROADMAP.md']}
p.save('manifest.json',{'created_utc':datetime.now(timezone.utc).isoformat(),'scope':'Profiling artifacts only. Compiler cache, Python bytecode, temporary/static library objects and this self-referential manifest excluded. No dataset inventory or test access. Raw-byte hashes describe the local snapshot; LF-normalized hashes permit text line-ending conversion.','network_sha256':p.common.sha(p.MODEL),'root_reports_sha256':reports,'files':inventory})
print('All measurement and preservation assertions passed; inventory files:',len(inventory))
