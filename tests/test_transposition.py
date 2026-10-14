"""Verify the actual C++ table and cached/uncached engine searches."""

import json
import os
from pathlib import Path
import subprocess
import sys

import chess
import chess.engine
import pytest

from app.engine_client import table_stats

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="session")
def native_tests():
    result = subprocess.run([sys.executable, "tools/build_engine.py", "--target", "tt-tests"],
                            cwd=ROOT, capture_output=True, text=True, timeout=90)
    assert result.returncode == 0, result.stdout + result.stderr
    return ROOT / "engine/build" / ("chesslab-tt-tests.exe" if os.name == "nt" else "chesslab-tt-tests")


@pytest.mark.parametrize("group", ["hashes", "bounds", "storage", "histories", "quiescence", "pvs"])
def test_native_table_and_zobrist_invariants(native_tests, group):
    result = subprocess.run([str(native_tests), group], capture_output=True, text=True, timeout=5)
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.strip() == f"{group} passed"


POSITIONS = [
    chess.STARTING_FEN,
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "7k/8/8/1p6/p7/Q7/8/7K w - - 0 1",
    "8/5pk1/6p1/8/3K4/6P1/5P2/8 w - - 0 1",
    "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1",
    "7k/8/8/3pP3/8/8/8/7K w - d6 0 2",
    "1r5k/P7/8/8/8/8/8/7K w - - 0 1",
    "7k/8/5KQ1/8/8/8/8/8 w - - 0 1",
]


@pytest.mark.parametrize("fen", POSITIONS)
@pytest.mark.parametrize("pruning", [False, True])
@pytest.mark.parametrize("iterative", [False, True])
@pytest.mark.parametrize("pst", [False, True])
def test_cache_preserves_fixed_depth_score_and_full_legal_pv(engine, engine_path, fen, pruning, iterative, pst):
    board = chess.Board(fen)
    results = []
    for cached in (False, True):
        engine.configure({"AlphaBeta": pruning, "IterativeDeepening": iterative, "UsePST": pst,
                          "MoveOrdering": True, "TranspositionTable": cached, "Hash": 1})
        result = engine.play(board, chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
        assert result.info["depth"] == 3 and result.move in board.legal_moves
        pv_board = board.copy()
        for move in result.info["pv"]:
            assert move in pv_board.legal_moves
            pv_board.push(move)
        assert len(result.info["pv"]) == 3 or pv_board.is_game_over(claim_draw=True)
        if not pv_board.is_game_over(claim_draw=True):
            args = [str(engine_path), "--eval", *([] if pst else ["--no-pst"]), pv_board.fen()]
            evaluated = subprocess.run(args, capture_output=True, text=True, check=True, timeout=3)
            assert json.loads(evaluated.stdout)["total"] == result.info["score"].white().score()
        results.append(result)
    plain, cached = results
    assert plain.info["score"] == cached.info["score"]
    # Ties may select a different move. Prove the cached move's value independently
    # by searching its child exhaustively without any table or ordering hints.
    child = board.copy()
    child.push(cached.move)
    engine.configure({"AlphaBeta": False, "TranspositionTable": False, "IterativeDeepening": False,
                      "MoveOrdering": False})
    reply = engine.play(child, chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
    if not cached.info["score"].white().is_mate():
        assert reply.info["score"].white() == cached.info["score"].white()
    else:
        assert reply.info["score"].white().is_mate()


def test_cache_has_real_hits_cutoffs_and_reduces_work(engine):
    results = []
    for cached in (False, True):
        engine.configure({"UsePST": True, "TranspositionTable": cached, "AlphaBeta": True})
        results.append(engine.play(chess.Board(), chess.engine.Limit(depth=5), info=chess.engine.INFO_ALL))
    off, on = results
    assert off.info["score"] == on.info["score"]
    assert off.move == on.move
    assert table_stats(off.info) == {"probes": 0, "hits": 0, "cutoffs": 0}
    counters = table_stats(on.info)
    assert counters["probes"] >= counters["hits"] >= counters["cutoffs"] > 0
    assert on.info["nodes"] < off.info["nodes"]
    assert 0 < on.info["hashfull"] <= 1000


@pytest.mark.parametrize("clock", [0, 98, 99, 100])
def test_halfmove_draw_context_never_changes_cached_score(engine, clock):
    board = chess.Board(f"7k/8/8/8/8/8/R7/7K w - - {clock} 51")
    results = []
    for cached in (False, True):
        engine.configure({"TranspositionTable": cached, "UsePST": True})
        results.append(engine.play(board, chess.engine.Limit(depth=4), info=chess.engine.INFO_ALL))
    assert results[0].info["score"] == results[1].info["score"]
    if clock == 100:
        assert not results[1].move


@pytest.mark.parametrize("cycles", [1, 2])
def test_pre_root_repetition_history_is_respected(engine, cycles):
    board = chess.Board("7k/8/8/8/8/8/R7/7K w - - 0 1")
    for _ in range(cycles):
        for move in ("h1g1", "h8g8", "g1h1", "g8h8"):
            board.push_uci(move)
    results = []
    for cached in (False, True):
        engine.configure({"TranspositionTable": cached, "UsePST": True})
        results.append(engine.play(board, chess.engine.Limit(depth=4), info=chess.engine.INFO_ALL))
    assert results[0].info["score"] == results[1].info["score"]
    if cycles == 2:
        assert not results[1].move and results[1].info["score"].white().score() == 0
        # Identical FEN has no known pre-root repetitions when its stack is absent.
        without_history = engine.play(chess.Board(board.fen()), chess.engine.Limit(depth=4),
                                      info=chess.engine.INFO_ALL)
        assert without_history.move in chess.Board(board.fen()).legal_moves
        assert without_history.info["score"].white().score() > 0


def test_each_search_starts_fresh_and_evaluation_modes_do_not_share_entries(engine):
    engine.configure({"UsePST": True, "TranspositionTable": True, "Hash": 1})
    first = engine.play(chess.Board(), chess.engine.Limit(depth=4), info=chess.engine.INFO_ALL)
    engine.configure({"UsePST": False})
    material = engine.play(chess.Board(), chess.engine.Limit(depth=4), info=chess.engine.INFO_ALL)
    engine.configure({"UsePST": True})
    again = engine.play(chess.Board(), chess.engine.Limit(depth=4), info=chess.engine.INFO_ALL)
    for key in ("nodes", "score", "pv", "hashfull"):
        assert first.info[key] == again.info[key]
    assert table_stats(first.info) == table_stats(again.info)
    assert material.move in chess.Board().legal_moves
