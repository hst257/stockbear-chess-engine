"""Bounded Stage 2.1; frozen three-way comparisons, strict numerical parity."""
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
ART = ROOT / 'artifacts'
sys.path.insert(0, str(REPO))
from tools import nnue_showdown as common
from tools.nnue_diagnosis import capture, open_engine
from tools.profile_nnue_diagnosis import canonical


def save(name, data):
    common.save(ROOT / name, data)


def pin():
    api = ctypes.windll.kernel32
    api.GetCurrentProcess.restype = ctypes.c_void_p
    api.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    if not api.SetProcessAffinityMask(api.GetCurrentProcess(), 1):
        raise ctypes.WinError()


def command(args, name, timeout=600):
    result = subprocess.run(list(map(str,args)), cwd=REPO, capture_output=True, text=True,
        env=dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(ART/'zig-cache')), timeout=timeout)
    (ART/(name+'.log')).write_text(result.stdout+result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'{name} failed: {result.stderr[-1500:]}')
    return result.stdout


def prepare():
    import chess
    assert not (ROOT/'plan.json').exists(), 'Frozen workspace already exists'
    ART.mkdir(exist_ok=True)
    protected = common.load(ART/'references/preservation-before.json')
    # Stage 2 tracked evidence lives on its preserved branch. Hash its ignored
    # binaries as well, without requiring files absent on the Stage 1 base.
    for path in (REPO/'nnue-optimization-stage2-20261017/artifacts/sort').glob('*'):
        if path.is_file():
            protected[path.relative_to(REPO).as_posix()] = common.sha(path)
    save('preservation-before.json', protected)
    preserve()
    for source, target in [('variant-source','baseline-source'),('generated','generated'),('variant','baseline')]:
        shutil.copytree(OLD/'artifacts'/source, ART/target)
    shutil.copytree(ART/'stage2-source', ART/'sort-source')
    (ART/'sort').mkdir()
    shutil.copy2(REPO/'nnue-optimization-stage2-20261017/artifacts/sort/engine.exe', ART/'sort/engine.exe')
    prior = common.load(OLD/'plan.json')
    diag_fens = [
        'r6k/1P6/8/8/8/8/8/K7 w - - 0 1',
        '7k/8/8/8/8/8/4p3/K7 b - - 0 1',
        '7k/P7/8/8/8/8/7p/K5R1 w - - 0 1']
    supp_fens = [
        '2r3k1/1P6/8/8/8/8/6p1/4K3 w - - 0 1',
        '4k3/6p1/8/8/8/8/1p5R/3K4 b - - 0 1',
        '7k/2P5/8/8/8/8/5p2/2K5 w - - 0 1',
        '1r4k1/P6p/8/8/8/8/6P1/4K2R w K - 0 1']
    for fen in diag_fens+supp_fens:
        board = chess.Board(fen)
        assert board.is_valid() and not board.is_game_over(), (fen, board.status())
        assert any(m.promotion for m in board.legal_moves), fen
    rows = common.load(ROOT/'positions.json')
    save('diagnostic-positions.json', [next(r for r in rows if r['id']=='promotion')]+[
        dict(id=f'diagnostic_promotion_{i+1}',fen=f,category='promotion') for i,f in enumerate(diag_fens)])
    save('supplementary-positions.json', [dict(id=f'validation_promotion_{i+1}',fen=f,category='promotion') for i,f in enumerate(supp_fens)])
    save('plan.json', dict(prior, baseline_commit='f397a5af002900bbc15a7261dc6027c48daaeff4',
        stage2_commit='004281cb8a24357e61229c8945d8d4aababc4a4c',
        options=dict(prior['options'],NNUEKernel='clip'), repeats=7,maximum_repeats=10,
        baseline_binary_sha256=common.sha(ART/'baseline/engine.exe'),
        stage2_sort_binary_sha256=common.sha(ART/'sort/engine.exe'),maximum_new_variants=2,
        primary_runtime_budget_seconds=2700,diagnostic_repeats=5,
        acceptance='Exact gates; positive grouped intervals; repeatable whole-search gain; no >3% elapsed fixture median regression; no active promotion.',
        supplementary_frozen_before_candidate=True))
    assert common.sha(ART/'sort/engine.exe')==common.load(ART/'references/build-sort-engine.json')['sha256']
    shutil.copy2(ART/'references/build-sort-engine.json',ROOT/'build-sort-engine.json')
    save('reference-inputs.json',{str(path.relative_to(ART)):common.sha(path) for path in (ART/'references').glob('*') if path.is_file()})
    checks = dict(oracle=json.loads(command([ART/'baseline/oracle.exe','--verify-throughput','clip'],'baseline-reconfirm-oracle')),
        head=json.loads(command([ART/'baseline/micro.exe','--parity',ROOT/'golden-fens.txt'],'baseline-reconfirm-head')))
    assert checks['oracle']['bitwise_exact'] and checks['head']['passed']
    save('baseline-reconfirmed.json',checks)
    print('Frozen baseline, preservation, diagnostics and untouched validation set',flush=True)


