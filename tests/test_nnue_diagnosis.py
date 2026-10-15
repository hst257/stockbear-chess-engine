"""Validate diagnostic sampling, score perspectives and real counter oracles."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
from types import SimpleNamespace

import chess
import chess.engine
import pytest

from tools.analyze_nnue_diagnosis import bootstrap, candidate_quality, pair_scores, partial_pair_scores
from tools.nnue_diagnosis import capture, open_engine, positions
from tools.match_optimizations import version_match
from tools.verify_match_records import verify_record


def test_stratified_positions_are_legal_and_nonterminal():
    rows = positions()
    assert len(rows) == 24 and len({r["category"] for r in rows}) == 12
    assert len({r["fen"] for r in rows}) == 24
    assert all(chess.Board(r["fen"]).is_valid() for r in rows)


def test_paired_analysis_excludes_censored_pairs_without_calling_them_draws():
    games = [{"pair": 1, "candidate_outcome": "win"}, {"pair": 1, "candidate_outcome": "loss"},
             {"pair": 2, "candidate_outcome": "win"}, {"pair": 2, "candidate_outcome": "unfinished"}]
    assert pair_scores(games) == {1: .5}
    assert partial_pair_scores(games) == {1: [.5, .5], 2: [.5, 1.]}
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


def test_pilot_resume_retains_the_full_schedule_and_replayable_games(tmp_path, monkeypatch):
    class Player:
        id = {"name": "test player"}
        options = {"Evaluator": SimpleNamespace(default="classical")}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def configure(self, options):
            pass

        def play(self, board, limit, **kwargs):
            return SimpleNamespace(move=next(iter(board.legal_moves)),
                                   info={"depth": 1, "nodes": 1, "time": .01, "nps": 100,
                                         "score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE)})

    monkeypatch.setattr(chess.engine.SimpleEngine, "popen_uci", lambda *args, **kwargs: Player())
    binary, book, output = (tmp_path / name for name in ("engine.exe", "book.json", "match.json"))
    binary.write_bytes(b"fake engine identity")
    openings = []
    for moves in ([], ["e2e4"]):
        board = chess.Board()
        for move in moves:
            board.push_uci(move)
        openings.append({"moves": moves, "fen": board.fen()})
    book.write_text(json.dumps({"method": "test neutral book", "openings": openings}), encoding="utf-8")
    args = SimpleNamespace(engine=binary, opponent=binary, opening_book=book, output=output,
                           games=4, movetime=50, max_plies=2, seed=1, candidate_options=None,
                           opponent_options=None, resume=False, max_new_games=2)
    version_match(args)
    progress = output.with_suffix(".progress.json")
    pilot = json.loads(progress.read_text(encoding="utf-8"))
    assert not output.exists() and pilot["requested_games"] == 4 and len(pilot["games"]) == 2
    args.resume, args.max_new_games = True, None
    version_match(args)
    finished = json.loads(output.read_text(encoding="utf-8"))
    assert finished["games"][:2] == pilot["games"] and not progress.exists()
    assert verify_record(output, check_binaries=True)["games"] == 4
    assert finished["summary"]["unfinished"] == 4 and finished["summary"]["draws"] == 0
    assert all("wall_seconds" in s for g in finished["games"] for s in g["searches"])


def test_actual_game_capture_preserves_pre_root_draw_history():
    moves = ["g1f3", "g8f6", "f3g1", "f6g8"]
    board = chess.Board()
    for move in moves:
        board.push_uci(move)
    chosen = chess.Move.from_uci("e2e4")

    class Analysis:
        info = {"depth": 1, "seldepth": 1, "nodes": 21, "time": .001, "nps": 21000,
                "score": chess.engine.PovScore(chess.engine.Cp(0), chess.WHITE), "pv": [chosen]}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def __iter__(self):
            yield self.info

        def wait(self):
            return SimpleNamespace(move=chosen)

    class Engine:
        def analysis(self, root, limit, **kwargs):
            assert [m.uci() for m in root.move_stack] == moves
            assert root.is_repetition(2) and not root.is_game_over(claim_draw=True)
            return Analysis()

    result = capture(Engine(), {"id": "history", "fen": board.fen(), "moves": moves}, "depth", 1)
    assert result["move"] == "e2e4" and result["iterations"][0]["pv"] == ["e2e4"]


@pytest.mark.skipif(not os.environ.get("CHESSLAB_DIAGNOSTIC_ENGINE"), reason="Explicit diagnostic build required")
def test_counter_oracle_distinguishes_unused_ancestors_from_unused_leaves():
    binary = Path(os.environ["CHESSLAB_DIAGNOSTIC_ENGINE"]).with_name("micro.exe")
    d = json.loads(subprocess.check_output([str(binary), "--diagnostics-verify"], text=True, timeout=10))
    assert d["unused_updates"] == 2 and d["unused_leaf_updates"] == 1
    assert d["unused_null_updates"] == 1 and d["evaluation_calls"] == 3
    assert d["pending_edges"] == 4 and d["pending_rows"] == 9


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
        sidecar = Path(os.environ["CHESSLAB_DIAGNOSTIC_ENGINE"]).with_suffix(".build.json")
        strategy = json.loads(sidecar.read_text()).get("nnue_update", "legacy")
        # Initial legal moves retain all four castling state rows, no legal EP.
        # Compact metadata: 256 float bytes + 2*4 uint16 rows + one count.
        payload = 408 if strategy in ("legacy", "merge") else 276
        assert d["copy_payload_bytes"] == 20 * payload
        assert d["row_weight_bytes"] == 40 * 2 * 32 * 4
        assert d["row_value_read_write_bytes"] == 40 * 4 * 32 * 4
        assert d["evaluation_calls"] == 20 and d["refreshes"] == 1
        assert d["unused_updates"] == d["null_updates"] == d["qvisits"] == 0
        assert d["pending_edges"] == 20 and d["pending_rows"] == 40
