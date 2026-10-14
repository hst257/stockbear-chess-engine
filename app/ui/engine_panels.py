"""Game setup and the search comparison interface."""

from dataclasses import replace

import chess
import pygame

from app.engine_client import EngineSettings, SearchStats
from app.ui import dialogs, theme


def setup(surface: pygame.Surface, settings: EngineSettings, available: bool) -> dict[str, pygame.Rect]:
    rect = dialogs.panel(surface, "Set up a game", "Choose an opponent and a search algorithm.", 616)
    targets: dict[str, pygame.Rect] = {}

    def choices(y: int, title: str, options: list[tuple[str, str, bool]]) -> None:
        theme.text(surface, title, (rect.x + 25, rect.y + y), 12, theme.MUTED, True)
        width = (rect.width - 60) // 2
        for index, (name, label, selected) in enumerate(options):
            target = pygame.Rect(rect.x + 25 + index * (width + 10), rect.y + y + 20, width, 32)
            theme.button(surface, target, label, primary=selected)
            targets[name] = target

    choices(92, "OPPONENT", [("local", "Local two players", not settings.enabled),
                             ("engine", "ChessLab engine", settings.enabled)])
    choices(148, "YOUR PIECES", [("white", "White", settings.human_color),
                                 ("black", "Black", not settings.human_color)])
    choices(204, "SEARCH", [("minimax", "Minimax", not settings.alpha_beta),
                            ("alphabeta", "Alpha-beta", settings.alpha_beta)])
    choices(260, "DEEPENING", [("iterative", "Depth 1 → target", settings.iterative_deepening),
                              ("fixed", "Target depth only", not settings.iterative_deepening)])
    choices(316, "MOVE ORDERING", [("ordered", "PV / promotions / captures", settings.move_ordering),
                                   ("unordered", "Original move order", not settings.move_ordering)])
    choices(372, "EVALUATION", [("pst_on", "Material + PST (on)", settings.use_pst),
                               ("pst_off", "Material only (off)", not settings.use_pst)])
    choices(428, "TRANSPOSITION TABLE", [("tt_on", "Cache on · Zobrist", settings.transposition_table),
                                        ("tt_off", "Cache off · baseline", not settings.transposition_table)])
    theme.text(surface, "TARGET DEPTH (PLIES)", (rect.x + 25, rect.y + 498), 12, theme.MUTED, True)
    for name, label, x, enabled in (("less", "−", rect.x + 290, settings.depth > 1),
                                     ("more", "+", rect.x + 402, settings.depth < 5)):
        target = pygame.Rect(x, rect.y + 490, 38, 32)
        theme.button(surface, target, label, enabled)
        targets[name] = target
    theme.text(surface, str(settings.depth), (rect.x + 353, rect.y + 493), 18, theme.ACCENT, True)
    note = "Both algorithms use the selected evaluation."
    if settings.enabled and not available:
        note = "Build the engine first: run build_engine.bat"
    theme.text(surface, note, (rect.x + 25, rect.y + 533), 13,
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
        "iterative": {"iterative_deepening": True}, "fixed": {"iterative_deepening": False},
        "ordered": {"move_ordering": True}, "unordered": {"move_ordering": False},
        "pst_on": {"use_pst": True}, "pst_off": {"use_pst": False},
        "tt_on": {"transposition_table": True}, "tt_off": {"transposition_table": False},
        "less": {"depth": max(1, settings.depth - 1)},
        "more": {"depth": min(5, settings.depth + 1)},
    }
    return replace(settings, **changes.get(name, {}))


