"""The final match boundary, fresh openings and true classical selection."""
import chess.pgn
import pytest

from tools import final_nnue_showdown as final
from tools import nnue_showdown as core


def test_exact_48_games_two_matches_same_paired_openings():
    games = final.schedule()
    assert len(games) == 48 and all(g["ms"] == 1000 for g in games)
    for offset, candidate in ((0, "64"), (24, "128")):
        cohort = games[offset:offset + 24]
        assert {tuple(g["pair"]) for g in cohort} == {("classical", candidate)}
        for index in range(12):
            a, b = cohort[2*index:2*index+2]
            assert a["opening"] == b["opening"] == index
            assert a["white"] == b["black"] and a["black"] == b["white"]


def test_fresh_openings_legal_reproducible_and_not_previous_roots():
    assert final.openings() == final.openings()
    previous = {o["fen"] for o in core.make_openings()}
    for opening in final.openings():
        board = chess.Board()
        for move in opening["moves"]:
            board.push_uci(move)
        assert board.fen() == opening["fen"] and board.is_valid()
        assert not board.is_game_over(claim_draw=True) and not board.is_check()
        assert opening["fen"] not in previous


def test_counter_guard_rejects_hybrid_and_missing_counters():
    final.validate_counters({"eval_calls": 23, "nnue_evaluations": 0}, "classical")
    final.validate_counters({"eval_calls": 23, "nnue_evaluations": 23}, "nnue")
    for counts, mode in (({"eval_calls": 23, "nnue_evaluations": 1}, "classical"),
                         ({"eval_calls": 23, "nnue_evaluations": 0}, "nnue"), ({}, "classical")):
        with pytest.raises(ValueError):
            final.validate_counters(counts, mode)


def test_pgn_marks_classical_network_disabled(tmp_path):
    from tests.test_nnue_showdown import fixture
    plan, game = fixture(tmp_path)
    game["white"] = "classical"
    game["pair"] = ["classical", "64"]
    game["black"] = "64"
    plan["engines"] = {"classical": dict(plan["engines"]["32"], evaluator="classical"),
                       "64": dict(plan["engines"]["64"], evaluator="nnue")}
    record = {"started_utc": core.utc(), "result": "*", "termination": "in_progress",
              "plan_sha256": "frozen", "searches": []}
    (tmp_path / "games").mkdir()
    final.export_pgn(tmp_path, plan, game, record)
    with (tmp_path / "games/G001.pgn").open() as stream:
        pgn = chess.pgn.read_game(stream)
    assert pgn.headers["WhiteNetworkSHA256"] == "disabled"
    assert pgn.headers["WhiteEvaluator"] == "classical"
    assert pgn.headers["BlackNetworkSHA256"] == plan["engines"]["64"]["network_sha256"]


def test_final_uncertainty_exchanges_pairs_and_elo_keeps_infinite_bounds():
    from tools.report_final_nnue_showdown import paired_test, elo
    rows = []
    for game in final.schedule()[:24]:
        rows.append({"game": game, "result": "1-0" if game["white"] == "64" else "0-1"})
    estimate = paired_test(rows, "64")
    assert estimate["complete_pairs"] == 12 and estimate["paired_score"] == 1
    assert estimate["nnue_superiority_p_one_sided"] == 1 / 4096
    assert estimate["difference_p_two_sided"] == 2 / 4096
    assert estimate["elo_from_score"] == "+infinity"
    assert elo(.5) == 0 and elo(0) == "-infinity"
    for row in rows:
        row["result"] = "1/2-1/2"
    assert paired_test(rows, "64")["nnue_superiority_p_one_sided"] == 1
