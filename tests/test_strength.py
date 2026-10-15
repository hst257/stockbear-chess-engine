"""Ordering estimates, selective guards, tuning math and endgame conversion."""
import json
import random
import subprocess

import chess
import chess.engine
import pytest

from tools.benchmark_optimizations import POSITIONS, counters
from tools.tune_evaluation import fit, loss, predict, truncate

NEW_SEARCH = ("UseHistory", "UseKillers", "UseSEE", "UseAdaptiveLMR",
              "UseReverseFutility", "UseFutility", "UseCheckExtensions")


@pytest.mark.parametrize("fen,move,expected", [
    ("7k/8/8/4p3/3P4/8/8/K7 w - - 0 1", "d4e5", 100),
    ("7k/8/5p2/4p3/3Q4/8/8/K7 w - - 0 1", "d4e5", -800),
    ("5k2/8/5n2/3p4/2P5/8/8/K4R2 w - - 0 1", "c4d5", 100),  # pinned knight
    ("7k/8/8/3pP3/8/8/8/K7 w - d6 0 1", "e5d6", 100),
    ("7k/4P3/8/8/8/8/8/K7 w - - 0 1", "e7e8q", 800),
    ("7r/6P1/k7/8/8/8/8/K7 w - - 0 1", "g7h8q", 1300),
    ("7r/6P1/k7/8/8/8/8/K7 w - - 0 1", "g7h8n", 720),
    ("6k1/6p1/8/8/8/8/6Q1/K5R1 w - - 0 1", "g2g7", 100),  # protected from king
    ("4k3/8/8/8/8/8/8/4K2R w K - 0 1", "e1g1", 0),
])
def test_see_material_and_legality(engine_path, fen, move, expected):
    board = chess.Board(fen)
    assert board.is_valid() and chess.Move.from_uci(move) in board.legal_moves
    for position in (board, board.mirror()):
        mirrored = (chess.Move(chess.square_mirror(chess.parse_square(move[:2])),
                               chess.square_mirror(chess.parse_square(move[2:4])),
                               promotion=chess.Move.from_uci(move).promotion)
                    if position is not board else chess.Move.from_uci(move))
        output = subprocess.check_output([str(engine_path), "--see", position.fen(), mirrored.uci()], text=True)
        assert int(output) == expected


def test_see_matches_independent_legal_exchange_oracle(engine_path):
    # Restrict generated positions to pawns/rooks so the exchange tree has
    # unambiguous least-valued attackers; the oracle uses legal move generation.
    values = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
              chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}
    def exchanges(board, square):
        best = 0
        for move in board.legal_moves:
            if move.to_square != square or not board.is_capture(move):
                continue
            gain = values[board.piece_type_at(square)]
            if move.promotion:
                gain += values[move.promotion] - 100
            board.push(move)
            best = max(best, gain - exchanges(board, square))
            board.pop()
        return best
    rng = random.Random(187)
    verified = 0
    for _ in range(200):
        board = chess.Board("7k/8/8/8/8/8/8/K7 w - - 0 1")
        for symbol in ("P", "P", "p", "p", "R", "r"):
            square = rng.choice(range(8, 56))
            if board.piece_at(square) is None:
                board.set_piece_at(square, chess.Piece.from_symbol(symbol))
        if not board.is_valid() or board.is_check():
            continue
        for move in list(board.legal_moves):
            if not board.is_capture(move) or move.promotion:
                continue
            gain = values[board.piece_type_at(move.to_square)]
            board.push(move)
            expected = gain - exchanges(board, move.to_square)
            board.pop()
            value = int(subprocess.check_output([str(engine_path), "--see", board.fen(), move.uci()], text=True))
            assert value == expected
            verified += 1
    assert verified >= 20


@pytest.mark.parametrize("feature", ("UseHistory", "UseKillers", "UseSEE"))
@pytest.mark.parametrize("black", (False, True))
def test_ordering_preserves_exhaustive_score(engine, feature, black):
    board = chess.Board(POSITIONS["middlegame"])
    if black:
        board = board.mirror()
    engine.configure({"UsePST": True, "PVS": True, "Quiescence": True})
    results = []
    for enabled in (False, True):
        engine.configure({feature: enabled})
        result = engine.play(board, chess.engine.Limit(depth=4), info=chess.engine.INFO_ALL)
        replay = board.copy()
        for move in result.info["pv"]:
            assert move in replay.legal_moves
            replay.push(move)
        results.append(result.info["score"])
    assert results[0] == results[1]


def test_production_features_exercised_and_search_local(engine_path):
    with chess.engine.SimpleEngine.popen_uci(str(engine_path)) as instance:
        for name in (*NEW_SEARCH, "UseMopUp"):
            assert instance.options[name].default is True
        board = chess.Board(POSITIONS["middlegame"])
        runs = [instance.play(board, chess.engine.Limit(depth=5), info=chess.engine.INFO_ALL) for _ in range(2)]
        assert runs[0].info["score"] == runs[1].info["score"] and runs[0].info["pv"] == runs[1].info["pv"]
        assert runs[0].info["nodes"] == runs[1].info["nodes"]
        c = counters(runs[0].info)
        for name in ("history_updates", "killer_cutoffs", "see_calls", "reverse_futility_cutoffs",
                     "futility_prunes", "check_extensions", "lmr_verifications"):
            assert c[name] > 0, name


