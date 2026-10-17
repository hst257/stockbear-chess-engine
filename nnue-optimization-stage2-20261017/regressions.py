"""Interrupted UCI search, fallback, terminal and classical-preservation checks."""
import json
import os
import subprocess
import sys
import time
import chess
import chess.engine
import experiment as p

label = sys.argv[1]
p.pin()
data = {'interrupted': [], 'classical': [], 'terminal': []}
rows = p.common.load(p.ROOT / 'positions.json')
with p.player('baseline') as a, p.player(label) as b:
    for row in rows:
        board = chess.Board() if 'moves' in row else chess.Board(row['fen'])
        for move in row.get('moves', []):
            board.push_uci(move)
        assert board.fen() == row['fen']
        before = board.fen()
        for name, engine in [('baseline', a), (label, b)]:
            with engine.analysis(board, game=object()) as analysis:
                saw_depth = 0
                for info in analysis:
                    saw_depth = info.get('depth', saw_depth)
                    if saw_depth >= 3:
                        # Allow another unfinished iteration, then explicit stop.
                        time.sleep(.007)
                        analysis.stop()
                        break
                result = analysis.wait()
            assert result.move in board.legal_moves
            assert board.fen() == before
            data['interrupted'].append({'position': row['id'], 'build': name,
                 'completed_depth_before_stop': saw_depth, 'legal_move': result.move.uci(),
                 'board_unchanged': True})
        x, y = p.capture(a, row, 'nodes', 200000), p.capture(b, row, 'nodes', 200000)
        assert p.canonical(x) == p.canonical(y)
        data['interrupted'][-1]['post_stop_fixed_search_exact'] = True
    a.configure({'Evaluator': 'classical'})
    b.configure({'Evaluator': 'classical'})
    for row in rows:
        x, y = p.capture(a, row, 'nodes', 200000), p.capture(b, row, 'nodes', 200000)
        assert p.canonical(x) == p.canonical(y)
        assert x['counters']['nnue_evaluations'] == y['counters']['nnue_evaluations'] == 0
        data['classical'].append({'position': row['id'], 'baseline': x, 'variant': y})
with p.player(label) as engine:
    for fen in ['7k/8/8/8/8/8/8/K7 w - - 0 1',
                '7k/6Q1/5K2/8/8/8/8/8 b - - 0 1',
                '7k/5Q2/6K1/8/8/8/8/8 b - - 0 1',
                chess.STARTING_FEN.replace('0 1', '100 1')]:
        board = chess.Board(fen)
        r = engine.play(board, chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
        assert not r.move
        score = r.info['score'].pov(board.turn)
        assert score.mate() == 0 if board.is_checkmate() else score.score() == 0
        data['terminal'].append({'fen': fen, 'score': str(score)})
binary = str(p.ART / label / 'engine.exe')
original = json.loads(subprocess.check_output([binary, '--eval', '--nnue', '--kernel', 'scalar', chess.STARTING_FEN], text=True))
fallback = json.loads(subprocess.check_output([binary, '--eval', '--nnue', '--kernel', 'clip', chess.STARTING_FEN], text=True,
                     env=dict(os.environ, CHESSLAB_DISABLE_SIMD='1')))
assert original == fallback
data.update(passed=True, fallback_original=original, fallback_disabled_simd=fallback)
p.save('regressions-' + label + '.json', data)
print('Cancellation, rerun, terminal, scalar fallback and classical parity passed', flush=True)
