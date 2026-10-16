"""Frozen, serial and resumable equal-time NNUE architecture showdown.

No engine/training source is edited. Run prepare, verify, then run. Game JSON is
authoritative; PGNs/scoreboards are derived. In-progress games checkpoint moves.
"""
from __future__ import annotations

import argparse
from collections import Counter, deque
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import statistics
import subprocess
import sys
import time

import chess
import chess.engine
import chess.pgn

from tools.match_optimizations import write_record

REPO = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = REPO / "nnue-showdown-20261016"
SCALING = REPO / "StockBear_NNUE_training/scaling-experiment-20261016"
MODELS = {"32": ("baseline", 32, 16), "64": ("medium", 64, 32), "128": ("large", 128, 32)}
SEED = 20261016
ALLOWANCE = .100
MAX_PLIES = 400
FAMILIES = (
    ("Ruy Lopez", "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6"),
    ("Queen's Gambit Declined", "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7"),
    ("Sicilian Najdorf", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6"),
    ("King's Indian", "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O"),
    ("French", "e4 e6 d4 d5 Nc3 Nf6 Bg5 Be7"),
    ("English", "c4 e5 Nc3 Nf6 g3 d5 cxd5 Nxd5 Bg2 Nb6"),
    ("Caro-Kann", "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5"),
    ("Slav", "d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4 a4 Bf5"),
    ("Italian", "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6"),
    ("Nimzo-Indian", "d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O Bd3 d5"),
    ("Scotch", "e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Bc5 Be3 Qf6"),
    ("Catalan", "d4 Nf6 c4 e6 g3 d5 Bg2 Be7 Nf3 O-O"),
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: dict | list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_record(path, json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + "\n")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def make_openings() -> list[dict]:
    families = list(FAMILIES)
    random.Random(SEED).shuffle(families)
    openings = []
    for index, (name, line) in enumerate(families):
        board = chess.Board()
        for san in line.split():
            board.push_san(san)
        if not board.is_valid() or board.is_game_over(claim_draw=True) or board.is_check():
            raise ValueError(f"Invalid opening: {name}")
        # Established main lines, no random loose-piece extensions or model filter.
        openings.append({"id": f"O{index + 1:02}", "family": name, "san": line,
                         "fen": board.fen(), "moves": [m.uci() for m in board.move_stack]})
    return openings


def schedule(models: tuple[str, ...] = ("32", "64", "128")) -> list[dict]:
    pairs = ((models[0], models[1]), (models[1], models[2]), (models[0], models[2]))
    games = []
    for ms, count in ((500, 12), (1000, 6), (3000, 3)):
        for opening in range(count):
            order = pairs[opening % 3:] + pairs[:opening % 3]
            for a, b in order:
                for reverse in range(2):
                    white, black = (a, b) if (reverse + opening) % 2 == 0 else (b, a)
                    games.append({"id": f"G{len(games) + 1:03}", "ms": ms, "opening": opening,
                                  "pair": [a, b], "white": white, "black": black, "stage": "round_robin"})
    assert len(games) == 126
    return games


def prepare(root: Path) -> dict:
    if (root / "plan.json").exists():
        plan = load(root / "plan.json")
        validate_identity(root, plan)
        return plan
    root.mkdir(parents=True, exist_ok=True)
    protected = load(SCALING / "preservation-before.json")
    for path in (SCALING / "artifacts").rglob("*"):
        if path.is_file() and path.suffix in (".pt", ".sbnnue", ".exe"):
            protected[path.relative_to(REPO).as_posix()] = sha(path)
    save(root / "preservation-before.json", protected)
    engines = {}
    environment = os.environ.copy()
    environment.setdefault("ZIG_GLOBAL_CACHE_DIR", str(root / "artifacts/zig-cache"))
    for label, (name, width, hidden) in MODELS.items():
        export = SCALING / "artifacts/native" / name / f"{name}.sbnnue"
        expected = load(SCALING / "native-benchmark.json")[name]["export_sha256"]
        if sha(export) != expected:
            raise ValueError("Verified export identity changed")
        destination = root / "artifacts/engines" / label
        binary = destination / f"StockBear-NNUE-{label}.exe"
        if binary.exists():
            raise ValueError("Unregistered binary exists; preserve it and use another experiment directory")
        command = [str(REPO / ".venv/Scripts/python.exe"), str(REPO / "tools/build_engine.py"),
                   "--target", "engine", "--nnue-model", str(export), "--output", str(binary),
                   "--optimization", "O2", "--nnue-update", "compact"]
        destination.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(command, cwd=REPO, env=environment, text=True, capture_output=True)
        (destination / "build.log").write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError(f"Build failed: {destination / 'build.log'}")
        build = load(binary.with_suffix(".build.json"))
        engines[label] = {"name": f"StockBear-NNUE-{label}", "path": str(binary), "sha256": sha(binary),
                          "network": str(export), "network_sha256": expected,
                          "width": width, "hidden": hidden, "build": build}
    options = {"AlphaBeta": True, "IterativeDeepening": True, "MoveOrdering": True,
               "Evaluator": "nnue", "NNUEKernel": "scalar", "NNUEIncremental": True,
               "Hash": 16, "TranspositionTable": True, "Quiescence": True, "PVS": True,
               "UseAspirationWindows": True, "AspirationDelta": 25, "UseNullMovePruning": True,
               "UseLMR": True, "LMRReduction": 1, "UseHistory": True, "UseKillers": True,
               "UseSEE": True, "UseAdaptiveLMR": True, "UseReverseFutility": True,
               "UseFutility": True, "UseCheckExtensions": True, "FastMovegen": True,
               "PawnCache": True, "UsePST": True, "UseAdvancedEvaluation": True, "UseMopUp": True}
    plan = {"schema": 1, "created_utc": utc(), "seed": SEED, "engines": engines, "options": options,
            "openings": make_openings(), "schedule": schedule(), "planned_games": 130,
            "allowance_seconds": ALLOWANCE, "max_searched_plies": MAX_PLIES,
            "threads": 1, "ponder": False, "python": sys.version, "python_chess": chess.__version__,
            "runner_sha256": sha(Path(__file__)),
            "rules": {"draws": "Automatically claim available threefold/50-move draws; also enforce fivefold/75-move/insufficient material/stalemate/checkmate via python-chess, retaining full opening history.",
                      "cap": "400 searched plies: unfinished, unscored, not a draw; never automatically replayed or extended.",
                      "failure": "Save and halt on timeout/crash/illegal move; infrastructure failures are unscored, not forfeits. Fix/review before explicit retry.",
                      "openings": "Twelve established main lines in seeded order, no evaluator or Stockfish filter. Nested first 12/6/3/2 pairs at 500/1000/3000/5000 ms; same within every pairing.",
                      "finalists": "Equal-weight mean of the three per-format round-robin point fractions. Tie: equal-weight head-to-head fraction, then fewer parameters. Final four games exploratory; no extra games.",
                      "clocks": "Fresh processes per game; movetime only, no depth/nodes cap. Wall deadline movetime+100ms includes protocol/OS allowance. Engine and wall times both recorded.",
                      "instrumentation": "Existing final UCI node/depth/eval_calls/nnue_evaluations counters; no diagnostic build. Accumulator updates/refresh counts unavailable in release, not inferred."}}
    save(root / "plan.json", plan)
    validate_identity(root, plan)
    return plan


def validate_identity(root: Path, plan: dict) -> None:
    if sha(Path(__file__)) != plan["runner_sha256"]:
        raise ValueError("Frozen runner source changed; do not resume with different rules")
    sources = []
    defaults = []
    compiler_flags = []
    for label, engine in plan["engines"].items():
        if sha(Path(engine["path"])) != engine["sha256"] or sha(Path(engine["network"])) != engine["network_sha256"]:
            raise ValueError(f"Engine/network identity changed: {label}")
        b = engine["build"]
        if b["nnue"]["sha256"] != engine["network_sha256"] or (b["nnue"]["width"], b["nnue"]["hidden"]) != (engine["width"], engine["hidden"]):
            raise ValueError("Build/model dimensions disagree")
        sources.append(b["source_sha256"])
        defaults.append((b["compiler"], b["optimization"], b["lto"], b["profile"], b["diagnostics"], b["nnue_update"], b["sanitizer"]))
        compiler_flags.append([flag.replace(str(Path(engine["path"]).parent / "generated"), "{generated}").replace(engine["path"], "{binary}") for flag in b["flags"]])
    if any(s != sources[0] for s in sources) or any(d != defaults[0] for d in defaults) or any(f != compiler_flags[0] for f in compiler_flags):
        raise ValueError("Tournament builds differ in source or search compilation settings")
    for name, expected in sources[0].items():
        if sha(REPO / name) != expected:
            raise ValueError(f"Native source changed after builds: {name}")


class CapturingProtocol(chess.engine.UciProtocol):
    def __init__(self) -> None:
        super().__init__()
        self.transcript = deque(maxlen=256)
        self.counters: dict[str, int] = {}

    def send_line(self, line: str) -> None:
        self.transcript.append("> " + line)
        if line.startswith("go "):
            self.counters = {}
        super().send_line(line)

    def line_received(self, line: str) -> None:
        self.transcript.append("< " + line)
        if line.startswith("info string "):
            self.counters.update({k: int(v) for k, v in re.findall(r"\b([a-z_]+)\s+(\d+)\b", line)})
        super().line_received(line)


def identity(player: chess.engine.SimpleEngine) -> dict:
    class Command(chess.engine.BaseCommand):
        def __init__(self, engine):
            super().__init__(engine)
            self.engine = engine

        def start(self):
            self.value = None
            self.engine.send_line("position startpos")
            self.engine.send_line("eval")
            self.engine.send_line("isready")

        def line_received(self, line):
            if line.startswith("info string eval "):
                self.value = json.loads(line[len("info string eval "):])
            if line == "readyok":
                self.result.set_result(self.value)
                self.set_finished()
    return player.communicate(Command)


def open_engine(entry: dict, options: dict) -> chess.engine.SimpleEngine:
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    engine = chess.engine.SimpleEngine.popen(CapturingProtocol, entry["path"], timeout=10, **flags)
    try:
        engine.configure(options)
        engine.ping()
        actual = identity(engine)
        if (not actual or actual["sha256"] != entry["network_sha256"] or actual["width"] != entry["width"]
                or actual["hidden"] != entry["hidden"] or actual["kernel"] != "scalar"):
            raise ValueError("Running engine identity/kernel mismatch")
        return engine
    except BaseException:
        engine.close()
        raise


def board_for(plan: dict, game: dict, record: dict | None = None) -> chess.Board:
    board = chess.Board()
    opening = plan["openings"][game["opening"]]
    for uci in opening["moves"]:
        board.push_uci(uci)
    if board.fen() != opening["fen"]:
        raise ValueError("Opening reconstruction mismatch")
    if record:
        for row in record["searches"]:
            if row["engine"] != (game["white"] if board.turn else game["black"]):
                raise ValueError("Saved move belongs to the wrong engine")
            board.push_uci(row["move"])
    return board


def export_pgn(root: Path, plan: dict, game: dict, record: dict) -> None:
    board = board_for(plan, game, record)
    pgn = chess.pgn.Game.from_board(board)
    pgn.headers.update({"Event": "StockBear NNUE Architecture Showdown", "Site": "Local isolated engines",
        "Date": record["started_utc"][:10].replace("-", "."), "Round": game["id"],
        "White": plan["engines"][game["white"]]["name"], "Black": plan["engines"][game["black"]]["name"],
        "Result": record["result"], "TimeControl": "?", "ThinkTimeMs": str(game["ms"]),
        "Opening": plan["openings"][game["opening"]]["family"], "OpeningId": plan["openings"][game["opening"]]["id"],
        "OpeningFEN": plan["openings"][game["opening"]]["fen"], "Termination": record["termination"],
        "WhiteEngineSHA256": plan["engines"][game["white"]]["sha256"],
        "BlackEngineSHA256": plan["engines"][game["black"]]["sha256"],
        "WhiteNetworkSHA256": plan["engines"][game["white"]]["network_sha256"],
        "BlackNetworkSHA256": plan["engines"][game["black"]]["network_sha256"],
        "PlanSHA256": record["plan_sha256"], "Kernel": "scalar-float32", "HashMB": "16", "Threads": "1"})
    write_record(root / "games" / (game["id"] + ".pgn"), str(pgn) + "\n")


def play_game(root: Path, plan: dict, game: dict) -> dict:
    fingerprint = sha(root / "plan.json")
    final = root / "games" / (game["id"] + ".json")
    partial = root / "games" / (game["id"] + ".partial.json")
    if final.exists():
        record = load(final)
        if record["plan_sha256"] != fingerprint or record["game"] != game:
            raise ValueError("Completed game identity mismatch")
        board = board_for(plan, game, record)
        outcome = board.outcome(claim_draw=True)
        if record["result"] != (outcome.result() if outcome else "*"):
            raise ValueError("Completed game result disagrees with replayed rules")
        if not (root / "games" / (game["id"] + ".pgn")).exists():
            export_pgn(root, plan, game, record)
        return record
    if partial.exists():
        record = load(partial)
        if record["plan_sha256"] != fingerprint or record["game"] != game:
            raise ValueError("In-progress game identity mismatch")
    else:
        record = {"plan_sha256": fingerprint, "game": game, "started_utc": utc(), "searches": [],
                  "seconds": 0., "result": "*", "termination": "in_progress", "complete": False}
    board = board_for(plan, game, record)
    root.joinpath("games").mkdir(exist_ok=True)
    players = {}
    try:
        with ExitStack() as stack:
            for label in (game["white"], game["black"]):
                players[label] = stack.enter_context(open_engine(plan["engines"][label], plan["options"]))
            for player in players.values():
                player.timeout = plan["allowance_seconds"]
            last_tick = time.monotonic()
            while len(record["searches"]) < plan["max_searched_plies"]:
                outcome = board.outcome(claim_draw=True)
                if outcome:
                    break
                label = game["white"] if board.turn else game["black"]
                player = players[label]
                started = time.perf_counter()
                result = player.play(board, chess.engine.Limit(time=game["ms"] / 1000),
                                     game=game["id"], info=chess.engine.INFO_ALL, ponder=False)
                wall = time.perf_counter() - started
                if wall > game["ms"] / 1000 + plan["allowance_seconds"]:
                    raise TimeoutError(f"Wall clock deadline exceeded: {wall:.6f}s")
                if result.move is None or result.move not in board.legal_moves:
                    raise chess.engine.EngineError(f"Illegal or null move: {result.move}")
                info = result.info
                counters = dict(player.protocol.counters)
                score = info.get("score")
                if not {"depth", "nodes", "time", "nps"}.issubset(info) or "nnue_evaluations" not in counters:
                    raise RuntimeError("Required final search instrumentation missing")
                row = {"engine": label, "move": result.move.uci(), "depth": info["depth"],
                       "seldepth": info.get("seldepth"), "nodes": info["nodes"], "nps": info["nps"],
                       "engine_seconds": info["time"], "wall_seconds": wall,
                       "eval_calls": counters["eval_calls"], "nnue_evaluations": counters["nnue_evaluations"],
                       "qnodes": counters.get("qnodes"), "score_cp_white": score.white().score() if score else None,
                       "mate_white": score.white().mate() if score else None}
                record["searches"].append(row)
                record["seconds"] += wall
                board.push(result.move)
                save(partial, record)
                if time.monotonic() - last_tick >= 30:
                    current = {"game": game["id"], "searched_moves": len(record["searches"]),
                               "ms": game["ms"], "thinking_seconds": record["seconds"], "updated_utc": utc()}
                    save(root / "current.json", current)
                    print(json.dumps(current), flush=True)
                    last_tick = time.monotonic()
            outcome = board.outcome(claim_draw=True)
            record.update(complete=True, completed_utc=utc(), result=outcome.result() if outcome else "*",
                          termination=outcome.termination.name.lower() if outcome else "safety_cap_unfinished",
                          final_fen=board.fen())
            save(final, record)
            export_pgn(root, plan, game, record)
            return record
    except BaseException as error:
        save(partial, record)
        if isinstance(error, (KeyboardInterrupt, SystemExit)):
            raise
        kind = "timeout" if isinstance(error, TimeoutError) else "crash" if isinstance(error, chess.engine.EngineTerminatedError) else "illegal_move" if "Illegal" in str(error) else "infrastructure"
        failed = {"utc": utc(), "game": game, "kind": kind, "error": repr(error), "unscored": True,
                  "completed_searches": len(record["searches"]), "plan_sha256": fingerprint,
                  "transcripts": {label: list(player.protocol.transcript) for label, player in players.items()}}
        save(root / "failures" / f"{game['id']}-{time.time_ns()}.json", failed)
        raise RuntimeError(f"Critical {kind} in {game['id']}; saved raw state and stopped") from error


def records(root: Path) -> list[dict]:
    return [load(p) for p in sorted((root / "games").glob("G[0-9][0-9][0-9].json"))]


def points(record: dict, label: str) -> float | None:
    if record["result"] == "*":
        return None
    if record["result"] == "1/2-1/2":
        return .5
    winner = record["game"]["white"] if record["result"] == "1-0" else record["game"]["black"]
    return float(label == winner)


def stats(rows: list[dict], label: str) -> dict:
    selected = [r for r in rows if label in r["game"]["pair"]]
    values = [points(r, label) for r in selected]
    scored = [v for v in values if v is not None]
    searches = [s for r in selected for s in r["searches"] if s["engine"] == label]
    seconds = sum(s["engine_seconds"] for s in searches)
    nodes = sum(s["nodes"] for s in searches)
    return {"games": len(selected), "wins": scored.count(1.), "draws": scored.count(.5), "losses": scored.count(0.),
            "unfinished": values.count(None), "points": sum(scored),
            "score_fraction": sum(scored) / len(scored) if scored else None,
            "nodes": nodes, "moves": len(searches), "aggregate_nps": nodes / seconds if seconds else None,
            "mean_reported_nps": statistics.mean(s["nps"] for s in searches) if searches else None,
            "mean_depth": statistics.mean(s["depth"] for s in searches) if searches else None,
            "median_depth": statistics.median(s["depth"] for s in searches) if searches else None,
            "engine_seconds": seconds, "mean_wall_seconds": statistics.mean(s["wall_seconds"] for s in searches) if searches else None,
            "mean_engine_seconds": seconds / len(searches) if searches else None,
            "max_wall_seconds": max((s["wall_seconds"] for s in searches), default=None),
            "eval_calls": sum(s["eval_calls"] for s in searches),
            "nnue_evaluations": sum(s["nnue_evaluations"] for s in searches)}


def standings(rows: list[dict]) -> list[dict]:
    result = []
    for label in MODELS:
        formats = {str(ms): stats([r for r in rows if r["game"]["ms"] == ms and r["game"]["stage"] == "round_robin"], label)
                   for ms in (500, 1000, 3000)}
        scores = [s["score_fraction"] for s in formats.values()]
        result.append({"model": label, "formats": formats,
                       "equal_format_score": statistics.mean(scores) if all(s is not None for s in scores) else None,
                       "round_robin": stats([r for r in rows if r["game"]["stage"] == "round_robin"], label)})
    return sorted(result, key=lambda r: (-(r["equal_format_score"] or 0), int(r["model"])))


def select_finalists(rows: list[dict]) -> list[str]:
    if len([r for r in rows if r["game"]["stage"] == "round_robin"]) != 126:
        raise ValueError("Complete the 126 round-robin games before choosing finalists")
    ranking = standings(rows)
    # Mini-league score breaks tied groups without cyclic pairwise sorting.
    ordered = []
    while ranking:
        score = ranking[0]["equal_format_score"]
        group = [r for r in ranking if abs(r["equal_format_score"] - score) <= 1e-12]
        labels = {r["model"] for r in group}
        for entry in group:
            mutual = [r for r in rows if set(r["game"]["pair"]).issubset(labels)]
            scores = [stats([r for r in mutual if r["game"]["ms"] == ms], entry["model"])["score_fraction"]
                      for ms in (500, 1000, 3000)]
            entry["tie_score"] = statistics.mean([s for s in scores if s is not None]) if any(s is not None for s in scores) else .5
        ordered.extend(sorted(group, key=lambda r: (-r["tie_score"], int(r["model"]))))
        ranking = [r for r in ranking if r["model"] not in labels]
    return [r["model"] for r in ordered[:2]]


def publish_progress(root: Path, plan: dict) -> dict:
    rows = records(root)
    seconds = sum(r["seconds"] for r in rows)
    moves = [len(r["searches"]) for r in rows]
    mean_moves = statistics.mean(moves) if moves else None
    # Runtime estimate uses observed game lengths and per-move wall overhead.
    searches = [s for r in rows for s in r["searches"]]
    overhead = statistics.mean(s["wall_seconds"] - s["engine_seconds"] for s in searches) if searches else 0
    remaining = [g for g in plan["schedule"] if not (root / "games" / (g["id"] + ".json")).exists()]
    nominal = sum(g["ms"] / 1000 + max(0., overhead) for g in remaining) + 4 * (5 + max(0., overhead))
    if (root / "finalists.json").exists():
        final_games = load(root / "finalists.json")["schedule"]
        nominal -= 4 * (5 + max(0., overhead))
        nominal += sum(g["ms"] / 1000 + max(0., overhead) for g in final_games if not (root / "games" / (g["id"] + ".json")).exists())
    progress = {"updated_utc": utc(), "completed_games": len(rows), "planned_games": 130,
                "searched_seconds": seconds, "mean_searched_moves_per_game": mean_moves,
                "estimated_remaining_seconds": mean_moves * nominal if mean_moves else None,
                "standings": standings(rows), "failures": len(list((root / "failures").glob("*.json"))),
                "eta_note": "Observed completed game lengths and measured move overhead; game lengths differ by time control; no schedule extension"}
    save(root / "scoreboard.json", progress)
    return progress


@contextmanager
def run_lock(root: Path):
    from StockBear_NNUE_training.stockbear.labeling.storage import writer_lock
    with writer_lock(root / "artifacts/lock"):
        yield


@contextmanager
def stay_awake():
    """Keep the authorized computation awake without changing power settings."""
    if os.name != "nt":
        yield
        return
    import ctypes
    call = ctypes.windll.kernel32.SetThreadExecutionState
    call.argtypes = [ctypes.c_uint]
    call.restype = ctypes.c_uint
    if not call(0x80000001):
        raise ctypes.WinError()
    try:
        yield
    finally:
        call(0x80000000)


def run(root: Path, resume: bool, max_new: int | None = None) -> None:
    plan = load(root / "plan.json")
    validate_identity(root, plan)
    verification = load(root / "verification.json")
    if not verification["passed"] or verification["plan_sha256"] != sha(root / "plan.json"):
        raise ValueError("Engine verification has not passed")
    if (records(root) or list((root / "games").glob("*.partial.json"))) and not resume:
        raise ValueError("Existing games; use --resume")
    with run_lock(root), stay_awake():
        todo = list(plan["schedule"])
        index, new = 0, 0
        while index < len(todo):
            game = todo[index]
            validate_identity(root, plan)
            existing = (root / "games" / (game["id"] + ".json")).exists()
            print(json.dumps({"starting": game, "already_complete": existing}), flush=True)
            record = play_game(root, plan, game)
            progress = publish_progress(root, plan)
            print(json.dumps({"completed": game["id"], "result": record["result"], "termination": record["termination"],
                "count": progress["completed_games"], "eta_seconds": progress["estimated_remaining_seconds"],
                "standings": [{"model": r["model"], "score": r["equal_format_score"],
                               "points": r["round_robin"]["points"], "games": r["round_robin"]["games"]}
                              for r in progress["standings"]]}), flush=True)
            index += 1
            new += not existing
            if max_new and new >= max_new:
                return
            if index == 126:
                selection = root / "finalists.json"
                finalists = select_finalists(records(root))
                final = [{"id": f"G{127+i:03}", "ms": 5000, "opening": i // 2, "pair": finalists,
                          "white": finalists[i % 2], "black": finalists[1 - i % 2], "stage": "final"} for i in range(4)]
                frozen = {"plan_sha256": sha(root / "plan.json"), "finalists": finalists, "schedule": final,
                          "standings_at_selection": standings(records(root))}
                if selection.exists() and load(selection) != frozen:
                    raise ValueError("Finalist selection differs from saved round-robin evidence")
                save(selection, frozen)
                todo.extend(final)
        publish_progress(root, plan)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify", "run", "progress"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-new-games", type=int)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.action == "prepare":
        prepare(root)
    elif args.action == "verify":
        from tools.verify_nnue_showdown import verify
        verify(root)
    elif args.action == "progress":
        print(json.dumps(publish_progress(root, load(root / "plan.json")), indent=2))
    else:
        run(root, args.resume, args.max_new_games)


if __name__ == "__main__":
    main()
