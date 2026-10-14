"""Frozen audit measurements and canonical perft checks; no benchmark overwrites."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import time

import chess
import chess.engine

from app.engine_client import DEFAULT_ENGINE
from tools.benchmark_optimizations import POSITIONS

# Exact FENs/counts verified against https://chessprogramming.org/Perft_Results.
PERFT = (
    ("start", chess.STARTING_FEN, [20, 400, 8902, 197281, 4865609]),
    ("kiwipete", POSITIONS["tactical"], [48, 2039, 97862, 4085603]),
    ("endgame_ep", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", [14, 191, 2812, 43238, 674624]),
    ("promotions_checks", "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", [6, 264, 9467, 422333]),
    ("underpromotion", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", [44, 1486, 62379, 2103487]),
    ("pins", "r4rk1/1pp1qppp/p1np1n2/2b1p1B1/2B1P1b1/P1NP1N2/1PP1QPPP/R4RK1 w - - 0 10", [46, 2079, 89890, 3894594]),
)


def metadata(engine):
    return {"utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
            "processor": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()), "logical_cpus": os.cpu_count(),
            "python": platform.python_version(), "executable": str(engine.resolve()),
            "sha256": hashlib.sha256(engine.read_bytes()).hexdigest(),
            "git": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()}


def measure(engine, board, depth=None, ms=None, nodes=None):
    stats = {}
    profile = None
    start = time.perf_counter()
    limit = chess.engine.Limit(depth=depth, time=30, nodes=nodes) if depth else chess.engine.Limit(time=ms / 1000)
    with engine.analysis(board, limit, info=chess.engine.INFO_ALL) as analysis:
        for info in analysis:
            if info.get("string", "").startswith("profile "):
                profile = json.loads(info["string"][8:])
            stats.update({k: int(v) for k, v in re.findall(r"\b([a-z_]+)\s+(\d+)\b", info.get("string", ""))})
        result = analysis.wait()
        info = analysis.info
    wall = time.perf_counter() - start
    assert result.move in board.legal_moves if result.move else board.is_game_over(claim_draw=True)
    if depth and not nodes:
        assert info["depth"] == depth
    elif not depth:
        assert wall < ms / 1000 + 2
    replay = board.copy()
    for move in info.get("pv", []):
        assert move in replay.legal_moves
        replay.push(move)
    return {"depth": info["depth"], "nodes": info["nodes"], "qnodes": stats.get("qnodes"),
            "seconds": info["time"], "wall_seconds": wall, "nps": info["nps"],
            "score": str(info["score"].white()) if "score" in info else None, "move": result.move.uci() if result.move else "0000",
            "profile": profile, "pv": [m.uci() for m in info.get("pv", [])], "counters": stats,
            "tt_hit_rate": stats.get("hits", 0) / max(1, stats.get("probes", 0))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--depth", type=int, default=6)
    parser.add_argument("--times", type=int, nargs="*", default=[100, 500, 1000])
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--perft-only", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output exists: frozen records cannot be overwritten; choose a new path")
    data = metadata(args.engine)
    data["compiler"] = "Zig 0.13.0 / Clang; C++17 -O2 -pthread -Wall -Wextra unless build metadata overrides"
    build_info = args.engine.with_suffix(".build.json")
    if build_info.exists():
        data["build"] = json.loads(build_info.read_text())
    data["perft_source"] = "https://chessprogramming.org/Perft_Results"
    data["perft"] = []
    for name, fen, counts in PERFT:
        for depth, expected in enumerate(counts, 1):
            actual = int(subprocess.check_output([str(args.engine), "--perft", str(depth), fen], text=True, timeout=30))
            assert actual == expected, (name, depth, expected, actual)
            data["perft"].append({"position": name, "fen": fen, "depth": depth, "nodes": actual})
    data["positions"] = []
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    if not args.perft_only:
        with chess.engine.SimpleEngine.popen_uci(str(args.engine), timeout=40, **flags) as engine:
            data["engine_name"] = engine.id.get("name")
            data["options"] = {name: opt.default for name, opt in engine.options.items()}
            for mode, depth, ms in [("depth", args.depth, None)] + [("time", None, ms) for ms in args.times]:
                for name, fen in POSITIONS.items():
                    samples = [measure(engine, chess.Board(fen), depth, ms) for _ in range(args.repeats)]
                    data["positions"].append({"position": name, "fen": fen, "mode": mode,
                                              "requested_depth": depth, "requested_ms": ms, "samples": samples})
                    print(f"{mode} {ms or depth} {name}: d{samples[-1]['depth']} {samples[-1]['nodes']:,} "
                          f"{samples[-1]['nps']:,} NPS {samples[-1]['move']} {samples[-1]['score']}", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Saved immutable {args.output}")


if __name__ == "__main__":
    main()
