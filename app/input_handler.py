"""Selection and promotion interactions, independent of window coordinates."""

import chess

from app.game import Game


class InputHandler:
    def __init__(self, game: Game) -> None:
        self.game = game
        self.selected: chess.Square | None = None
        self.pending_promotion: tuple[int, int] | None = None

    def clear(self) -> None:
        self.selected = None
        self.pending_promotion = None

    def click_square(self, square: chess.Square | None) -> None:
        if self.pending_promotion:
            return
        if square is None or self.game.outcome:
            self.clear()
            return
        piece = self.game.board.piece_at(square)
        if piece and piece.color == self.game.board.turn:
            self.selected = None if square == self.selected else square
            return
        if self.selected is None:
            return
        if self.game.promotion_choices(self.selected, square):
            self.pending_promotion = (self.selected, square)
        elif self.game.play(chess.Move(self.selected, square)):
            self.clear()

    def promote(self, piece_type: chess.PieceType) -> bool:
        if self.pending_promotion is None:
            return False
        source, destination = self.pending_promotion
        if piece_type not in self.game.promotion_choices(source, destination):
            return False
        if self.game.play(chess.Move(source, destination, promotion=piece_type)):
            self.clear()
            return True
        return False
