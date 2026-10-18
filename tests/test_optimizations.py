"""Exact aspiration windows and conservative selective-search invariants."""
import chess
import chess.engine
import pytest

from tools.engine_checks import POSITIONS, counters


@pytest.mark.parametrize("fen", list(POSITIONS.values()))
@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("pvs", [False, True])
@pytest.mark.parametrize("qsearch", [False, True])
def test_aspiration_matches_full_window(engine, fen, cached, pvs, qsearch):
    board = chess.Board(fen)
    results = []
    engine.configure({"UsePST": True, "TranspositionTable": cached, "PVS": pvs,
                      "Quiescence": qsearch, "AspirationDelta": 1})
    for enabled in (False, True):
        engine.configure({"UseAspirationWindows": enabled})
        result = engine.play(board, chess.engine.Limit(depth=4, time=5), info=chess.engine.INFO_ALL)
        assert result.info["depth"] == 4
        replay = board.copy()
        for move in result.info.get("pv", []):
            assert move and move in replay.legal_moves
            replay.push(move)
        results.append(result)
    assert results[0].info["score"] == results[1].info["score"]
    assert not counters(results[0].info)["aspiration_attempts"]


def test_aspiration_widens_both_bounds_and_publishes_only_successes(engine):
    engine.configure({"UseAspirationWindows": True, "AspirationDelta": 1, "UsePST": True})
    result = engine.play(chess.Board(), chess.engine.Limit(depth=4), info=chess.engine.INFO_ALL)
    c = counters(result.info)
    assert c["aspiration_fail_high"] > 0 and c["aspiration_fail_low"] > 0
    assert c["aspiration_retries"] == c["aspiration_fail_high"] + c["aspiration_fail_low"]
    assert c["aspiration_successes"] == c["aspiration_attempts"] == 3
    assert c["aspiration_searches"] == c["aspiration_successes"] + c["aspiration_retries"]


