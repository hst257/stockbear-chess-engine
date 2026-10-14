"""Check reordered search against an independent rules/evaluation oracle."""

import chess
import chess.engine
import pytest


def reference_score(board, depth, ply):
    moves = list(board.legal_moves)
    if not moves:
        return (-30000 + ply if board.turn else 30000 - ply) if board.is_check() else 0
    if board.is_insufficient_material() or board.halfmove_clock >= 100 or board.is_repetition(3):
        return 0
    if depth == 0:
        return sum(value * (len(board.pieces(piece, chess.WHITE)) - len(board.pieces(piece, chess.BLACK)))
                   for piece, value in ((chess.PAWN, 100), (chess.KNIGHT, 320), (chess.BISHOP, 330),
                                        (chess.ROOK, 500), (chess.QUEEN, 900)))
    scores = []
    for move in moves:
        board.push(move)
        scores.append(reference_score(board, depth - 1, ply + 1))
        board.pop()
    return (max if board.turn else min)(scores)


@pytest.fixture(scope="module", params=[
    chess.STARTING_FEN,
    "r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1",
    "r3k2r/8/8/8/8/8/8/R3K2R b KQkq - 0 1",
    "7k/P7/8/8/8/8/8/7K w - - 0 1",
    "7k/8/8/8/8/8/p7/7K b - - 0 1",
    "4r1k1/8/8/8/8/8/4R3/4K3 w - - 0 1",
    "7k/8/8/3pP3/8/8/8/7K w - d6 0 2",
    "7k/8/8/8/3pP3/8/8/7K b - e3 0 2",
    "1r5k/P7/8/8/8/8/8/7K w - - 0 1",
    "7k/8/8/8/8/8/p7/1R5K b - - 0 1",
    "7k/8/8/1p6/p7/Q7/8/7K w - - 0 1",
    "r6k/Q7/8/8/8/8/8/7K b - - 0 1",
    "7k/8/5KQ1/8/8/8/8/8 w - - 0 1",
])
def reference_position(request):
    board = chess.Board(request.param)
    scores = {}
    for move in list(board.legal_moves):
        board.push(move)
        scores[move] = reference_score(board, 1, 1)
        board.pop()
    best = (max if board.turn else min)(scores.values())
    return board, best, {move for move, score in scores.items() if score == best}


@pytest.mark.parametrize("pruning", [False, True])
@pytest.mark.parametrize("iterative", [False, True])
def test_ordering_preserves_optimal_score_and_move(engine, reference_position, pruning, iterative):
    board, best, optimal = reference_position
    for ordering in (False, True):
        engine.configure({"AlphaBeta": pruning, "IterativeDeepening": iterative, "MoveOrdering": ordering})
        result = engine.play(board, chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
        assert result.info["depth"] == 2
        assert result.move in optimal
        score = result.info["score"].white()
        if abs(best) >= 29872:
            assert score.mate() == ((30000 - abs(best) + 1) // 2) * (1 if best > 0 else -1)
        else:
            assert score.score() == best
        pv_board = board.copy()
        for move in result.info["pv"]:
            assert move in pv_board.legal_moves
            pv_board.push(move)


@pytest.mark.parametrize("pruning,iterative,nodes", [
    (False, False, 9323), (True, False, 586), (False, True, 9765), (True, True, 667),
])
def test_disabling_ordering_retains_original_node_baseline(engine, pruning, iterative, nodes):
    engine.configure({"AlphaBeta": pruning, "IterativeDeepening": iterative, "MoveOrdering": False})
    result = engine.play(chess.Board(), chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
    assert result.info["nodes"] == nodes
    assert result.move == chess.Move.from_uci("a2a3")
    assert result.info["score"].white().score() == 0


@pytest.mark.parametrize("iterative", [False, True])
def test_ordering_reduces_alpha_beta_work_on_tactical_position(engine, iterative):
    board = chess.Board("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1")
    results = []
    for ordering in (False, True):
        engine.configure({"AlphaBeta": True, "IterativeDeepening": iterative, "MoveOrdering": ordering})
        results.append(engine.play(board, chess.engine.Limit(depth=4), info=chess.engine.INFO_ALL))
    plain, ordered = results
    assert plain.info["depth"] == ordered.info["depth"] == 4
    assert plain.info["score"] == ordered.info["score"]
    assert plain.move == ordered.move
    assert ordered.info["nodes"] < plain.info["nodes"] / 2


def test_pv_ordering_does_not_leak_between_searches(engine):
    engine.configure({"MoveOrdering": True})
    first = engine.play(chess.Board(), chess.engine.Limit(depth=4), info=chess.engine.INFO_ALL)
    engine.play(chess.Board("7k/8/8/1p6/p7/Q7/8/7K w - - 0 1"), chess.engine.Limit(depth=3))
    again = engine.play(chess.Board(), chess.engine.Limit(depth=4), info=chess.engine.INFO_ALL)
    assert first.move == again.move
    for key in ("nodes", "score", "pv"):
        assert first.info[key] == again.info[key]


@pytest.mark.parametrize("iterative", [False, True])
def test_ordering_preserves_exhaustive_minimax_node_count(engine, iterative):
    board = chess.Board("r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1")
    results = []
    for ordering in (False, True):
        engine.configure({"AlphaBeta": False, "IterativeDeepening": iterative, "MoveOrdering": ordering})
        results.append(engine.play(board, chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL))
    assert results[0].info["depth"] == results[1].info["depth"] == 3
    assert results[0].info["nodes"] == results[1].info["nodes"]
    assert results[0].info["score"] == results[1].info["score"]
