"""Static evaluator diagnostics and their integration into actual C++ searches."""

import json
import random
import subprocess

import chess
import chess.engine
import pytest


def breakdown(engine_path, board, use_pst=True):
    command = [str(engine_path), "--eval"]
    if not use_pst:
        command.append("--no-pst")
    result = subprocess.run([*command, board.fen()], check=True, text=True,
                            capture_output=True, timeout=3)
    assert not result.stderr
    value = json.loads(result.stdout)
    assert value["use_pst"] == use_pst
    assert value["positional"] == sum(value["pst"].values())
    assert value["total"] == value["material"] + value["positional"]
    return value


def position(piece, square):
    board = chess.Board(None)
    board.set_piece_at(chess.H1, chess.Piece(chess.KING, chess.WHITE))
    board.set_piece_at(chess.H8, chess.Piece(chess.KING, chess.BLACK))
    board.set_piece_at(square, chess.Piece(piece, chess.WHITE))
    board.turn = chess.BLACK  # A White piece may legitimately be giving check.
    return board


@pytest.mark.parametrize("piece,square,name,bonus,material", [
    (chess.PAWN, chess.E2, "pawn", -20, 100),
    (chess.PAWN, chess.E7, "pawn", 50, 100),
    (chess.KNIGHT, chess.B3, "knight", 5, 320),
    (chess.KNIGHT, chess.B6, "knight", 0, 320),
    (chess.BISHOP, chess.B2, "bishop", 5, 330),
    (chess.ROOK, chess.D1, "rook", 5, 500),
    (chess.ROOK, chess.D7, "rook", 10, 500),
    (chess.QUEEN, chess.C2, "queen", 5, 900),  # C2 differs from F2: mirror ranks only.
    (chess.QUEEN, chess.C7, "queen", 0, 900),
])
def test_table_values_and_black_rank_orientation(engine_path, piece, square, name, bonus, material):
    board = position(piece, square)
    value = breakdown(engine_path, board)
    mirrored = breakdown(engine_path, board.mirror())
    assert value["pst"][name] == bonus
    assert value["material"] == material
    assert value["pst"]["king"] == 0  # Identically oriented kings cancel.
    assert value["total"] == material + bonus
    assert mirrored["total"] == -value["total"]
    assert mirrored["phase"] == value["phase"]
    assert mirrored["pst"] == {key: -score for key, score in value["pst"].items()}
    off = breakdown(engine_path, board, False)
    assert off["total"] == material and off["positional"] == 0
    assert all(score == 0 for score in off["pst"].values())