@pytest.mark.parametrize("pruning,iterative", [(False, True), (True, False)])
def test_aspiration_inactive_for_minimax_or_direct_search(engine, pruning, iterative):
    engine.configure({"UseAspirationWindows": True, "AlphaBeta": pruning, "IterativeDeepening": iterative})
    result = engine.play(chess.Board(), chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
    assert counters(result.info)["aspiration_searches"] == 0


def test_interruption_during_aspiration_retry_retains_last_completed_snapshot(engine):
    engine.configure({"UseAspirationWindows": True, "AspirationDelta": 1, "UsePST": True})
    shallow = engine.play(chess.Board(), chess.engine.Limit(depth=1), info=chess.engine.INFO_ALL)
    found = False
    for nodes in (64, 128, 256, 512, 1024):
        result = engine.play(chess.Board(), chess.engine.Limit(depth=4, nodes=nodes), info=chess.engine.INFO_ALL)
        if result.info["depth"] == 1 and counters(result.info)["aspiration_retries"] > 0:
            assert result.move == shallow.move
            assert result.info["score"] == shallow.info["score"]
            assert result.info["pv"] == shallow.info["pv"]
            found = True
            break
    assert found, "Fixture did not interrupt a failed-window retry"


@pytest.mark.parametrize("fen", [POSITIONS["endgame"], POSITIONS["zugzwang"],
                                 chess.Board(POSITIONS["zugzwang"]).mirror().fen()])
def test_null_move_zugzwang_guards_keep_pawn_endgames_unchanged(engine, fen):
    engine.configure({"UseNullMovePruning": True, "UseAspirationWindows": True, "UsePST": True, "PVS": True})
    enabled = engine.play(chess.Board(fen), chess.engine.Limit(depth=5), info=chess.engine.INFO_ALL)
    assert counters(enabled.info)["null_attempts"] == counters(enabled.info)["null_cutoffs"] == 0
    engine.configure({"UseNullMovePruning": False})
    baseline = engine.play(chess.Board(fen), chess.engine.Limit(depth=5), info=chess.engine.INFO_ALL)
    assert enabled.info["score"] == baseline.info["score"] and enabled.move == baseline.move


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("fen", [POSITIONS["opening"], chess.Board(POSITIONS["opening"]).mirror().fen(), POSITIONS["tactical"]])
def test_null_move_has_actual_cutoffs_and_returns_only_legal_moves(engine, cached, fen):
    engine.configure({"UseNullMovePruning": True, "UseAspirationWindows": True, "UsePST": True,
                      "PVS": True, "Quiescence": True, "TranspositionTable": cached})
    board = chess.Board(fen)
    result = engine.play(board, chess.engine.Limit(depth=5, time=5), info=chess.engine.INFO_ALL)
    c = counters(result.info)
    assert result.info["depth"] == 5 and c["null_attempts"] >= c["null_cutoffs"] > 0
    assert result.move in board.legal_moves
    for move in result.info["pv"]:
        assert move and move in board.legal_moves
        board.push(move)


def test_null_move_disabled_for_minimax(engine):
    engine.configure({"UseNullMovePruning": True, "AlphaBeta": False})
    result = engine.play(chess.Board(), chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
    assert counters(result.info)["null_attempts"] == 0


OPERA_MOVES = "e2e4 e7e5 g1f3 d7d6 d2d4 c8g4 d4e5 g4f3 d1f3 d6e5 f1c4 g8f6 f3b3 d8e7 b1c3 c7c6 c1g5 b7b5 c3b5 c6b5 c4b5 b8d7 e1c1 a8d8 d1d7 d8d7 h1d1 e7e6 b5d7 f6d7".split()


def opera_board():
    board = chess.Board()
    for move in OPERA_MOVES:
        board.push_uci(move)
    return board


@pytest.mark.parametrize("board,expected_mate", [(opera_board(), 2),
    (chess.Board("7k/4Q3/8/5K2/8/8/8/8 w - - 0 1"), 2)])
def test_null_move_preserves_forced_sacrifice_and_quiet_mate(engine, board, expected_mate):
    engine.configure({"UsePST": True, "Quiescence": True, "PVS": True, "UseAspirationWindows": True,
                      "TranspositionTable": True})
    results = []
    for enabled in (False, True):
        engine.configure({"UseNullMovePruning": enabled})
        results.append(engine.play(board, chess.engine.Limit(depth=5, time=5), info=chess.engine.INFO_ALL))
    assert all(r.info["score"].white().mate() == expected_mate for r in results)
    assert results[0].move == results[1].move
    if board.fen() == opera_board().fen():
        assert results[1].move.uci() == "b3b8"  # Qb8+! Nxb8 Rd8#.
    else:
        assert not board.is_capture(results[1].move) and not board.gives_check(results[1].move)


def test_real_threefold_and_fifty_move_draws_precede_null_search(engine):
    engine.configure({"UseNullMovePruning": True, "PVS": True, "Quiescence": True})
    repeated = chess.Board()
    for _ in range(2):
        for move in ("g1f3", "g8f6", "f3g1", "f6g8"):
            repeated.push_uci(move)
    clock = chess.Board()
    clock.halfmove_clock = 100
    for board in (repeated, clock):
        result = engine.play(board, chess.engine.Limit(depth=5), info=chess.engine.INFO_ALL)
        assert not result.move and result.info["score"].white().score() == 0
        assert counters(result.info)["null_attempts"] == 0


@pytest.mark.parametrize("reduction", [1, 2, 3])
@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("null_move", [False, True])
@pytest.mark.parametrize("black", [False, True])
def test_lmr_reductions_and_full_depth_verifications_are_exercised(engine, reduction, cached, null_move, black):
    engine.configure({"UseLMR": True, "LMRReduction": reduction, "UsePST": True, "Quiescence": True,
                      "PVS": True, "UseNullMovePruning": null_move, "UseAspirationWindows": True,
                      "TranspositionTable": cached})
    board = chess.Board(POSITIONS["middlegame"])
    if black:
        board = board.mirror()
    result = engine.play(board, chess.engine.Limit(depth=5, time=5), info=chess.engine.INFO_ALL)
    c = counters(result.info)
    assert result.info["depth"] == 5
    assert c["lmr_attempts"] == c["lmr_searches"] > 0
    assert c["lmr_researches"] == c["lmr_verifications"] > 0
    assert c["lmr_verifications"] <= c["lmr_searches"]
    for move in result.info["pv"]:
        assert move and move in board.legal_moves
        board.push(move)


@pytest.mark.parametrize("setting", [{"AlphaBeta": False}, {"MoveOrdering": False},
                                       {"PVS": False}, {"Depth": 2}])
def test_lmr_conservative_fallback_without_ordering_pvs_or_depth(engine, setting):
    engine.configure({"UseLMR": True, "UsePST": True, "PVS": True, **setting})
    depth = setting.get("Depth", 3 if setting.get("AlphaBeta") is False else 4)
    result = engine.play(chess.Board(), chess.engine.Limit(depth=depth), info=chess.engine.INFO_ALL)
    assert counters(result.info)["lmr_searches"] == 0


@pytest.mark.parametrize("aspiration,null_move,lmr", [(a,n,l) for a in (False,True) for n in (False,True) for l in (False,True)])
@pytest.mark.parametrize("cached,pvs,qsearch,pst", [(True,True,True,True), (False,True,True,False),
                                                   (True,False,True,False), (False,True,False,True)])
@pytest.mark.parametrize("fen", [POSITIONS["opening"], chess.Board().mirror().fen(), POSITIONS["tactical"]])
def test_all_optimization_toggles_are_deterministic_and_return_legal_complete_pvs(engine, aspiration, null_move, lmr, cached, pvs, qsearch, pst, fen):
    engine.configure({"UseAspirationWindows": aspiration, "UseNullMovePruning": null_move, "UseLMR": lmr,
                      "TranspositionTable": cached, "PVS": pvs, "Quiescence": qsearch, "UsePST": pst})
    results = []
    for _ in range(2):
        board = chess.Board(fen)
        result = engine.play(board, chess.engine.Limit(depth=4, time=5), info=chess.engine.INFO_ALL)
        assert result.info["depth"] == 4 and result.move in board.legal_moves
        pv = result.info["pv"]
        assert result.move == pv[0]
        for move in pv:
            assert move and move in board.legal_moves
            board.push(move)
        assert len(pv) >= 4 or board.is_game_over(claim_draw=True)
        c = counters(result.info)
        if not aspiration:
            assert c["aspiration_attempts"] == 0
        if not null_move:
            assert c["null_attempts"] == 0
        if not lmr:
            assert c["lmr_searches"] == 0
        results.append((result.move, result.info["score"], pv, result.info["nodes"]))
    assert results[0] == results[1]


@pytest.mark.parametrize("board", [opera_board(), chess.Board("7k/4Q3/8/5K2/8/8/8/8 w - - 0 1")])
@pytest.mark.parametrize("null_move", [False, True])
def test_combined_lmr_keeps_quiet_and_sacrificial_forced_mates(engine, board, null_move):
    engine.configure({"UseAspirationWindows": True, "UseNullMovePruning": null_move, "UseLMR": True,
                      "UsePST": True, "PVS": True, "Quiescence": True, "TranspositionTable": True})
    result = engine.play(board, chess.engine.Limit(depth=5, time=5), info=chess.engine.INFO_ALL)
    assert result.info["score"].white().mate() == 2
    if board.fen() == opera_board().fen():
        assert result.move.uci() == "b3b8"
    else:
        assert not board.is_capture(result.move) and not board.gives_check(result.move)


@pytest.mark.parametrize("cached", [False, True])
def test_all_features_abort_deeper_work_without_overwriting_completed_root(engine, cached):
    engine.configure({"UseAspirationWindows": True, "UseNullMovePruning": True, "UseLMR": True,
                      "UsePST": True, "PVS": True, "Quiescence": True, "TranspositionTable": cached})
    board = chess.Board(POSITIONS["middlegame"])
    shallow = engine.play(board, chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
    previous = counters(shallow.info)
    observed = False
    for extra in (128, 512, 2048, 8192, 16384):
        result = engine.play(board, chess.engine.Limit(depth=7, nodes=shallow.info["nodes"] + extra), info=chess.engine.INFO_ALL)
        c = counters(result.info)
        if result.info["depth"] == 3 and (c["null_attempts"] > previous["null_attempts"] or c["lmr_searches"] > previous["lmr_searches"]):
            assert result.move == shallow.move
            assert result.info["score"] == shallow.info["score"] and result.info["pv"] == shallow.info["pv"]
            observed = True
            break
    assert observed, "Fixture did not interrupt a selective pass"


def test_all_advanced_flags_are_inactive_in_exhaustive_minimax(engine):
    engine.configure({"AlphaBeta": False, "Quiescence": False, "UsePST": False, "TranspositionTable": False})
    results = []
    for enabled in (False, True):
        engine.configure({name: enabled for name in ("UseAspirationWindows", "UseNullMovePruning", "UseLMR")})
        result = engine.play(chess.Board(), chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
        results.append((result.move, result.info["score"], result.info["pv"], result.info["nodes"]))
        assert all(v == 0 for v in counters(result.info).values())
    assert results[0] == results[1] and results[0][-1] == 9765


def test_uci_advanced_defaults_and_tuning_ranges(engine):
    for name in ("UseAspirationWindows", "UseNullMovePruning", "UseLMR"):
        assert engine.options[name].default is True
    assert (engine.options["AspirationDelta"].default, engine.options["AspirationDelta"].min, engine.options["AspirationDelta"].max) == (25, 1, 500)
    assert (engine.options["LMRReduction"].default, engine.options["LMRReduction"].min, engine.options["LMRReduction"].max) == (1, 1, 3)
