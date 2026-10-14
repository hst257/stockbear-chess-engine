"""Published perft references, independent tactical checks and full-state undo."""
import os
from pathlib import Path
import subprocess
import sys

import chess
import chess.engine
import pytest

from tools.audit_engine import PERFT


@pytest.mark.parametrize("name,fen,counts", PERFT)
def test_published_perft_positions(engine_path, name, fen, counts):
    for depth, expected in enumerate(counts, 1):
        actual = int(subprocess.check_output([str(engine_path), "--perft", str(depth), fen], text=True, timeout=20))
        assert actual == expected, (name, depth, fen)


def test_full_native_make_unmake_and_history():
    subprocess.run([sys.executable, "tools/build_engine.py", "--target", "audit-tests"], check=True, timeout=90)
    executable = Path("engine/build/chesslab-audit-tests" + (".exe" if os.name == "nt" else ""))
    result = subprocess.check_output([str(executable.resolve())], text=True, timeout=30)
    assert "complete history" in result


def forced_mate(board, plies):
    """Independent exhaustive legal-move oracle: can the current attacker force mate?"""
    attacker = board.turn
    def visit(remaining):
        if board.is_checkmate():
            return board.turn != attacker
        if remaining == 0 or board.is_game_over(claim_draw=True):
            return False
        outcomes = []
        for move in board.legal_moves:
            board.push(move)
            outcomes.append(visit(remaining - 1))
            board.pop()
        return any(outcomes) if board.turn == attacker else all(outcomes)
    return visit(plies)


@pytest.mark.parametrize("fen,mate", [
    ("7k/8/5KQ1/8/8/8/8/8 w - - 0 1", 1),
    ("7k/4Q3/8/5K2/8/8/8/8 w - - 0 1", 2),
    ("4kb1r/p2n1ppp/4q3/4p1B1/4P3/1Q6/PPP2PPP/2KR4 w k - 0 16", 2),
])
def test_verified_mate_corpus_with_all_features(engine_path, fen, mate):
    board = chess.Board(fen)
    assert forced_mate(board, 2 * mate - 1)
    with chess.engine.SimpleEngine.popen_uci(str(engine_path)) as engine:
        result = engine.play(board, chess.engine.Limit(depth=5), info=chess.engine.INFO_ALL)
        assert result.move in board.legal_moves
        assert result.info["score"].relative.mate() == mate
        if mate == 1:
            board.push(result.move)
            assert board.is_checkmate()


@pytest.mark.parametrize("fen,expected", [
    ("7k/8/8/8/8/8/q7/R6K w - - 0 1", "a1a2"),
    ("4k3/8/8/8/q7/8/4B3/4R2K w - - 0 1", "e2b5"),  # discovered double-check
    ("k3r3/8/8/8/8/8/4R3/4K3 w - - 0 1", "e2e8"),  # pinned rook captures pinner
    ("8/8/8/8/8/5k2/8/5r1K w - - 0 1", "h1h2"),  # sole quiet evasion  # forced queen capture
    ("8/1q3k2/8/8/2N5/8/8/6K1 w - - 0 1", "c4d6"),  # fork queen and king
])
def test_material_tactics(engine_path, fen, expected):
    board = chess.Board(fen)
    with chess.engine.SimpleEngine.popen_uci(str(engine_path)) as engine:
        result = engine.play(board, chess.engine.Limit(depth=4), info=chess.engine.INFO_ALL)
        assert result.move.uci() == expected
