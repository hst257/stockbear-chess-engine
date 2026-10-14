import chess
import pytest
import random

from app.game import DrawClaim, Game


def play(game: Game, *moves: str) -> None:
    for uci in moves:
        assert game.play(chess.Move.from_uci(uci)), uci


def test_normal_moves_capture_and_san() -> None:
    game = Game()
    play(game, "e2e4", "d7d5", "e4d5")
    assert [r.san for r in game.records] == ["e4", "d5", "exd5"]
    assert game.board.piece_at(chess.D5) == chess.Piece(chess.PAWN, chess.WHITE)
    assert game.board.turn == chess.BLACK
    assert game.captured_by(chess.WHITE) == (chess.Piece(chess.PAWN, chess.BLACK),)
    assert game.captured_by(chess.BLACK) == ()


@pytest.mark.parametrize("uci", ["e2e5", "e7e5", "a1a4", "e1g1", "e2e4q", "0000"])
def test_illegal_move_does_not_mutate_state(uci: str) -> None:
    game = Game()
    before = game.board.fen(), game.revision, game.draw_claims
    assert not game.play(chess.Move.from_uci(uci))
    assert (game.board.fen(), game.revision, game.draw_claims) == before
    assert not game.records


def test_cannot_expose_own_king() -> None:
    game = Game("4r1k1/8/8/8/8/8/4R3/4K3 w - - 0 1")
    assert not game.play(chess.Move.from_uci("e2d2"))
    assert game.board.piece_at(chess.E2) == chess.Piece(chess.ROOK, chess.WHITE)


@pytest.mark.parametrize("side,uci,king,rook,san", [
    ("w", "e1g1", chess.G1, chess.F1, "O-O"),
    ("w", "e1c1", chess.C1, chess.D1, "O-O-O"),
    ("b", "e8g8", chess.G8, chess.F8, "O-O"),
    ("b", "e8c8", chess.C8, chess.D8, "O-O-O"),
])
def test_castling_and_undo(side, uci, king, rook, san) -> None:
    game = Game(f"r3k2r/8/8/8/8/8/8/R3K2R {side} KQkq - 0 1")
    before = game.board.fen()
    color = game.board.turn
    play(game, uci)
    assert game.board.piece_at(king) == chess.Piece(chess.KING, color)
    assert game.board.piece_at(rook) == chess.Piece(chess.ROOK, color)
    assert game.records[-1].san == san
    assert game.undo()
    assert game.board.fen() == before


