"""Preflight isolated engines, openings, clocks and existing regressions."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

import chess
import chess.engine

from tools.nnue_showdown import REPO, SCALING, load, save, sha, validate_identity, open_engine, utc


def verify(root: Path) -> dict:
    plan = load(root / "plan.json")
    validate_identity(root, plan)
    results = {}
    for label, entry in plan["engines"].items():
        binary = entry["path"]
        checks = []
        with open_engine(entry, plan["options"]) as player:
            defaults = {name: option.default for name, option in player.options.items()}
            # No Threads or Ponder UCI option: the source has one search worker.
            for fen in ("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"):
                result = player.play(chess.Board(fen), chess.engine.Limit(time=.1), game=object(), info=chess.engine.INFO_ALL)
                if result.move:
                    raise AssertionError("Terminal position emitted a move")
                checks.append({"terminal": fen, "no_move": True})
            for ms in (500, 1000, 3000, 5000):
                board = chess.Board()
                for move in plan["openings"][0]["moves"]:
                    board.push_uci(move)
                player.timeout = plan["allowance_seconds"]
                started = time.perf_counter()
                result = player.play(board, chess.engine.Limit(time=ms / 1000), game=object(), info=chess.engine.INFO_ALL)
                wall = time.perf_counter() - started
                if result.move not in board.legal_moves or wall > ms / 1000 + plan["allowance_seconds"]:
                    raise AssertionError("Timed search legality/deadline failure")
                if result.info["depth"] < 1 or player.protocol.counters.get("nnue_evaluations", 0) < 1:
                    raise AssertionError("Missing completed depth/NNUE counter")
                checks.append({"ms": ms, "wall_seconds": wall, "depth": result.info["depth"],
                               "nodes": result.info["nodes"], "counters": dict(player.protocol.counters)})
            player.timeout = 10
        fixtures = [chess.STARTING_FEN, "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1",
                    "7k/4P3/8/8/8/8/8/K7 w - - 0 1"]
        for fen in fixtures:
            board = chess.Board(fen)
            legal = set(subprocess.check_output([binary, "--legal-moves", fen], text=True).split())
            if legal != {m.uci() for m in board.legal_moves}:
                raise AssertionError("Native special-move rules differ from python-chess")
            value = json.loads(subprocess.check_output([binary, "--eval", "--nnue", "--kernel", "scalar", fen], text=True))
            if value["sha256"] != entry["network_sha256"] or value["kernel"] != "scalar":
                raise AssertionError("CLI embedded model identity mismatch")
        environment = os.environ.copy()
        environment["CHESSLAB_TEST_ENGINE"] = binary
        command = [str(REPO / ".venv/Scripts/python.exe"), "-m", "pytest", "-q",
                   "tests/test_engine.py", "tests/test_time_control.py", "tests/test_nnue.py",
                   "-k", "starting_position_perft or castling_position_perft or special_legal_moves or legal_moves_across_seeded or position_move_stack_preserves_threefold or timed_search_retains_last_completed or timed_terminal_positions or timed_forced_mate or incremental_search_agrees or nnue_preserves_terminal_precedence",
                   "--basetemp", str(root / "artifacts" / f"pytest-{label}")]
        tested = subprocess.run(command, cwd=REPO, env=environment, capture_output=True, text=True)
        (root / "artifacts" / f"regression-{label}.log").write_text(tested.stdout + tested.stderr, encoding="utf-8")
        if tested.returncode:
            raise RuntimeError(f"Relevant regression failure for {label}: {tested.stdout[-2000:]}")
        results[label] = {"checks": checks, "defaults": defaults, "regressions": tested.stdout.strip(),
                          "binary_sha256": sha(Path(binary)), "network_sha256": entry["network_sha256"]}
        save(root / "verification.partial.json", results)
        print(json.dumps({"verified": label, "regressions": tested.stdout.strip()}), flush=True)
    # Validate the full frozen plan and both color assignments for every pair.
    for ms, games in ((500, 72), (1000, 36), (3000, 18)):
        cohort = [g for g in plan["schedule"] if g["ms"] == ms]
        assert len(cohort) == games
        for i in range(0, len(cohort), 2):
            a, b = cohort[i:i+2]
            assert a["opening"] == b["opening"] and a["white"] == b["black"] and a["black"] == b["white"]
    if any(r["defaults"] != results["32"]["defaults"] for r in results.values()):
        raise ValueError("UCI defaults differ between tournament builds")
    frozen = {"passed": True, "utc": utc(), "plan_sha256": sha(root / "plan.json"), "models": results,
              "single_search_thread": "One std::thread worker in unchanged UCI implementation; Threads/Ponder options absent; ponder=False",
              "test_dataset_opened": False, "training_or_stockfish_started": False}
    save(root / "verification.json", frozen)
    return frozen
