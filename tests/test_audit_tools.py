"""Match scoring and a real two-executable end-to-end harness check."""
import io
import errno
import json
import subprocess
import sys

import chess.pgn
import pytest

from tools.match_optimizations import strength_summary, write_record


def test_strength_statistics_keep_pairs_and_exclude_unfinished():
    records = [{"candidate_outcome": result} for result in ("win", "draw", "loss", "draw", "unfinished", "win")]
    summary = strength_summary(records)
    assert (summary["wins"], summary["draws"], summary["losses"], summary["unfinished"]) == (2, 2, 1, 1)
    assert summary["completed_games"] == 5 and summary["score_percent"] == 60
    assert summary["rating_difference_estimate"] == pytest.approx(70.4365, abs=.001)
    assert summary["complete_pairs"] == 2 and summary["paired_score"] == .5


def test_all_draws_do_not_imply_zero_uncertainty():
    summary = strength_summary([{"candidate_outcome": "draw"} for _ in range(200)])
    assert summary["rating_difference_estimate"] == 0
    low, high = summary["paired_rating_95_bound"]
    assert low < 0 < high


def test_checkpoint_survives_transient_windows_replace_error(tmp_path, monkeypatch):
    import os
    path = tmp_path / "checkpoint.json"
    path.write_text('{"games": 178}', encoding="utf-8")
    original = os.replace
    calls = []
    def transient(source, destination):
        calls.append(1)
        assert json.loads(path.read_text(encoding="utf-8"))["games"] == 178
        if len(calls) < 3:
            raise OSError(errno.EINVAL, "simulated Windows lock")
        original(source, destination)
    monkeypatch.setattr(os, "replace", transient)
    write_record(path, '{"games": 179}')
    assert json.loads(path.read_text(encoding="utf-8"))["games"] == 179
    assert len(calls) == 3


def test_real_version_match_saves_replayable_pgn_and_marks_caps(engine_path, tmp_path):
    output = tmp_path / "match.json"
    subprocess.run([sys.executable, "-m", "tools.match_optimizations", "--comparison", "versions",
                    "--engine", str(engine_path), "--opponent", str(engine_path), "--games", "2",
                    "--movetime", "5", "--max-plies", "6", "--output", str(output)],
                   check=True, capture_output=True, text=True, timeout=20)
    data = json.loads(output.read_text())
    assert len(data["openings"]) == 1 and len(data["games"]) == 2
    assert data["games"][0]["candidate_color"] == "white"
    assert data["games"][1]["candidate_color"] == "black"
    source = io.StringIO(output.with_suffix(".pgn").read_text())
    for record in data["games"]:
        game = chess.pgn.read_game(source)
        assert not game.errors
        board = game.end().board()
        assert len(board.move_stack) == record["plies"]
        assert game.headers["Result"] == record["result"]
        if record["candidate_outcome"] == "unfinished":
            assert record["result"] == "*" and record["termination"] == "ply cap (unfinished)"
    assert chess.pgn.read_game(source) is None
    assert not output.with_suffix(".progress.json").exists()