def test_castling_through_attacked_square_rejected() -> None:
    game = Game("r3kr1r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    assert not game.play(chess.Move.from_uci("e1g1"))


def test_en_passant_capture_and_undo_restore_rights() -> None:
    game = Game()
    play(game, "e2e4", "a7a6", "e4e5", "d7d5")
    before = game.board.fen()
    play(game, "e5d6")
    assert game.records[-1].san == "exd6"
    assert game.board.piece_at(chess.D5) is None
    assert game.captured_by(chess.WHITE) == (chess.Piece(chess.PAWN, chess.BLACK),)
    assert game.undo()
    assert game.board.fen() == before
    assert not game.captured_by(chess.WHITE)
    assert chess.Move.from_uci("e5d6") in game.legal_moves


@pytest.mark.parametrize("kind", [chess.QUEEN, chess.ROOK, chess.BISHOP, chess.KNIGHT])
@pytest.mark.parametrize("side", [chess.WHITE, chess.BLACK])
def test_all_promotions_and_undo(kind, side) -> None:
    fen = ("7k/P7/8/8/8/8/8/7K w - - 0 1" if side
           else "7k/8/8/8/8/8/p7/7K b - - 0 1")
    source, destination = (chess.A7, chess.A8) if side else (chess.A2, chess.A1)
    game = Game(fen)
    assert set(game.promotion_choices(source, destination)) == {2, 3, 4, 5}
    assert not game.play(chess.Move(source, destination))
    assert game.play(chess.Move(source, destination, promotion=kind))
    assert game.board.piece_at(destination) == chess.Piece(kind, side)
    assert "=" in game.records[-1].san
    assert game.undo()
    assert game.board.fen() == fen


def test_capture_promotion_and_capture_of_promoted_piece() -> None:
    game = Game("1r5k/P7/8/8/8/8/8/7K w - - 0 1")
    play(game, "a7b8q")
    assert game.captured_by(chess.WHITE) == (chess.Piece(chess.ROOK, chess.BLACK),)
    assert game.undo()
    assert not game.captured_by(chess.WHITE)
    game = Game("1r5k/P7/8/8/8/8/8/7K w - - 0 1")
    play(game, "a7a8q", "b8a8")
    assert game.captured_by(chess.BLACK) == (chess.Piece(chess.QUEEN, chess.WHITE),)
    assert game.undo()
    assert game.board.piece_at(chess.A8) == chess.Piece(chess.QUEEN, chess.WHITE)


def test_check_checkmate_and_undo() -> None:
    game = Game()
    play(game, "f2f3", "e7e5", "g2g4", "d8h4")
    assert game.board.is_check()
    assert game.status == "Black wins"
    assert game.outcome.termination == chess.Termination.CHECKMATE
    assert not game.play(chess.Move.from_uci("a2a3"))
    assert game.undo()
    assert game.outcome is None
    assert len(game.records) == 3


@pytest.mark.parametrize("fen,termination", [
    ("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1", chess.Termination.STALEMATE),
    ("7k/8/8/8/8/8/8/7K w - - 0 1", chess.Termination.INSUFFICIENT_MATERIAL),
    ("7k/8/8/8/8/8/6B1/7K w - - 0 1", chess.Termination.INSUFFICIENT_MATERIAL),
    ("7k/8/8/8/8/8/6N1/7K w - - 0 1", chess.Termination.INSUFFICIENT_MATERIAL),
    ("7k/8/8/8/8/8/R7/7K w - - 150 76", chess.Termination.SEVENTYFIVE_MOVES),
])
def test_automatic_draws(fen, termination) -> None:
    game = Game(fen)
    assert game.status == "Draw"
    assert game.outcome.termination == termination
    assert game.outcome.result() == "1/2-1/2"
    assert not game.draw_claims


def test_checkmate_precedes_seventyfive_moves() -> None:
    game = Game("7k/8/5KQ1/8/8/8/8/8 w - - 149 75")
    play(game, "g6g7")
    assert game.board.halfmove_clock == 150
    assert game.outcome.termination == chess.Termination.CHECKMATE


def test_fifty_moves_are_claimable_not_automatic() -> None:
    game = Game("7k/8/8/8/8/8/R7/7K w - - 100 51")
    assert game.outcome is None
    claim = DrawClaim(chess.Termination.FIFTY_MOVES)
    assert claim in game.draw_claims
    before = game.board.fen()
    assert game.claim_draw(claim)
    assert game.outcome.termination == chess.Termination.FIFTY_MOVES
    assert game.board.fen() == before
    assert game.undo()  # Withdraw a claim without undoing a move.
    assert game.board.fen() == before
    assert game.outcome is None


def test_intended_fifty_move_claim_excludes_pawn_moves() -> None:
    game = Game("7k/8/8/8/8/8/RP6/7K w - - 99 51")
    before = game.board.fen()
    claim = DrawClaim(chess.Termination.FIFTY_MOVES, chess.Move.from_uci("a2a3"))
    assert claim in game.draw_claims
    assert DrawClaim(chess.Termination.FIFTY_MOVES, chess.Move.from_uci("b2b3")) not in game.draw_claims
    assert game.claim_draw(claim)
    assert game.board.fen() == before
    assert not game.records


CYCLE = ("g1f3", "g8f6", "f3g1", "f6g8")


def test_current_threefold_claim_and_undo_history() -> None:
    game = Game()
    play(game, *CYCLE, *CYCLE)
    claim = DrawClaim(chess.Termination.THREEFOLD_REPETITION)
    assert game.outcome is None
    assert claim in game.draw_claims
    assert game.claim_draw(claim)
    assert game.undo()
    assert len(game.records) == 8
    assert game.undo()
    assert len(game.records) == 7
    assert claim not in game.draw_claims
    play(game, "f6g8")
    assert claim in game.draw_claims


def test_intended_threefold_claim_does_not_play_move() -> None:
    game = Game()
    play(game, *CYCLE, *CYCLE[:3])
    claim = DrawClaim(chess.Termination.THREEFOLD_REPETITION, chess.Move.from_uci("f6g8"))
    before = game.board.fen()
    assert claim in game.draw_claims
    assert game.claim_draw(claim)
    assert game.board.fen() == before
    assert len(game.records) == 7


def test_fivefold_is_automatic_and_reversible() -> None:
    game = Game()
    for _ in range(4):
        play(game, *CYCLE)
    assert game.outcome.termination == chess.Termination.FIVEFOLD_REPETITION
    assert game.undo()
    assert game.outcome is None


def test_invalid_and_stale_claim_rejected() -> None:
    game = Game()
    assert not game.claim_draw(DrawClaim(chess.Termination.THREEFOLD_REPETITION))
    play(game, *CYCLE, *CYCLE[:3])
    old = game.draw_claims[0]
    play(game, "b8c6")
    assert not game.claim_draw(old)
    assert game.outcome is None


def test_restart_clears_entire_game_and_undo_empty_is_safe() -> None:
    game = Game()
    assert not game.undo()
    play(game, *CYCLE, *CYCLE)
    assert game.claim_draw(DrawClaim(chess.Termination.THREEFOLD_REPETITION))
    game.reset()
    assert game.board.fen() == chess.STARTING_FEN
    assert not game.records
    assert not game.draw_claims
    assert not game.can_undo
    assert game.outcome is None


def test_undo_capture_restores_both_sides_and_history() -> None:
    game = Game()
    play(game, "e2e4", "d7d5")
    before = game.board.fen()
    play(game, "e4d5", "d8d5")
    assert len(game.captured_by(chess.WHITE)) == 1
    assert len(game.captured_by(chess.BLACK)) == 1
    assert game.undo() and game.undo()
    assert game.board.fen() == before
    assert not game.captured_by(chess.WHITE)
    assert not game.captured_by(chess.BLACK)
    assert [r.san for r in game.records] == ["e4", "d5"]


def test_constructor_rejects_invalid_positions() -> None:
    with pytest.raises(ValueError):
        Game("8/8/8/8/8/8/8/8 w - - 0 1")


def test_seeded_game_rewinds_every_position_exactly() -> None:
    game = Game()
    rng = random.Random(2026)
    positions = [game.board.fen()]
    for _ in range(180):
        if game.outcome:
            break
        assert game.play(rng.choice(game.legal_moves))
        positions.append(game.board.fen())
    for expected in reversed(positions[:-1]):
        assert game.undo()
        assert game.board.fen() == expected
    assert not game.records and not game.can_undo


def test_nonterminal_check_status() -> None:
    game = Game("6k1/8/8/8/8/8/8/R6K w - - 0 1")
    play(game, "a1a8")
    assert game.status == "Black in check"
    assert game.outcome is None
