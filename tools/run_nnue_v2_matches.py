"""Execute the fixed, resumable v2 match schedule serially, after regressions."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess
import sys

import chess
from tools.match_optimizations import OPENINGS
from tools.verify_match_records import verify_record

ROOT = Path("docs/nnue-v2")
PLAN = ROOT / "match-plan.json"


def create_plan() -> dict:
    if PLAN.exists():
        return json.loads(PLAN.read_text())
    rng, book, seen = random.Random(20261016), [], set()
    while len(book) < 50:
        board = chess.Board()
        for uci in OPENINGS[len(book) % len(OPENINGS)]:
            board.push_uci(uci)
        for _ in range(rng.choice((4, 6, 8))):
            quiet = [m for m in board.legal_moves if not board.is_capture(m) and not board.gives_check(m)]
            if not quiet:
                break
            board.push(rng.choice(quiet))
        if board.fen() in seen or board.is_game_over(claim_draw=True):
            continue
        seen.add(board.fen())
        book.append({"moves": [m.uci() for m in board.move_stack], "fen": board.fen(), "parent_opening": len(book) % len(OPENINGS)})
    opening_path = ROOT / "openings.json"
    opening_path.write_text(json.dumps({"seed": 20261016,
        "method": "Frozen evaluator-independent seeded quiet continuations of four opening families; no evaluation filter; identical paired openings/reversed colors in every comparison. Limited opening diversity, no universal Elo claim.",
        "openings": book}, indent=2) + "\n")
    preset = ROOT / "float-options.json"
    preset.write_text(json.dumps({"Evaluator": "nnue", "NNUEIncremental": True, "NNUEKernel": "scalar"}, indent=2) + "\n")
    classical = ROOT / "classical-options.json"
    classical.write_text(json.dumps({"Evaluator": "classical"}, indent=2) + "\n")
    compact = "artifacts/nnue-v2/final-compact/engine.exe"
    small = "artifacts/nnue-v2/final-small/engine.exe"
    pairs = (("compact-classical", compact, compact, str(preset), str(classical)),
             ("small-classical", small, small, str(preset), str(classical)),
             ("compact-small", compact, small, str(preset), str(preset)))
    schedule = []
    for stage, games, ms in (("smoke", 2, 25), ("primary", 100, 50), ("long", 20, 200)):
        for name, candidate, opponent, candidate_options, opponent_options in pairs:
            schedule.append({"name": f"{stage}-{name}", "engine": candidate, "opponent": opponent,
                "candidate_options": candidate_options, "opponent_options": opponent_options,
                "games": games, "movetime": ms, "max_plies": 240, "seed": 20261016,
                "output": str(ROOT / f"{stage}-{name}.json")})
    data = {"method": "Fixed before the first game; no optional stopping or kernel selection on game outcomes. All matches serial. Smoke is validation only; primary and longer controls reported separately.",
            "opening_book": str(opening_path), "opening_book_sha256": hashlib.sha256(opening_path.read_bytes()).hexdigest(),
            "schedule": schedule, "planned_games": sum(s["games"] for s in schedule)}
    PLAN.write_text(json.dumps(data, indent=2) + "\n")
    return data


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    args = parser.parse_args()
    plan = create_plan()
    if args.prepare_only:
        print("Prepared", plan["planned_games"], "games")
        return
    for match in plan["schedule"]:
        output = Path(match["output"])
        if output.exists():
            verify_record(output, check_binaries=True)
            continue
        command = [sys.executable, "-m", "tools.match_optimizations", "--comparison", "versions",
                   "--opening-book", plan["opening_book"]]
        for name, value in match.items():
            if name != "name":
                command += ["--" + name.replace("_", "-"), str(value)]
        if output.with_suffix(".progress.json").exists():
            command.append("--resume")
        log = Path("artifacts/nnue-v2/match-logs") / (match["name"] + ".log")
        log.parent.mkdir(parents=True, exist_ok=True)
        print("Starting", match["name"], flush=True)
        with log.open("a", encoding="utf-8") as stream:
            subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, check=True)
        verify_record(output, check_binaries=True)
        result = json.loads(output.read_text())["summary"]
        print("Completed", match["name"], result, flush=True)


if __name__ == "__main__":
    main()
