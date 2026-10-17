"""Bounded dense-head study against exact accepted Stage 1, never production."""
from __future__ import annotations
import argparse
from contextlib import ExitStack
import ctypes
import difflib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
OLD = REPO / 'nnue-optimization-stage1-20261017'
PROFILE = REPO / 'nnue-profiling-20261017'
ART = ROOT / 'artifacts'
sys.path.insert(0, str(REPO))
from tools import nnue_showdown as common
from tools.nnue_diagnosis import capture, open_engine
from tools.profile_nnue_diagnosis import canonical


def save(name: str, data) -> None:
    common.save(ROOT / name, data)


def pin(mask: int = 1) -> None:
    api = ctypes.windll.kernel32
    api.GetCurrentProcess.restype = ctypes.c_void_p
    api.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    if not api.SetProcessAffinityMask(api.GetCurrentProcess(), mask):
        raise ctypes.WinError()


def command(args, name: str, timeout: int = 600) -> str:
    result = subprocess.run(list(map(str, args)), cwd=REPO, capture_output=True,
        text=True, timeout=timeout,
        env=dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(ART / 'zig-cache')))
    (ART / (name + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'{name} failed: {result.stderr[-1500:]}')
    return result.stdout


def prepare() -> None:
    assert not (ROOT / 'plan.json').exists(), 'Preserve frozen experiment'
    ART.mkdir(exist_ok=True)
    protected = common.load(ART / 'references/preservation-before.json')
    for folder in [REPO/'nnue-optimization-stage2-1-20261017/artifacts/selective',
                   OLD/'artifacts/variant', OLD/'artifacts/variant-source', OLD/'artifacts/generated']:
        for path in folder.glob('*'):
            if path.is_file():
                protected[path.relative_to(REPO).as_posix()] = common.sha(path)
    save('preservation-before.json', protected)
    preserve()
    for old, new in [('variant-source','baseline-source'),('generated','generated'),('variant','baseline')]:
        shutil.copytree(OLD/'artifacts'/old, ART/new)
    prior = common.load(OLD/'plan.json')
    save('plan.json', dict(prior, options=dict(prior['options'], NNUEKernel='clip'),
        source_revision='f397a5af002900bbc15a7261dc6027c48daaeff4',
        baseline_commit='f397a5af002900bbc15a7261dc6027c48daaeff4',
        baseline_binary_sha256=common.sha(ART/'baseline/engine.exe'),
        variant='At most two independent profile-directed dense-head variants',
        maximum_variants=2, initial_repeats=3, repeats=7, maximum_repeats=10,
        primary_runtime_budget_seconds=2700,
        extension_rule='Only if positive micro/fixed-work signals have uncertain grouped bounds without material fixture/order failure; document before extending, maximum ten. No automatic extension.',
        material_elapsed_regression=0.03,
        acceptance='All exact gates; representative micro gain; positive grouped search support across controls/orders; no unexplained material fixture/common inference regression; no promotion.'))
    assert common.sha(ART/'baseline/engine.exe')=='e64146bf7ccf219d3254d258615408e4b782c4aa7b430c9140beb73228055d4d'
    assert common.sha(Path(prior['network']))==prior['network_sha256']
    result = json.loads(command([ART/'baseline/oracle.exe','--verify-throughput','clip'],'baseline-oracle'))
    head = json.loads(command([ART/'baseline/micro.exe','--parity',ROOT/'golden-fens.txt'],'baseline-head'))
    assert result['bitwise_exact'] and head['passed']
    save('baseline-reconfirmed.json', dict(oracle=result, head=head))
    save('config.json', common.load(ROOT/'plan.json'))
    print('Preserved exact Stage 1, frozen configuration and model', flush=True)


def build(label: str, only: str | None = None) -> None:
    source = ART / (label + '-source')
    if label != 'baseline':
        assert (ROOT/'candidate-selection.json').exists(), 'Profile before implementation'
        if not source.exists(): shutil.copytree(ART/'baseline-source', source)
        shutil.copy2(ROOT/(label+'_head.hpp'), source/'stage1_head.hpp')
    original = common.load(OLD/'build-variant-engine.json')['command']
    args = original[:original.index(str(OLD/'artifacts/variant-source/main.cpp'))]
    args = [str(ART/'generated') if v==str(OLD/'artifacts/generated') else
            str(source) if v==str(OLD/'artifacts/variant-source') else v for v in args]
    out = ART/label
    out.mkdir(exist_ok=True)
    targets = [only] if only else (['micro'] if label=='baseline' else ['engine','micro','oracle'])
    for target in targets:
        if target=='engine':
            sources = [source/name for name in ['main.cpp','search.cpp','evaluation.cpp','nnue.cpp','nnue_v3.cpp']]
        elif target=='oracle':
            sources = [REPO/'engine/tests/benchmark_nnue.cpp']+[source/name for name in ['search.cpp','evaluation.cpp','nnue.cpp','nnue_v3.cpp']]
        else:
            sources = [ROOT/'head_harness.cpp', source/'nnue.cpp']
        cmd = args+list(map(str,sources))+['-o',str(out/(target+'.exe'))]
        command(cmd, f'build-{label}-{target}')
        save(f'build-{label}-{target}.json', dict(command=cmd, sha256=common.sha(out/(target+'.exe')),
            sources={p.name:common.sha(p) for p in source.glob('*') if p.is_file()},
            target_sources={str(p.relative_to(REPO)):common.sha(p) for p in sources}))
        print('Built', label, target, flush=True)
    command(args+['-S',str(source/'nnue.cpp'),'-o',str(out/'nnue.s')], 'assembly-'+label)
    if label != 'baseline':
        (ROOT/(label+'.patch')).write_text(''.join(difflib.unified_diff(
            (ART/'baseline-source/stage1_head.hpp').read_text().splitlines(True),
            (source/'stage1_head.hpp').read_text().splitlines(True),
            fromfile='a/stage1_head.hpp',tofile='b/stage1_head.hpp',n=2)))


def player(label: str, evaluator: str = 'nnue'):
    instance = open_engine(ART/label/'engine.exe')
    instance.configure(dict(common.load(ROOT/'plan.json')['options'], Evaluator=evaluator, NNUEKernel='clip'))
    return instance


def head_checks(label: str) -> dict:
    head = json.loads(command([ART/label/'micro.exe','--parity',ROOT/'golden-fens.txt'],label+'-head-parity'))
    assert head['passed'] and head['head_bit_comparisons']>=161420
    extra = json.loads(command([ART/label/'micro.exe','--edge-bits'],label+'-edge-bits'))
    if label=='baseline': save('baseline-edge-bits.json', extra)
    else: assert extra==common.load(ROOT/'baseline-edge-bits.json'), 'Stage 1 special-value bit mismatch'
    return dict(head=head,extra_special_heads=extra['comparisons'])


def correctness(label: str) -> None:
    pin()
    data = head_checks(label)
    data['oracle'] = json.loads(command([ART/label/'oracle.exe','--verify-throughput','clip'],label+'-oracle'))
    assert data['oracle']==dict(bitwise_exact=True,transitions=31876,nulls=26908)
    data['fixed_work'] = []
    with player('baseline') as a, player(label) as b:
        for row in common.load(ROOT/'positions.json'):
            for mode,budget in [('depth',5),('nodes',200000),('nodes',1000000)]:
                x,y = capture(a,row,mode,budget),capture(b,row,mode,budget)
                assert canonical(x)==canonical(y),(label,row['id'],mode,budget)
                data['fixed_work'].append(dict(baseline=x,variant=y))
            print('Exact parity',label,row['id'],flush=True)
    data['passed'] = True
    save('correctness-'+label+'.json', data)


def initial() -> None:
    pin()
    save('baseline-head-checks.json',head_checks('baseline'))
    data = dict(records=[],micro_records=[])
    with player('baseline') as engine:
        for repeat in range(3):
            for row in common.load(ROOT/'positions.json'):
                for mode,budget in common.load(ROOT/'plan.json')['budgets']:
                    data['records'].append(dict(capture(engine,row,mode,budget),build='baseline',repeat=repeat))
                save('initial-baseline.json',data)
                print('Fresh baseline',repeat+1,row['id'],flush=True)
            for size in [1,32,128,512]:
                r = json.loads(command([ART/'baseline/micro.exe','--bench','clip',str(size),'200000'],f'initial-head-{repeat}-{size}'))
                data['micro_records'].append(dict(r,frames=size,repeat=repeat,build='baseline'))
            save('initial-baseline.json',data)


def micro(label: str) -> None:
    assert common.load(ROOT/('correctness-'+label+'.json'))['passed']
    assert common.load(ROOT/('regressions-'+label+'.json'))['passed']
    pin()
    data = dict(records=[],iterations=200000,warmup=10000)
    for repeat in range(7):
        for size in [1,32,128,512]:
            for b in (['baseline',label] if repeat%2 else [label,'baseline']):
                r = json.loads(command([ART/b/'micro.exe','--bench','clip',str(size),'200000'],f'micro-{b}-{repeat}-{size}'))
                data['records'].append(dict(r,build=b,frames=size,repeat=repeat))
            pair = data['records'][-2:]
            assert pair[0]['checksum']==pair[1]['checksum']
        save('micro-'+label+'.json',data)
        print('Micro',label,repeat+1,flush=True)


def search(label: str) -> None:
    assert common.load(ROOT/('correctness-'+label+'.json'))['passed']
    assert common.load(ROOT/('regressions-'+label+'.json'))['passed']
    pin()
    path = ROOT/('search-'+label+'.json')
    data = common.load(path) if path.exists() else dict(records=[],environment_segments=[],runtime_seconds=0)
    done = {(r['position'],r['mode'],r['budget'],r['build'],r['repeat']) for r in data['records']}
    plan = common.load(ROOT/'plan.json')
    count = common.load(ROOT/('extension-'+label+'.json'))['total_repeats'] if (ROOT/('extension-'+label+'.json')).exists() else 7
    assert 7<=count<=10
    prior=data['runtime_seconds'];started=time.monotonic()
    with ExitStack() as stack:
        players = {b:stack.enter_context(player(b)) for b in ['baseline',label]}
        from load_meter import Meter
        meter=Meter([os.getpid()]+[v.transport.get_pid() for v in players.values()]);stack.callback(meter.close)
        for engine in players.values(): capture(engine,common.load(ROOT/'positions.json')[0],'nodes',50000)
        for repeat in range(count):
            for i,row in enumerate(common.load(ROOT/'positions.json')):
                if all((row['id'],mode,budget,b,repeat) in done for mode,budget in plan['budgets'] for b in players):continue
                order = ['baseline',label] if (repeat+i)%2 else [label,'baseline']
                for mode,budget in plan['budgets']:
                    for b in order:
                        key=(row['id'],mode,budget,b,repeat)
                        if key in done:continue
                        if prior+time.monotonic()-started>plan['primary_runtime_budget_seconds']:
                            raise RuntimeError('Bounded primary runtime reached')
                        data['records'].append(dict(capture(players[b],row,mode,budget),build=b,repeat=repeat,order=order))
                        done.add(key)
                    if mode=='nodes':
                        pair=[r for r in data['records'] if r['position']==row['id'] and r['mode']==mode and r['budget']==budget and r['repeat']==repeat]
                        assert len(pair)==2 and canonical(pair[0])==canonical(pair[1]) and pair[0]['nodes']==budget
                    data['runtime_seconds']=prior+time.monotonic()-started
                    save(path.name,data)
                data['environment_segments'].append(dict(meter.read(),position=row['id'],repeat=repeat))
                save(path.name,data)
                print('Search',label,repeat+1,row['id'],flush=True)


def preserve() -> None:
    original=common.load(ROOT/'preservation-before.json')
    changed=[name for name,sha in original.items() if not (REPO/name).exists() or common.sha(REPO/name)!=sha]
    save('preservation-after.json',dict(checked_files=len(original),changed=changed,passed=not changed))
    assert not changed,changed


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','build','initial','correctness','micro','search','preserve'])
    parser.add_argument('label',nargs='?');parser.add_argument('--target')
    args=parser.parse_args()
    if args.action=='build':build(args.label,args.target)
    elif args.action in ['correctness','micro','search']:globals()[args.action](args.label)
    else:globals()[args.action]()
