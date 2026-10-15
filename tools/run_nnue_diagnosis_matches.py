"""Freeze and execute the amended 190-game diagnosis, serially and resumably."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import subprocess
import sys

import chess

from tools.match_optimizations import write_record
from tools.verify_match_records import verify_record

ROOT = Path(os.environ.get("STOCKBEAR_DIAGNOSIS_ROOT", "docs/nnue-v2-diagnosis"))
PLAN = ROOT / "match-plan.json"
ENGINE = Path(os.environ.get("STOCKBEAR_DIAGNOSIS_ENGINE", "artifacts/nnue-v2/final-compact/engine.exe"))
MODEL = Path("engine/networks/v2/stockbear-v2-compact.sbnnue")
MODEL_SHA = "788b865a15dbdeeb3e03b7493f8155fd19d6c73b9b0873453ad16fba51a65aa7"
SEED = 20261017
FAMILIES = (
    ("Ruy Lopez", "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6"),
    ("Queen's Gambit Declined", "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7"),
    ("Sicilian Najdorf", "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6"),
    ("King's Indian", "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6"),
    ("French", "e4 e6 d4 d5 Nc3 Nf6 Bg5 Be7"),
    ("English", "c4 e5 Nc3 Nf6 g3 d5 cxd5 Nxd5"),
    ("Caro-Kann", "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5"),
    ("Slav", "d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4"),
    ("Italian", "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6"),
    ("Nimzo-Indian", "d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O"),
    ("Scotch", "e4 e5 Nf3 Nc6 d4 exd4 Nxd4 Bc5"),
    ("Queen's Indian", "d4 Nf6 c4 e6 Nf3 b6 g3 Bb7"),
    ("Pirc", "e4 d6 d4 Nf6 Nc3 g6 Nf3 Bg7"),
    ("Catalan", "d4 Nf6 c4 e6 g3 d5 Bg2 Be7"),
    ("Scandinavian", "e4 d5 exd5 Qxd5 Nc3 Qa5 d4 Nf6"),
    ("Dutch", "d4 f5 g3 Nf6 Bg2 e6 Nf3 Be7"),
    ("Four Knights", "e4 e5 Nf3 Nc6 Nc3 Nf6 Bb5 Bb4"),
    ("Grunfeld", "d4 Nf6 c4 g6 Nc3 d5 cxd5 Nxd5"),
    ("Sicilian Closed", "e4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7"),
    ("Reti", "Nf3 d5 g3 Nf6 Bg2 e6 O-O Be7"),
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def create_plan() -> dict:
    if PLAN.exists():
        plan = json.loads(PLAN.read_text(encoding="utf-8"))
        assert digest(Path(plan["opening_book"])) == plan["opening_book_sha256"]
        assert digest(ENGINE) == plan["engine_sha256"] and digest(MODEL) == MODEL_SHA
        return plan
    assert digest(MODEL) == MODEL_SHA
    ROOT.mkdir(parents=True, exist_ok=True)
    rng, openings, seen = random.Random(SEED), [], set()
    for variant in range(2):
        for family, line in FAMILIES:
            while True:
                board = chess.Board()
                for san in line.split():
                    board.push_san(san)
                for _ in range(2 + 2 * variant):
                    moves = sorted((m for m in board.legal_moves if not board.is_capture(m) and not board.gives_check(m)), key=lambda m: m.uci())
                    if not moves:
                        break
                    board.push(rng.choice(moves))
                if board.fen() not in seen and not board.is_game_over(claim_draw=True):
                    break
            assert board.is_valid()
            seen.add(board.fen())
            openings.append({"family": family, "variant": variant, "fen": board.fen(),
                             "moves": [m.uci() for m in board.move_stack]})
    book = ROOT / "openings.json"
    write_record(book, json.dumps({"seed": SEED, "method": "Twenty named opening families, two seeded quiet continuations each, sorted legal move choices. No evaluator queried or evaluation/outcome filter. Frozen before games; nested prefixes; reversed colors.", "openings": openings}, indent=2) + "\n")
    for evaluator in ("nnue", "classical"):
        write_record(ROOT / f"{evaluator}-options.json", json.dumps({"Evaluator": evaluator, "Hash": 16, "NNUEKernel": "scalar", "NNUEIncremental": True}, indent=2) + "\n")
    schedule = [{"name": f"{ms}ms", "games": games, "movetime": ms, "max_plies": 240,
                 "seed": SEED, "output": str(ROOT / f"{ms}ms.json"), "exploratory": ms >= 500}
                for ms, games in ((50, 80), (200, 60), (500, 30), (1000, 20))]
    plan = {"source_baseline": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
            "engine": str(ENGINE), "engine_sha256": digest(ENGINE), "model": str(MODEL), "model_sha256": MODEL_SHA,
            "opening_book": str(book), "opening_book_sha256": digest(book),
            "method": "Fixed amended schedule, no extensions or outcome-based stopping; serial single search threads, identical defaults except Evaluator, fresh game/search state, claimable draws, unfinished caps excluded. Pilot is first two scheduled 50ms games. Trend uses first ten pairs at all controls. Family-related openings limit generalization.",
            "schedule": schedule, "planned_games": 190, "trend_pairs": list(range(1, 11))}
    write_record(PLAN, json.dumps(plan, indent=2) + "\n")
    return plan


def command(plan: dict, match: dict) -> list[str]:
    args = [sys.executable, "-m", "tools.match_optimizations", "--comparison", "versions",
            "--engine", plan["engine"], "--opponent", plan["engine"],
            "--opening-book", plan["opening_book"], "--candidate-options", str(ROOT / "nnue-options.json"),
            "--opponent-options", str(ROOT / "classical-options.json")]
    for key in ("games", "movetime", "max_plies", "seed", "output"):
        args += ["--" + key.replace("_", "-"), str(match[key])]
    if Path(match["output"]).with_suffix(".progress.json").exists():
        args.append("--resume")
    return args


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--pilot-only", action="store_true")
    args = parser.parse_args()
    plan = create_plan()
    if args.prepare_only:
        print(json.dumps(plan, indent=2))
        return
    for match in plan["schedule"]:
        path = Path(match["output"])
        if path.exists():
            verify_record(path, check_binaries=True)
            continue
        cmd = command(plan, match)
        if args.pilot_only:
            assert match["movetime"] == 50 and not path.with_suffix(".progress.json").exists()
            cmd += ["--max-new-games", "2"]
        log = Path(os.environ.get("STOCKBEAR_DIAGNOSIS_ARTIFACTS", "artifacts/nnue-v2-diagnosis")) / f"{match['name']}.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        print("Starting", match["name"], flush=True)
        with log.open("a", encoding="utf-8") as stream:
            subprocess.run(cmd, stdout=stream, stderr=subprocess.STDOUT, check=True)
        if args.pilot_only:
            data = json.loads(path.with_suffix(".progress.json").read_text(encoding="utf-8"))
            games = data["games"]
            searches = [s for g in games for s in g["searches"]]
            plies = len(searches) / len(games)
            overhead = sum(s["wall_seconds"] - s["seconds"] for s in searches) / len(searches)
            estimate = sum(m["games"] * plies * (m["movetime"] / 1000 + overhead) for m in plan["schedule"])
            pilot = {"scheduled_games_used": len(games), "mean_searched_plies": plies,
                     "actual_seconds": sum(g["wall_seconds"] for g in games),
                     "mean_observed_move_overhead_seconds": overhead,
                     "estimated_full_schedule_seconds": estimate,
                     "nominal_all_games_cap_seconds": sum(m["games"] * m["max_plies"] * m["movetime"] / 1000 for m in plan["schedule"]),
                     "limitations": "Two-game runtime estimate, not a result-based schedule decision. Game lengths and overhead can differ by control. Fixed 190 games; no extension."}
            write_record(ROOT / "pilot.json", json.dumps(pilot, indent=2) + "\n")
            print(json.dumps(pilot, indent=2), flush=True)
            return
        print("Completed", match["name"], verify_record(path, check_binaries=True), flush=True)


if __name__ == "__main__":
    main()
