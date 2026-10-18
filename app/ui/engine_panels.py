"""Game setup and the search comparison interface."""

from dataclasses import replace

import chess
import pygame

from app.engine_client import EngineSettings, SearchStats, THINKING_TIMES
from app.ui import dialogs, theme

EVALUATOR_LABELS = {"classical": "Classical (Default)", "nnue": "NNUE Hiddenclip", "nnue_v3": "NNUE v3 (legacy)"}
EVALUATORS = ("classical", "nnue")


def setup(surface: pygame.Surface, settings: EngineSettings, available: bool) -> dict[str, pygame.Rect]:
    rect = dialogs.panel(surface, "Set up a game", "Choose settings, then apply or start a new game.", 648)
    targets: dict[str, pygame.Rect] = {}

    def choices(y: int, title: str, options: list[tuple[str, str, bool]]) -> None:
        theme.text(surface, title, (rect.x + 25, rect.y + y), 12, theme.MUTED, True)
        width = (rect.width - 60) // 2
        for index, (name, label, selected) in enumerate(options):
            target = pygame.Rect(rect.x + 25 + index * (width + 10), rect.y + y + 20, width, 32)
            theme.button(surface, target, label, primary=selected)
            targets[name] = target

    choices(92, "OPPONENT", [("local", "Local two players", not settings.enabled),
                             ("engine", "StockBear engine", settings.enabled)])
    choices(148, "YOUR PIECES", [("white", "White", settings.human_color),
                                 ("black", "Black", not settings.human_color)])
    choices(204, "SEARCH", [("minimax", "Minimax", not settings.alpha_beta),
                            ("alphabeta", "Alpha-beta", settings.alpha_beta)])
    theme.text(surface, "SEARCH OPTIONS", (rect.x + 25, rect.y + 272), 12, theme.MUTED, True)
    evaluator = pygame.Rect(rect.x + 250, rect.y + 264, 215, 28)
    theme.button(surface, evaluator, "Eval: " + EVALUATOR_LABELS[settings.evaluator])
    targets["toggle_evaluator"] = evaluator
    options = [
        ("toggle_deepening", "Deepening", settings.iterative_deepening),
        ("toggle_ordering", "Ordering", settings.move_ordering),
        ("toggle_pst", "PST", settings.use_pst),
        ("toggle_tt", "Transpositions", settings.transposition_table),
        ("toggle_quiescence", "Quiescence", settings.quiescence),
        ("toggle_pvs", "PVS", settings.principal_variation_search),
    ]
    for index, (name, label, selected) in enumerate(options):
        target = pygame.Rect(rect.x + 25 + (index % 2) * 225, rect.y + 296 + (index // 2) * 36, 215, 30)
        active = ((name != "toggle_pvs" or settings.alpha_beta) and
                  (name != "toggle_deepening" or not settings.timed_search) and
                  (name != "toggle_pst" or settings.evaluator == "classical"))
        if name == "toggle_deepening" and settings.timed_search:
            label, selected = "Deepening", True
        text = f"{label}: " + (("on" if selected else "off") if active else "inactive")
        if name == "toggle_deepening" and settings.timed_search:
            text = "Deepening: automatic"
        if name == "toggle_pst" and settings.evaluator != "classical":
            text = "PST: classical only"
        theme.button(surface, target, text, active, selected and active)
        if active:
            targets[name] = target
    for index, (name, label, selected) in enumerate((("time_mode", "Time budget", settings.timed_search),
                                                   ("depth_mode", "Fixed depth", not settings.timed_search))):
        target = pygame.Rect(rect.x + 25 + index * 225, rect.y + 414, 215, 28)
        theme.button(surface, target, label, primary=selected)
        targets[name] = target
    theme.text(surface, "ENGINE THINKING TIME", (rect.x + 25, rect.y + 450), 12, theme.MUTED, True)
    for index, (label, milliseconds) in enumerate(THINKING_TIMES):
        target = pygame.Rect(rect.x + 25 + index * 89, rect.y + 471, 84, 40)
        selected = settings.thinking_time_ms == milliseconds
        theme.button(surface, target, "", primary=selected)
        color = theme.BACKGROUND if selected else theme.TEXT
        theme.centered(surface, label, pygame.Rect(target.x, target.y + 1, target.width, 19), 12, color, selected)
        theme.centered(surface, f"{milliseconds / 1000:g}s", pygame.Rect(target.x, target.y + 20, target.width, 17), 12, color)
        targets[f"time_{milliseconds}"] = target
    theme.text(surface, "DEBUG TARGET DEPTH", (rect.x + 25, rect.y + 534), 12, theme.MUTED, True)
    for name, label, x, enabled in (("less", "−", rect.x + 290, settings.depth > 1),
                                     ("more", "+", rect.x + 402, settings.depth < 5)):
        target = pygame.Rect(x, rect.y + 526, 38, 32)
        theme.button(surface, target, label, enabled)
        targets[name] = target
    theme.text(surface, str(settings.depth), (rect.x + 353, rect.y + 529), 18, theme.ACCENT, True)
    note = "Time mode deepens automatically; depth is for debugging."
    if settings.enabled and not available:
        note = "Build the engine first: run build_engine.bat"
    theme.text(surface, note, (rect.x + 25, rect.y + 567), 12,
               theme.CHECK if settings.enabled and not available else theme.MUTED)
    start = pygame.Rect(rect.x + 25, rect.bottom - 48, 180, 32)
    theme.button(surface, start, "Start new game", not settings.enabled or available, True)
    if not settings.enabled or available:
        targets["start"] = start
    apply = pygame.Rect(rect.x + 215, rect.bottom - 48, 145, 32)
    theme.button(surface, apply, "Apply to game", not settings.enabled or available)
    if not settings.enabled or available:
        targets["apply"] = apply
    targets["cancel"] = pygame.Rect(rect.x + 370, rect.bottom - 48, 95, 32)
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
        "toggle_evaluator": {"evaluator": "nnue" if settings.evaluator == "classical" else "classical"},
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
        "time_mode": {"timed_search": True}, "depth_mode": {"timed_search": False},
    }
    changes.update({f"time_{ms}": {"thinking_time_ms": ms} for _, ms in THINKING_TIMES})
    return replace(settings, **changes.get(name, {}))


def diagnostics(surface: pygame.Surface, rows: tuple[SearchStats, ...],
                settings: EngineSettings, busy: bool, error: str,
                position_label: str) -> dict[str, pygame.Rect]:
    rect = dialogs.panel(surface, "Search lab", "Minimax vs alpha-beta/PVS · cumulative work.", 648)
    # Six compact columns fit inside the minimum-size window's modal panel.
    theme.text(surface, position_label, (rect.x + 25, rect.y + 91), 13, theme.ACCENT)
    evaluator = pygame.Rect(rect.x + 250, rect.y + 80, 215, 28)
    theme.button(surface, evaluator, "Eval: " + EVALUATOR_LABELS[settings.evaluator], not busy)
    toggle = pygame.Rect(rect.x + 25, rect.y + 116, 215, 30)
    theme.button(surface, toggle, "Deepening: automatic" if settings.timed_search else
                 "Deepening: " + ("on" if settings.iterative_deepening else "off"), not busy and not settings.timed_search)
    ordering = pygame.Rect(rect.x + 250, rect.y + 116, 215, 30)
    theme.button(surface, ordering, "Ordering: " + ("on" if settings.move_ordering else "off"), not busy)
    pst = pygame.Rect(rect.x + 25, rect.y + 154, 215, 30)
    theme.button(surface, pst, "PST: classical only" if settings.evaluator != "classical" else
                 "PST: " + ("on" if settings.use_pst else "off"), not busy and settings.evaluator == "classical")
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
        depth = str(row.depth) if row.timed_search or row.complete else f"{row.depth}/{row.requested_depth}"
        values = [row.algorithm, row.san, depth,
                  f"{row.nodes:,}", f"{row.seconds:.3f}s", row.score]
        for value, (_, x) in zip(values, columns):
            theme.text(surface, value, (rect.x + x, y), 13)
    detail = "Scores favor White (+) or Black (−); 1.00 = one pawn."
    if len(rows) == 2 and all(row.complete and not row.timed_search for row in rows) and rows[0].depth == rows[1].depth:
        reduction = 100 * (1 - rows[1].nodes / max(1, rows[0].nodes))
        detail = f"{rows[1].algorithm} visited {reduction:.1f}% fewer nodes."
    elif rows and rows[-1].timed_search:
        detail = "Equal time budgets; completed depths can differ."
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
        "toggle_evaluator": evaluator,
    }
    theme.button(surface, targets["compare"], f"Compare position · {settings.search_label}", not busy, True)
    theme.button(surface, targets["cancel_search"], "Stop", busy)
    theme.centered(surface, "Close  ·  Esc", targets["close"], 13, theme.MUTED)
    return targets
