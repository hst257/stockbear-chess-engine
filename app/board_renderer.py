"""Board geometry and drawing; both orientations use the same mapping."""

from pathlib import Path

import chess
import pygame

from app.game import Game
from app.input_handler import InputHandler
from app.ui import theme

ASSET_DIR = Path(__file__).resolve().parent / "assets" / "pieces"


class BoardGeometry:
    def __init__(self, rect: pygame.Rect, flipped: bool = False) -> None:
        self.rect = rect
        self.flipped = flipped
        self.square_size = rect.width // 8

    def square_rect(self, square: chess.Square) -> pygame.Rect:
        file, rank = chess.square_file(square), chess.square_rank(square)
        col, row = (7 - file, rank) if self.flipped else (file, 7 - rank)
        return pygame.Rect(self.rect.x + col * self.square_size,
                           self.rect.y + row * self.square_size,
                           self.square_size, self.square_size)

    def square_at(self, position: tuple[int, int]) -> chess.Square | None:
        if not self.rect.collidepoint(position):
            return None
        col = (position[0] - self.rect.x) // self.square_size
        row = (position[1] - self.rect.y) // self.square_size
        return chess.square(7 - col, row) if self.flipped else chess.square(col, 7 - row)


class PieceImages:
    def __init__(self) -> None:
        self.originals: dict[str, pygame.Surface] = {}
        self.scaled: dict[tuple[str, int], pygame.Surface] = {}
        for symbol in "PNBRQKpnbrqk":
            filename = ("w" if symbol.isupper() else "b") + symbol.upper() + ".png"
            self.originals[symbol] = pygame.image.load(ASSET_DIR / filename).convert_alpha()

    def get(self, piece: chess.Piece, size: int) -> pygame.Surface:
        key = (piece.symbol(), size)
        if key not in self.scaled:
            self.scaled[key] = pygame.transform.smoothscale(self.originals[key[0]], (size, size))
        return self.scaled[key]

    def clear_scaled(self) -> None:
        self.scaled.clear()


class BoardRenderer:
    def __init__(self, pieces: PieceImages) -> None:
        self.pieces = pieces

    def draw(self, surface: pygame.Surface, geometry: BoardGeometry,
             game: Game, inputs: InputHandler) -> None:
        board = game.board
        last = game.records[-1].move if game.records else None
        legal = game.legal_destinations(inputs.selected) if inputs.selected is not None else set()
        checked_king = board.king(board.turn) if board.is_check() else None
        padding = geometry.square_size // 12
        piece_size = geometry.square_size - 2 * padding
        pygame.draw.rect(surface, theme.LINE, geometry.rect.inflate(4, 4), border_radius=2)
        for square in chess.SQUARES:
            rect = geometry.square_rect(square)
            light = (chess.square_file(square) + chess.square_rank(square)) % 2 != 0
            fill = theme.LIGHT if light else theme.DARK
            if last and square in (last.from_square, last.to_square):
                fill = theme.LAST_LIGHT if light else theme.LAST_DARK
            if square == inputs.selected:
                fill = theme.SELECTED
            if square == checked_king:
                fill = theme.CHECK
            pygame.draw.rect(surface, fill, rect)
            piece = board.piece_at(square)
            if piece:
                surface.blit(self.pieces.get(piece, piece_size), rect.move(padding, padding))
            if square in legal:
                mark = pygame.Surface(rect.size, pygame.SRCALPHA)
                if piece or (inputs.selected is not None and
                             board.is_en_passant(chess.Move(inputs.selected, square))):
                    pygame.draw.circle(mark, (35, 46, 37, 130),
                                       (rect.width // 2, rect.height // 2), rect.width // 2 - 4, 5)
                else:
                    pygame.draw.circle(mark, (35, 46, 37, 95),
                                       (rect.width // 2, rect.height // 2), max(5, rect.width // 9))
                surface.blit(mark, rect)
        for index in range(8):
            file = 7 - index if geometry.flipped else index
            rank = index if geometry.flipped else 7 - index
            theme.centered(surface, chess.FILE_NAMES[file],
                           pygame.Rect(geometry.rect.x + index * geometry.square_size,
                                       geometry.rect.bottom + 9, geometry.square_size, 20),
                           13, theme.MUTED)
            theme.centered(surface, str(rank + 1),
                           pygame.Rect(geometry.rect.x - 27,
                                       geometry.rect.y + index * geometry.square_size,
                                       20, geometry.square_size), 13, theme.MUTED)
