"""Compare static/quiescent leaves and alpha-beta/PVS on identical positions.

Run from the repository root: python -m tools.benchmark_search
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import time

import chess
import chess.engine

from app.engine_client import DEFAULT_ENGINE, search_counters, table_stats
from tools.benchmark_evaluation import POSITIONS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--depth", type=int, choices=range(1, 9), default=4)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--output", type=Path, default=Path("artifacts/search-benchmark.json"))
    args = parser.parse_args()
    if args.repeats < 1 or args.seconds <= 0:
        parser.error("repeats and seconds must be positive")
    settings = {"AlphaBeta": True, "IterativeDeepening": True, "MoveOrdering": True,
                "UsePST": True, "TranspositionTable": True, "Hash": 16}
    positions = {name: (fen, args.depth) for name, fen in POSITIONS.items()}
    positions["poisoned-pawn"] = ("7k/8/8/1p6/p7/Q7/8/7K w - - 0 1", 1)
    modes = [(False, False), (False, True), (True, False), (True, True)]
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    rows = []
    with chess.engine.SimpleEngine.popen_uci(str(args.engine), timeout=args.seconds + 5, **flags) as engine:
        engine.configure(settings)
        for name, (fen, depth) in positions.items():
            samples = {mode: [] for mode in modes}
            for repeat in range(args.repeats):
                order = modes[repeat % 4:] + modes[:repeat % 4]
                for qsearch, pvs in order:
                    engine.configure({"Quiescence": qsearch, "PVS": pvs})
                    board = chess.Board(fen)
                    start = time.perf_counter()
                    result = engine.play(board, chess.engine.Limit(depth=depth, time=args.seconds),
                                         info=chess.engine.INFO_ALL)
                    wall = time.perf_counter() - start
                    info = result.info
                    if info.get("depth") != depth or result.move not in board.legal_moves:
                        raise RuntimeError(f"{name}: target depth not completed")
                    samples[qsearch, pvs].append({"move": result.move.uci(), "san": board.san(result.move),
                        "score_white": str(info["score"].white()), "depth": info["depth"],
                        "seldepth": info["seldepth"], "pv": [m.uci() for m in info.get("pv", [])],
                        "nodes": info["nodes"], "seconds": info["time"], "nps": info["nps"],
                        "wall_seconds": wall, **table_stats(info), **search_counters(info)})
            for qsearch in (False, True):
                full = {row["score_white"] for row in samples[qsearch, False]}
                pvs = {row["score_white"] for row in samples[qsearch, True]}
                if full != pvs or len(full) != 1:
                    raise RuntimeError(f"{name}: PVS and full-window scores disagree")
            for (qsearch, pvs), runs in samples.items():
                median = statistics.median(run["wall_seconds"] for run in runs)
                run = min(runs, key=lambda row: abs(row["wall_seconds"] - median))
                rows.append({"position": name, "fen": fen, "quiescence": qsearch,
                             "pvs": pvs, **run, "samples": runs})
        data = {"generated_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
                "processor": platform.processor(), "engine_name": engine.id.get("name"),
                "engine_sha256": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
                "settings": {**settings, "depth": args.depth, "seconds": args.seconds, "repeats": args.repeats},
                "positions": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("Position      Depth Q     PVS   Move      White cp    Nodes      Q nodes   Re-searches")
    for row in rows:
        print(f"{row['position']:14} {row['depth']}   {str(row['quiescence']):5} {str(row['pvs']):5} "
              f"{row['san']:8} {row['score_white']:>7} {row['nodes']:10,} {row['qnodes']:10,} {row['researches']:9,}")
    print(f"Saved {args.output}. Quiescence changes the leaf model; PVS preserves its full-window score. No Elo claim.")


if __name__ == "__main__":
    main()
