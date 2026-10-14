"""Modal promotion and claim dialogs. Drawing returns clickable targets."""

import pygame

from app.board_renderer import PieceImages
from app.game import Game
from app.input_handler import InputHandler
from app.ui import theme
import chess


def panel(surface: pygame.Surface, title: str, subtitle: str, height: int) -> pygame.Rect:
    shade = pygame.Surface(surface.get_size(), pygame.SRCALPHA)
    shade.fill((8, 13, 17, 195))
    surface.blit(shade, (0, 0))
    rect = pygame.Rect(0, 0, 490, height)
    rect.center = surface.get_rect().center
    pygame.draw.rect(surface, theme.PANEL, rect, border_radius=14)
    pygame.draw.rect(surface, theme.LINE, rect, 1, border_radius=14)
    theme.text(surface, title, (rect.x + 25, rect.y + 21), 26, bold=True)
    theme.text(surface, subtitle, (rect.x + 25, rect.y + 61), 14, theme.MUTED)
    return rect


def promotion(surface: pygame.Surface, game: Game, inputs: InputHandler,
              pieces: PieceImages) -> dict[object, pygame.Rect]:
    rect = panel(surface, "Choose your promotion", "Select a piece to complete the move.", 250)
    targets: dict[object, pygame.Rect] = {}
    source, destination = inputs.pending_promotion
    for index, kind in enumerate(game.promotion_choices(source, destination)):
        choice = pygame.Rect(rect.x + 25 + index * 112, rect.y + 100, 104, 100)
        pygame.draw.rect(surface, theme.RAISED, choice, border_radius=8)
        if choice.collidepoint(pygame.mouse.get_pos()):
            pygame.draw.rect(surface, theme.ACCENT, choice, 2, border_radius=8)
        surface.blit(pieces.get(chess.Piece(kind, game.board.turn), 66), (choice.x + 19, choice.y + 3))
        theme.centered(surface, chess.piece_name(kind).title(),
                       pygame.Rect(choice.x, choice.y + 72, choice.width, 21), 14)
        targets[kind] = choice
    cancel = pygame.Rect(rect.x + 25, rect.bottom - 35, rect.width - 50, 25)
    theme.centered(surface, "Cancel  ·  Esc", cancel, 13, theme.MUTED)
    targets["cancel"] = cancel
    return targets


def draw_claim(surface: pygame.Surface, game: Game, scroll: int) -> dict[object, pygame.Rect]:
    visible = game.draw_claims[scroll:scroll + 5]
    height = 135 + len(visible) * 48
    rect = panel(surface, "Claim a draw", "Choose a reason. Intended moves are declared, not played.", height)
    targets: dict[object, pygame.Rect] = {}
    for index, claim in enumerate(visible):
        label = claim.label
        if claim.intended_move is not None:
            label += " · after " + game.board.san(claim.intended_move)
        target = pygame.Rect(rect.x + 25, rect.y + 98 + index * 48, rect.width - 50, 38)
        theme.button(surface, target, label)
        targets[claim] = target
    cancel = pygame.Rect(rect.x + 25, rect.bottom - 29, rect.width - 50, 22)
    theme.centered(surface, "Cancel  ·  Esc" + ("  /  Scroll for more" if len(game.draw_claims) > 5 else ""),
                   cancel, 12, theme.MUTED)
    targets["cancel"] = cancel
    return targets
