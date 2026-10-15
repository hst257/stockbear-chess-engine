"""Validate diagnostic sampling, score perspectives and real counter oracles."""
from __future__ import annotations

import json
import os
from pathlib import Path

import chess
import pytest

from tools.analyze_nnue_diagnosis import bootstrap, candidate_quality, pair_scores
from tools.nnue_diagnosis import capture, open_engine, positions


def test_stratified_positions_are_legal_and_nonterminal():
    rows = positions()
    assert len(rows) == 24 and len({r["category"] for r in rows}) == 12
    assert len({r["fen"] for r in rows}) == 24
    assert all(chess.Board(r["fen"]).is_valid() for r in rows)


def test_paired_analysis_excludes_censored_pairs_without_calling_them_draws():
    games = [{"pair": 1, "candidate_outcome": "win"}, {"pair": 1, "candidate_outcome": "loss"},
             {"pair": 2, "candidate_outcome": "win"}, {"pair": 2, "candidate_outcome": "unfinished"}]
    assert pair_scores(games) == {1: .5}
    assert bootstrap([.5] * 10) == [.5, .5]
    assert bootstrap([0, .25, .75, 1]) == bootstrap([0, .25, .75, 1])


def test_candidate_quality_uses_same_child_context_and_keeps_mates_separate():
    reference = {"root": {"move": "a2a3", "score_root": {"cp": 130, "mate": None}},
                 "candidates": {"a2a3": {"score_root": {"cp": 100, "mate": None}},
                                "b2b3": {"score_root": {"cp": -20, "mate": None}},
                                "c2c3": {"score_root": {"cp": None, "mate": -2}}}}
    assert candidate_quality(reference, "b2b3")["loss_cp"] == 120
    assert candidate_quality(reference, "c2c3")["loss_cp"] is None
    assert candidate_quality(reference, "a2a3")["sf_best_agreement"]


def test_frozen_schedule_is_nested_and_exactly_190_games():
    root = Path("docs/nnue-v2-diagnosis")
    plan = json.loads((root / "match-plan.json").read_text(encoding="utf-8"))
    assert [(m["movetime"], m["games"]) for m in plan["schedule"]] == [(50, 80), (200, 60), (500, 30), (1000, 20)]
    assert sum(m["games"] for m in plan["schedule"]) == 190
    book = json.loads((root / "openings.json").read_text(encoding="utf-8"))["openings"]
    assert len(book) == 40 and len({o["family"] for o in book}) == 20
    for opening in book:
        board = chess.Board()
        for move in opening["moves"]:
            board.push_uci(move)
        assert board.fen() == opening["fen"]


@pytest.mark.skipif(not os.environ.get("CHESSLAB_DIAGNOSTIC_ENGINE"), reason="Explicit diagnostic build required")
def test_accumulator_counters_match_the_exhaustive_depth_one_oracle():
    with open_engine(Path(os.environ["CHESSLAB_DIAGNOSTIC_ENGINE"])) as engine:
        engine.configure({"Evaluator": "nnue", "NNUEKernel": "scalar", "AlphaBeta": False,
                          "IterativeDeepening": False, "Quiescence": False, "TranspositionTable": False})
        result = capture(engine, {"id": "oracle", "fen": chess.STARTING_FEN}, "depth", 1)
        d = result["diagnostics"]
        assert result["nodes"] == d["visits"] == 21
        assert d["updates"] == d["copies"] == d["evaluated_visits"] == 20
        assert d["delta_rows"] == 40 and d["delta_histogram"][2] == 20
        assert d["copy_payload_bytes"] == 20 * 408
        assert d["evaluation_calls"] == 20 and d["refreshes"] == 1
        assert d["unused_updates"] == d["null_updates"] == d["qvisits"] == 0
        assert d["pending_edges"] == 20 and d["pending_rows"] == 40
