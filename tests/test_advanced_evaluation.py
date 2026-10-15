"""Component-level contracts for the allocation-free C++ evaluator."""
import json
import random
import subprocess

import chess
import chess.engine
import pytest

from tests.test_engine import protocol


def diagnostic(engine_path, fen, *flags):
    return json.loads(subprocess.check_output(
        [str(engine_path), "--eval", *flags, fen], text=True, timeout=5))


def component(engine_path, fen, name):
    return diagnostic(engine_path, fen)["components"][name]


def position(**pieces):
    board = chess.Board("7k/8/8/8/8/8/8/K7 w - - 0 1")
    for square, symbol in pieces.items():
        board.set_piece_at(chess.parse_square(square), chess.Piece.from_symbol(symbol))
    return board.fen()


@pytest.mark.parametrize("seed", range(8))
def test_components_reconcile_and_mirror(engine_path, seed):
    rng = random.Random(seed)
    board = chess.Board()
    for _ in range(seed * 7):
        if not board.is_game_over():
            board.push(rng.choice(list(board.legal_moves)))
    value = diagnostic(engine_path, board.fen())
    mirror = diagnostic(engine_path, board.mirror().fen())
    assert value["advanced"]
    assert value["mg"] == sum(c["mg"] for c in value["components"].values())
    assert value["eg"] == sum(c["eg"] for c in value["components"].values())
    cp = sum(c["cp"] for c in value["components"].values())
    assert value["total"] == cp + value["rounding"] + value["scaling"]
    assert mirror["phase"] == value["phase"]
    assert mirror["total"] == -value["total"]
    for name, c in value["components"].items():
        assert mirror["components"][name] == {k: -v for k, v in c.items()}
    if not board.is_check():
        board.turn = not board.turn
        assert diagnostic(engine_path, board.fen()) == value


