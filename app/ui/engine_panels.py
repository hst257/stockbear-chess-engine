"""Game setup and the search comparison interface."""

from dataclasses import replace

import chess
import pygame

from app.engine_client import EngineSettings, SearchStats
from app.ui import dialogs, theme


def setup(surface: pygame.Surface, settings: EngineSettings, available: bool) -> dict[str, pygame.Rect]:
    rect = dialogs.panel(surface, "Set up a game", "Choose an opponent and a search algorithm.", 590)
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
    theme.text(surface, "SEARCH OPTIONS · CLICK TO TOGGLE", (rect.x + 25, rect.y + 272), 12, theme.MUTED, True)
    options = [
        ("toggle_deepening", "Deepening", settings.iterative_deepening),
        ("toggle_ordering", "Ordering", settings.move_ordering),
        ("toggle_pst", "PST", settings.use_pst),
        ("toggle_tt", "Transpositions", settings.transposition_table),
        ("toggle_quiescence", "Quiescence", settings.quiescence),
        ("toggle_pvs", "PVS", settings.principal_variation_search),
    ]
    for index, (name, label, selected) in enumerate(options):
        target = pygame.Rect(rect.x + 25 + (index % 2) * 225, rect.y + 296 + (index // 2) * 40, 215, 32)
        active = name != "toggle_pvs" or settings.alpha_beta
        text = f"{label}: " + (("on" if selected else "off") if active else "inactive")
        theme.button(surface, target, text, active, selected and active)
        if active:
            targets[name] = target
    theme.text(surface, "TARGET DEPTH (PLIES)", (rect.x + 25, rect.y + 434), 12, theme.MUTED, True)
    for name, label, x, enabled in (("less", "−", rect.x + 290, settings.depth > 1),
                                     ("more", "+", rect.x + 402, settings.depth < 5)):
        target = pygame.Rect(x, rect.y + 426, 38, 32)
        theme.button(surface, target, label, enabled)
        targets[name] = target
    theme.text(surface, str(settings.depth), (rect.x + 353, rect.y + 429), 18, theme.ACCENT, True)
    note = "PVS uses alpha-beta; Minimax keeps full windows."
    if settings.enabled and not available:
        note = "Build the engine first: run build_engine.bat"
    theme.text(surface, note, (rect.x + 25, rect.y + 480), 13,
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
        "toggle_deepening": {"iterative_deepening": not settings.iterative_deepening},
        "toggle_ordering": {"move_ordering": not settings.move_ordering},
        "toggle_pst": {"use_pst": not settings.use_pst},
        "toggle_tt": {"transposition_table": not settings.transposition_table},
        "toggle_quiescence": {"quiescence": not settings.quiescence},
        "toggle_pvs": {"principal_variation_search": not settings.principal_variation_search}
                      if settings.alpha_beta else {},
        "less": {"depth": max(1, settings.depth - 1)},
        "more": {"depth": min(5, settings.depth + 1)},
    }
    return replace(settings, **changes.get(name, {}))


def diagnostics(surface: pygame.Surface, rows: tuple[SearchStats, ...],
                settings: EngineSettings, busy: bool, error: str,
                position_label: str) -> dict[str, pygame.Rect]:
    rect = dialogs.panel(surface, "Search lab", "Minimax vs alpha-beta/PVS · cumulative work.", 648)
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
    quiescence = pygame.Rect(rect.x + 25, rect.y + 192, 215, 30)
    theme.button(surface, quiescence, "Quiescence: " + ("on" if settings.quiescence else "off"), not busy)
    pvs = pygame.Rect(rect.x + 250, rect.y + 192, 215, 30)
    theme.button(surface, pvs, "PVS: " + ("on" if settings.principal_variation_search else "off"), not busy)
    columns = [("Algorithm", 25), ("Move", 135), ("Depth", 199),
               ("Nodes", 255), ("Time", 340), ("Score", 405)]
    for label, x in columns:
        theme.text(surface, label, (rect.x + x, rect.y + 239), 12, theme.MUTED, True)
    for index, row in enumerate(rows):
        y = rect.y + 265 + index * 38
        values = [row.algorithm, row.san, str(row.depth) if row.complete else f"{row.depth}/{row.requested_depth}",
                  f"{row.nodes:,}", f"{row.seconds:.3f}s", row.score]
        for value, (_, x) in zip(values, columns):
            theme.text(surface, value, (rect.x + x, y), 13)
    detail = "Scores favor White (+) or Black (−); 1.00 = one pawn."
    if len(rows) == 2 and all(row.complete for row in rows):
        reduction = 100 * (1 - rows[1].nodes / max(1, rows[0].nodes))
        detail = f"{rows[1].algorithm} visited {reduction:.1f}% fewer nodes."
    elif rows and any(not row.complete for row in rows):
        detail = "Target not reached; showing last completed depths."
    if busy:
        detail = "Searching… each completed depth appears below."
    theme.text(surface, detail, (rect.x + 25, rect.y + 350), 13, theme.MUTED)
    theme.text(surface, "COMPLETED PASSES" + (f" · {rows[-1].algorithm}" if rows else ""),
               (rect.x + 25, rect.y + 384), 12, theme.MUTED, True)
    if rows and rows[-1].iterations:
        for index, iteration in enumerate(rows[-1].iterations[-5:]):
            line = (f"Depth {iteration.depth}    {iteration.san}    {iteration.nodes:,} nodes"
                    f"    {iteration.seconds:.3f}s    {iteration.score}")
            theme.text(surface, line, (rect.x + 25, rect.y + 408 + index * 20), 12)
    else:
        theme.text(surface, "No completed pass yet.", (rect.x + 25, rect.y + 408), 13, theme.MUTED)
    if rows:
        latest = rows[-1]
        line = (f"TT hits {latest.tt_hits:,} · cutoffs {latest.tt_cutoffs:,}"
                f" · occupied {latest.hashfull / 10:.1f}%")
        theme.text(surface, line, (rect.x + 25, rect.y + 516), 12, theme.MUTED)
        if not error:
            line = (f"Q nodes {latest.qnodes:,} · PVS probes {latest.pvs_scouts:,}"
                    f" · re-searches {latest.pvs_researches:,}")
            theme.text(surface, line, (rect.x + 25, rect.y + 534), 12, theme.MUTED)
    if error:
        theme.text(surface, error[:62], (rect.x + 25, rect.y + 540), 13, theme.CHECK)
    targets = {
        "compare": pygame.Rect(rect.x + 25, rect.bottom - 85, 300, 36),
        "cancel_search": pygame.Rect(rect.x + 340, rect.bottom - 85, 125, 36),
        "close": pygame.Rect(rect.x + 25, rect.bottom - 39, rect.width - 50, 25),
        "toggle_deepening": toggle,
        "toggle_ordering": ordering,
        "toggle_pst": pst,
        "toggle_tt": table,
        "toggle_quiescence": quiescence,
        "toggle_pvs": pvs,
    }
    theme.button(surface, targets["compare"], f"Compare position · depth {settings.depth}", not busy, True)
    theme.button(surface, targets["cancel_search"], "Stop", busy)
    theme.centered(surface, "Close  ·  Esc", targets["close"], 13, theme.MUTED)
    return targets
