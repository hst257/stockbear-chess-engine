"""Pygame event loop joining state, input, and rendering."""

import sys
from dataclasses import replace
from pathlib import Path

import chess
import pygame

from app.board_renderer import BoardGeometry, BoardRenderer, PieceImages
from app.game import DrawClaim, Game
from app.engine_client import DEFAULT_ENGINE, EngineClient, EngineSettings
from app.input_handler import InputHandler
from app.ui import dialogs, engine_panels, theme
from app.ui.sidebar import Sidebar

MIN_SIZE = (960, 680)
DEFAULT_SIZE = (1100, 760)


class Application:
    def __init__(self, size: tuple[int, int] = DEFAULT_SIZE, game: Game | None = None,
                 settings: EngineSettings | None = None, engine_path: Path = DEFAULT_ENGINE,
                 engine_client: EngineClient | None = None) -> None:
        pygame.display.init()
        pygame.font.init()
        # Cached Font objects cannot survive SDL_ttf shutdown/reinitialization.
        theme.font.cache_clear()
        pygame.display.set_caption("ChessLab — Play & search")
        self.game = game if game is not None else Game()
        self.inputs = InputHandler(self.game)
        self.sidebar = Sidebar()
        self.flipped = False
        self.claim_dialog = False
        self.claim_scroll = 0
        self.settings = settings or EngineSettings()
        self.engine = engine_client if engine_client is not None else EngineClient(engine_path)
        self.settings_dialog = False
        self.draft_settings = self.settings
        self.diagnostics_dialog = False
        self.engine_error = ""
        self.search_rows = ()
        self.last_play_stats = None
        self.search_position = "No search yet. Compare the current position."
        self._request_revision: int | None = None
        self._request_token: int | None = None
        self.running = True
        self.modal_targets: dict[object, pygame.Rect] = {}
        self.resize(size)
        self.pieces = PieceImages()
        pygame.display.set_icon(self.pieces.get(chess.Piece(chess.KNIGHT, chess.WHITE), 32))
        self.renderer = BoardRenderer(self.pieces)
        if self.settings.enabled and not self.settings.human_color:
            self.flipped = self.geometry.flipped = True

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
        if name in ("new", "undo", "setup", "diagnostics"):
            self.engine.cancel()
            self._request_revision = self._request_token = None
        if name in ("new", "undo"):
            self.engine_error = ""
            self.search_rows = ()
            self.last_play_stats = None
            self.search_position = "No search yet. Compare the current position."
        if name == "new":
            self.game.reset()
            self.flipped = self.settings.enabled and not self.settings.human_color
            self.geometry.flipped = self.flipped
        elif name == "undo":
            if self.can_undo:
                self.game.undo()
                # Against an engine, return to the human's previous decision.
                while (self.settings.enabled and self.game.records and
                       self.game.board.turn != self.settings.human_color):
                    self.game.undo()
        elif name == "flip":
            self.flipped = not self.flipped
            self.geometry.flipped = self.flipped
        elif name == "claim" and self.game.draw_claims and self.human_turn:
            self.engine.cancel()
            self.claim_dialog = True
        elif name == "setup":
            self.draft_settings = self.settings
            self.settings_dialog = True
        elif name == "diagnostics":
            self.diagnostics_dialog = True

    @property
    def human_turn(self) -> bool:
        return not self.settings.enabled or self.game.board.turn == self.settings.human_color

    @property
    def can_undo(self) -> bool:
        if not self.settings.enabled:
            return self.game.can_undo
        return bool(self.game.claimed_draw or any(r.color == self.settings.human_color for r in self.game.records))

    def start_search(self, kind: str) -> None:
        self.inputs.clear()
        self.engine_error = ""
        self.search_rows = ()
        turn = "White" if self.game.board.turn else "Black"
        self.search_position = f"Move {self.game.board.fullmove_number} · {turn} to move · depth {self.settings.depth}"
        self._request_revision = self.game.revision
        self._request_token = self.engine.start(self.game.board, self.game.revision, self.settings, kind)

    def update_engine(self) -> None:
        if self._request_revision is not None and self._request_revision != self.game.revision:
            self.engine.cancel()
            self._request_revision = self._request_token = None
        for message in self.engine.poll():
            if message.token != self._request_token or message.revision != self.game.revision:
                continue
            if message.finished:
                self._request_revision = self._request_token = None
            if message.error:
                self.engine_error = message.error
                print(f"ChessLab engine: {message.error}", file=sys.stderr)
            else:
                self.search_rows = message.stats
                if message.finished and message.kind == "play" and not self.human_turn and not self.game.outcome:
                    move = message.stats[0].move if message.stats else None
                    if move is None or not self.game.play(move):
                        self.engine_error = "Engine did not return a legal move. Start a new game to retry."
                    else:
                        self.last_play_stats = message.stats[0]
        modal = (self.settings_dialog or self.diagnostics_dialog or self.claim_dialog or
                 self.inputs.pending_promotion is not None)
        if (self.settings.enabled and not self.human_turn and not self.game.outcome and
                not self.engine.busy and not self.engine_error and not modal):
            if self.game.draw_claims:
                self.game.claim_draw(self.game.draw_claims[0])
            else:
                self.start_search("play")

    def header_buttons(self) -> dict[str, pygame.Rect]:
        width = self.surface.get_width()
        return {"diagnostics": pygame.Rect(width - 405, 32, 162, 32),
                "setup": pygame.Rect(width - 225, 32, 192, 32)}

    def panel_action(self, target: str) -> None:
        if self.settings_dialog:
            if target == "start":
                self.settings = self.draft_settings
                self.settings_dialog = False
                self.action("new")
            elif target == "cancel":
                self.settings_dialog = False
            else:
                self.draft_settings = engine_panels.adjust(self.draft_settings, target)
        elif self.diagnostics_dialog:
            if target == "close":
                self.diagnostics_dialog = False
            elif target == "compare" and not self.engine.busy:
                self.start_search("compare")
            elif target == "cancel_search" and self.engine.busy:
                self.engine.stop()
            elif target == "toggle_deepening" and not self.engine.busy:
                self.settings = replace(self.settings, iterative_deepening=not self.settings.iterative_deepening)
                self.search_rows = ()
            elif target == "toggle_ordering" and not self.engine.busy:
                self.settings = replace(self.settings, move_ordering=not self.settings.move_ordering)
                self.search_rows = ()
            elif target == "toggle_pst" and not self.engine.busy:
                self.settings = replace(self.settings, use_pst=not self.settings.use_pst)
                self.search_rows = ()
            elif target == "toggle_tt" and not self.engine.busy:
                self.settings = replace(self.settings, transposition_table=not self.settings.transposition_table)
                self.search_rows = ()
            elif target == "toggle_quiescence" and not self.engine.busy:
                self.settings = replace(self.settings, quiescence=not self.settings.quiescence)
                self.search_rows = ()
            elif target == "toggle_pvs" and not self.engine.busy:
                self.settings = replace(self.settings, principal_variation_search=not self.settings.principal_variation_search)
                self.search_rows = ()

    def handle_event(self, event: pygame.event.Event) -> None:
        if event.type == pygame.QUIT:
            self.running = False
            return
        if event.type == pygame.VIDEORESIZE:
            self.resize(event.size)
            return
        modal = (self.settings_dialog or self.diagnostics_dialog or self.claim_dialog or
                 self.inputs.pending_promotion is not None)
        if event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                self.claim_dialog = False
                self.settings_dialog = False
                self.diagnostics_dialog = False
                self.inputs.clear()
            elif self.inputs.pending_promotion is not None:
                kind = {pygame.K_q: chess.QUEEN, pygame.K_r: chess.ROOK,
                        pygame.K_b: chess.BISHOP, pygame.K_n: chess.KNIGHT}.get(event.key)
                if kind:
                    self.inputs.promote(kind)
            elif not modal:
                name = {pygame.K_n: "new", pygame.K_u: "undo", pygame.K_f: "flip",
                        pygame.K_d: "claim", pygame.K_g: "setup",
                        pygame.K_e: "diagnostics"}.get(event.key)
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
                        if self.settings_dialog or self.diagnostics_dialog:
                            self.panel_action(target)
                        elif target == "cancel":
                            self.inputs.clear()
                            self.claim_dialog = False
                        elif self.claim_dialog and isinstance(target, DrawClaim):
                            self.game.claim_draw(target)
                            self.claim_dialog = False
                        elif isinstance(target, int):
                            self.inputs.promote(target)
                        break
            else:
                for name, rect in self.header_buttons().items():
                    if rect.collidepoint(event.pos):
                        self.action(name)
                        return
                for name, rect in self.sidebar.buttons(self.sidebar_rect).items():
                    if rect.collidepoint(event.pos):
                        self.action(name)
                        return
                if self.human_turn:
                    self.inputs.click_square(self.geometry.square_at(event.pos))

    def draw(self) -> None:
        surface = self.surface
        surface.fill(theme.BACKGROUND)
        theme.text(surface, "CHESSLAB", (39, 24), 30, bold=True)
        theme.text(surface, "A place to play. A space to learn.", (41, 64), 14, theme.MUTED)
        header = self.header_buttons()
        theme.button(surface, header["diagnostics"], "Search lab  ·  E")
        theme.button(surface, header["setup"], "vs ChessLab  ·  G" if self.settings.enabled else "Local game  ·  G")
        board = self.geometry.rect
        top_side = "WHITE" if self.flipped else "BLACK"
        theme.text(surface, top_side, (board.x, board.y - 27), 12, theme.MUTED, True)
        theme.text(surface, "STANDARD CHESS", (board.right - 128, board.y - 27), 12, theme.MUTED)
        self.renderer.draw(surface, self.geometry, self.game, self.inputs)
        detail = None
        if self.engine_error:
            detail = "Engine unavailable · see Search lab"
        elif self.settings.enabled:
            detail = f"{self.settings.algorithm} · depth {self.settings.depth}"
            if self.engine.busy:
                if self.search_rows:
                    detail = f"Thinking… completed depth {self.search_rows[-1].depth}/{self.settings.depth}"
                else:
                    detail += " · thinking…"
            elif self.last_play_stats:
                last = self.last_play_stats
                detail = f"{last.san} · depth {last.depth}/{last.requested_depth} · {last.nodes:,} nodes"
        self.sidebar.draw(surface, self.sidebar_rect, self.game, self.pieces,
                          detail=detail, undo_enabled=self.can_undo,
                          claim_enabled=bool(self.game.draw_claims) and self.human_turn,
                          turn_label="ENGINE TURN" if not self.human_turn else "YOUR TURN")
        bottom = "Black" if self.flipped else "White"
        theme.text(surface, f"{bottom} at the bottom", (board.x, board.bottom + 34), 12, theme.MUTED)
        theme.text(surface, "Click a piece, then a destination.",
                   (board.right - 205, board.bottom + 34), 12, theme.MUTED)
        if self.game.outcome:
            self.draw_result()
        self.modal_targets = {}
        if self.settings_dialog:
            self.modal_targets = engine_panels.setup(surface, self.draft_settings, self.engine.path.is_file())
        elif self.diagnostics_dialog:
            self.modal_targets = engine_panels.diagnostics(surface, self.search_rows, self.settings,
                                                          self.engine.busy, self.engine_error, self.search_position)
        elif self.inputs.pending_promotion is not None:
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
            self.update_engine()
            self.draw()
            pygame.display.flip()
            count += 1
            if frames is not None and count >= frames:
                break
            clock.tick(60)
        if screenshot:
            pygame.image.save(self.surface, screenshot)

    def close(self) -> None:
        self.engine.close()
        theme.font.cache_clear()
        pygame.quit()
