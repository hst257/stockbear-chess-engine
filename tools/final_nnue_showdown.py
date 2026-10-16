"""Frozen 48-game classical versus expanded-data NNUE comparison."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime
import json
import os
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import time

import chess
import chess.engine
import chess.pgn

from tools import nnue_showdown as core

ROOT = core.REPO / "final-nnue-showdown-20261017"
PREVIOUS = core.DEFAULT_ROOT
SEED = 20261017
LABELS = ("classical", "64", "128")
DEPENDENCIES = ("tools/final_nnue_showdown.py", "tools/nnue_showdown.py",
                "tools/match_optimizations.py", "StockBear_NNUE_training/stockbear/labeling/storage.py")
LINES = (
    ("Petroff", "e4 e5 Nf3 Nf6 Nxe5 d6 Nf3 Nxe4 d4 d5 Bd3 Be7 O-O Nc6"),
    ("Scandinavian", "e4 d5 exd5 Qxd5 Nc3 Qa5 d4 c6 Nf3 Nf6 Bc4 Bf5"),
    ("Pirc", "e4 d6 d4 Nf6 Nc3 g6 Be3 Bg7 Qd2 c6 f3 b5"),
    ("Reti", "Nf3 d5 g3 Nf6 Bg2 e6 O-O Be7 c4 O-O b3 c5"),
    ("Sicilian Alapin", "e4 c5 c3 Nf6 e5 Nd5 d4 cxd4 Nf3 Nc6 cxd4 d6"),
    ("French Advance", "e4 e6 d4 d5 e5 c5 c3 Nc6 Nf3 Qb6 a3 Bd7"),
    ("Caro-Kann Advance", "e4 c6 d4 d5 e5 Bf5 Nf3 e6 Be2 c5 O-O Nc6"),
    ("Queen's Gambit Accepted", "d4 d5 c4 dxc4 Nf3 Nf6 e3 e6 Bxc4 c5 O-O a6"),
    ("Grunfeld Exchange", "d4 Nf6 c4 g6 Nc3 d5 cxd5 Nxd5 e4 Nxc3 bxc3 Bg7"),
    ("Bogo-Indian", "d4 Nf6 c4 e6 Nf3 Bb4+ Bd2 Bxd2+ Qxd2 d5 Nc3 O-O"),
    ("Queen's Indian", "d4 Nf6 c4 e6 Nf3 b6 g3 Bb7 Bg2 Be7 O-O O-O"),
    ("London", "d4 d5 Nf3 Nf6 Bf4 e6 e3 Bd6 Bg3 O-O Bd3 c5"),
)


def openings() -> list[dict]:
    lines = list(LINES)
    random.Random(SEED).shuffle(lines)
    result = []
    previous = {o["fen"] for o in core.load(PREVIOUS / "plan.json")["openings"]}
    for name, san in lines:
        board = chess.Board()
        for move in san.split():
            board.push_san(move)
        if not board.is_valid() or board.is_game_over(claim_draw=True) or board.is_check() or board.fen() in previous:
            raise ValueError(f"Invalid or previously used opening: {name}")
        result.append({"id": f"F{len(result)+1:02}", "family": name, "san": san,
                       "fen": board.fen(), "moves": [m.uci() for m in board.move_stack]})
    assert len({o["fen"] for o in result}) == 12
    return result


def schedule() -> list[dict]:
    result = []
    for candidate in ("64", "128"):
        for opening in range(12):
            for reverse in range(2):
                white, black = ("classical", candidate) if (opening + reverse) % 2 == 0 else (candidate, "classical")
                result.append({"id": f"G{len(result)+1:03}", "ms": 1000, "opening": opening,
                               "pair": ["classical", candidate], "white": white, "black": black,
                               "stage": f"classical_vs_{candidate}"})
    return result


def prepare(root: Path) -> dict:
    if (root / "plan.json").exists():
        plan = core.load(root / "plan.json")
        validate(root, plan)
        return plan
    previous = core.load(PREVIOUS / "plan.json")
    core.validate_identity(PREVIOUS, previous)
    protected = core.load(PREVIOUS / "preservation-before.json")
    for path in PREVIOUS.rglob("*"):
        if path.is_file() and "artifacts" not in path.relative_to(PREVIOUS).parts:
            protected[path.relative_to(core.REPO).as_posix()] = core.sha(path)
    for entry in previous["engines"].values():
        protected[Path(entry["path"]).relative_to(core.REPO).as_posix()] = entry["sha256"]
    for name in ("NNUE_SCALING_EXPERIMENT_REPORT.md", "NNUE_SHOWDOWN_REPORT.md"):
        protected[name] = core.sha(core.REPO / name)
    core.save(root / "preservation-before.json", protected)
    engines = {}
    for label in LABELS:
        source = previous["engines"]["64" if label == "classical" else label]
        binary = root / "artifacts/engines" / label / f"StockBear-{label}.exe"
        if binary.exists():
            raise ValueError("Unregistered isolated executable; preserve it and investigate")
        binary.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source["path"], binary)
        entry = dict(source, path=str(binary), source_path=source["path"],
                     evaluator="classical" if label == "classical" else "nnue",
                     name="StockBear-Classical" if label == "classical" else f"StockBear-NNUE-{label}")
        engines[label] = entry
    options = dict(previous["options"])
    options.pop("Evaluator")
    plan = {"schema": 1, "created_utc": core.utc(), "seed": SEED,
            "engines": engines, "options": options, "openings": openings(), "schedule": schedule(),
            "planned_games": 48, "allowance_seconds": .100, "max_searched_plies": 400,
            "threads": 1, "ponder": False, "runner_sha256": core.sha(Path(core.__file__)),
            "dependencies": {n: core.sha(core.REPO / n) for n in DEPENDENCIES},
            "previous_plan_sha256": core.sha(PREVIOUS / "plan.json"),
            "rules": {"order": "24 classical-64 games, then 24 classical-128 games; no extension",
                      "draws": previous["rules"]["draws"], "cap": previous["rules"]["cap"],
                      "failure": previous["rules"]["failure"], "clocks": previous["rules"]["clocks"],
                      "openings": "12 fresh hand-selected established lines, fixed seed, no evaluator/Stockfish filter; distinct from previous starting FENs, not independent random samples from all chess openings",
                      "classical": "Identical copy of verified 64/32 executable, explicitly Evaluator=classical; embedded network unused, NNUE evaluation counter must remain zero; original advanced/PST/mop-up/pawn-cache behavior preserved"}}
    core.save(root / "plan.json", plan)
    validate(root, plan)
    return plan


def validate(root: Path, plan: dict) -> None:
    for name, expected in plan["dependencies"].items():
        if core.sha(core.REPO / name) != expected:
            raise ValueError(f"Frozen runner dependency changed: {name}")
    provenance = dict(plan, engines={})
    for label, entry in plan["engines"].items():
        if core.sha(Path(entry["path"])) != entry["sha256"]:
            raise ValueError(f"Isolated executable changed: {label}")
        provenance["engines"][label] = dict(entry, path=entry["source_path"])
    core.validate_identity(root, provenance)
    if plan["schedule"] != schedule() or plan["planned_games"] != 48:
        raise ValueError("Not the frozen 48-game schedule")
    expected = {g["id"]: g for g in plan["schedule"]}
    for path in (root / "games").glob("*.json"):
        record = core.load(path)
        if record["plan_sha256"] != core.sha(root / "plan.json") or record["game"] != expected.get(path.name.split(".")[0]):
            raise ValueError(f"Game/checkpoint identity mismatch: {path.name}")


def evaluation_probe(player, board: chess.Board) -> dict:
    class Probe(chess.engine.BaseCommand):
        def __init__(self, engine):
            super().__init__(engine)
            self.engine = engine

        def start(self):
            self.value = None
            self.engine.send_line("position fen " + board.fen())
            self.engine.send_line("eval")
            self.engine.send_line("isready")

        def line_received(self, line):
            if line.startswith("info string eval "):
                self.value = json.loads(line[len("info string eval "):])
            if line == "readyok":
                self.result.set_result(self.value)
                self.set_finished()
    return player.communicate(Probe)


def validate_counters(counters: dict, evaluator: str) -> None:
    if "eval_calls" not in counters or "nnue_evaluations" not in counters:
        raise ValueError("Missing evaluator counters")
    expected = 0 if evaluator == "classical" else counters["eval_calls"]
    if counters["nnue_evaluations"] != expected:
        raise ValueError("Wrong evaluator in search; refuse to score game")


class VerifiedEngine(chess.engine.SimpleEngine):
    evaluator: str

    def play(self, *args, **kwargs):
        result = super().play(*args, **kwargs)
        validate_counters(self.protocol.counters, self.evaluator)
        return result


def open_engine(entry: dict, options: dict):
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    player = VerifiedEngine.popen(core.CapturingProtocol, entry["path"], timeout=10, **flags)
    try:
        player.evaluator = entry["evaluator"]
        player.configure(dict(options, Evaluator=entry["evaluator"]))
        player.ping()
        actual = core.identity(player)
        if entry["evaluator"] == "classical":
            if not actual or "components" not in actual or actual.get("advanced") is not True or "sha256" in actual or "evaluator" in actual:
                raise ValueError("Classical evaluation probe is not the original handcrafted evaluator")
        elif not actual or actual.get("evaluator") != "nnue" or any(actual.get(k) != entry[v] for k, v in
                (("sha256", "network_sha256"), ("width", "width"), ("hidden", "hidden"))) or actual.get("kernel") != "scalar":
            raise ValueError("NNUE identity/dimensions/kernel mismatch")
        return player
    except BaseException:
        player.close()
        raise


def export_pgn(root: Path, plan: dict, game: dict, record: dict) -> None:
    pgn = chess.pgn.Game.from_board(core.board_for(plan, game, record))
    pgn.headers.update({"Event": "StockBear Final Classical vs NNUE", "Site": "Local isolated engines",
                        "Date": record["started_utc"][:10].replace("-", "."), "Round": game["id"],
                        "White": plan["engines"][game["white"]]["name"], "Black": plan["engines"][game["black"]]["name"],
                        "Result": record["result"], "Termination": record["termination"], "TimeControl": "?", "ThinkTimeMs": "1000",
                        "Opening": plan["openings"][game["opening"]]["family"],
                        "OpeningId": plan["openings"][game["opening"]]["id"], "OpeningFEN": plan["openings"][game["opening"]]["fen"],
                        "PlanSHA256": record["plan_sha256"], "HashMB": "16", "Threads": "1", "Ponder": "false"})
    for color, label in (("White", game["white"]), ("Black", game["black"])):
        entry = plan["engines"][label]
        pgn.headers[color + "EngineSHA256"] = entry["sha256"]
        pgn.headers[color + "Evaluator"] = entry["evaluator"]
        pgn.headers[color + "NetworkSHA256"] = entry["network_sha256"] if entry["evaluator"] == "nnue" else "disabled"
    core.write_record(root / "games" / (game["id"] + ".pgn"), str(pgn) + "\n")


@contextmanager
def game_adapters():
    original = core.open_engine, core.export_pgn
    core.open_engine, core.export_pgn = open_engine, export_pgn
    try:
        yield
    finally:
        core.open_engine, core.export_pgn = original


def progress(root: Path, plan: dict | None = None) -> dict:
    plan = plan or core.load(root / "plan.json")
    rows = core.records(root)
    searches = [s for r in rows for s in r["searches"]]
    mean_moves = statistics.mean(len(r["searches"]) for r in rows) if rows else None
    mean_wall = statistics.mean(s["wall_seconds"] for s in searches) if searches else None
    completed = {r["game"]["id"] for r in rows}
    remaining = [g for g in plan["schedule"] if g["id"] not in completed]
    matches = {candidate: {label: core.stats([r for r in rows if candidate in r["game"]["pair"]], label)
                           for label in ("classical", candidate)} for candidate in ("64", "128")}
    elapsed = (datetime.fromisoformat(core.utc()) - min(datetime.fromisoformat(r["started_utc"]) for r in rows)).total_seconds() if rows else 0
    result = {"updated_utc": core.utc(), "plan_sha256": core.sha(root / "plan.json"), "planned_games": 48,
              "completed_games": len(rows), "remaining_games": len(remaining), "elapsed_wall_seconds": elapsed,
              "searched_seconds": sum(r["seconds"] for r in rows), "matches": matches,
              "estimated_remaining_seconds": len(remaining) * mean_moves * mean_wall if rows and searches else None,
              "failures": len(list((root / "failures").glob("*.json"))),
              "eta_note": "Observed game lengths times measured mean wall thinking time; same 1-second limit throughout; no automatic extension"}
    core.save(root / "scoreboard.json", result)
    if not remaining:
        core.save(root / "current.json", {"complete": True, "completed_games": 48, "updated_utc": core.utc()})
    return result


def run(root: Path, resume: bool, max_new: int | None = None) -> None:
    plan = core.load(root / "plan.json")
    validate(root, plan)
    verified = core.load(root / "verification.json")
    if not verified["passed"] or verified["plan_sha256"] != core.sha(root / "plan.json"):
        raise ValueError("Verification not passed for this plan")
    if list((root / "games").glob("*.json")) and not resume:
        raise ValueError("Existing results/checkpoints; use --resume")
    if max_new is not None and max_new < 1:
        raise ValueError("--max-new-games must be positive")
    with core.run_lock(root), core.stay_awake(), game_adapters():
        new = 0
        for game in plan["schedule"]:
            validate(root, plan)
            existing = (root / "games" / (game["id"] + ".json")).exists()
            print(json.dumps({"starting": game, "already_complete": existing}), flush=True)
            record = core.play_game(root, plan, game)
            state = progress(root, plan)
            print(json.dumps({"completed": game["id"], "result": record["result"], "termination": record["termination"],
                              "count": state["completed_games"], "eta_seconds": state["estimated_remaining_seconds"],
                              "nnue_points": {c: m[c]["points"] for c, m in state["matches"].items()}}), flush=True)
            new += not existing
            if max_new and new >= max_new:
                return


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "verify", "run", "progress"))
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--max-new-games", type=int)
    args = parser.parse_args()
    root = args.root.resolve()
    if args.action == "prepare":
        prepare(root)
    elif args.action == "verify":
        from tools.verify_final_nnue_showdown import verify
        verify(root)
    elif args.action == "run":
        run(root, args.resume, args.max_new_games)
    else:
        print(json.dumps(progress(root), indent=2))


if __name__ == "__main__":
    main()
