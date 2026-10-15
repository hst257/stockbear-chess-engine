"""Alternate executable order to reduce timing drift in release comparisons."""
import argparse
from contextlib import ExitStack
import json
import os
from pathlib import Path
import statistics
import subprocess

import chess
import chess.engine

from tools.audit_engine import measure, metadata
from tools.benchmark_optimizations import POSITIONS


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engines", nargs="+", required=True, help="NAME=EXECUTABLE pairs")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--times", type=int, nargs="*", default=[100, 500, 1000])
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--allow-search-changes", action="store_true",
                        help="Compare strength changes without requiring identical search trees/results.")
    parser.add_argument("--positions", nargs="+", choices=list(POSITIONS), default=list(POSITIONS))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Refusing to overwrite a frozen comparison")
    paths = {name: Path(path) for name, path in (item.split("=", 1) for item in args.engines)}
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    data = {"executables": {name: metadata(path) for name, path in paths.items()},
            "repeats": args.repeats, "ordering": "alternate/reverse between repeats", "positions": []}
    with ExitStack() as stack:
        engines = {name: stack.enter_context(chess.engine.SimpleEngine.popen_uci(str(path), timeout=40, **flags))
                   for name, path in paths.items()}
        for mode, depth, ms in [("depth", args.depth, None)] + [("time", None, t) for t in args.times]:
            for position in args.positions:
                fen = POSITIONS[position]
                runs = {name: [] for name in engines}
                for repeat in range(args.repeats):
                    order = list(engines) if repeat % 2 == 0 else list(engines)[::-1]
                    for name in order:
                        runs[name].append(measure(engines[name], chess.Board(fen), depth=depth, ms=ms))
                if depth and not args.allow_search_changes:
                    first = next(iter(runs.values()))[0]
                    for samples in runs.values():
                        for sample in samples:
                            assert all(sample[k] == first[k] for k in ("nodes", "qnodes", "score", "move", "pv")), position
                data["positions"].append({"position": position, "fen": fen, "mode": mode,
                                          "requested_depth": depth, "requested_ms": ms, "samples": runs})
                print(f"{mode} {ms or depth} {position}: " + "; ".join(
                    f"{name}: {statistics.median(s['nps'] for s in samples):,.0f} NPS "
                    f"d{statistics.median(s['depth'] for s in samples):g}" for name, samples in runs.items()), flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