@pytest.mark.parametrize("black", (False, True))
def test_selective_guards_and_minimax(engine, black):
    engine.configure({name: True for name in NEW_SEARCH})
    board = chess.Board(POSITIONS["middlegame"])
    if black:
        board = board.mirror()
    engine.configure({"AlphaBeta": False})
    result = engine.play(board, chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
    c = counters(result.info)
    for name in ("history_updates", "killer_cutoffs", "reverse_futility_cutoffs", "futility_prunes", "check_extensions"):
        assert c[name] == 0
    engine.configure({"AlphaBeta": True, "PVS": True})
    board = chess.Board(POSITIONS["zugzwang"])
    result = engine.play(board, chess.engine.Limit(depth=5), info=chess.engine.INFO_ALL)
    c = counters(result.info)
    assert c["reverse_futility_cutoffs"] == c["futility_prunes"] == 0


@pytest.mark.parametrize("black", (False, True))
@pytest.mark.parametrize("cached", (False, True))
def test_new_search_preserves_sacrifice_and_quiet_mate(engine, black, cached):
    from tests.test_optimizations import opera_board
    engine.configure({name: True for name in NEW_SEARCH})
    engine.configure({"UseAdvancedEvaluation": True, "TranspositionTable": cached, "UsePST": True,
                      "Quiescence": True, "PVS": True, "UseNullMovePruning": True, "UseLMR": True})
    for board in (opera_board(), chess.Board("7k/4Q3/8/5K2/8/8/8/8 w - - 0 1")):
        if black:
            board = board.mirror()
        result = engine.play(board, chess.engine.Limit(depth=5), info=chess.engine.INFO_ALL)
        assert result.info["score"].pov(board.turn).mate() == 2
        for move in result.info["pv"]:
            assert move in board.legal_moves
            board.push(move)


def eval_batch(engine_path, fens, options=None):
    commands = [f"setoption name {name} value {str(value).lower()}" for name, value in (options or {}).items()]
    for fen in fens:
        commands.extend(("position fen " + fen, "eval"))
    output = subprocess.check_output([str(engine_path)], input="\n".join(commands + ["quit"]) + "\n", text=True)
    return [json.loads(s.removeprefix("info string eval ")) for s in output.splitlines() if s.startswith("info string eval ")]


def test_mop_up_gates_symmetry_and_king_gradient(engine_path):
    far = chess.Board("7k/8/8/8/8/8/8/K3R3 w - - 0 1")
    near = chess.Board("7k/8/5K2/8/8/8/8/4R3 w - - 0 1")
    a, b, mirror = eval_batch(engine_path, [far.fen(), near.fen(), near.mirror().fen()])
    assert b["components"]["endgame"]["eg"] > a["components"]["endgame"]["eg"]
    assert mirror["total"] == -b["total"]
    off = eval_batch(engine_path, [near.fen()], {"UseMopUp": False})[0]
    assert off["components"]["endgame"]["eg"] == 0
    for fen in (chess.STARTING_FEN, "7k/8/8/8/8/8/8/K3NN2 w - - 0 1",
                "7k/8/8/8/8/8/8/K3B3 w - - 0 1", "7k/8/8/8/8/8/8/K3R2r w - - 0 1"):
        assert eval_batch(engine_path, [fen])[0] == eval_batch(engine_path, [fen], {"UseMopUp": False})[0]


def test_weights_match_tuner_integer_prediction(engine_path):
    from tools.tune_evaluation import COMPONENTS, OPTION_NAMES
    board = chess.Board(POSITIONS["middlegame"])
    raw = eval_batch(engine_path, [board.fen()])[0]
    weights = [50 + i * 7 for i in range(18)]
    value = eval_batch(engine_path, [board.fen()], dict(zip(OPTION_NAMES, weights)))[0]
    comp = raw["components"]
    row = {"phase": raw["phase"], "scale": raw["scale"],
           "fixed": [sum(comp[n][p] for n in ("material", "pst")) for p in ("mg", "eg")],
           "features": [[comp[n][p] for p in ("mg", "eg")] for n in COMPONENTS]}
    assert value["total"] == predict(row, weights)
    mirrored = eval_batch(engine_path, [board.mirror().fen()], dict(zip(OPTION_NAMES, weights)))[0]
    assert mirrored["total"] == -value["total"]


def test_tuner_fits_signal_and_truncates_like_cpp():
    rows = [{"phase": 24, "scale": 256, "fixed": [0, 0],
             "features": [[n, 0]] + [[0, 0]] * 8, "target_cp": truncate(n * 150, 100)}
            for n in range(-300, 301, 30)]
    fitted = fit(rows)
    assert fitted[0] == 150 and loss(rows, fitted) < loss(rows, [100] * 18)
    assert truncate(-5, 2) == -2
