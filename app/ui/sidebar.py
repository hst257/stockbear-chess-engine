"""Sidebar presentation and scrollable SAN history."""

import chess
import pygame

from app.board_renderer import PieceImages
from app.game import Game
from app.ui import theme


class Sidebar:
    ROW_HEIGHT = 32

    def __init__(self) -> None:
        self.scroll = 0
        self._revision = -1
        self._visible_rows = 1
        self._row_count = 0

    @staticmethod
    def history_rows(game: Game) -> list[tuple[int, str, str]]:
        rows: dict[int, list[str]] = {}
        for record in game.records:
            row = rows.setdefault(record.number, ["", ""])
            row[0 if record.color else 1] = record.san
        return [(number, moves[0], moves[1]) for number, moves in rows.items()]

    def scroll_by(self, amount: int) -> None:
        self.scroll = max(0, min(self.scroll + amount,
                                 max(0, self._row_count - self._visible_rows)))

    def history_rect(self, rect: pygame.Rect) -> pygame.Rect:
        return pygame.Rect(rect.x, rect.y + 252, rect.width, rect.height - 252 - 142)

    def buttons(self, rect: pygame.Rect) -> dict[str, pygame.Rect]:
        width = (rect.width - 10) // 2
        y = rect.bottom - 126
        return {
            "new": pygame.Rect(rect.x, y, width, 42),
            "undo": pygame.Rect(rect.x + width + 10, y, width, 42),
            "flip": pygame.Rect(rect.x, y + 52, width, 42),
            "claim": pygame.Rect(rect.x + width + 10, y + 52, width, 42),
        }

    def draw(self, surface: pygame.Surface, rect: pygame.Rect,
             game: Game, pieces: PieceImages) -> None:
        turn = pygame.Rect(rect.x, rect.y, rect.width, 104)
        pygame.draw.rect(surface, theme.PANEL, turn, border_radius=10)
        theme.text(surface, "GAME RESULT" if game.outcome else "YOUR TURN",
                   (rect.x + 18, rect.y + 14), 12, theme.ACCENT, True)
        theme.text(surface, game.status, (rect.x + 18, rect.y + 35), 27, bold=True)
        theme.text(surface, game.result_reason, (rect.x + 18, rect.y + 75), 14,
                   theme.CHECK if game.board.is_check() and not game.outcome else theme.MUTED)

        theme.text(surface, "CAPTURED PIECES", (rect.x, rect.y + 126), 12, theme.MUTED, True)
        for color, offset in ((chess.WHITE, 151), (chess.BLACK, 190)):
            theme.text(surface, "White" if color else "Black", (rect.x, rect.y + offset + 5),
                       14, theme.MUTED)
            captured = sorted(game.captured_by(color), key=lambda p: p.piece_type, reverse=True)
            x = rect.x + 55
            if not captured:
                theme.text(surface, "—", (x, rect.y + offset + 4), 16, theme.MUTED)
            else:
                step = min(25, (rect.width - 65) // len(captured))
                for piece in captured:
                    surface.blit(pieces.get(piece, 28), (x, rect.y + offset))
                    x += step
        pygame.draw.line(surface, theme.LINE, (rect.x, rect.y + 235),
                         (rect.right, rect.y + 235))
        self.draw_history(surface, self.history_rect(rect), game)

        buttons = self.buttons(rect)
        theme.button(surface, buttons["new"], "New game", primary=True)
        theme.button(surface, buttons["undo"], "Undo move", game.can_undo)
        theme.button(surface, buttons["flip"], "Flip board")
        theme.button(surface, buttons["claim"], "Claim draw", bool(game.draw_claims))
        theme.text(surface, "N  New     U  Undo     F  Flip", (rect.x, rect.bottom - 17),
                   12, theme.MUTED)

    def draw_history(self, surface: pygame.Surface, rect: pygame.Rect, game: Game) -> None:
        theme.text(surface, "MOVE HISTORY", (rect.x, rect.y), 12, theme.MUTED, True)
        rows = self.history_rows(game)
        viewport = pygame.Rect(rect.x, rect.y + 30, rect.width, max(32, rect.height - 30))
        self._visible_rows = max(1, viewport.height // self.ROW_HEIGHT)
        self._row_count = len(rows)
        if self._revision != game.revision:
            self.scroll = max(0, len(rows) - self._visible_rows)
            self._revision = game.revision
        self.scroll_by(0)
        if not rows:
            theme.text(surface, "A new game. Your first move.", (rect.x, viewport.y + 8),
                       15, theme.MUTED)
            return
        old_clip = surface.get_clip()
        surface.set_clip(viewport)
        for index in range(self.scroll, min(len(rows), self.scroll + self._visible_rows)):
            number, white, black = rows[index]
            y = viewport.y + (index - self.scroll) * self.ROW_HEIGHT
            if index % 2 == 0:
                pygame.draw.rect(surface, theme.PANEL,
                                 pygame.Rect(rect.x, y, rect.width - 10, self.ROW_HEIGHT),
                                 border_radius=4)
            theme.text(surface, f"{number}.", (rect.x + 10, y + 5), 15, theme.MUTED)
            for color, san, x in ((chess.WHITE, white, rect.x + 53),
                                   (chess.BLACK, black, rect.x + rect.width // 2 + 12)):
                latest = game.records[-1]
                selected = latest.number == number and latest.color == color
                theme.text(surface, san, (x, y + 5), 16,
                           theme.ACCENT if selected else theme.TEXT, selected)
        if len(rows) > self._visible_rows:
            track = pygame.Rect(rect.right - 4, viewport.y, 3, viewport.height)
            pygame.draw.rect(surface, theme.LINE, track, border_radius=1)
            height = max(12, track.height * self._visible_rows // len(rows))
            distance = max(1, len(rows) - self._visible_rows)
            thumb = pygame.Rect(track.x, track.y + (track.height - height) * self.scroll // distance,
                                3, height)
            pygame.draw.rect(surface, theme.ACCENT, thumb, border_radius=1)
        surface.set_clip(old_clip)
