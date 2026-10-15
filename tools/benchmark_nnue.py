"""Alternate evaluator modes in the same binary; scores/trees may differ."""
import argparse
import json
from pathlib import Path
import statistics

import chess
import chess.engine

from app.engine_client import DEFAULT_ENGINE
from tools.audit_engine import measure, metadata
from tools.benchmark_optimizations import POSITIONS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=5)
    parser.add_argument("--times", type=int, nargs="+", default=[100, 1000])
    parser.add_argument("--repeats", type=int, default=3)
    args = parser.parse_args()
    if args.output.exists() or args.repeats < 1 or not 1 <= args.depth <= 8 or min(args.times) < 1:
        parser.error("Choose a fresh path, positive repeats/times and depth 1..8")
    data = {"engine": metadata(args.engine), "method": "Alternating evaluator order; same executable and search defaults; different scores/trees allowed", "positions": []}
    build = args.engine.with_suffix(".build.json")
    if build.exists():
        data["build"] = json.loads(build.read_text())
    with chess.engine.SimpleEngine.popen_uci(str(args.engine), timeout=40) as engine:
        data["defaults"] = {name: option.default for name, option in engine.options.items()}
        for depth, ms in [(args.depth, None)] + [(None, ms) for ms in args.times]:
            for name in ("opening", "middlegame", "tactical", "endgame", "zugzwang"):
                row = {"position": name, "fen": POSITIONS[name], "depth_limit": depth,
                       "movetime_ms": ms, "samples": {"classical": [], "nnue": []}}
                for repeat in range(args.repeats):
                    modes = ("classical", "nnue") if repeat % 2 == 0 else ("nnue", "classical")
                    for mode in modes:
                        engine.configure({"Evaluator": mode})
                        row["samples"][mode].append(measure(engine, chess.Board(row["fen"]), depth=depth, ms=ms))
                data["positions"].append(row)
                print(f"{name} depth={depth} ms={ms}: " + "; ".join(
                    f"{mode} d{statistics.median(s['depth'] for s in samples):g} {statistics.median(s['nps'] for s in samples):,.0f} NPS"
                    for mode, samples in row["samples"].items()), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
