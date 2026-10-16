"""Verify evaluator isolation, reused builds, rules and clocks before games."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import time

import chess
import chess.engine

from tools import nnue_showdown as core
from tools.final_nnue_showdown import PREVIOUS, open_engine, evaluation_probe, validate


def verify(root: Path) -> dict:
    plan = core.load(root / "plan.json")
    validate(root, plan)
    prior = core.load(PREVIOUS / "verification.json")
    assert prior["passed"] and prior["plan_sha256"] == core.sha(PREVIOUS / "plan.json")
    probes = [chess.STARTING_FEN, plan["openings"][0]["fen"], plan["openings"][6]["fen"],
              "7k/8/8/8/8/2K5/3P4/8 w - - 0 1",
              "7k/8/8/8/8/2K5/3Q4/8 w - - 0 1"]
    active = core.REPO / "engine/build/chesslab-engine.exe"
    if not active.is_file():
        raise ValueError("Protected original engine missing; cannot verify original classical behavior")
    classical = {fen: json.loads(subprocess.check_output([str(active), "--eval", fen], text=True)) for fen in probes}
    results = {}
    defaults = None
    for label, entry in plan["engines"].items():
        original_label = "64" if label == "classical" else label
        assert prior["models"][original_label]["binary_sha256"] == entry["sha256"]
        for fen in probes:
            cli = json.loads(subprocess.check_output([entry["path"], "--eval", fen], text=True))
            if cli != classical[fen]:
                raise ValueError("Original classical evaluation differs across old/new network builds")
        with open_engine(entry, plan["options"]) as player:
            current_defaults = {name: option.default for name, option in player.options.items()}
            if defaults is not None and defaults != current_defaults:
                raise ValueError("UCI defaults differ")
            defaults = current_defaults
            values = []
            for fen in probes:
                board = chess.Board(fen)
                value = evaluation_probe(player, board)
                if label == "classical" and value != classical[fen]:
                    raise ValueError("UCI classical is not identical to original CLI evaluator")
                if label != "classical" and value.get("sha256") != entry["network_sha256"]:
                    raise ValueError("Wrong NNUE network in evaluation probe")
                values.append({"fen": fen, "evaluation": value})
            if label == "classical":
                # Verify switching through NNUE restores the original evaluator,
                # including after changing NNUE-only settings. Restore shared
                # tournament options before the timed search.
                player.configure({"Evaluator": "nnue", "NNUEIncremental": False})
                neural = evaluation_probe(player, chess.Board(probes[1]))
                assert neural["evaluator"] == "nnue"
                player.configure({"Evaluator": "classical", "NNUEKernel": "reference"})
                assert evaluation_probe(player, chess.Board(probes[1])) == classical[probes[1]]
                player.configure(dict(plan["options"], Evaluator="classical"))
            terminal_checks = []
            for fen in ("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1", "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1"):
                move = player.play(chess.Board(fen), chess.engine.Limit(time=.1), game=object(), info=chess.engine.INFO_ALL)
                assert not move.move
                terminal_checks.append({"fen": fen, "no_move": True})
            board = core.board_for(plan, plan["schedule"][0])
            player.timeout = .100
            started = time.perf_counter()
            move = player.play(board, chess.engine.Limit(time=1), game=object(), info=chess.engine.INFO_ALL)
            wall = time.perf_counter() - started
            assert move.move in board.legal_moves and wall <= 1.1 and move.info["depth"] >= 1
            assert player.protocol.counters["eval_calls"] > 0
            counters = dict(player.protocol.counters)
            timed = {"wall_seconds": wall, "depth": move.info["depth"], "nodes": move.info["nodes"], "counters": counters}
        fixtures = [chess.STARTING_FEN, "r3k2r/8/8/3pP3/8/8/8/R3K2R w KQkq d6 0 1",
                    "7k/4P3/8/8/8/8/8/K7 w - - 0 1"]
        for fen in fixtures:
            legal = subprocess.check_output([entry["path"], "--legal-moves", fen], text=True).split()
            assert set(legal) == {m.uci() for m in chess.Board(fen).legal_moves}
        results[label] = {"binary_sha256": entry["sha256"], "evaluator": entry["evaluator"],
                          "probes": values, "terminal_checks": terminal_checks, "timed": timed,
                          "reused_regression_receipt": prior["models"][original_label]["regressions"]}
        print(json.dumps({"verified": label, "wall_seconds": wall, "counters": counters}), flush=True)
        core.save(root / "verification.partial.json", results)
    environment = os.environ.copy()
    environment["CHESSLAB_TEST_ENGINE"] = plan["engines"]["classical"]["path"]
    command = [str(core.REPO / ".venv/Scripts/python.exe"), "-m", "pytest", "-q", "tests/test_nnue.py",
               "tests/test_advanced_evaluation.py", "tests/test_engine.py", "tests/test_time_control.py",
               "-k", "mode_switch_keeps_classical or nnue_ignores_classical or advanced_uci_default or components_reconcile or evaluation_mode_changes or advanced_full_window_pvs_and_cache or timed_search_retains_last_completed or position_move_stack_preserves_threefold or stop_and_quit_with_all_optimizations",
               "--basetemp", str(root / "artifacts/classical-regressions")]
    tested = subprocess.run(command, cwd=core.REPO, env=environment, capture_output=True, text=True)
    (root / "artifacts/classical-regressions.log").write_text(tested.stdout + tested.stderr, encoding="utf-8")
    if tested.returncode:
        raise RuntimeError("Classical/evaluator-switch regressions failed: " + tested.stdout[-2000:])
    receipt = {"passed": True, "utc": core.utc(), "plan_sha256": core.sha(root / "plan.json"),
               "models": results, "new_regressions": tested.stdout.strip(), "regression_command": command,
               "previous_verification_sha256": core.sha(PREVIOUS / "verification.json"),
               "original_classical_binary_sha256": core.sha(active), "test_dataset_opened": False,
               "search_threads": 1, "ponder": False,
               "classical_source_proof": {"engine/src/main.cpp": "Evaluator=classical sets use_nnue_=false and use_nnue_v3_=false; go copies these into SearchLimits",
                                          "engine/src/search.cpp": "No NNUE stack allocated when disabled; static_evaluation falls through to evaluate(...pawn_cache) with zero nnue_evaluations"}}
    core.save(root / "verification.json", receipt)
    print(json.dumps({"passed": True, "new_regressions": tested.stdout.strip()}), flush=True)
    return receipt
