import time

import chess
import pytest

from app.engine_client import DEFAULT_ENGINE, EngineClient, EngineSettings


def wait_result(client, seconds=8, progress=None):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        messages = client.poll()
        for message in messages:
            if progress is not None:
                progress.append(message)
            if message.finished:
                return message
        time.sleep(.01)
    raise AssertionError("Engine worker did not complete")


@pytest.mark.parametrize("ordering", [False, True])
@pytest.mark.parametrize("use_pst", [False, True])
@pytest.mark.parametrize("cached", [False, True])
def test_comparison_runs_both_algorithms_on_unchanged_snapshot(ordering, use_pst, cached):
    assert DEFAULT_ENGINE.is_file(), "Build engine before running integration tests"
    client = EngineClient()
    board = chess.Board()
    try:
        token = client.start(board, 42, EngineSettings(depth=3, move_ordering=ordering, use_pst=use_pst, advanced_evaluation=False,
                                                      transposition_table=cached, quiescence=False,
                                                      principal_variation_search=False, timed_search=False, aspiration_windows=False, null_move_pruning=False, late_move_reductions=False,
                                                      history_heuristic=False, killer_heuristic=False, static_exchange=False,
                                                      adaptive_lmr=False, reverse_futility=False, futility=False, check_extensions=False), "compare")
        progress = []
        message = wait_result(client, progress=progress)
        assert message.token == token and message.revision == 42
        assert not message.error
        plain, pruned = message.stats
        assert plain.algorithm == "Minimax" and pruned.algorithm == "Alpha-beta"
        assert plain.complete and pruned.complete
        assert plain.move_ordering == pruned.move_ordering == ordering
        assert plain.use_pst == pruned.use_pst == use_pst
        assert plain.transposition_table == pruned.transposition_table == cached
        if not cached:
            assert plain.tt_hits == pruned.tt_hits == 0
        if not ordering and not use_pst and not cached:
            assert (plain.nodes, pruned.nodes) == (9765, 667)
        assert plain.score == pruned.score and plain.move == pruned.move
        assert pruned.nodes < plain.nodes
        assert any(not row.finished for row in progress)
        assert [row.depth for row in plain.iterations] == [1, 2, 3]
        assert [row.depth for row in pruned.iterations] == [1, 2, 3]
        assert board.fen() == chess.STARTING_FEN
        assert not client.busy
    finally:
        client.close()


def test_missing_executable_reports_error_without_touching_board(tmp_path):
    client = EngineClient(tmp_path / "missing.exe")
    board = chess.Board()
    try:
        client.start(board, 0, EngineSettings(enabled=True, timed_search=False))
        message = wait_result(client)
        assert "build_engine.bat" in message.error
        assert board.fen() == chess.STARTING_FEN
    finally:
        client.close()


def test_cancel_discards_old_results_and_new_job_completes():
    client = EngineClient()
    try:
        old = client.start(chess.Board(), 1, EngineSettings(depth=5, alpha_beta=False, timed_search=False))
        client.cancel()
        assert not client.busy
        new = client.start(chess.Board(), 2, EngineSettings(depth=1, timed_search=False))
        message = wait_result(client)
        assert message.token == new and new != old
        assert message.revision == 2 and not message.error
        assert message.stats[0].move in chess.Board().legal_moves
    finally:
        client.close()


def test_fixed_setting_emits_only_the_target_pass():
    client = EngineClient()
    try:
        client.start(chess.Board(), 0, EngineSettings(depth=3, iterative_deepening=False, timed_search=False))
        result = wait_result(client)
        assert not result.error
        assert [row.depth for row in result.stats[0].iterations] == [3]
        assert not result.stats[0].iterative_deepening
    finally:
        client.close()


def test_graceful_stop_retains_proven_score_and_result():
    client = EngineClient()
    try:
        client.start(chess.Board(), 0, EngineSettings(depth=5, alpha_beta=False, timed_search=False))
        end = time.monotonic() + 8
        result = None
        while time.monotonic() < end:
            for message in client.poll():
                if message.finished:
                    result = message
                elif message.stats[-1].depth >= 1:
                    client.stop()
            if result:
                break
            time.sleep(.001)
        assert result is not None and not result.error
        row = result.stats[0]
        assert row.depth >= 1 and row.score != "—"
        assert row.move in chess.Board().legal_moves
        assert not client.busy
    finally:
        client.close()


@pytest.mark.parametrize("qsearch", [False, True])
@pytest.mark.parametrize("pvs", [False, True])
def test_new_search_modes_stream_actual_counters_and_labels(qsearch, pvs):
    client = EngineClient()
    board = chess.Board()
    try:
        client.start(board, 9, EngineSettings(depth=3, quiescence=qsearch,
                                             principal_variation_search=pvs, timed_search=False), "compare")
        result = wait_result(client)
        assert not result.error and result.finished
        minimax, pruned = result.stats
        assert minimax.algorithm == "Minimax"
        assert pruned.algorithm == ("PVS" if pvs else "Alpha-beta")
        assert minimax.quiescence == pruned.quiescence == qsearch
        assert not minimax.principal_variation_search
        assert pruned.principal_variation_search == pvs
        assert minimax.complete and pruned.complete and minimax.score == pruned.score
        assert minimax.pvs_scouts == minimax.pvs_researches == 0
        if qsearch:
            assert 0 < minimax.qnodes <= minimax.nodes
            assert 0 < pruned.qnodes <= pruned.nodes
        else:
            assert minimax.qnodes == pruned.qnodes == 0
        if pvs:
            assert pruned.pvs_scouts >= pruned.pvs_researches > 0
        else:
            assert pruned.pvs_scouts == pruned.pvs_researches == 0
        assert board.fen() == chess.STARTING_FEN
    finally:
        client.close()
