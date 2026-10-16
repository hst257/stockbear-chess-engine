"""Frozen pairing, game durability, resume and scoring behavior."""
from types import SimpleNamespace

import chess
import chess.engine
import pytest

from tools import nnue_showdown as showdown


def test_schedule_is_exact_paired_and_nested():
    openings = showdown.make_openings()
    games = showdown.schedule()
    assert len(openings) == 12 and len({o["fen"] for o in openings}) == 12
    assert len(games) == 126
    for ms, count in ((500, 72), (1000, 36), (3000, 18)):
        cohort = [g for g in games if g["ms"] == ms]
        assert len(cohort) == count
        for i in range(0, len(cohort), 2):
            a, b = cohort[i:i + 2]
            assert a["opening"] == b["opening"]
            assert a["white"] == b["black"] and a["black"] == b["white"]
        for pair in (("32", "64"), ("64", "128"), ("32", "128")):
            assert sorted({g["opening"] for g in cohort if tuple(g["pair"]) == pair}) == list(range(count // 6))


def fixture(tmp_path):
    entries = {n: {"name": n, "sha256": "binary" + n, "network_sha256": "network" + n} for n in ("32", "64")}
    plan = {"openings": [{"id": "test", "family": "fixture", "fen": chess.STARTING_FEN, "moves": []}],
            "engines": entries, "options": {}, "allowance_seconds": .1, "max_searched_plies": 400}
    game = {"id": "G001", "opening": 0, "pair": ["32", "64"], "white": "32", "black": "64", "ms": 500, "stage": "round_robin"}
    showdown.save(tmp_path / "plan.json", plan)
    return plan, game


class FakePlayer:
    interrupt = None
    calls = 0

    def __init__(self):
        self.protocol = SimpleNamespace(counters={"eval_calls": 1, "nnue_evaluations": 1, "qnodes": 0}, transcript=[])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def play(self, board, limit, **kwargs):
        type(self).calls += 1
        if self.interrupt == len(board.move_stack):
            raise KeyboardInterrupt()
        move = chess.Move.from_uci(["f2f3", "e7e5", "g2g4", "d8h4"][len(board.move_stack)])
        return SimpleNamespace(move=move, info={"depth": 1, "nodes": 1, "time": .001, "nps": 1000})


def test_completed_game_is_not_replayed_and_missing_pgn_recovers(tmp_path, monkeypatch):
    plan, game = fixture(tmp_path)
    FakePlayer.interrupt, FakePlayer.calls = None, 0
    monkeypatch.setattr(showdown, "open_engine", lambda *args: FakePlayer())
    result = showdown.play_game(tmp_path, plan, game)
    assert result["result"] == "0-1" and result["termination"] == "checkmate"
    assert FakePlayer.calls == 4
    (tmp_path / "games/G001.pgn").unlink()
    monkeypatch.setattr(showdown, "open_engine", lambda *args: pytest.fail("Completed game replayed"))
    assert showdown.play_game(tmp_path, plan, game) == result
    assert (tmp_path / "games/G001.pgn").exists()
    plan["allowance_seconds"] = .2
    showdown.save(tmp_path / "plan.json", plan)
    with pytest.raises(ValueError, match="identity"):
        showdown.play_game(tmp_path, plan, game)


def test_interruption_resumes_saved_moves_without_duplicates(tmp_path, monkeypatch):
    plan, game = fixture(tmp_path)
    FakePlayer.interrupt, FakePlayer.calls = 2, 0
    monkeypatch.setattr(showdown, "open_engine", lambda *args: FakePlayer())
    with pytest.raises(KeyboardInterrupt):
        showdown.play_game(tmp_path, plan, game)
    partial = showdown.load(tmp_path / "games/G001.partial.json")
    assert len(partial["searches"]) == 2
    assert not list((tmp_path / "failures").glob("*.json"))
    FakePlayer.interrupt = None
    result = showdown.play_game(tmp_path, plan, game)
    assert len(result["searches"]) == 4 and result["result"] == "0-1"
    assert FakePlayer.calls == 5


def test_scoring_excludes_caps_and_finalists_use_fixed_tie_rule():
    rows = [{"game": game, "result": "1/2-1/2", "searches": []} for game in showdown.schedule()]
    assert showdown.select_finalists(rows) == ["32", "64"]
    assert all(r["equal_format_score"] == .5 for r in showdown.standings(rows))
    rows[0]["result"] = "*"
    a = showdown.stats(rows[:2], rows[0]["game"]["white"])
    assert a["unfinished"] == 1 and a["points"] == .5 and a["score_fraction"] == .5


def test_illegal_move_stops_unscored_and_keeps_failure_log(tmp_path, monkeypatch):
    plan, game = fixture(tmp_path)
    class IllegalPlayer(FakePlayer):
        def play(self, *args, **kwargs):
            return SimpleNamespace(move=chess.Move.from_uci("e2e5"), info={})
    monkeypatch.setattr(showdown, "open_engine", lambda *args: IllegalPlayer())
    with pytest.raises(RuntimeError, match="Critical illegal_move"):
        showdown.play_game(tmp_path, plan, game)
    failures = list((tmp_path / "failures").glob("*.json"))
    assert len(failures) == 1 and showdown.load(failures[0])["unscored"]
    assert not (tmp_path / "games/G001.json").exists()


def test_uncertainty_clusters_colors_and_root_comparison_matches_openings():
    from tools.report_nnue_showdown import paired_uncertainty, matched_roots
    rows = []
    for opening in range(3):
        for reverse in range(2):
            white, black = ("32", "64") if reverse == 0 else ("64", "32")
            rows.append({"game": {"opening": opening, "white": white, "black": black, "pair": ["32", "64"]},
                         "result": "1-0", "searches": [{"engine": white, "nodes": 100 if white == "32" else 80,
                             "engine_seconds": 1., "depth": 10 if white == "32" else 9}]})
    uncertainty = paired_uncertainty(rows, "32")
    assert uncertainty["complete_pairs"] == 3 and uncertainty["paired_score"] == .5
    assert uncertainty["pair_scores"] == [.5] * 3
    roots = matched_roots(rows)["matched_comparisons"]["64/32"]
    assert roots["opening_positions"] == 3
    assert roots["geometric_nps_ratio"] == pytest.approx(.8)
    assert roots["mean_depth_difference"] == -1
