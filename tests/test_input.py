import chess

from app.game import Game
from app.input_handler import InputHandler


def test_selection_moves_friendly_reselection_and_deselection() -> None:
    game = Game()
    inputs = InputHandler(game)
    inputs.click_square(chess.E2)
    assert inputs.selected == chess.E2
    assert game.legal_destinations(inputs.selected) == {chess.E3, chess.E4}
    inputs.click_square(chess.D2)
    assert inputs.selected == chess.D2
    inputs.click_square(chess.D2)
    assert inputs.selected is None
    inputs.click_square(chess.E2)
    inputs.click_square(None)
    assert inputs.selected is None
    inputs.click_square(chess.E2)
    inputs.click_square(chess.E4)
    assert inputs.selected is None
    assert game.records[-1].san == "e4"


def test_illegal_square_preserves_selection_and_board() -> None:
    game = Game()
    inputs = InputHandler(game)
    inputs.click_square(chess.E2)
    inputs.click_square(chess.E5)
    assert inputs.selected == chess.E2
    assert game.board.fen() == chess.STARTING_FEN
    inputs.click_square(chess.E7)  # Opponent's piece cannot be selected.
    assert inputs.selected == chess.E2


def test_promotion_waits_for_choice_and_can_cancel() -> None:
    game = Game("7k/P7/8/8/8/8/8/7K w - - 0 1")
    inputs = InputHandler(game)
    before = game.board.fen()
    inputs.click_square(chess.A7)
    inputs.click_square(chess.A8)
    assert inputs.pending_promotion == (chess.A7, chess.A8)
    assert game.board.fen() == before
    assert not inputs.promote(chess.KING)
    inputs.clear()
    assert game.board.fen() == before
    inputs.click_square(chess.A7)
    inputs.click_square(chess.A8)
    assert inputs.promote(chess.KNIGHT)
    assert game.board.piece_at(chess.A8) == chess.Piece(chess.KNIGHT, chess.WHITE)
    assert inputs.selected is None and inputs.pending_promotion is None
