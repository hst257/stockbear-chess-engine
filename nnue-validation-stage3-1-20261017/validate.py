"""Exact-binary, predeclared Stage 3.1 study. Never builds an executable."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import ctypes as c
from ctypes import wintypes as w
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
OLD = REPO / 'nnue-optimization-stage3-20261017'
sys.path[:0] = [str(REPO), str(OLD)]
import chess
from tools import nnue_showdown as common
from tools.nnue_diagnosis import capture, open_engine
from tools.profile_nnue_diagnosis import canonical
from load_meter import Meter, integer, k

CONTROLS = [('nodes', 200000), ('nodes', 1000000), ('time', 100),
            ('time', 200), ('time', 500), ('time', 1000)]
BINARIES = {b: OLD / 'artifacts' / b / 'engine.exe' for b in ['baseline', 'hiddenclip']}


def save(name, obj):
    common.save(ROOT / name, obj)


def load(name):
    return common.load(ROOT / name)


def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def append(name, obj):
    with (ROOT / name).open('a', encoding='utf-8') as f:
        f.write(json.dumps(obj, allow_nan=False, separators=(',', ':')) + '\n')
        f.flush()
        os.fsync(f.fileno())


def pin():
    k.GetCurrentProcess.restype = w.HANDLE
    k.SetProcessAffinityMask.argtypes = [w.HANDLE, c.c_size_t]
    k.GetProcessAffinityMask.argtypes = [w.HANDLE, c.POINTER(c.c_size_t), c.POINTER(c.c_size_t)]
    assert k.SetProcessAffinityMask(k.GetCurrentProcess(), 1)


def affinity(pid):
    h = k.OpenProcess(0x1000, False, pid)
    try:
        process, system = c.c_size_t(), c.c_size_t()
        assert k.GetProcessAffinityMask(h, c.byref(process), c.byref(system))
        return process.value
    finally:
        k.CloseHandle(h)


def cpu_seconds(handle):
    values = [w.FILETIME() for _ in range(4)]
    assert k.GetProcessTimes(handle, *[c.byref(x) for x in values])
    return (integer(values[2]) + integer(values[3])) / 1e7


class Power(c.Structure):
    _fields_ = [('ac', w.BYTE), ('flag', w.BYTE), ('percent', w.BYTE),
               ('reserved', w.BYTE), ('life', w.DWORD), ('full', w.DWORD)]


def environment():
    value = Power()
    assert k.GetSystemPowerStatus(c.byref(value))
    result = subprocess.run(['powercfg', '/getactivescheme'], capture_output=True,
                            text=True, check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    return dict(timestamp=stamp(), ac_online=value.ac == 1, ac_raw=value.ac,
                power_plan=result.stdout.strip(), affinity_mask=1,
                frequency='Reliable effective search-core frequency unavailable; nominal clocks not substituted',
                thermal='Reliable temperature/throttling unavailable',
                nitrosense='Quiet / Eco last user-confirmed; current setting not independently exposed')


def identities():
    manifest = common.load(OLD / 'manifest.json')['files']
    found = {}
    for b, path in BINARIES.items():
        for p in [path, path.with_suffix('.pdb')]:
            rel = p.relative_to(REPO).as_posix()
            expected = manifest[rel]['sha256']
            actual = common.sha(p)
            assert actual == expected, (rel, actual, expected)
            found[rel] = actual
    assert found[BINARIES['baseline'].relative_to(REPO).as_posix()] == 'e64146bf7ccf219d3254d258615408e4b782c4aa7b430c9140beb73228055d4d'
    model = REPO / 'StockBear_NNUE_training/scaling-experiment-20261016/artifacts'
    for path, expected in [(model / 'medium/best.pt', '7d9ca27194e664f5f1d42fe8e4a5d4bac2f600a989405df9d91512555abb8264'),
                           (model / 'native/medium/medium.sbnnue', 'a08ce2c60280c8c6dffbbe2f653b6c481e8d5282be7bed203db8b72492b0a2d3')]:
        assert common.sha(path) == expected
        found[path.relative_to(REPO).as_posix()] = expected
    # These EXEs embed identical generated weights; they do not load a new model at runtime.
    for path in (OLD / 'artifacts/generated').glob('*'):
        if path.is_file():
            rel = path.relative_to(REPO).as_posix()
            assert common.sha(path) == manifest[rel]['sha256']
            found[rel] = common.sha(path)
    return dict(files=found, manifest_sha256=common.sha(OLD / 'manifest.json'),
                baseline_commit='f397a5af002900bbc15a7261dc6027c48daaeff4',
                study_parent='3aaaf5046993c154793845a4e865d9fd51832dec',
                model_contract='Identical frozen embedded generated float weights, matching archived checkpoint/export; no runtime export substitution',
                provenance=[str(OLD / 'build-hiddenclip-engine.json'),
                            str(REPO / 'nnue-optimization-stage1-20261017/build-variant-engine.json')],
                flags='Zig 0.13 / Clang 18.1.6, C++17 -O2 -pthread -Wall -Wextra -ffp-contract=off -DCHESSLAB_NNUE_UPDATE=2; no rebuild')


def snapshot():
    paths = set(common.load(OLD / 'preservation-before.json'))
    paths.update(common.load(OLD / 'manifest.json')['files'])
    paths.add('nnue-optimization-stage3-20261017/manifest.json')
    return {rel: common.sha(REPO / rel) for rel in sorted(paths)}


def endgames():
    fixtures = [
        ('pawn_opposition', 'pawn/quiet/few_moves', '8/8/4k3/4p3/4P3/4K3/8/8 w - - 0 1'),
        ('pawn_wings', 'pawn/quiet', '8/p5pk/1p6/3p4/3P4/1P3K2/P5PP/8 w - - 0 1'),
        ('pawn_race', 'pawn/promotion', '8/6k1/1P6/8/8/6p1/1K6/8 w - - 0 1'),
        ('rook_active', 'rook/quiet', '6k1/5pp1/8/4r3/8/4R3/5PP1/6K1 w - - 0 1'),
        ('rook_check', 'rook/in_check', '7k/6pp/8/8/8/5P2/6rP/R5K1 w - - 0 1'),
        ('rook_capture', 'rook/tactical_capture', '6k1/5pp1/8/8/3r4/3R4/5PP1/6K1 w - - 0 1'),
        ('knight_pawns', 'minor/knight', '8/5pk1/6p1/3n4/8/3N2P1/5PK1/8 w - - 0 1'),
        ('bishop_pawns', 'minor/bishop', '8/5pk1/4b1p1/8/8/6P1/2B2PK1/8 w - - 0 1'),
        ('bishop_knight', 'minor/imbalance', '8/5pk1/6p1/3n4/8/6P1/2B2PK1/8 w - - 0 1'),
        ('queen_rook', 'piece/imbalance/many_moves', '6k1/5pp1/8/4r3/8/3Q4/5PP1/6K1 w - - 0 1'),
        ('rook_minor', 'piece/imbalance', '6k1/5pp1/3b4/8/8/4R3/5PP1/6K1 w - - 0 1'),
        ('queen_checks', 'piece/queen/many_moves', '6k1/5pp1/8/3q4/8/3Q4/5PP1/6K1 w - - 0 1'),
    ]
    rows = []
    for i, (name, category, fen) in enumerate(fixtures):
        board = chess.Board(fen)
        assert board.is_valid() and not board.is_game_over(), (name, board.status())
        rows.append(dict(id=name, category=category, fen=fen, group=f'composition_{i+1:02}',
                         origin='Independent hand-composed material/category fixture, selected before any candidate timings; not extracted from a game or dataset',
                         legal_moves=board.legal_moves.count(), in_check=board.is_check(),
                         legal_captures=sum(board.is_capture(m) for m in board.legal_moves)))
    return rows


def freeze():
    assert not (ROOT / 'validation-plan.json').exists(), 'Frozen plan exists'
    save('binary-identities.json', identities())
    save('preservation-before.json', snapshot())
    (ROOT / 'general-positions.json').write_bytes((OLD / 'positions.json').read_bytes())
    general = load('general-positions.json')
    new = endgames()
    save('endgame-positions.json', new)
    sentinel = next(x for x in general if x['id'] == 'piece_endgame')
    save('sentinel.json', sentinel)
    rng = random.Random(2026101731)
    schedule = []
    # Each round mixes suites, controls and positions; every position/control has exact order balance.
    choices = {}
    for suite, rows, repeats, controls in [('general', general, 10, [x for x in CONTROLS if x != ('time', 200)]),
                                          ('endgame', new, 12, CONTROLS), ('sentinel', [sentinel], 12, CONTROLS)]:
        for row in rows:
            for mode, budget in controls:
                orders = [0, 1] * (repeats // 2)
                rng.shuffle(orders)
                choices[(suite, row['id'], mode, budget)] = orders
    for repeat in range(12):
        blocks = []
        for suite, rows, repeats in [('general', general, 10), ('endgame', new, 12), ('sentinel', [sentinel], 12)]:
            if repeat >= repeats:
                continue
            for row in rows:
                controls = [x for x in CONTROLS if suite != 'general' or x != ('time', 200)]
                rng.shuffle(controls)
                pairs = []
                for mode, budget in controls:
                    order = ['baseline', 'hiddenclip']
                    if choices[(suite, row['id'], mode, budget)][repeat]:
                        order.reverse()
                    pairs.append(dict(mode=mode, budget=budget, order=order))
                blocks.append(dict(suite=suite, position=row['id'], repeat=repeat, pairs=pairs))
        rng.shuffle(blocks)
        for block in blocks:
            schedule.append(dict(block_id=len(schedule), **block))
    save('schedule.json', schedule)
    plan = dict(frozen_utc=stamp(), seed=2026101731, options=common.load(OLD / 'plan.json')['options'],
                affinity=1, threads=1, hash_mb=16, fresh_tt='game=object() per search; full histories',
                schedule_sha256=common.sha(ROOT / 'schedule.json'),
                general_positions_sha256=common.sha(ROOT / 'general-positions.json'),
                endgame_positions_sha256=common.sha(ROOT / 'endgame-positions.json'),
                sentinel_sha256=common.sha(ROOT / 'sentinel.json'),
                general_repeats=10, endgame_and_sentinel_repeats=12,
                expected_searches=sum(2 * len(b['pairs']) for b in schedule),
                estimated_runtime_minutes=[30, 45], maximum_benchmark_seconds=5400,
                statistic='exp(mean(per-position median(log(paired candidate wall-NPS / baseline wall-NPS)))); fixed nodes equivalent inverse wall time',
                uncertainty='10000 hierarchical bootstrap draws: positions/groups then paired repeats; sentinel repeat-only. Seed 2026101731. Circular moving-block repeat bootstrap length 2 and early/late halves as dependence sensitivities. No multiplicity correction; not universal/random-workload confidence.',
                environment_policy=dict(preblock_probe_seconds=0.5, other_cpu_pause_threshold=20,
                    pause_seconds=5, max_pauses_per_block=3, flag_threshold=25,
                    retain_flagged_results=True, excessive_flagged_block_fraction=0.25,
                    ac_and_power_plan='Check before/after every position/repeat block; stop on change; do not alter settings',
                    invalid='Engine crash, illegal/protocol failure or externally verified power/plan interruption only. Preserve partial pair and reason, stop; never remove inconvenient performance. Resume repeats only incomplete pairs; prior valid pairs retained.'),
                material_factor=1 / 1.03,
                decisions=dict(
                    accepted='Exact identities/correctness; general 1M and 1000ms grouped lower95 > 1 and both order point estimates >1; no other aggregate upper95<1; endgame100ms lower95>1/1.03; no established or unresolved material regression; <=25% flagged blocks, stable-block and length2 bootstrap long-control points/intervals do not contradict gain.',
                    established_regression='Per-position repeat95 upper bound <1/1.03, or endgame100ms grouped upper95<1/1.03. Classify REJECTED. Intervals are unadjusted; inspect consistency across orders/controls.',
                    unresolved='Observed material median is not automatically a defect: flag as unresolved if repeat95 upper<1 but >=1/1.03, or both order medians<1/1.03 AND a second control on same fixture has material median. Isolated short-time material medians whose intervals include1 may be noise only if both 1M and1000ms fixture points>1 and no consistent neighboring-control/order loss; otherwise INCONCLUSIVE.',
                    rejected='Correctness failure, established material regression, or both general long-control upper95<=1 (gain disappears).',
                    inconclusive='Any other failure of acceptance, excessive environment noise, conflicting CPU/wall or temporal/order evidence, incomplete schedule, unresolved concerning regression.'),
                restrictions='Validation only; exact preserved executables; no rebuild, optimization, training, labeling, sealed split, tournaments or production promotion')
    save('validation-plan.json', plan)
    print(f'Frozen {len(schedule)} blocks / {plan["expected_searches"]} searches; 30-45 minute estimate, 90-minute hard benchmark budget', flush=True)


def check_plan():
    plan = load('validation-plan.json')
    for name, key in [('schedule.json', 'schedule_sha256'), ('general-positions.json', 'general_positions_sha256'),
                      ('endgame-positions.json', 'endgame_positions_sha256'), ('sentinel.json', 'sentinel_sha256')]:
        assert common.sha(ROOT / name) == plan[key]
    assert identities() == load('binary-identities.json')
    return plan


def engines(stack):
    result = {}
    for name, path in BINARIES.items():
        engine = stack.enter_context(open_engine(path))
        assert engine.options['Evaluator'].default == 'classical'
        engine.configure(load('validation-plan.json')['options'])
        assert affinity(engine.transport.get_pid()) == 1
        result[name] = engine
    return result


def work_equal(a, b):
    assert canonical(a) == canonical(b), (a['position'], a['mode'], a['budget'])
    clean = lambda x: [{k: v for k, v in r.items() if k not in ['seconds', 'nps']} for r in x['iterations']]
    assert clean(a) == clean(b), 'Completed iteration mismatch'


def correctness():
    check_plan()
    pin()
    rows = load('general-positions.json') + load('endgame-positions.json')
    receipt = dict(timestamp=stamp(), fixed_work=[], cancellation=[], uci={}, historical={})
    with ExitStack() as stack:
        players = engines(stack)
        for name, engine in players.items():
            receipt['uci'][name] = {k: dict(default=v.default, type=v.type) for k, v in engine.options.items()}
        assert receipt['uci']['baseline'] == receipt['uci']['hiddenclip']
        for row in rows:
            a, b = [capture(players[name], row, 'nodes', 200000) for name in players]
            work_equal(a, b)
            receipt['fixed_work'].append(dict(baseline=a, hiddenclip=b))
        for row in [rows[0], rows[4], rows[13], rows[16]]:
            for name, engine in players.items():
                board = chess.Board(row['fen'])
                with engine.analysis(board, game=object()) as analysis:
                    for info in analysis:
                        if info.get('depth', 0) >= 3:
                            time.sleep(0.007)
                            analysis.stop()
                            break
                    result = analysis.wait()
                assert result.move in board.legal_moves
                receipt['cancellation'].append(dict(position=row['id'], binary=name, legal_move=result.move.uci()))
            a, b = [capture(players[name], row, 'nodes', 200000) for name in players]
            work_equal(a, b)
        for name in players:
            players[name].configure({'Evaluator': 'classical'})
        receipt['classical'] = []
        for row in [rows[0], rows[4], rows[-1]]:
            a, b = [capture(players[name], row, 'nodes', 200000) for name in players]
            work_equal(a, b)
            assert a['counters']['nnue_evaluations'] == b['counters']['nnue_evaluations'] == 0
            receipt['classical'].append(dict(baseline=a, hiddenclip=b))
    # Check production UCI executables, excluding standalone test/benchmark programs.
    active_paths = [REPO / 'engine/build' / name for name in
                    ['chesslab-engine.exe', 'stockbear-v2-compact.exe', 'stockbear-v2-small.exe']]
    receipt['active_defaults'] = {}
    for active in active_paths:
        with open_engine(active) as engine:
            assert engine.options['Evaluator'].default == 'classical'
            receipt['active_defaults'][str(active.relative_to(REPO))] = 'classical'
    assert receipt['active_defaults'], 'No active executable checked'
    for name in ['correctness-hiddenclip.json', 'regressions-hiddenclip.json', 'regressions-restore-hiddenclip.json']:
        old = common.load(OLD / name)
        assert old['passed']
        receipt['historical'][name] = dict(sha256=common.sha(OLD / name), reused=True)
    receipt['passed'] = True
    save('correctness.json', receipt)
    print('Fresh 24-position fixed-work, eight stop checks, post-stop parity, classical and UCI/default gates passed', flush=True)


def read_lines(name):
    path = ROOT / name
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line]


def run():
    plan = check_plan()
    assert load('correctness.json')['passed']
    pin()
    rows = {('general', r['id']): r for r in load('general-positions.json')}
    rows.update({('endgame', r['id']): r for r in load('endgame-positions.json')})
    rows[('sentinel', 'piece_endgame')] = load('sentinel.json')
    completed = {x['pair_id'] for x in read_lines('pairs.jsonl')}
    expected = {f'{b["block_id"]}:{i}' for b in load('schedule.json') for i, _ in enumerate(b['pairs'])}
    assert completed <= expected
    if completed == expected:
        assert snapshot() == load('preservation-before.json')
        print('Frozen schedule already complete; no engines started or measurements added', flush=True)
        return
    telemetry = read_lines('blocks.jsonl')
    consumed = sum(b.get('elapsed_seconds', 0) for b in telemetry)
    start = time.monotonic()
    append('events.jsonl', dict(event='run_or_resume', timestamp=stamp(), completed_pairs=len(completed)))
    expected_plan = environment()['power_plan']
    save('environment-before.json', environment())
    with ExitStack() as stack:
        players = engines(stack)
        meter = Meter([os.getpid()] + [e.transport.get_pid() for e in players.values()])
        stack.callback(meter.close)
        handles = {name: k.OpenProcess(0x1000, False, e.transport.get_pid()) for name, e in players.items()}
        for h in handles.values():
            assert h
            stack.callback(k.CloseHandle, h)
        # Identical untimed warm-up, excluded and recorded, before randomized study.
        warm = rows[('general', 'opening')]
        for name in players:
            capture(players[name], warm, 'nodes', 25000)
        append('events.jsonl', dict(event='symmetric_warmup', timestamp=stamp(), nodes_each=25000))
        for block in load('schedule.json'):
            bid = block['block_id']
            todo = [(i, pair) for i, pair in enumerate(block['pairs']) if f'{bid}:{i}' not in completed]
            if not todo:
                continue
            if consumed + time.monotonic() - start > plan['maximum_benchmark_seconds']:
                append('events.jsonl', dict(event='budget_stop', timestamp=stamp()))
                raise RuntimeError('Frozen benchmark runtime budget exhausted')
            began = time.monotonic()
            before = environment()
            assert before['ac_online'] and before['power_plan'] == expected_plan, 'Power interruption before block'
            meter.previous = meter.snapshot()
            time.sleep(0.5)
            probe = meter.read()
            for pause in range(3):
                if probe['other_cpu_percent_estimate'] <= 20:
                    break
                append('events.jsonl', dict(event='background_pause', timestamp=stamp(), block_id=bid,
                                           pause=pause, probe=probe, seconds=5))
                time.sleep(5)
                probe = meter.read()
            segment_rows = []
            for i, pair in todo:
                pair_id = f'{bid}:{i}'
                recorded = []
                try:
                    for name in pair['order']:
                        meter.previous = meter.snapshot()
                        cpu = cpu_seconds(handles[name])
                        at = stamp()
                        result = capture(players[name], rows[(block['suite'], block['position'])], pair['mode'], pair['budget'])
                        cpu_delta = cpu_seconds(handles[name]) - cpu
                        load_delta = meter.read()
                        result.update(binary=name, binary_sha256=load('binary-identities.json')['files'][BINARIES[name].relative_to(REPO).as_posix()],
                                      pair_id=pair_id, block_id=bid, suite=block['suite'], repeat=block['repeat'],
                                      order=pair['order'], order_index=len(recorded), timestamp=at,
                                      process_cpu_seconds=cpu_delta, wall_nps=result['nodes'] / result['wall_seconds'],
                                      cpu_nps=result['nodes'] / cpu_delta if cpu_delta > 0 else None,
                                      background=load_delta, affinity_mask=affinity(players[name].transport.get_pid()))
                        assert result['affinity_mask'] == 1
                        recorded.append(result)
                    if pair['mode'] == 'nodes':
                        work_equal(*recorded)
                        assert recorded[0]['nodes'] == recorded[1]['nodes'] == pair['budget']
                    append('pairs.jsonl', dict(pair_id=pair_id, records=recorded))
                    completed.add(pair_id)
                    segment_rows.extend(recorded)
                except BaseException as error:
                    append('discarded.jsonl', dict(pair_id=pair_id, partial_records=recorded, error=repr(error),
                                                  timestamp=stamp(), policy='Stop on objective failure; preserve evidence; no performance-based exclusions'))
                    raise
            after = environment()
            loads = [r['background']['other_cpu_percent_estimate'] for r in segment_rows]
            flagged = probe['other_cpu_percent_estimate'] > 25 or any(v > 25 for v in loads)
            power_valid = after['ac_online'] and after['power_plan'] == expected_plan
            append('blocks.jsonl', dict(block_id=bid, before=before, after=after, probe=probe,
                                       elapsed_seconds=time.monotonic()-began, flagged_background=flagged,
                                       power_valid=power_valid, completed_pairs=len(completed)))
            if not power_valid:
                append('events.jsonl', dict(event='power_interruption', block_id=bid, timestamp=stamp()))
                raise RuntimeError('External power/plan interruption; retain block and stop for audit')
            save('progress.json', dict(timestamp=stamp(), completed_searches=2*len(completed),
                                      expected_searches=plan['expected_searches'], elapsed_seconds=consumed+time.monotonic()-start))
            print(f'{2*len(completed)}/{plan["expected_searches"]} searches; block {bid+1}; {consumed+time.monotonic()-start:.0f}s elapsed', flush=True)
    save('environment-after.json', environment())
    assert snapshot() == load('preservation-before.json'), 'Protected artifact changed'
    save('preservation-after.json', dict(passed=True, files=len(load('preservation-before.json')), timestamp=stamp()))
    assert len(completed)*2 == plan['expected_searches']
    print('Frozen schedule complete; all protected artifacts unchanged', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['freeze', 'correctness', 'run', 'integrity'])
    args = parser.parse_args()
    if args.action == 'integrity':
        check_plan()
        assert snapshot() == load('preservation-before.json')
        print('Exact identities, frozen plan and preservation verified')
    else:
        globals()[args.action]()
