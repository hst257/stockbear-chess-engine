"""Published perft references, independent tactical checks and full-state undo."""
import os
from pathlib import Path
import subprocess
import sys

import chess
import chess.engine
import pytest

from tools.audit_engine import PERFT
from tools.audit_engine import measure


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
    ("8/8/8/8/8/5k2/8/5r1K w - - 0 1", "h1h2"),  # sole quiet evasion
    ("8/1q3k2/8/8/2N5/8/8/6K1 w - - 0 1", "c4d6"),  # fork queen and king
])
def test_material_tactics(engine_path, fen, expected):
    board = chess.Board(fen)
    with chess.engine.SimpleEngine.popen_uci(str(engine_path)) as engine:
        result = engine.play(board, chess.engine.Limit(depth=4), info=chess.engine.INFO_ALL)
        assert result.move.uci() == expected


@pytest.mark.parametrize("fen", [fen for _, fen, _ in PERFT])
def test_pawn_cache_preserves_all_search_work(engine_path, fen):
    with chess.engine.SimpleEngine.popen_uci(str(engine_path)) as engine:
        assert engine.options["PawnCache"].default is True
        results = []
        for enabled in (False, True):
            engine.configure({"PawnCache": enabled})
            results.append(measure(engine, chess.Board(fen), depth=4))
        for key in ("depth", "nodes", "qnodes", "score", "move", "pv"):
            assert results[0][key] == results[1][key]
        assert results[0]["counters"]["pawn_probes"] == 0
        assert results[1]["counters"]["pawn_probes"] == results[1]["counters"]["eval_calls"]
        assert results[1]["counters"]["pawn_hits"] > 0


@pytest.mark.parametrize("fen", [fen for _, fen, _ in PERFT] + [
    "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",  # stalemate before stand pat
    "7k/6Q1/5K2/8/8/8/8/8 b - - 100 51",  # mate before fifty-move draw
    "7k/8/8/3pP3/8/8/8/7K w - d6 0 2",  # en passant
])
@pytest.mark.parametrize("qsearch,ordering,pruning", [(True, True, True), (True, False, True),
                                                       (False, True, True), (True, True, False)])
def test_fast_movegen_preserves_search_semantics(engine_path, fen, qsearch, ordering, pruning):
    with chess.engine.SimpleEngine.popen_uci(str(engine_path), timeout=30) as engine:
        assert engine.options["FastMovegen"].default is True
        engine.configure({"Quiescence": qsearch, "MoveOrdering": ordering, "AlphaBeta": pruning})
        rows = []
        for enabled in (False, True):
            engine.configure({"FastMovegen": enabled})
            rows.append(measure(engine, chess.Board(fen), depth=3 if pruning else 2,
                                nodes=50000 if not ordering or not pruning else None))
        for key in ("depth", "nodes", "qnodes", "score", "move", "pv"):
            assert rows[0][key] == rows[1][key]


@pytest.mark.parametrize("fen,drawn", [
    ("7k/8/8/6B1/8/4B3/8/K1B5 w - - 0 1", True),
    ("5b1k/8/8/6B1/8/4B3/8/K1B5 w - - 0 1", True),
    ("7k/8/8/8/8/2N1N3/8/K7 w - - 0 1", False),
    ("7k/8/8/8/8/4N3/8/K1B5 w - - 0 1", False),
])
@pytest.mark.parametrize("mirror", [False, True])
def test_promoted_bishop_draws_and_mating_material(engine_path, fen, drawn, mirror):
    board = chess.Board(fen)
    if mirror:
        board = board.mirror()
    assert board.is_insufficient_material() == drawn
    with chess.engine.SimpleEngine.popen_uci(str(engine_path)) as engine:
        result = engine.play(board, chess.engine.Limit(depth=1), info=chess.engine.INFO_ALL)
        assert bool(result.move) != drawn
        if drawn:
            assert result.info["score"].white().score() == 0


@pytest.mark.parametrize("halfmove", [100, 150, 255, 256, 300, 65535])
def test_large_fen_halfmove_clocks_cannot_wrap_into_live_search(engine_path, halfmove):
    board = chess.Board(f"7k/8/8/8/8/8/R7/7K w - - {halfmove} 1000")
    with chess.engine.SimpleEngine.popen_uci(str(engine_path)) as engine:
        for advance in (False, True):
            if advance:
                board.push_uci("a2a3")
            result = engine.play(board, chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
            assert not result.move and result.info["score"].white().score() == 0


@pytest.mark.parametrize("fen,reset_move", [
    ("7k/8/8/8/8/8/P7/7K w - - 300 1000", "a2a3"),
    ("7k/8/8/8/8/8/q7/R6K w - - 300 1000", "a1a2"),
])
def test_saturated_input_clock_still_resets_after_pawn_move_or_capture(engine_path, fen, reset_move):
    board = chess.Board(fen)
    board.push_uci(reset_move)
    assert board.halfmove_clock == 0 and not board.is_game_over(claim_draw=True)
    with chess.engine.SimpleEngine.popen_uci(str(engine_path)) as engine:
        result = engine.play(board, chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
        assert result.move in board.legal_moves
