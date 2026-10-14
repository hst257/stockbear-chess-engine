"""Time budgets, completed snapshots, and engine/client integration."""
import time

import chess
import chess.engine
import pytest

from app.engine_client import EngineClient, EngineSettings, THINKING_TIMES, search_stats

POSITIONS = [chess.STARTING_FEN,
    "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 4 7",
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/5pk1/6p1/8/3K4/6P1/5P2/8 w - - 0 1"]


def defaults(engine):
    engine.configure({"AlphaBeta": True, "UsePST": True, "Quiescence": True, "PVS": True,
                      "TranspositionTable": True})


def test_standard_is_default_and_exactly_five_presets():
    assert THINKING_TIMES == (("Blitz", 100), ("Fast", 500), ("Standard", 1000),
                              ("Deep", 3000), ("Maximum", 5000))
    assert EngineSettings().timed_search and EngineSettings().thinking_time_ms == 1000
    with pytest.raises(ValueError):
        EngineSettings(thinking_time_ms=200)
    board = chess.Board()
    fallback = search_stats({"depth": 0, "nodes": 1}, next(iter(board.legal_moves)),
                            board, EngineSettings(), True, ())
    assert not fallback.complete and fallback.depth == 0
    assert fallback.score == "\u2014" and fallback.move in board.legal_moves


@pytest.mark.parametrize("fen", POSITIONS)
@pytest.mark.parametrize("cached", [False, True])
def test_timed_search_retains_last_completed_move_score_and_legal_pv(engine, fen, cached):
    defaults(engine)
    engine.configure({"TranspositionTable": cached, "IterativeDeepening": False})
    board = chess.Board(fen)
    completed = []
    start = time.monotonic()
    with engine.analysis(board, chess.engine.Limit(time=.1), info=chess.engine.INFO_ALL) as analysis:
        for info in analysis:
            if "depth" in info and "score" in info:
                completed.append(info)
        result = analysis.wait()
        final = analysis.info.copy()
    elapsed = time.monotonic() - start
    assert completed and final["depth"] == completed[-1]["depth"]
    assert result.move == completed[-1]["pv"][0] and result.move in board.legal_moves
    assert final["score"] == completed[-1]["score"] and final["pv"] == completed[-1]["pv"]
    assert final["nodes"] >= completed[-1]["nodes"]
    assert [i["depth"] for i in completed] == list(range(1, final["depth"] + 1))
    for move in final["pv"]:
        assert move in board.legal_moves
        board.push(move)
    assert .08 <= final["time"] <= .6 and elapsed < 1.5
    # The next go must be unaffected by the aborted speculative board/TT state.
    engine.configure({"IterativeDeepening": True})
    check = engine.play(chess.Board(fen), chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
    engine.configure({"TranspositionTable": False})
    baseline = engine.play(chess.Board(fen), chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
    assert check.info["score"] == baseline.info["score"]


def test_timed_search_exceeds_depth_five(engine):
    defaults(engine)
    result = engine.play(chess.Board(POSITIONS[-1]), chess.engine.Limit(time=.5), info=chess.engine.INFO_ALL)
    assert result.info["depth"] > 5


@pytest.mark.parametrize("fen", ["7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"])
def test_timed_terminal_positions_return_null_early(engine, fen):
    defaults(engine)
    result = engine.play(chess.Board(fen), chess.engine.Limit(time=5), info=chess.engine.INFO_ALL)
    assert not result.move and result.info["time"] < 1
    assert result.info["depth"] == 1


def test_timed_forced_mate_can_finish_early(engine):
    defaults(engine)
    board = chess.Board("7k/8/5KQ1/8/8/8/8/8 w - - 0 1")
    result = engine.play(board, chess.engine.Limit(time=5), info=chess.engine.INFO_ALL)
    assert result.info["time"] < 1 and result.info["score"].white().mate() == 1
    board.push(result.move)
    assert board.is_checkmate()


@pytest.mark.parametrize("milliseconds", [100, 500, 1000, 3000, 5000])
def test_actual_client_uses_time_without_depth_and_forces_deepening(milliseconds):
    client = EngineClient()
    board = chess.Board(POSITIONS[-1])
    settings = EngineSettings(depth=1, iterative_deepening=False, thinking_time_ms=milliseconds)
    try:
        token = client.start(board, 12, settings)
        end = time.monotonic() + milliseconds / 1000 + 3
        completed = []
        result = None
        while time.monotonic() < end and result is None:
            for message in client.poll():
                if message.finished:
                    result = message
                else:
                    completed.append(message)
            time.sleep(.005)
        assert result and not result.error and result.token == token
        row = result.stats[0]
        assert row.timed_search and row.thinking_time_ms == milliseconds
        assert row.requested_depth == 0 and row.depth > 1 and row.complete
        assert row.iterative_deepening and row.move in board.legal_moves and row.nps > 0
        assert row.seconds >= milliseconds / 1000 * .8
        assert completed and all(not m.finished for m in completed)
        assert row.score != "—" and len(board.move_stack) == 0
    finally:
        client.close()


def test_cancel_returns_immediately_and_worker_process_exits_cleanly():
    client = EngineClient()
    try:
        client.start(chess.Board(), 99, EngineSettings(thinking_time_ms=5000))
        end = time.monotonic() + 3
        while time.monotonic() < end:
            job = client._job
            if job and job.analysis is not None:
                break
            time.sleep(.005)
        assert job and job.analysis is not None and job.engine is not None
        process = job.engine
        start = time.monotonic()
        client.cancel()
        assert time.monotonic() - start < .2 and not client.busy
        assert process.returncode.result(timeout=3) == 0
        assert client.poll() == []
    finally:
        client.close()