def diagnostics(surface: pygame.Surface, rows: tuple[SearchStats, ...],
                settings: EngineSettings, busy: bool, error: str,
                position_label: str) -> dict[str, pygame.Rect]:
    rect = dialogs.panel(surface, "Search lab", "Minimax vs alpha-beta · cumulative nodes and time.", 648)
    # Six compact columns fit inside the minimum-size window's modal panel.
    theme.text(surface, position_label, (rect.x + 25, rect.y + 91), 13, theme.ACCENT)
    toggle = pygame.Rect(rect.x + 25, rect.y + 116, 215, 30)
    theme.button(surface, toggle, "Deepening: " + ("on" if settings.iterative_deepening else "off"), not busy)
    ordering = pygame.Rect(rect.x + 250, rect.y + 116, 215, 30)
    theme.button(surface, ordering, "Ordering: " + ("on" if settings.move_ordering else "off"), not busy)
    pst = pygame.Rect(rect.x + 25, rect.y + 154, 215, 30)
    theme.button(surface, pst, "PST: " + ("on" if settings.use_pst else "off"), not busy)
    table = pygame.Rect(rect.x + 250, rect.y + 154, 215, 30)
    theme.button(surface, table, "Transpositions: " + ("on" if settings.transposition_table else "off"), not busy)
    columns = [("Algorithm", 25), ("Move", 135), ("Depth", 199),
               ("Nodes", 255), ("Time", 340), ("Score", 405)]
    for label, x in columns:
        theme.text(surface, label, (rect.x + x, rect.y + 201), 12, theme.MUTED, True)
    for index, row in enumerate(rows):
        y = rect.y + 227 + index * 38
        values = [row.algorithm, row.san, str(row.depth) if row.complete else f"{row.depth}/{row.requested_depth}",
                  f"{row.nodes:,}", f"{row.seconds:.3f}s", row.score]
        for value, (_, x) in zip(values, columns):
            theme.text(surface, value, (rect.x + x, y), 13)
    detail = "Scores favor White (+) or Black (−); 1.00 = one pawn."
    if len(rows) == 2 and all(row.complete for row in rows):
        reduction = 100 * (1 - rows[1].nodes / max(1, rows[0].nodes))
        detail = f"Alpha-beta visited {reduction:.1f}% fewer nodes."
    elif rows and any(not row.complete for row in rows):
        detail = "Target not reached; showing last completed depths."
    if busy:
        detail = "Searching… each completed depth appears below."
    theme.text(surface, detail, (rect.x + 25, rect.y + 312), 13, theme.MUTED)
    theme.text(surface, "COMPLETED PASSES" + (f" · {rows[-1].algorithm}" if rows else ""),
               (rect.x + 25, rect.y + 352), 12, theme.MUTED, True)
    if rows and rows[-1].iterations:
        for index, iteration in enumerate(rows[-1].iterations[-5:]):
            line = (f"Depth {iteration.depth}    {iteration.san}    {iteration.nodes:,} nodes"
                    f"    {iteration.seconds:.3f}s    {iteration.score}")
            theme.text(surface, line, (rect.x + 25, rect.y + 378 + index * 23), 12)
    else:
        theme.text(surface, "No completed pass yet.", (rect.x + 25, rect.y + 378), 13, theme.MUTED)
    if rows:
        latest = rows[-1]
        line = (f"TT hits {latest.tt_hits:,} · cutoffs {latest.tt_cutoffs:,}"
                f" · occupied {latest.hashfull / 10:.1f}%")
        theme.text(surface, line, (rect.x + 25, rect.y + 498), 12, theme.MUTED)
    if error:
        theme.text(surface, error[:62], (rect.x + 25, rect.y + 521), 13, theme.CHECK)
    targets = {
        "compare": pygame.Rect(rect.x + 25, rect.bottom - 85, 300, 36),
        "cancel_search": pygame.Rect(rect.x + 340, rect.bottom - 85, 125, 36),
        "close": pygame.Rect(rect.x + 25, rect.bottom - 39, rect.width - 50, 25),
        "toggle_deepening": toggle,
        "toggle_ordering": ordering,
        "toggle_pst": pst,
        "toggle_tt": table,
    }
    theme.button(surface, targets["compare"], f"Compare position · depth {settings.depth}", not busy, True)
    theme.button(surface, targets["cancel_search"], "Stop", busy)
    theme.centered(surface, "Close  ·  Esc", targets["close"], 13, theme.MUTED)
    return targets
