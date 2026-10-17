"""Isolated Stage 1 clip baseline and bounded Stage 2 accumulator trials."""
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

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
OLD = REPO / 'nnue-optimization-stage1-20261017'
ART = ROOT / 'artifacts'
sys.path.insert(0, str(REPO))
from tools import nnue_showdown as common
from tools.nnue_diagnosis import capture, open_engine
from tools.profile_nnue_diagnosis import canonical


def save(name, value):
    common.save(ROOT / name, value)


def pin():
    api = ctypes.windll.kernel32
    api.GetCurrentProcess.restype = ctypes.c_void_p
    api.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    if not api.SetProcessAffinityMask(api.GetCurrentProcess(), 1):
        raise ctypes.WinError()


def command(args, name, timeout=600):
    result = subprocess.run(args, cwd=REPO, capture_output=True, text=True,
                            env=dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(ART / 'zig-cache')),
                            timeout=timeout)
    (ART / (name + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
    if result.returncode:
        raise RuntimeError(f'{name} failed: see artifacts/{name}.log')
    return result.stdout


def prepare():
    assert not (ROOT / 'plan.json').exists(), 'Frozen workspace exists'
    ART.mkdir(exist_ok=True)
    protected = common.load(OLD / 'preservation-before.json')
    for path in OLD.rglob('*'):
        if path.is_file() and not {'artifacts', '__pycache__'}.intersection(path.relative_to(OLD).parts):
            protected[path.relative_to(REPO).as_posix()] = common.sha(path)
    for folder in ['artifacts/variant-source', 'artifacts/generated', 'artifacts/variant']:
        for path in (OLD / folder).rglob('*'):
            if path.is_file():
                protected[path.relative_to(REPO).as_posix()] = common.sha(path)
    protected['NNUE_STAGE1_OPTIMIZATION_REPORT.md'] = common.sha(REPO / 'NNUE_STAGE1_OPTIMIZATION_REPORT.md')
    save('preservation-before.json', protected)
    preserve()
    shutil.copytree(OLD / 'artifacts/variant-source', ART / 'baseline-source')
    shutil.copytree(OLD / 'artifacts/generated', ART / 'generated')
    shutil.copytree(OLD / 'artifacts/variant', ART / 'baseline')
    for name in ['positions.json', 'golden-fens.txt', 'observe.ps1', 'load_meter.py', 'head_harness.cpp']:
        shutil.copy2(OLD / name, ROOT / name)
    observer = ROOT / 'observe.ps1'
    observer.write_text(observer.read_text().replace(
        "'nnue-optimization-stage1-20261017/environment.json'",
        "(Join-Path $PSScriptRoot 'environment.json')"))
    prior = common.load(OLD / 'plan.json')
    save('plan.json', dict(prior, options=dict(prior['options'], NNUEKernel='clip'),
         baseline_commit='f397a5af002900bbc15a7261dc6027c48daaeff4',
         source_revision='f397a5af002900bbc15a7261dc6027c48daaeff4',
         baseline_binary_sha256=common.sha(ART / 'baseline/engine.exe'),
         variant='Independent narrow accumulator changes; Stage 1 clip unchanged',
         maximum_variants=3, acceptance='Exact parity; positive grouped intervals; '
         'maintenance decrease; practical ~3% gain, tiny unstable results inconclusive; '
         'investigate position median regressions exceeding 3%; no promotion'))
    checks = {}
    for target, args in [('oracle', ['--verify-throughput', 'clip']),
                         ('micro', ['--parity', str(ROOT / 'golden-fens.txt')])]:
        checks[target] = json.loads(command([str(ART / 'baseline' / (target + '.exe')), *args], 'baseline-reconfirm-' + target))
    assert checks['oracle']['bitwise_exact'] and checks['micro']['passed']
    save('baseline-reconfirmed.json', checks)
    print('Preserved Stage 1 and reconfirmed baseline', flush=True)


def build(label, only=None):
    source = ART / (label + '-source')
    if not source.exists():
        shutil.copytree(ART / 'baseline-source', source)
    mode = {'counters': 2, 'timers': 2, 'small': 5, 'fused': 4, 'sort': 2, 'baseline': 2}[label]
    if label == 'sort':
        shutil.copy2(ROOT / 'small_sort.hpp', source / 'small_sort.hpp')
        path = source / 'nnue.cpp'
        text = path.read_text()
        if '#include "small_sort.hpp"' not in text:
            text = text.replace('#include "nnue.hpp"', '#include "nnue.hpp"\n#include "small_sort.hpp"')
            at = text.index('void nnue_update_search_states(')
            prefix, body = text[:at], text[at:]
            body = body.replace('std::sort(active.begin(), active.begin() + states.count)',
                 'stage2::small_sort(active.data(), states.count, [](auto f) { return f; })', 1)
            body = body.replace('std::sort(changes, changes + size, [](int a, int b) { return std::abs(a) < std::abs(b); })',
                 'stage2::small_sort(changes, size, [](int f) { return std::abs(f); })', 1)
            path.write_text(prefix + body)
    if label == 'timers' and 'NNUE_SORT' not in (source / 'profiling.hpp').read_text():
        path = source / 'profiling.hpp'
        text = path.read_text().replace('NNUE_ROWS,', 'NNUE_ROWS, NNUE_SORT, NNUE_EP,')
        text = text.replace('"nnue_rows"', '"nnue_rows", "nnue_sort", "nnue_ep"')
        path.write_text(text)
        path = source / 'nnue.cpp'
        text = path.read_text()
        text = text.replace('        chess::Movelist captures;',
             '        profiling::Scope ep_measured(profiling::NNUE_EP);\n        chess::Movelist captures;')
        text = text.replace('    for (auto& active : states.active) std::sort(active.begin(), active.begin() + states.count);',
             '    { profiling::Scope sort_measured(profiling::NNUE_SORT);\n'
             '    for (auto& active : states.active) std::sort(active.begin(), active.begin() + states.count); }')
        # Only compact search updater, not generic/reference implementation.
        at = text.index('void nnue_update_search_states(')
        text = text[:at] + text[at:].replace(
            '        std::sort(changes, changes + size, [](int a, int b) { return std::abs(a) < std::abs(b); });',
            '        { profiling::Scope sort_measured(profiling::NNUE_SORT);\n'
            '        std::sort(changes, changes + size, [](int a, int b) { return std::abs(a) < std::abs(b); }); }', 1)
        path.write_text(text)
    meta = common.load(OLD / 'build-variant-engine.json')
    original = meta['command']
    args = original[:original.index(str(OLD / 'artifacts/variant-source/main.cpp'))]
    args = [str(ART / 'generated') if a == str(OLD / 'artifacts/generated') else
            str(source) if a == str(OLD / 'artifacts/variant-source') else
            f'-DCHESSLAB_NNUE_UPDATE={mode}' if a.startswith('-DCHESSLAB_NNUE_UPDATE=') else a for a in args]
    if label in ['counters', 'timers']:
        args += ['-DCHESSLAB_DIAGNOSTICS']
    if label == 'timers':
        args += ['-DCHESSLAB_PROFILE']
    out = ART / label
    out.mkdir(exist_ok=True)
    targets = ['engine'] if label in ['counters', 'timers'] else ['engine', 'oracle', 'micro', 'head']
    if label == 'baseline':
        targets = ['micro']  # Preserve the exact accepted Stage 1 engine/oracle binaries.
    if only:
        targets = [only]
    for target in targets:
        if target == 'engine':
            sources = [source / n for n in ['main.cpp', 'search.cpp', 'evaluation.cpp', 'nnue.cpp', 'nnue_v3.cpp']]
        elif target == 'oracle':
            sources = [REPO / 'engine/tests/benchmark_nnue.cpp'] + [source / n for n in ['search.cpp', 'evaluation.cpp', 'nnue.cpp', 'nnue_v3.cpp']]
        elif target == 'micro':
            sources = [ROOT / 'update_harness.cpp', source / 'nnue.cpp']
        else:
            sources = [ROOT / 'head_harness.cpp', source / 'nnue.cpp']
        cmd = args + list(map(str, sources)) + ['-o', str(out / (target + '.exe'))]
        command(cmd, f'build-{label}-{target}')
        save(f'build-{label}-{target}.json', {'command': cmd, 'sha256': common.sha(out / (target + '.exe')),
             'sources': {p.name: common.sha(p) for p in source.glob('*') if p.is_file()}})
        print('Built', label, target, flush=True)
    command(args + ['-S', str(source / 'nnue.cpp'), '-o', str(out / 'nnue.s')], 'assembly-' + label)
    patch = []
    for path in source.glob('*'):
        old = ART / 'baseline-source' / path.name
        if old.exists() and old.read_bytes() != path.read_bytes():
            patch.extend(difflib.unified_diff(old.read_text().splitlines(True), path.read_text().splitlines(True),
                         fromfile='a/engine/src/' + path.name, tofile='b/engine/src/' + path.name, n=0))
    (ROOT / (label + '.patch')).write_text(''.join(patch))


def player(label, evaluator='nnue'):
    instance = open_engine(ART / label / 'engine.exe')
    instance.configure(dict(common.load(ROOT / 'plan.json')['options'], Evaluator=evaluator, NNUEKernel='clip'))
    return instance


def repeats(label):
    plan = common.load(ROOT / 'plan.json')
    path = ROOT / ('extension-'+label+'.json')
    count = common.load(path)['total_repeats'] if path.exists() else plan['repeats']
    assert plan['repeats'] <= count <= plan['maximum_repeats']
    return count


def instrumented():
    pin()
    data = {'records': []}
    labels = ['baseline', 'counters', 'timers']
    with ExitStack() as stack:
        players = {b: stack.enter_context(player(b)) for b in labels}
        for repeat in range(3):
            for i, row in enumerate(common.load(ROOT / 'positions.json')):
                order = labels[(repeat+i) % 3:] + labels[:(repeat+i) % 3]
                pair = []
                for label in order:
                    r = dict(capture(players[label], row, 'nodes', 200000), build=label, repeat=repeat)
                    pair.append(r)
                    data['records'].append(r)
                assert all(canonical(r) == canonical(pair[0]) for r in pair)
                save('instrumented.json', data)
                print('Profile', repeat, row['id'], flush=True)


def correctness(label):
    pin()
    data = {'oracle': json.loads(command([str(ART / label / 'oracle.exe'), '--verify-throughput', 'clip'], label + '-oracle'))}
    assert data['oracle'] == {'bitwise_exact': True, 'transitions': 31876, 'nulls': 26908}
    data['targeted'] = json.loads(command([str(ART / label / 'micro.exe'), '--verify'], label + '-targeted'))
    assert data['targeted']['passed']
    expected = json.loads(command([str(ART / 'baseline/micro.exe'), '--verify'], 'baseline-targeted'))
    assert data['targeted']['digest'] == expected['digest']
    data['baseline_targeted'] = expected
    data['head'] = json.loads(command([str(ART / label / 'head.exe'), '--parity', str(ROOT / 'golden-fens.txt')], label + '-head-parity'))
    assert data['head']['passed']
    data['fixed_work'] = []
    with player('baseline') as a, player(label) as b:
        for row in common.load(ROOT / 'positions.json'):
            for mode, budget in [('depth', 5), ('nodes', 200000), ('nodes', 1000000)]:
                x, y = capture(a, row, mode, budget), capture(b, row, mode, budget)
                assert canonical(x) == canonical(y), (label, row['id'], mode, budget)
                data['fixed_work'].append({'baseline': x, 'variant': y})
            print('Parity', label, row['id'], flush=True)
    data['passed'] = True
    save('correctness-' + label + '.json', data)


def search(label):
    assert common.load(ROOT / ('correctness-' + label + '.json'))['passed']
    assert common.load(ROOT / ('regressions-' + label + '.json'))['passed']
    pin()
    path = ROOT / ('search-' + label + '.json')
    data = common.load(path) if path.exists() else {'records': [], 'environment_segments': []}
    done = {(r['position'], r['mode'], r['budget'], r['build'], r['repeat']) for r in data['records']}
    plan = common.load(ROOT / 'plan.json')
    with ExitStack() as stack:
        players = {b: stack.enter_context(player(b)) for b in ['baseline', label]}
        from load_meter import Meter
        meter = Meter([os.getpid()] + [e.transport.get_pid() for e in players.values()])
        stack.callback(meter.close)
        for instance in players.values():
            capture(instance, common.load(ROOT / 'positions.json')[0], 'nodes', 50000)
        for repeat in range(repeats(label)):
            for i, row in enumerate(common.load(ROOT / 'positions.json')):
                if all((row['id'], mode, budget, b, repeat) in done
                       for mode, budget in plan['budgets'] for b in players):
                    continue
                for mode, budget in plan['budgets']:
                    labels = ['baseline', label] if (repeat+i) % 2 else [label, 'baseline']
                    for b in labels:
                        if (row['id'], mode, budget, b, repeat) in done:
                            continue
                        r = capture(players[b], row, mode, budget)
                        data['records'].append(dict(r, build=b, repeat=repeat))
                    if mode == 'nodes':
                        pair = [r for r in data['records'] if r['position'] == row['id'] and r['mode'] == mode and r['budget'] == budget and r['repeat'] == repeat]
                        assert len(pair) == 2 and canonical(pair[0]) == canonical(pair[1])
                    save(path.name, data)
                data['environment_segments'].append(dict(meter.read(), repeat=repeat, position=row['id']))
                save(path.name, data)
                print('Search', label, repeat+1, row['id'], flush=True)


def micro(label):
    assert common.load(ROOT / ('correctness-' + label + '.json'))['passed']
    assert common.load(ROOT / ('regressions-' + label + '.json'))['passed']
    pin()
    data = {'records': [], 'iterations': 100000}
    for repeat in range(7):
        for b in (['baseline', label] if repeat % 2 else [label, 'baseline']):
            result = json.loads(command([str(ART / b / 'micro.exe'), '--bench', '100000'], f'micro-{b}-{repeat}'))
            data['records'].append(dict(result, build=b, repeat=repeat))
        save('micro-' + label + '.json', data)
        print('Micro', label, repeat+1, flush=True)


def preserve():
    protected = common.load(ROOT / 'preservation-before.json')
    changed = [p for p, h in protected.items() if common.sha(REPO / p) != h]
    save('preservation-after.json', {'checked_files': len(protected), 'changed': changed, 'passed': not changed})
    assert not changed, changed


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'build', 'instrumented', 'correctness', 'search', 'micro', 'preserve'])
    parser.add_argument('label', nargs='?')
    parser.add_argument('--target', choices=['engine', 'micro', 'oracle', 'head'])
    args = parser.parse_args()
    if args.action in ['prepare', 'instrumented', 'preserve']:
        globals()[args.action]()
    elif args.action == 'build':
        build(args.label, args.target)
    else:
        globals()[args.action](args.label)
