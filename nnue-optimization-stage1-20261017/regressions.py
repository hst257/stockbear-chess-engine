"""Golden-model, fallback, terminal and score-contract regression checks."""
import json
import os
import shutil
import subprocess
import experiment as p
import chess
import chess.engine

# Reuse already existing immutable 32/16 headers for the existing golden-score
# tests. This is compatibility checking, not an architecture experiment.
generated = p.ART / 'legacy-generated'
shutil.copytree(p.REPO / 'engine/build/generated', generated, dirs_exist_ok=True)
config = p.common.load(p.ROOT / 'build-variant-engine.json')
args = [str(generated) if a == str(p.ART / 'generated') else a for a in config['command']]
out = p.ART / 'legacy-engine.exe'
args[-1] = str(out)
p.command(args, 'legacy-golden-build')
p.save('build-legacy-golden.json', {'command': args, 'sha256': p.common.sha(out),
                                 'purpose': 'Existing original 32/16 model golden compatibility only'})
p.pin()
rows = p.common.load(p.REPO / 'engine/networks/stockbear-compact.golden.json')
results = []
for row in rows:
    values = {}
    for kernel in ('scalar', 'clip'):
        values[kernel] = json.loads(subprocess.check_output([str(out), '--eval', '--nnue', '--kernel', kernel, row['fen']], text=True))
        assert abs(values[kernel]['side_to_move_cp'] - row['side_to_move_cp']) < .01
    assert {k:v for k,v in values['scalar'].items() if k != 'kernel'} == {k:v for k,v in values['clip'].items() if k != 'kernel'}
    results.append({'fen': row['fen'], 'expected_cp': row['side_to_move_cp'], 'values': values})

binary = p.ART / 'variant/engine.exe'
fen = chess.STARTING_FEN
normal = json.loads(subprocess.check_output([str(binary), '--eval', '--nnue', '--kernel', 'scalar', fen], text=True))
fallback = json.loads(subprocess.check_output([str(binary), '--eval', '--nnue', '--kernel', 'clip', fen], text=True, env=dict(os.environ, CHESSLAB_DISABLE_SIMD='1')))
assert fallback == normal and fallback['kernel'] == 'scalar'

terminal_fens = ['7k/8/8/8/8/8/8/K7 w - - 0 1', '7k/8/8/8/8/8/8/KN6 w - - 0 1',
                 chess.STARTING_FEN.replace('0 1', '100 1'),
                 '7k/6Q1/5K2/8/8/8/8/8 b - - 0 1', '7k/5Q2/6K1/8/8/8/8/8 b - - 0 1']
terminals = []
with p.player('variant') as engine:
    for f in terminal_fens:
        board = chess.Board(f)
        r = engine.play(board, chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
        # python-chess may represent UCI 0000 as a falsey null Move.
        assert not r.move
        score = r.info['score'].pov(board.turn)
        assert score.mate() == 0 if board.is_checkmate() else score.score() == 0
        terminals.append({'fen': f, 'move': None, 'score': str(score)})

classical = []
with p.player('baseline') as a, p.player('variant') as b:
    a.configure({'Evaluator': 'classical'})
    b.configure({'Evaluator': 'classical'})
    for row in p.common.load(p.ROOT/'positions.json'):
        x = p.capture(a,row,'nodes',200000); y = p.capture(b,row,'nodes',200000)
        assert p.canonical(x) == p.canonical(y)
        assert x['counters']['nnue_evaluations'] == y['counters']['nnue_evaluations'] == 0
        classical.append({'position': row['id'], 'baseline': x, 'variant': y})
p.save('regressions.json', {'passed': True, 'legacy_model_golden_scores': results,
                          'fallback_original': normal, 'fallback_disabled_simd': fallback,
                          'terminals': terminals, 'classical_fixed_node_parity': classical})
print('Existing golden scores, disabled-SIMD fallback, terminal and classical parity passed',flush=True)
