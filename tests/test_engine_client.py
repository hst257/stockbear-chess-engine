import time

import chess

from app.engine_client import DEFAULT_ENGINE, EngineClient, EngineSettings


def wait_result(client, seconds=8):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        messages = client.poll()
        if messages:
            return messages[0]
        time.sleep(.01)
    raise AssertionError("Engine worker did not complete")


def test_comparison_runs_both_algorithms_on_unchanged_snapshot():
    assert DEFAULT_ENGINE.is_file(), "Build engine before running integration tests"
    client = EngineClient()
    board = chess.Board()
    try:
        token = client.start(board, 42, EngineSettings(depth=3), "compare")
        message = wait_result(client)
        assert message.token == token and message.revision == 42
        assert not message.error
        plain, pruned = message.stats
        assert plain.algorithm == "Minimax" and pruned.algorithm == "Alpha-beta"
        assert plain.complete and pruned.complete
        assert plain.score == pruned.score and plain.move == pruned.move
        assert pruned.nodes < plain.nodes
        assert board.fen() == chess.STARTING_FEN
        assert not client.busy
    finally:
        client.close()


def test_missing_executable_reports_error_without_touching_board(tmp_path):
    client = EngineClient(tmp_path / "missing.exe")
    board = chess.Board()
    try:
        client.start(board, 0, EngineSettings(enabled=True))
        message = wait_result(client)
        assert "build_engine.bat" in message.error
        assert board.fen() == chess.STARTING_FEN
    finally:
        client.close()


def test_cancel_discards_old_results_and_new_job_completes():
    client = EngineClient()
    try:
        old = client.start(chess.Board(), 1, EngineSettings(depth=5, alpha_beta=False))
        client.cancel()
        assert not client.busy
        new = client.start(chess.Board(), 2, EngineSettings(depth=1))
        message = wait_result(client)
        assert message.token == new and new != old
        assert message.revision == 2 and not message.error
        assert message.stats[0].move in chess.Board().legal_moves
    finally:
        client.close()
