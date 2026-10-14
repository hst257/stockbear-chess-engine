"""Measure uncached/cached searches with identical depth, evaluation, and limits.

Run from the repository root: python -m tools.benchmark_transpositions
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

from app.engine_client import DEFAULT_ENGINE, table_stats
from tools.benchmark_evaluation import POSITIONS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--depth", type=int, choices=range(1, 9), default=5)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--hash", type=int, choices=range(1, 257), default=16, metavar="MB")
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--pst", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument("--output", type=Path, default=Path("artifacts/tt-benchmark.json"))
    args = parser.parse_args()
    if args.repeats < 1 or args.seconds <= 0:
        parser.error("repeats and seconds must be positive")
    settings = {"AlphaBeta": True, "IterativeDeepening": True, "MoveOrdering": True,
                "UsePST": args.pst, "Hash": args.hash, "Quiescence": False, "PVS": False}
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    rows = []
    with chess.engine.SimpleEngine.popen_uci(str(args.engine), timeout=args.seconds + 5, **flags) as engine:
        engine.configure(settings)
        for name, fen in POSITIONS.items():
            samples = {False: [], True: []}
            for repeat in range(args.repeats):
                for cached in ((False, True) if repeat % 2 == 0 else (True, False)):
                    engine.configure({"TranspositionTable": cached})
                    board = chess.Board(fen)
                    start = time.perf_counter()
                    result = engine.play(board, chess.engine.Limit(depth=args.depth, time=args.seconds),
                                         info=chess.engine.INFO_ALL)
                    wall = time.perf_counter() - start
                    info = result.info
                    if info.get("depth") != args.depth or result.move not in board.legal_moves:
                        raise RuntimeError(f"{name}: target depth not completed")
                    samples[cached].append({"move": result.move.uci(), "san": board.san(result.move),
                        "score_white": str(info["score"].white()), "depth": info["depth"],
                        "nodes": info["nodes"], "seconds": info["time"], "nps": info["nps"],
                        "wall_seconds": wall, "hashfull": info.get("hashfull", 0), **table_stats(info)})
            off_score = {s["score_white"] for s in samples[False]}
            on_score = {s["score_white"] for s in samples[True]}
            if off_score != on_score or len(off_score) != 1:
                raise RuntimeError(f"{name}: cached and uncached scores disagree")
            for cached, runs in samples.items():
                median = statistics.median(run["wall_seconds"] for run in runs)
                run = min(runs, key=lambda row: abs(row["wall_seconds"] - median))
                rows.append({"position": name, "fen": fen, "cached": cached, **run, "samples": runs})
        data = {"generated_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
                "processor": platform.processor(), "engine_name": engine.id.get("name"),
                "engine_sha256": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
                "settings": {**settings, "depth": args.depth, "seconds": args.seconds, "repeats": args.repeats},
                "positions": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print("Position     TT    Move    White cp    Nodes      Time(s)      Hits  Cutoffs")
    for row in rows:
        print(f"{row['position']:12} {str(row['cached']):5} {row['san']:7} {row['score_white']:>7} "
              f"{row['nodes']:9,} {row['seconds']:10.3f} {row['hits']:9,} {row['cutoffs']:8,}")
    print(f"Saved {args.output}. Short timings include fresh table allocation; node savings do not measure strength.")


if __name__ == "__main__":
    main()