def build(label, only=None):
    source = ART/(label+'-source')
    if not source.exists():
        shutil.copytree(ART/'baseline-source',source)
    if label=='selective':
        assert (ROOT/'candidate-selection.json').exists(), 'Characterize before implementation'
        shutil.copy2(ROOT/'selective_sort.hpp',source/'selective_sort.hpp')
        path = source/'nnue.cpp'
        text = path.read_text()
        if '#include "selective_sort.hpp"' not in text:
            text = text.replace('#include "nnue.hpp"','#include "nnue.hpp"\n#include "selective_sort.hpp"')
            at = text.index('void nnue_update_search_states(')
            body = text[at:].replace('std::sort(active.begin(), active.begin() + states.count)',
                'stage21::state_sort(active.data(), states.count)',1)
            body = body.replace('std::sort(changes, changes + size, [](int a, int b) { return std::abs(a) < std::abs(b); })',
                'stage21::row_sort(changes, size)',1)
            text = text[:at]+body
            path.write_text(text)
    meta = common.load(OLD/'build-variant-engine.json')
    original = meta['command']
    args = original[:original.index(str(OLD/'artifacts/variant-source/main.cpp'))]
    args = [str(ART/'generated') if a==str(OLD/'artifacts/generated') else
            str(source) if a==str(OLD/'artifacts/variant-source') else a for a in args]
    out = ART/label
    out.mkdir(exist_ok=True)
    targets = [only] if only else (['micro','sorttest'] if label in ['baseline','sort'] else ['engine','oracle','micro','head','sorttest'])
    for target in targets:
        if target=='engine':
            sources = [source/n for n in ['main.cpp','search.cpp','evaluation.cpp','nnue.cpp','nnue_v3.cpp']]
        elif target=='oracle':
            sources = [REPO/'engine/tests/benchmark_nnue.cpp']+[source/n for n in ['search.cpp','evaluation.cpp','nnue.cpp','nnue_v3.cpp']]
        elif target=='sorttest':
            sources = [ROOT/'sort_harness.cpp']
        else:
            sources = [ROOT/('update_harness.cpp' if target=='micro' else 'head_harness.cpp'),source/'nnue.cpp']
        extra = [f'-DSTAGE21_SORT_MODE={dict(baseline=0,sort=1,selective=2).get(label,0)}','-I',str(ROOT)] if target=='sorttest' else []
        cmd = args+extra+list(map(str,sources))+['-o',str(out/(target+'.exe'))]
        command(cmd,f'build-{label}-{target}')
        save(f'build-{label}-{target}.json',dict(command=cmd,sha256=common.sha(out/(target+'.exe')),
            sources={p.name:common.sha(p) for p in source.glob('*') if p.is_file()},
            target_sources={str(p.relative_to(REPO)):common.sha(p) for p in sources}))
        print('Built',label,target,flush=True)
    command(args+['-S',str(source/'nnue.cpp'),'-o',str(out/'nnue.s')],'assembly-'+label)
    patch=[]
    for path in source.glob('*'):
        old=ART/'baseline-source'/path.name
        if old.exists() and old.read_bytes()!=path.read_bytes():
            patch.extend(difflib.unified_diff(old.read_text().splitlines(True),path.read_text().splitlines(True),
                fromfile='a/engine/src/'+path.name,tofile='b/engine/src/'+path.name,n=0))
    (ROOT/(label+'.patch')).write_text(''.join(patch))


def player(label,evaluator='nnue'):
    engine=open_engine(ART/label/'engine.exe')
    engine.configure(dict(common.load(ROOT/'plan.json')['options'],Evaluator=evaluator,NNUEKernel='clip'))
    return engine


def correctness(label):
    pin()
    oracle = ART/label/'oracle.exe'
    if label=='sort':
        oracle=REPO/'nnue-optimization-stage2-20261017/artifacts/sort/oracle.exe'
    data=dict(oracle=json.loads(command([oracle,'--verify-throughput','clip'],label+'-oracle')))
    assert data['oracle']==dict(bitwise_exact=True,transitions=31876,nulls=26908)
    data['targeted']=json.loads(command([ART/label/'micro.exe','--verify'],label+'-targeted'))
    expected=json.loads(command([ART/'baseline/micro.exe','--verify'],'baseline-targeted'))
    assert data['targeted']['passed'] and data['targeted']['digest']==expected['digest']
    data['baseline_targeted']=expected
    head=ART/label/'head.exe'
    if label=='sort':
        head=REPO/'nnue-optimization-stage2-20261017/artifacts/sort/head.exe'
    data['head']=json.loads(command([head,'--parity',ROOT/'golden-fens.txt'],label+'-head'))
    assert data['head']['passed']
    data['sorting']=json.loads(command([ART/label/'sorttest.exe','--verify'],label+'-sorttest'))
    assert data['sorting']['passed']
    data['fixed_work']=[]
    rows=common.load(ROOT/'positions.json')+common.load(ROOT/'supplementary-positions.json')
    with player('baseline') as a,player(label) as b:
        for row in rows:
            for mode,budget in [('depth',5),('nodes',200000),('nodes',1000000)]:
                x,y=capture(a,row,mode,budget),capture(b,row,mode,budget)
                assert canonical(x)==canonical(y),(label,row['id'],mode,budget)
                data['fixed_work'].append(dict(baseline=x,variant=y))
            print('Parity',label,row['id'],flush=True)
    data['passed']=True
    save('correctness-'+label+'.json',data)


