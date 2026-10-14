"""Compare material/PST with advanced evaluation under identical search settings."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess

import chess.engine

from app.engine_client import DEFAULT_ENGINE
from tools.benchmark_optimizations import POSITIONS, configure_stage, measure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--depth", type=int, choices=range(1, 9), default=5)
    parser.add_argument("--times", type=int, nargs="*", default=[100, 500, 1000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("docs/advanced-evaluation-benchmark.json"))
    args = parser.parse_args()
    if args.repeats < 1 or any(ms < 1 for ms in args.times):
        parser.error("repeats and times must be positive")
    options = {"AlphaBeta": True, "IterativeDeepening": True, "MoveOrdering": True,
               "UsePST": True, "TranspositionTable": True, "Hash": 16, "Quiescence": True, "PVS": True,
               "UseAspirationWindows": True, "AspirationDelta": 25,
               "UseNullMovePruning": True, "UseLMR": True, "LMRReduction": 1}
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    rows = []
    with chess.engine.SimpleEngine.popen_uci(str(DEFAULT_ENGINE), timeout=30, **flags) as engine:
        engine.configure(options)
        configure_stage(engine, 3)
        for mode, depth, ms in [("depth", args.depth, None)] + [("time", None, ms) for ms in args.times]:
            for name, fen in POSITIONS.items():
                samples = {False: [], True: []}
                for repeat in range(args.repeats):
                    for advanced in ((False, True) if repeat % 2 == 0 else (True, False)):
                        engine.configure({"UseAdvancedEvaluation": advanced})
                        samples[advanced].append(measure(engine, fen, depth, ms))
                for advanced, runs in samples.items():
                    median = statistics.median(r["wall_seconds"] for r in runs)
                    run = min(runs, key=lambda r: abs(r["wall_seconds"] - median))
                    rows.append({"position": name, "fen": fen, "mode": mode, "requested_depth": depth,
                                 "requested_ms": ms, "advanced": advanced, **run, "samples": runs})
                print(f"{mode} {ms or depth} {name}: " + "; ".join(
                    f"{'advanced' if advanced else 'baseline'} d{runs[-1]['depth']} "
                    f"{runs[-1]['nodes']:,} nodes {runs[-1]['san']} {runs[-1]['score_white']}"
                    for advanced, runs in samples.items()), flush=True)
        data = {"generated_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
                "engine_name": engine.id.get("name"),
                "engine_sha256": hashlib.sha256(DEFAULT_ENGINE.read_bytes()).hexdigest(),
                "settings": options, "repeats": args.repeats, "positions": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
