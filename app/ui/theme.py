"""A small shared palette and cached typography, without a widget framework."""

from functools import lru_cache

import pygame

BACKGROUND = "#171D22"
PANEL = "#20282E"
RAISED = "#2A343B"
LINE = "#364149"
TEXT = "#F2EDE3"
MUTED = "#9DAAAF"
ACCENT = "#D8B477"
LIGHT = "#E9DDC7"
DARK = "#977350"
SELECTED = "#D7B85B"
LAST_LIGHT = "#E8D38F"
LAST_DARK = "#B19755"
CHECK = "#C36B60"


@lru_cache(maxsize=20)
def font(size: int, bold: bool = False) -> pygame.font.Font:
    return pygame.font.SysFont("segoeui,dejavusans,arial", size, bold=bold)


def text(surface: pygame.Surface, label: str, position: tuple[int, int],
         size: int = 16, color: str = TEXT, bold: bool = False) -> pygame.Rect:
    image = font(size, bold).render(label, True, color)
    return surface.blit(image, position)


def centered(surface: pygame.Surface, label: str, rect: pygame.Rect,
             size: int = 16, color: str = TEXT, bold: bool = False) -> None:
    image = font(size, bold).render(label, True, color)
    surface.blit(image, image.get_rect(center=rect.center))


def button(surface: pygame.Surface, rect: pygame.Rect, label: str,
           enabled: bool = True, primary: bool = False) -> None:
    hovered = enabled and rect.collidepoint(pygame.mouse.get_pos())
    fill = ACCENT if primary and enabled else RAISED if enabled else PANEL
    pygame.draw.rect(surface, fill, rect, border_radius=8)
    pygame.draw.rect(surface, ACCENT if hovered else LINE, rect, 1, border_radius=8)
    color = BACKGROUND if primary and enabled else TEXT if enabled else MUTED
    centered(surface, label, rect, 15, color, primary)
