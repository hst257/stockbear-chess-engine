"""Independent tactical oracle, PVS/full-window equivalence, and shared limits."""

import chess
import chess.engine
import pytest

from app.engine_client import search_counters

KIWIPETE = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
POISONED = "7k/8/8/1p6/p7/Q7/8/7K w - - 0 1"


def material(board):
    return sum(value * (len(board.pieces(kind, chess.WHITE)) - len(board.pieces(kind, chess.BLACK)))
               for kind, value in ((1, 100), (2, 320), (3, 330), (4, 500), (5, 900)))


def reference(board, depth, ply=0, qply=0):
    moves = list(board.legal_moves)
    if not moves:
        return (-30000 + ply if board.turn else 30000 - ply) if board.is_check() else 0
    if board.is_insufficient_material() or board.halfmove_clock >= 100 or board.is_repetition(3):
        return 0
    scores = []
    if depth == 0 and not board.is_check():
        scores.append(material(board))
        if qply >= 16 or ply >= 64:
            return scores[0]
        moves = [move for move in moves if board.is_capture(move) or move.promotion]
    assert ply < 64, "Reference fixture hit the absolute check-evasion limit"
    for move in moves:
        board.push(move)
        scores.append(reference(board, max(0, depth - 1), ply + 1, qply + 1 if depth == 0 else 0))
        board.pop()
    return (max if board.turn else min)(scores)


SPARSE = [POISONED, chess.Board(POISONED).mirror().fen(),
          "7k/8/8/8/8/8/q7/R6K w - - 0 1", "r6k/Q7/8/8/8/8/8/7K b - - 0 1",
          "7k/8/8/3pP3/8/8/8/7K w - d6 0 2", "7k/P7/8/8/8/8/8/7K w - - 0 1"]


@pytest.fixture(scope="module", params=SPARSE)
def oracle_position(request):
    board = chess.Board(request.param)
    scores = {}
    for move in list(board.legal_moves):
        board.push(move)
        scores[move] = reference(board, 0, 1)
        board.pop()
    best = (max if board.turn else min)(scores.values())
    return board, best, {move for move, score in scores.items() if score == best}