def king_position(square, phase):
    board = chess.Board(None)
    board.set_piece_at(square, chess.Piece(chess.KING, chess.WHITE))
    board.set_piece_at(chess.H8, chess.Piece(chess.KING, chess.BLACK))
    for name in ("a2", "b2", "c2", "d2", "e2", "f2", "h2")[:phase // 4]:
        board.set_piece_at(chess.parse_square(name), chess.Piece(chess.QUEEN, chess.WHITE))
    if phase % 4 >= 2:
        board.set_piece_at(chess.G2, chess.Piece(chess.ROOK, chess.WHITE))
    if phase % 2:
        board.set_piece_at(chess.A3, chess.Piece(chess.KNIGHT, chess.WHITE))
    board.turn = chess.BLACK
    return board


def rounded_blend(mg, eg, phase):
    numerator = mg * phase + eg * (24 - phase)
    return (1 if numerator >= 0 else -1) * ((abs(numerator) + 12) // 24)


@pytest.mark.parametrize("phase", range(25))
def test_king_phase_interpolation_and_symmetric_rounding(engine_path, phase):
    board = king_position(chess.B1, phase)
    value = breakdown(engine_path, board)
    assert value["phase"] == phase
    # White B1: MG +30, EG -30; Black H8 mirrors White H1: MG +20, EG -50.
    expected = rounded_blend(30, -30, phase) - rounded_blend(20, -50, phase)
    assert value["pst"]["king"] == expected
    mirror = breakdown(engine_path, board.mirror())
    assert mirror["pst"]["king"] == -expected
    assert mirror["total"] == -value["total"]


def test_phase_clamps_promoted_material_and_ignores_pawns(engine_path):
    board = king_position(chess.B1, 28)
    assert breakdown(engine_path, board)["phase"] == 24
    board = position(chess.PAWN, chess.D4)
    assert breakdown(engine_path, board)["phase"] == 0
    assert breakdown(engine_path, chess.Board())["phase"] == 24


def test_knight_centralization_has_modest_bonus(engine_path):
    center = breakdown(engine_path, position(chess.KNIGHT, chess.D4))
    edge = breakdown(engine_path, position(chess.KNIGHT, chess.A3))
    assert center["material"] == edge["material"] == 320
    assert center["pst"]["knight"] == 20 and edge["pst"]["knight"] == -30
    assert center["total"] - edge["total"] == 50


@pytest.mark.parametrize("phase", [0, 24])
def test_king_prefers_castled_square_in_middlegame_and_center_in_endgame(engine_path, phase):
    castled = breakdown(engine_path, king_position(chess.G1, phase))["pst"]["king"]
    center = breakdown(engine_path, king_position(chess.D4, phase))["pst"]["king"]
    if phase == 24:
        assert castled > center
    else:
        assert center > castled


def test_corrected_king_corner_signs(engine_path):
    board = king_position(chess.A1, 0)
    assert breakdown(engine_path, board)["pst"]["king"] == 0  # Both endgame corners -50.
    board = king_position(chess.A4, 24)
    assert breakdown(engine_path, board)["pst"]["king"] == -40  # MG A4 -20 minus H1 +20.


def test_seeded_positions_mirror_every_component_and_do_not_double_count_material(engine_path):
    rng = random.Random(97)
    board = chess.Board()
    for _ in range(12):
        for _ in range(4):
            if not board.is_game_over():
                board.push(rng.choice(list(board.legal_moves)))
        value = breakdown(engine_path, board)
        mirrored = breakdown(engine_path, board.mirror())
        material = sum(points * (len(board.pieces(kind, chess.WHITE)) - len(board.pieces(kind, chess.BLACK)))
                       for kind, points in ((1, 100), (2, 320), (3, 330), (4, 500), (5, 900)))
        assert value["material"] == material
        assert mirrored["material"] == -material
        assert mirrored["total"] == -value["total"]
        assert mirrored["pst"] == {key: -score for key, score in value["pst"].items()}
        # Side to move does not change a fixed White-relative static evaluation.
        if not board.is_check():
            opposite_turn = board.copy()
            opposite_turn.turn = not opposite_turn.turn
            assert breakdown(engine_path, opposite_turn) == value


def test_fresh_engine_defaults_to_pst_and_can_restore_original_opening(engine_path):
    with chess.engine.SimpleEngine.popen_uci(str(engine_path)) as fresh:
        board = chess.Board()
        result = fresh.play(board, chess.engine.Limit(depth=1), info=chess.engine.INFO_ALL)
        assert result.move.uci() in ("b1c3", "g1f3")
        assert result.info["score"].white().score() == 50
        fresh.configure({"UsePST": False})
        plain = fresh.play(board, chess.engine.Limit(depth=1), info=chess.engine.INFO_ALL)
        assert plain.move.uci() == "a2a3" and plain.info["score"].white().score() == 0


@pytest.mark.parametrize("fen", [
    chess.STARTING_FEN,
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "7k/8/8/1p6/p7/Q7/8/7K w - - 0 1",
    "8/5pk1/6p1/8/3K4/6P1/5P2/8 w - - 0 1",
])
@pytest.mark.parametrize("iterative", [False, True])
def test_pst_minimax_and_alpha_beta_agree_and_return_legal_pv(engine, engine_path, fen, iterative):
    board = chess.Board(fen)
    results = []
    for pruning in (False, True):
        engine.configure({"UsePST": True, "AlphaBeta": pruning, "IterativeDeepening": iterative})
        result = engine.play(board, chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
        assert result.info["depth"] == 3 and result.move in board.legal_moves
        pv_board = board.copy()
        for move in result.info["pv"]:
            assert move in pv_board.legal_moves
            pv_board.push(move)
        # No mate/draw leaves in these test PVs: diagnostics equal the search leaf.
        assert not pv_board.is_game_over(claim_draw=True)
        assert result.info["score"].white().score() == breakdown(engine_path, pv_board)["total"]
        results.append(result)
    assert results[0].info["score"] == results[1].info["score"]
    assert results[0].move == results[1].move


@pytest.mark.parametrize("fen,mate", [
    ("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", 0),
    ("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", None),
    ("7k/8/8/8/3N4/8/8/7K w - - 0 1", None),
    ("7k/8/8/8/8/8/R7/7K w - - 100 51", None),
    ("7k/8/5KQ1/8/8/8/8/8 w - - 99 50", 1),
])
def test_pst_preserves_terminal_scores_over_positional_bonuses(engine, fen, mate):
    engine.configure({"UsePST": True})
    result = engine.play(chess.Board(fen), chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
    if mate is None:
        assert not result.move and result.info["score"].relative.score() == 0
    else:
        assert result.info["score"].relative.mate() == mate
        if mate == 0:
            assert not result.move
