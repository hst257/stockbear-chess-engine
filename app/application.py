"""Pygame event loop joining state, input, and rendering."""

import chess
import pygame

from app.board_renderer import BoardGeometry, BoardRenderer, PieceImages
from app.game import DrawClaim, Game
from app.input_handler import InputHandler
from app.ui import dialogs, theme
from app.ui.sidebar import Sidebar

MIN_SIZE = (960, 680)
DEFAULT_SIZE = (1100, 760)


class Application:
    def __init__(self, size: tuple[int, int] = DEFAULT_SIZE, game: Game | None = None) -> None:
        pygame.display.init()
        pygame.font.init()
        # Cached Font objects cannot survive SDL_ttf shutdown/reinitialization.
        theme.font.cache_clear()
        pygame.display.set_caption("ChessLab — Local chess")
        self.game = game if game is not None else Game()
        self.inputs = InputHandler(self.game)
        self.sidebar = Sidebar()
        self.flipped = False
        self.claim_dialog = False
        self.claim_scroll = 0
        self.running = True
        self.modal_targets: dict[object, pygame.Rect] = {}
        self.resize(size)
        self.pieces = PieceImages()
        pygame.display.set_icon(self.pieces.get(chess.Piece(chess.KNIGHT, chess.WHITE), 32))
        self.renderer = BoardRenderer(self.pieces)

    def resize(self, size: tuple[int, int]) -> None:
        width, height = max(MIN_SIZE[0], size[0]), max(MIN_SIZE[1], size[1])
        self.surface = pygame.display.set_mode((width, height), pygame.RESIZABLE)
        board_size = (min(height - 168, width - 420) // 8) * 8
        self.geometry = BoardGeometry(pygame.Rect(40, 116, board_size, board_size), self.flipped)
        self.sidebar_rect = pygame.Rect(self.geometry.rect.right + 40, 116,
                                        width - self.geometry.rect.right - 72, board_size)
        if hasattr(self, "pieces"):
            self.pieces.clear_scaled()

    def action(self, name: str) -> None:
        self.inputs.clear()
        self.claim_dialog = False
        self.claim_scroll = 0
        if name == "new":
            self.game.reset()
            self.flipped = False
            self.geometry.flipped = False
        elif name == "undo":
            self.game.undo()
        elif name == "flip":
            self.flipped = not self.flipped
            self.geometry.flipped = self.flipped
        elif name == "claim" and self.game.draw_claims:
            self.claim_dialog = True

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
            return
        if event.type == pygame.VIDEORESIZE:
            self.resize(event.size)
            return
        modal = self.claim_dialog or self.inputs.pending_promotion is not None
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.claim_dialog = False
                self.inputs.clear()
            elif self.inputs.pending_promotion is not None:
                kind = {pygame.K_q: chess.QUEEN, pygame.K_r: chess.ROOK,
                        pygame.K_b: chess.BISHOP, pygame.K_n: chess.KNIGHT}.get(event.key)
                if kind:
                    self.inputs.promote(kind)
            elif not modal:
                name = {pygame.K_n: "new", pygame.K_u: "undo", pygame.K_f: "flip",
                        pygame.K_d: "claim"}.get(event.key)
                if name:
                    self.action(name)
        elif event.type == pygame.MOUSEWHEEL:
            if self.claim_dialog:
                self.claim_scroll = max(0, min(self.claim_scroll - event.y,
                                               max(0, len(self.game.draw_claims) - 5)))
            elif not modal and self.sidebar.history_rect(self.sidebar_rect).collidepoint(pygame.mouse.get_pos()):
                self.sidebar.scroll_by(-event.y * 2)
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if modal:
                # Recompute targets after any queued resize or modal-open event.
                self.draw()
                for target, rect in self.modal_targets.items():
                    if rect.collidepoint(event.pos):
                        if target == "cancel":
                            self.inputs.clear()
                            self.claim_dialog = False
                        elif self.claim_dialog and isinstance(target, DrawClaim):
                            self.game.claim_draw(target)
                            self.claim_dialog = False
                        elif isinstance(target, int):
                            self.inputs.promote(target)
                        break
            else:
                for name, rect in self.sidebar.buttons(self.sidebar_rect).items():
                    if rect.collidepoint(event.pos):
                        self.action(name)
                        return
                self.inputs.click_square(self.geometry.square_at(event.pos))

    def draw(self) -> None:
        surface = self.surface
        surface.fill(theme.BACKGROUND)
        theme.text(surface, "CHESSLAB", (39, 24), 30, bold=True)
        theme.text(surface, "A place to play. A space to learn.", (41, 64), 14, theme.MUTED)
        badge = pygame.Rect(surface.get_width() - 225, 32, 192, 32)
        pygame.draw.rect(surface, theme.PANEL, badge, border_radius=16)
        pygame.draw.circle(surface, theme.ACCENT, (badge.x + 16, badge.centery), 3)
        theme.centered(surface, "LOCAL  /  TWO PLAYERS", badge.move(7, 0), 12, theme.MUTED, True)
        board = self.geometry.rect
        top_side = "WHITE" if self.flipped else "BLACK"
        theme.text(surface, top_side, (board.x, board.y - 27), 12, theme.MUTED, True)
        theme.text(surface, "STANDARD CHESS", (board.right - 128, board.y - 27), 12, theme.MUTED)
        self.renderer.draw(surface, self.geometry, self.game, self.inputs)
        self.sidebar.draw(surface, self.sidebar_rect, self.game, self.pieces)
        bottom = "Black" if self.flipped else "White"
        theme.text(surface, f"{bottom} at the bottom", (board.x, board.bottom + 34), 12, theme.MUTED)
        theme.text(surface, "Click a piece, then a destination.",
                   (board.right - 205, board.bottom + 34), 12, theme.MUTED)
        if self.game.outcome:
            self.draw_result()
        self.modal_targets = {}
        if self.inputs.pending_promotion is not None:
            self.modal_targets = dialogs.promotion(surface, self.game, self.inputs, self.pieces)
        elif self.claim_dialog:
            self.modal_targets = dialogs.draw_claim(surface, self.game, self.claim_scroll)

    def draw_result(self) -> None:
        board = self.geometry.rect
        shade = pygame.Surface(board.size, pygame.SRCALPHA)
        shade.fill((12, 18, 21, 95))
        self.surface.blit(shade, board)
        rect = pygame.Rect(0, 0, min(410, board.width - 40), 170)
        rect.center = board.center
        pygame.draw.rect(self.surface, theme.PANEL, rect, border_radius=12)
        pygame.draw.rect(self.surface, theme.ACCENT, rect, 1, border_radius=12)
        theme.centered(self.surface, self.game.outcome.result(),
                       pygame.Rect(rect.x, rect.y + 18, rect.width, 23), 14, theme.ACCENT)
        theme.centered(self.surface, self.game.status,
                       pygame.Rect(rect.x, rect.y + 48, rect.width, 43), 32, bold=True)
        theme.centered(self.surface, self.game.result_reason,
                       pygame.Rect(rect.x, rect.y + 100, rect.width, 23), 17, theme.MUTED)
        theme.centered(self.surface, "Use Undo to review, or start a new game.",
                       pygame.Rect(rect.x, rect.y + 137, rect.width, 20), 13, theme.MUTED)

    def run(self, frames: int | None = None, screenshot: str | None = None) -> None:
        clock = pygame.time.Clock()
        count = 0
        while self.running:
            for event in pygame.event.get():
                self.handle_event(event)
            if not self.running:
                break
            self.draw()
            pygame.display.flip()
            count += 1
            if frames is not None and count >= frames:
                break
            clock.tick(60)
        if screenshot:
            pygame.image.save(self.surface, screenshot)

    @staticmethod
    def close() -> None:
        theme.font.cache_clear()
        pygame.quit()