def schedule(kind):
    pin()
    plan=common.load(ROOT/'plan.json')
    if kind=='diagnostic':
        labels=['baseline','sort'];rows=common.load(ROOT/'diagnostic-positions.json')
        budgets=[('nodes',1000000)];repeats=5
    elif kind=='observer':
        os.environ['STOCKBEAR_SORT_OBSERVER']=str(ROOT/'workload-raw.jsonl')
        labels=['baseline','observer'];rows=common.load(ROOT/'positions.json')+common.load(ROOT/'diagnostic-positions.json')[1:]
        budgets=[('nodes',200000)];repeats=3
    else:
        labels=['baseline','sort','selective']
        assert all(common.load(ROOT/('correctness-'+b+'.json'))['passed'] and common.load(ROOT/('regressions-'+b+'.json'))['passed'] for b in labels[1:])
        rows=common.load(ROOT/'positions.json')+common.load(ROOT/'supplementary-positions.json')
        budgets=plan['budgets'];repeats=plan['repeats']
        extension=ROOT/'extension.json'
        if extension.exists():
            repeats=common.load(extension)['total_repeats']
        assert 7<=repeats<=10
    path=ROOT/(kind+'.json')
    data=common.load(path) if path.exists() else dict(records=[],environment_segments=[],runtime_seconds=0)
    done={(r['position'],r['mode'],r['budget'],r['build'],r['repeat']) for r in data['records']}
    started=time.monotonic();prior=data['runtime_seconds']
    with ExitStack() as stack:
        players={b:stack.enter_context(player(b)) for b in labels}
        from load_meter import Meter
        meter=Meter([os.getpid()]+[e.transport.get_pid() for e in players.values()]);stack.callback(meter.close)
        for engine in players.values():
            capture(engine,common.load(ROOT/'positions.json')[0],'nodes',50000)
        for repeat in range(repeats):
            for i,row in enumerate(rows):
                if all((row['id'],mode,budget,b,repeat) in done for mode,budget in budgets for b in labels):
                    continue
                offset=(repeat+i)%len(labels)
                order=labels[offset:]+labels[:offset]
                # Reverse alternate blocks as well as rotating adjacency.
                if (repeat//len(labels))%2: order=order[::-1]
                for mode,budget in budgets:
                    for b in order:
                        key=(row['id'],mode,budget,b,repeat)
                        if key in done: continue
                        if kind=='primary' and prior+time.monotonic()-started>plan['primary_runtime_budget_seconds']:
                            raise RuntimeError('Predeclared primary time budget reached; do not extend')
                        r=capture(players[b],row,mode,budget)
                        data['records'].append(dict(r,build=b,repeat=repeat,order=order))
                        done.add(key)
                    if mode=='nodes':
                        pair=[r for r in data['records'] if r['position']==row['id'] and r['mode']==mode and r['budget']==budget and r['repeat']==repeat]
                        assert len(pair)==len(labels) and all(canonical(r)==canonical(pair[0]) for r in pair)
                    data['runtime_seconds']=prior+time.monotonic()-started
                    save(path.name,data)
                data['environment_segments'].append(dict(meter.read(),repeat=repeat,position=row['id']))
                save(path.name,data)
                print(kind,repeat+1,row['id'],flush=True)


def micro():
    pin();data=dict(records=[],sort_records=[],repeats=7,iterations=100000)
    labels=['baseline','sort','selective']
    for repeat in range(7):
        order=labels[repeat%3:]+labels[:repeat%3]
        if repeat%2:order=order[::-1]
        for b in order:
            assert common.load(ROOT/('correctness-'+b+'.json'))['passed'] if b!='baseline' else True
            result=json.loads(command([ART/b/'micro.exe','--bench','100000'],f'micro-{b}-{repeat}'))
            data['records'].append(dict(result,build=b,repeat=repeat))
            result=json.loads(command([ART/b/'sorttest.exe','--bench'],f'sort-micro-{b}-{repeat}'))
            data['sort_records'].append(dict(result,build=b,repeat=repeat))
        save('micro.json',data);print('Micro',repeat+1,flush=True)


def preserve():
    protected=common.load(ROOT/'preservation-before.json')
    changed=[p for p,h in protected.items() if not (REPO/p).exists() or common.sha(REPO/p)!=h]
    save('preservation-after.json',dict(checked_files=len(protected),changed=changed,passed=not changed))
    assert not changed,changed


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['prepare','build','correctness','diagnostic','observer','primary','micro','preserve'])
    parser.add_argument('label',nargs='?');parser.add_argument('--target')
    args=parser.parse_args()
    if args.action=='build':build(args.label,args.target)
    elif args.action=='correctness':correctness(args.label)
    elif args.action in ['diagnostic','observer','primary']:schedule(args.action)
    else:globals()[args.action]()