@pytest.mark.parametrize("pruning,pvs", [(False, False), (True, False), (True, True)])
@pytest.mark.parametrize("cached", [False, True])
def test_quiescence_matches_independent_tactical_oracle(engine, oracle_position, pruning, pvs, cached):
    board, best, optimal = oracle_position
    engine.configure({"Quiescence": True, "PVS": pvs, "AlphaBeta": pruning,
                      "UsePST": False, "TranspositionTable": cached})
    result = engine.play(board, chess.engine.Limit(depth=1, time=4), info=chess.engine.INFO_ALL)
    assert result.info["depth"] == 1 and result.move in optimal
    score = result.info["score"].white()
    if abs(best) >= 29872:
        assert score.mate() == ((30000 - abs(best) + 1) // 2) * (1 if best > 0 else -1)
    else:
        assert score.score() == best
    counters = search_counters(result.info)
    assert 0 < counters["qnodes"] <= result.info["nodes"]
    if not pruning or not pvs:
        assert counters["scouts"] == counters["researches"] == 0


@pytest.mark.parametrize("fen", [chess.STARTING_FEN, KIWIPETE, POISONED,
                                chess.Board(POISONED).mirror().fen(),
                                "8/5pk1/6p1/8/3K4/6P1/5P2/8 w - - 0 1",
                                "7k/8/5KQ1/8/8/8/8/8 w - - 0 1"])
@pytest.mark.parametrize("qsearch", [False, True])
@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("iterative", [False, True])
@pytest.mark.parametrize("pst", [False, True])
def test_pvs_matches_full_window_alpha_beta(engine, fen, qsearch, cached, iterative, pst):
    board = chess.Board(fen)
    results = []
    for pvs in (False, True):
        engine.configure({"Quiescence": qsearch, "PVS": pvs, "AlphaBeta": True,
                          "TranspositionTable": cached, "IterativeDeepening": iterative, "UsePST": pst})
        result = engine.play(board, chess.engine.Limit(depth=3, time=5), info=chess.engine.INFO_ALL)
        assert result.info["depth"] == 3 and result.move in board.legal_moves
        pv_board = board.copy()
        for move in result.info["pv"]:
            assert move in pv_board.legal_moves
            pv_board.push(move)
        assert len(result.info["pv"]) >= 3 or pv_board.is_game_over(claim_draw=True)
        if qsearch:
            assert not pv_board.is_check() or pv_board.is_checkmate()
        else:
            assert len(result.info["pv"]) <= 3
            assert search_counters(result.info)["qnodes"] == 0
        assert result.info["seldepth"] >= len(result.info["pv"])
        results.append(result)
    assert results[0].info["score"] == results[1].info["score"]
    if results[0].move != results[1].move and not results[1].info["score"].white().is_mate():
        child = board.copy()
        child.push(results[1].move)
        engine.configure({"PVS": False, "TranspositionTable": False, "IterativeDeepening": False})
        value = engine.play(child, chess.engine.Limit(depth=2, time=5), info=chess.engine.INFO_ALL)
        assert value.info["score"].white() == results[1].info["score"].white()


def test_quiescence_rejects_poisoned_pawn_at_depth_one(engine):
    board = chess.Board(POISONED)
    results = []
    for qsearch in (False, True):
        engine.configure({"Quiescence": qsearch, "PVS": True})
        results.append(engine.play(board, chess.engine.Limit(depth=1), info=chess.engine.INFO_ALL))
    assert results[0].move.uci() == "a3a4"
    assert results[1].move != results[0].move
    assert results[0].info["score"].white().score() == 800
    # Qb2+ can win the b-pawn after a forced king evasion. The safe line retains
    # +800; Qxa4 itself loses the queen to ...bxa4 and evaluates to -100.
    assert results[1].info["score"].white().score() == 800
    board.push_uci("a3a4")
    assert reference(board, 0, 1) == -100


def test_pvs_scouts_and_researches_are_exercised_without_ordering(engine):
    engine.configure({"Quiescence": True, "PVS": True, "UsePST": True, "MoveOrdering": False})
    result = engine.play(chess.Board(), chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
    counters = search_counters(result.info)
    assert counters["scouts"] >= counters["researches"] > 0


def test_pvs_is_inactive_for_minimax(engine):
    results = []
    for pvs in (False, True):
        engine.configure({"Quiescence": True, "PVS": pvs, "AlphaBeta": False, "UsePST": True})
        results.append(engine.play(chess.Board(), chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL))
    for key in ("nodes", "score", "pv"):
        assert results[0].info[key] == results[1].info[key]
    assert search_counters(results[1].info)["scouts"] == 0


def test_quiescence_safety_cap_is_exercised_in_dense_position(engine):
    engine.configure({"Quiescence": True, "PVS": False, "UsePST": True, "TranspositionTable": True})
    result = engine.play(chess.Board(KIWIPETE), chess.engine.Limit(depth=3, time=5), info=chess.engine.INFO_ALL)
    assert result.info["depth"] == 3 and result.info["seldepth"] <= 64
    assert search_counters(result.info)["qcaps"] > 0


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("pvs", [False, True])
def test_quiescence_and_pvs_share_node_budget_and_keep_completed_pv(engine, cached, pvs):
    engine.configure({"Quiescence": True, "PVS": pvs, "TranspositionTable": cached, "AlphaBeta": False})
    shallow = engine.play(chess.Board(POISONED), chess.engine.Limit(depth=1), info=chess.engine.INFO_ALL)
    limit = shallow.info["nodes"] + 1
    result = engine.play(chess.Board(POISONED), chess.engine.Limit(depth=5, nodes=limit), info=chess.engine.INFO_ALL)
    assert result.info["depth"] == 1 and result.info["nodes"] == limit
    assert result.move == shallow.move and result.info["score"] == shallow.info["score"]
    assert result.info["pv"] == shallow.info["pv"]