@pytest.mark.parametrize("phase", range(25))
def test_single_global_taper(engine_path, phase):
    from tests.test_evaluation import king_position, rounded_blend
    value = diagnostic(engine_path, king_position(chess.B1, phase).fen())
    assert value["phase"] == phase
    blended = rounded_blend(value["mg"], value["eg"], phase)
    expected = (1 if blended >= 0 else -1) * (abs(blended) * value["scale"] // 256)
    assert value["total"] == expected


def test_baseline_and_material_switches(engine_path):
    fen = position(d4="N", b2="P")
    legacy = diagnostic(engine_path, fen, "--baseline")
    assert not legacy["advanced"]
    assert legacy["total"] == legacy["material"] + sum(legacy["pst"].values())
    assert diagnostic(engine_path, fen, "--baseline", "--no-pst")["total"] == 420


def test_advanced_uci_default_and_diagnostic_search_identity(engine_path):
    with chess.engine.SimpleEngine.popen_uci(str(engine_path)) as engine:
        assert engine.options["UseAdvancedEvaluation"].default is True
        engine.configure({"Quiescence": False, "UseNullMovePruning": False, "UseLMR": False})
        for board in (chess.Board(), chess.Board(position(d4="P", f4="N", b6="p"))):
            result = engine.play(board, chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
            assert result.move in board.legal_moves
            for move in result.info["pv"]:
                assert move in board.legal_moves
                board.push(move)
            assert result.info["score"].white().score() == diagnostic(engine_path, board.fen())["total"]


@pytest.mark.parametrize("mirror", [False, True])
@pytest.mark.parametrize("pieces,expected", [
    ({"d3": "P", "d4": "P"}, (-32, -46)),  # two isolated, one doubled
    ({"d4": "P"}, (-10, -14)),
    ({"d4": "P", "e4": "P"}, (10, 16)),
    ({"d4": "P", "e3": "P"}, (5, 8)),
    ({"d3": "P", "e4": "P", "c5": "p", "b6": "p"}, (-8, -10)),
])
def test_pawn_structure(engine_path, mirror, pieces, expected):
    board = chess.Board(position(**pieces))
    white = component(engine_path, board.fen(), "pawn_structure")
    if mirror:
        board = board.mirror()
    value = component(engine_path, board.fen(), "pawn_structure")
    assert (white["mg"], white["eg"]) == expected
    assert (value["mg"], value["eg"]) == tuple((-1 if mirror else 1) * n for n in expected)


def test_passers_advancement_protection_blocking_and_enemy_corridor(engine_path):
    def score(**pieces):
        return component(engine_path, position(**pieces), "passed_pawns")["eg"]
    assert score(d6="P") > score(d4="P") > score(d3="P")
    assert score(d6="P", c5="P") > score(d6="P", c5="N")
    assert score(d6="P", d7="n") == score(d6="P") // 2
    assert score(d6="P", d8="r") == score(d6="P") // 2
    assert score(d4="P", e6="p") == 0
    assert score(d4="P", f6="p") != 0  # two separate passers
    value = diagnostic(engine_path, position(d6="P"))
    off = diagnostic(engine_path, position(d6="P"), "--disable", "EvalPassers")
    assert off["components"]["passed_pawns"] == {"mg": 0, "eg": 0, "cp": 0}
    assert value["components"]["passed_pawns"]["eg"] == 80


def test_bishop_pair_requires_both_square_colors(engine_path):
    assert component(engine_path, position(c1="B", f1="B"), "bishop_pair")["mg"] == 25
    assert component(engine_path, position(c1="B", e3="B"), "bishop_pair")["eg"] == 0
    assert component(engine_path, position(c1="B"), "bishop_pair")["eg"] == 0


def test_rook_files_seventh_and_behind_passers(engine_path):
    def rook(**pieces):
        return component(engine_path, position(**pieces), "rook_activity")
    assert rook(d4="R")["mg"] == 18
    assert rook(d4="R", d6="p")["mg"] == 10  # semi-open, enemy pawn ahead
    assert rook(d4="R", d3="P")["mg"] == 0  # friendly pawn excludes open-file bonus
    assert rook(d7="R")["eg"] - rook(d4="R")["eg"] == 25
    assert rook(d2="R", d6="P")["eg"] == 20  # behind own passer, no open-file bonus
    assert rook(d2="R", d4="N", d6="P")["eg"] == 0
    board = chess.Board(position(d2="R", d6="P"))
    assert component(engine_path, board.mirror().fen(), "rook_activity")["eg"] == -20


@pytest.mark.parametrize("piece", ["N", "B", "R", "Q"])
def test_mobility_rewards_safe_activity(engine_path, piece):
    def mobility(**pieces):
        board = chess.Board(position(**pieces))
        board.remove_piece_at(chess.H8)
        board.set_piece_at(chess.G8, chess.Piece(chess.KING, chess.BLACK))
        return component(engine_path, board.fen(), "mobility")
    free = mobility(d4=piece)
    blocked = mobility(d4=piece, c3="P", c4="P", c5="P", d3="P", d5="P", e3="P", e4="P", e5="P",
                       c2="P", e2="P", f3="P", f5="P")
    assert free["mg"] > blocked["mg"]
    assert free["eg"] > blocked["eg"]


def test_mobility_avoids_enemy_pawn_attacks(engine_path):
    # c6/e6 become unsafe knight destinations when the black pawn moves to d7.
    safe = component(engine_path, position(d4="N", d2="p"), "mobility")["mg"]
    unsafe = component(engine_path, position(d4="N", d7="p"), "mobility")["mg"]
    assert safe > unsafe


def test_moving_piece_is_not_its_own_defender(engine_path):
    # Nd4 has six safe destinations; Ba6 has five. Their common targets b5/e2
    # are attacked by the other side and have no second friendly defender.
    value = component(engine_path, position(d4="N", a6="b"), "mobility")
    assert value["mg"] == 3 * (6 - 4) - 3 * (5 - 6)
    assert value["eg"] == 3 * (6 - 4) - 4 * (5 - 6)


def test_outposts_need_support_advancement_and_no_future_pawn_challenge(engine_path):
    def outpost(**pieces):
        return component(engine_path, position(**pieces), "outposts")["mg"]
    assert outpost(d5="N", c4="P") == 18
    assert outpost(d5="N") == 0
    assert outpost(d3="N", c2="P") == 0
    assert outpost(d5="N", c4="P", e7="p") == 0
    assert outpost(d5="N", c4="P", e4="p") == 18  # enemy cannot move backwards
    board = chess.Board(position(d5="N", c4="P"))
    assert component(engine_path, board.mirror().fen(), "outposts")["mg"] == -18


def king_safety_board(shield=True, queen=True):
    board = chess.Board("r2q2k1/5ppp/8/8/8/8/8/6K1 w - - 0 1")
    if shield:
        for sq in (chess.F2, chess.G2, chess.H2):
            board.set_piece_at(sq, chess.Piece(chess.PAWN, chess.WHITE))
    if not queen:
        board.remove_piece_at(chess.D8)
    return board


def test_king_shield_and_attacking_material_scale(engine_path):
    def safety(board):
        return component(engine_path, board.fen(), "king_safety")
    shield = king_safety_board()
    exposed = king_safety_board(False)
    assert safety(shield)["mg"] > safety(exposed)["mg"]
    assert safety(exposed)["mg"] < safety(king_safety_board(False, False))["mg"]
    assert safety(exposed)["eg"] == 0
    no_major = king_safety_board(False, False)
    no_major.remove_piece_at(chess.A8)
    assert safety(no_major)["mg"] == 0
    assert safety(exposed.mirror())["mg"] == -safety(exposed)["mg"]


def test_king_zone_pressure_counts_enemies(engine_path):
    board = king_safety_board()
    quiet = component(engine_path, board.fen(), "king_safety")["mg"]
    board.remove_piece_at(chess.D8)
    board.set_piece_at(chess.H4, chess.Piece(chess.QUEEN, chess.BLACK))
    attacked = component(engine_path, board.fen(), "king_safety")["mg"]
    assert attacked < quiet
    # With only friendly attacking material, White has no safety penalty.
    board = chess.Board("7k/8/8/8/7Q/8/5PPP/6K1 w - - 0 1")
    board.turn = chess.BLACK  # black is legally in check
    assert component(engine_path, board.fen(), "king_safety")["mg"] >= 0


def test_safe_center_space_and_supported_expansion(engine_path):
    def space(**pieces):
        return component(engine_path, position(**pieces), "space")["mg"]
    assert space(d3="P") > space(a3="P")
    assert space(d4="P", c3="P") > space(d4="P", a3="P")
    assert space(f3="N") > space(a3="N")
    safe = space(d4="N", d2="p")
    unsafe = space(d4="N", d7="p")
    assert safe >= unsafe
    # The largest territory term is intentionally small compared with a pawn.
    assert abs(space(c4="P", d4="P", e4="P", f4="P")) < 30


def test_endgame_king_support_and_drawish_scaling(engine_path):
    far = chess.Board("7k/8/3P4/8/8/8/8/K7 w - - 0 1")
    near = far.copy()
    near.remove_piece_at(chess.A1)
    near.set_piece_at(chess.C5, chess.Piece(chess.KING, chess.WHITE))
    assert component(engine_path, near.fen(), "endgame")["eg"] > component(engine_path, far.fen(), "endgame")["eg"]
    drawish = diagnostic(engine_path, position(c3="B", f6="n"))
    assert drawish["scale"] == 128
    assert diagnostic(engine_path, position(c3="B", f6="n"), "--disable", "EvalEndgame")["scale"] == 256
    opposite = diagnostic(engine_path, position(c3="B", f7="b", d4="P"))
    assert opposite["scale"] == 192
    assert diagnostic(engine_path, position(c3="B", f6="b", d4="P"))["scale"] == 256
    assert diagnostic(engine_path, position(c1="B", f1="B"))["scale"] == 256
    assert diagnostic(engine_path, position(d4="R"))["scale"] == 256


@pytest.mark.parametrize("fen", ["7k/8/8/8/8/8/8/K7 w - - 0 1",
    "7k/8/8/8/3N4/8/8/K7 w - - 0 1", "7k/8/8/8/2B5/8/8/K7 w - - 0 1"])
def test_advanced_search_preserves_insufficient_material_draws(engine_path, fen):
    with chess.engine.SimpleEngine.popen_uci(str(engine_path)) as engine:
        result = engine.play(chess.Board(fen), chess.engine.Limit(depth=2), info=chess.engine.INFO_ALL)
        assert not result.move and result.info["score"].white().score() == 0


@pytest.mark.parametrize("option,category", [("EvalPawns", "pawn_structure"), ("EvalPassers", "passed_pawns"),
    ("EvalBishopPair", "bishop_pair"), ("EvalRooks", "rook_activity"), ("EvalMobility", "mobility"),
    ("EvalOutposts", "outposts"), ("EvalKingSafety", "king_safety"), ("EvalSpace", "space"), ("EvalEndgame", "endgame")])
def test_individual_category_switches(engine_path, option, category):
    board = chess.Board("r2q2k1/5ppp/3P4/3N4/2P5/8/1P3PPP/2B2BK1 w - - 0 1")
    value = diagnostic(engine_path, board.fen(), "--disable", option)
    assert value["components"][category] == {"mg": 0, "eg": 0, "cp": 0}
    if option == "EvalEndgame":
        assert value["scale"] == 256


@pytest.mark.parametrize("qsearch", [False, True])
@pytest.mark.parametrize("fen", [chess.STARTING_FEN,
    "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "8/5pk1/6p1/8/3K4/6P1/5P2/8 w - - 0 1"])
def test_advanced_full_window_pvs_and_cache_agree(engine_path, fen, qsearch):
    with chess.engine.SimpleEngine.popen_uci(str(engine_path)) as engine:
        engine.configure({"UseReverseFutility": False, "UseFutility": False, "UseCheckExtensions": False, "UseNullMovePruning": False, "UseLMR": False, "Quiescence": qsearch})
        scores = []
        for pvs, cached in ((False, False), (True, False), (True, True)):
            engine.configure({"PVS": pvs, "TranspositionTable": cached})
            board = chess.Board(fen)
            result = engine.play(board, chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
            assert result.move in board.legal_moves
            for move in result.info["pv"]:
                assert move in board.legal_moves
                board.push(move)
            scores.append(result.info["score"])
            if not qsearch and not board.is_game_over(claim_draw=True):
                assert result.info["score"].white().score() == diagnostic(engine_path, board.fen())["total"]
        assert scores[0] == scores[1] == scores[2]


def test_evaluation_mode_changes_do_not_reuse_old_tt_scores(engine_path):
    with chess.engine.SimpleEngine.popen_uci(str(engine_path)) as engine:
        scores = []
        board = chess.Board()
        for advanced in (False, True, False, True):
            engine.configure({"UseAdvancedEvaluation": advanced})
            result = engine.play(board, chess.engine.Limit(depth=3), info=chess.engine.INFO_ALL)
            scores.append(result.info["score"])
        assert scores[0] == scores[2] and scores[1] == scores[3]
        assert scores[0] != scores[1]


def test_uci_category_options_match_cli_and_reject_invalid_values(protocol, engine_path):
    fen = position(d4="P", c3="P", e5="N")
    protocol.send("setoption name UseAdvancedEvaluation value true")
    protocol.send("setoption name UsePST value true")
    protocol.send("position fen " + fen)
    for option in ("EvalPawns", "EvalPassers", "EvalBishopPair", "EvalRooks", "EvalMobility", "EvalOutposts",
                   "EvalKingSafety", "EvalSpace", "EvalEndgame"):
        protocol.send(f"setoption name {option} value false")
        protocol.send("eval")
        line = protocol.until("info string eval ")[-1]
        assert json.loads(line.removeprefix("info string eval ")) == diagnostic(engine_path, fen, "--disable", option)
        protocol.send(f"setoption name {option} value maybe")
        assert "error" in protocol.until("info string error")[-1]
        protocol.send(f"setoption name {option} value true")
