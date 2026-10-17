"""Bounded serial profiling of frozen 64/32; never optimizes production code."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import statistics
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent
sys.path.insert(0, str(REPO))
import chess
import chess.engine
from tools import nnue_showdown as common
from tools.nnue_diagnosis import capture, open_engine, positions
from tools.profile_nnue_diagnosis import canonical
from tools.benchmark_nnue_v2 import POSITIONS

ART = ROOT / "artifacts"
MODEL = REPO / "StockBear_NNUE_training/scaling-experiment-20261016/artifacts/native/medium/medium.sbnnue"
PYTHON = REPO / ".venv/Scripts/python.exe"


def save(name: str, value) -> None:
    common.save(ROOT / name, value)


def pin(mask: int = 1) -> None:
    api = ctypes.windll.kernel32
    api.GetCurrentProcess.restype = ctypes.c_void_p
    api.SetProcessAffinityMask.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
    if not api.SetProcessAffinityMask(api.GetCurrentProcess(), mask):
        raise ctypes.WinError()


def command(args: list[str], log: Path) -> None:
    log.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["ZIG_GLOBAL_CACHE_DIR"] = str(ART / "zig-cache")
    result = subprocess.run(args, cwd=REPO, env=env, capture_output=True, text=True)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode:
        raise RuntimeError(f"Command failed; see {log}")


def prepare() -> None:
    if (ROOT / "config.json").exists():
        raise ValueError("Prepared workspace exists; do not overwrite a frozen experiment")
    ART.mkdir(parents=True, exist_ok=True)
    old = REPO / "final-nnue-showdown-20261017"
    protected = common.load(old / "preservation-before.json")
    for path in old.rglob("*"):
        if path.is_file() and "artifacts" not in path.relative_to(old).parts:
            protected[path.relative_to(REPO).as_posix()] = common.sha(path)
    for path in (REPO / "engine/src").glob("*"):
        if path.is_file():
            protected[path.relative_to(REPO).as_posix()] = common.sha(path)
    for path in (REPO / "engine/tests").glob("*"):
        if path.is_file():
            protected[path.relative_to(REPO).as_posix()] = common.sha(path)
    protected["FINAL_NNUE_SHOWDOWN_REPORT.md"] = common.sha(REPO / "FINAL_NNUE_SHOWDOWN_REPORT.md")
    selected = REPO / "StockBear_NNUE_training/scaling-experiment-20261016/artifacts/medium/best.pt"
    protected[selected.relative_to(REPO).as_posix()] = common.sha(selected)
    save("preservation-before.json", protected)
    prior = common.load(old / "plan.json")
    source = prior["engines"]["64"]
    assert common.sha(MODEL) == source["network_sha256"]
    release = ART / "release/engine.exe"
    release.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source["path"], release)
    save("build-release.json", source["build"])
    suite = [{"id": k, "category": k, "fen": v} for k, v in POSITIONS.items() if k != "king_attack"]
    extra = {r["id"]: r for r in positions()}
    suite += [extra["pins"], extra["attack_complex"]]
    opening = prior["openings"][1]
    suite.append({"id": "opening_history", "category": "opening", "fen": opening["fen"], "moves": opening["moves"]})
    for row in suite:
        board = chess.Board(row["fen"])
        assert board.is_valid() and not board.is_game_over(claim_draw=True)
    save("positions.json", suite)
    snapshot = ART / "source"
    shutil.copytree(REPO / "engine/src", snapshot)
    save("config.json", {"network": str(MODEL), "network_sha256": source["network_sha256"],
                         "options": prior["options"], "production_build": source["build"], "seed": 20261017,
                         "nitrosense_profile_user_confirmed": "Quiet / Eco", "affinity_mask": 1,
                         "search_plan": {"depth": 5, "nodes": 200000, "time_ms": [100, 500, 1000], "repeats": 3},
                         "method": "Serial rotated evaluator/build order, same FEN/history/settings, fresh TT per go. Cold means fresh process, not flushed OS caches. No optimizations or integer model generation."})
    # Existing broad timers/counters require no production source modifications.
    for label, flags in (("counters", ["--diagnostics"]), ("timers", ["--diagnostics", "--profile"]), ("micro", [])):
        output = ART / label / "engine.exe"
        args = [str(PYTHON), str(REPO / "tools/build_engine.py"), "--target", "nnue-bench" if label == "micro" else "engine",
                "--nnue-model", str(MODEL), "--output", str(output), "--optimization", "O2", "--nnue-update", "compact", *flags]
        command(args, ART / label / "build.log")
        save(f"build-{label}.json", common.load(output.with_suffix(".build.json")))
        print("Built", label, flush=True)


def engine(label: str, evaluator: str):
    player = open_engine(ART / label / "engine.exe")
    options = common.load(ROOT / "config.json")["options"]
    player.configure(dict(options, Evaluator=evaluator))
    return player


def checked_capture(player, row: dict, mode: str, budget: int) -> dict:
    record = capture(player, row, mode, budget)
    record["evaluations_per_node"] = record["counters"]["eval_calls"] / max(1, record["nodes"])
    record["wall_nps"] = record["nodes"] / record["wall_seconds"]
    record["nodes_per_completed_depth"] = record["nodes"] / max(1, record["depth"])
    return record


def baseline() -> None:
    pin()
    rows = common.load(ROOT / "positions.json")
    path = ROOT / "baseline.json"
    data = common.load(path) if path.exists() else {"records": [], "cold": []}
    done = {(r["position"], r["mode"], r["budget"], r["evaluator"], r["repeat"]) for r in data["records"]}
    with ExitStack() as stack:
        players = {e: stack.enter_context(engine("release", e)) for e in ("classical", "nnue")}
        for e, player in players.items():
            checked_capture(player, rows[0], "time", 200)
        for repeat in range(3):
            for i, row in enumerate(rows):
                for mode, budget in (("depth", 5), ("nodes", 200000), ("time", 100), ("time", 500), ("time", 1000)):
                    for e in (("classical", "nnue") if (i + repeat) % 2 == 0 else ("nnue", "classical")):
                        key = row["id"], mode, budget, e, repeat
                        if key in done:
                            continue
                        result = checked_capture(players[e], row, mode, budget)
                        result.update(evaluator=e, repeat=repeat, warm=True)
                        data["records"].append(result)
                    save("baseline.json", data)
                print("Baseline", repeat, row["id"], flush=True)
    if not data["cold"]:
        for row in rows[::3]:
            for repeat in range(3):
                for e in ("classical", "nnue") if repeat % 2 == 0 else ("nnue", "classical"):
                    begin = time.perf_counter()
                    with engine("release", e) as player:
                        startup = time.perf_counter() - begin
                        result = checked_capture(player, row, "time", 100)
                    data["cold"].append(dict(result, evaluator=e, repeat=repeat, startup_seconds=startup))
            save("baseline.json", data)


def instrumented() -> None:
    pin()
    rows = common.load(ROOT / "positions.json")
    path = ROOT / "instrumented.json"
    data = common.load(path) if path.exists() else {"records": []}
    done = {(r["position"], r["build"], r["repeat"]) for r in data["records"]}
    labels = ("release", "counters", "timers")
    with ExitStack() as stack:
        players = {b: stack.enter_context(engine(b, "nnue")) for b in labels}
        for b, player in players.items():
            checked_capture(player, rows[0], "nodes", 20000)
        for repeat in range(3):
            for i, row in enumerate(rows):
                order = labels[(i+repeat) % 3:] + labels[:(i+repeat) % 3]
                for b in order:
                    if (row["id"], b, repeat) in done:
                        continue
                    result = checked_capture(players[b], row, "nodes", 200000)
                    result.update(build=b, repeat=repeat)
                    if b != "release":
                        d = result["diagnostics"]
                        assert d["visits"] == result["nodes"]
                        assert d["evaluation_calls"] == result["counters"]["nnue_evaluations"]
                        assert d["refreshes"] == 1 and d["unused_leaf_updates"] <= d["unused_updates"] <= d["updates"]
                    data["records"].append(result)
                selected = [r for r in data["records"] if r["position"] == row["id"] and r["repeat"] == repeat]
                assert all(canonical(r) == canonical(selected[0]) for r in selected)
                save("instrumented.json", data)
                print("Instrumentation", repeat, row["id"], flush=True)


def micro() -> None:
    pin()
    binary = ART / "micro/engine.exe"
    cpu = json.loads(subprocess.check_output([str(binary), "--cpu"], text=True))
    save("cpu-capabilities.json", cpu)
    checks = subprocess.check_output([str(binary), "--verify-throughput", "scalar"], text=True)
    save("transition-parity.json", json.loads(checks))
    rows = common.load(ROOT / "positions.json")
    data = {"records": []}
    for repeat in range(7):
        for row in rows:
            value = json.loads(subprocess.check_output([str(binary), row["fen"], "100000", "scalar"], text=True))
            data["records"].append(dict(value, position=row["id"], repeat=repeat))
        save("micro.json", data)
        print("Micro", repeat, flush=True)


def verify() -> None:
    protected = common.load(ROOT / "preservation-before.json")
    changed = [p for p, h in protected.items() if common.sha(REPO / p) != h]
    save("preservation-after.json", {"checked_files": len(protected), "changed": changed, "passed": not changed})
    assert not changed, changed


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "baseline", "instrumented", "micro", "verify"))
    args = parser.parse_args()
    globals()[args.action]()
