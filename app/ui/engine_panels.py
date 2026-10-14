"""Game setup and the search comparison interface."""

from dataclasses import replace

import chess
import pygame

from app.engine_client import EngineSettings, SearchStats
from app.ui import dialogs, theme


def setup(surface: pygame.Surface, settings: EngineSettings, available: bool) -> dict[str, pygame.Rect]:
    rect = dialogs.panel(surface, "Set up a game", "Choose an opponent and a search algorithm.", 470)
    targets: dict[str, pygame.Rect] = {}

    def choices(y: int, title: str, options: list[tuple[str, str, bool]]) -> None:
        theme.text(surface, title, (rect.x + 25, rect.y + y), 12, theme.MUTED, True)
        width = (rect.width - 60) // 2
        for index, (name, label, selected) in enumerate(options):
            target = pygame.Rect(rect.x + 25 + index * (width + 10), rect.y + y + 24, width, 36)
            theme.button(surface, target, label, primary=selected)
            targets[name] = target

    choices(98, "OPPONENT", [("local", "Local two players", not settings.enabled),
                             ("engine", "ChessLab engine", settings.enabled)])
    choices(174, "YOUR PIECES", [("white", "White", settings.human_color),
                                 ("black", "Black", not settings.human_color)])
    choices(250, "SEARCH", [("minimax", "Minimax", not settings.alpha_beta),
                            ("alphabeta", "Alpha-beta", settings.alpha_beta)])
    theme.text(surface, "DEPTH (PLIES)", (rect.x + 25, rect.y + 330), 12, theme.MUTED, True)
    for name, label, x, enabled in (("less", "−", rect.x + 290, settings.depth > 1),
                                     ("more", "+", rect.x + 402, settings.depth < 5)):
        target = pygame.Rect(x, rect.y + 322, 38, 32)
        theme.button(surface, target, label, enabled)
        targets[name] = target
    theme.text(surface, str(settings.depth), (rect.x + 353, rect.y + 325), 18, theme.ACCENT, True)
    note = "Same material evaluation in both search modes."
    if settings.enabled and not available:
        note = "Build the engine first: run build_engine.bat"
    theme.text(surface, note, (rect.x + 25, rect.y + 369), 13,
               theme.CHECK if settings.enabled and not available else theme.MUTED)
    start = pygame.Rect(rect.x + 25, rect.bottom - 55, 300, 36)
    theme.button(surface, start, "Start new game", not settings.enabled or available, True)
    if not settings.enabled or available:
        targets["start"] = start
    targets["cancel"] = pygame.Rect(rect.x + 340, rect.bottom - 55, 125, 36)
    theme.button(surface, targets["cancel"], "Cancel")
    return targets


def adjust(settings: EngineSettings, name: str) -> EngineSettings:
    changes = {
        "local": {"enabled": False}, "engine": {"enabled": True},
        "white": {"human_color": chess.WHITE}, "black": {"human_color": chess.BLACK},
        "minimax": {"alpha_beta": False}, "alphabeta": {"alpha_beta": True},
        "less": {"depth": max(1, settings.depth - 1)},
        "more": {"depth": min(5, settings.depth + 1)},
    }
    return replace(settings, **changes.get(name, {}))


def diagnostics(surface: pygame.Surface, rows: tuple[SearchStats, ...],
                settings: EngineSettings, busy: bool, error: str,
                position_label: str) -> dict[str, pygame.Rect]:
    rect = dialogs.panel(surface, "Search lab", "Minimax and alpha-beta, measured on the same position.", 430)
    # Six compact columns fit inside the minimum-size window's modal panel.
    theme.text(surface, position_label, (rect.x + 25, rect.y + 91), 13, theme.ACCENT)
    columns = [("Algorithm", 25), ("Move", 135), ("Depth", 199),
               ("Nodes", 255), ("Time", 340), ("Score", 405)]
    for label, x in columns:
        theme.text(surface, label, (rect.x + x, rect.y + 133), 12, theme.MUTED, True)
    for index, row in enumerate(rows):
        y = rect.y + 165 + index * 42
        values = [row.algorithm, row.san, str(row.depth) if row.complete else "partial",
                  f"{row.nodes:,}", f"{row.seconds:.3f}s", row.score]
        for value, (_, x) in zip(values, columns):
            theme.text(surface, value, (rect.x + x, y), 13)
    detail = "Scores favor White (+) or Black (−); 1.00 = one pawn."
    if len(rows) == 2 and all(row.complete for row in rows):
        reduction = 100 * (1 - rows[1].nodes / max(1, rows[0].nodes))
        detail = f"Alpha-beta visited {reduction:.1f}% fewer nodes."
    elif rows and any(not row.complete for row in rows):
        detail = "Time limit reached; partial searches are not comparable."
    if busy:
        detail = "Searching… You can close this panel or cancel."
    theme.text(surface, detail, (rect.x + 25, rect.y + 266), 13, theme.MUTED)
    if error:
        # Error text is clipped to the panel; full diagnostic goes to stderr.
        theme.text(surface, error[:62], (rect.x + 25, rect.y + 299), 13, theme.CHECK)
    targets = {
        "compare": pygame.Rect(rect.x + 25, rect.bottom - 85, 300, 36),
        "cancel_search": pygame.Rect(rect.x + 340, rect.bottom - 85, 125, 36),
        "close": pygame.Rect(rect.x + 25, rect.bottom - 39, rect.width - 50, 25),
    }
    theme.button(surface, targets["compare"], f"Compare position · depth {settings.depth}", not busy, True)
    theme.button(surface, targets["cancel_search"], "Stop", busy)
    theme.centered(surface, "Close  ·  Esc", targets["close"], 13, theme.MUTED)
    return targets
