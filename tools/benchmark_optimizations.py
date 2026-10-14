"""Controlled cumulative search stages; fixed-depth and fixed-time measurements."""
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

from app.engine_client import DEFAULT_ENGINE, THINKING_TIMES
from tools.benchmark_time import POSITIONS as TIME_POSITIONS

OPTIONS = ("UseAspirationWindows", "UseNullMovePruning", "UseLMR")
POSITIONS = {name: TIME_POSITIONS[name] for name in ("opening", "middlegame", "tactical", "endgame")}
POSITIONS.update({"zugzwang": "8/3k4/3P4/3K4/8/8/8/8 w - - 0 1",
                  "mate": TIME_POSITIONS["mate-in-one"], "stalemate": TIME_POSITIONS["stalemate"]})


def counters(info):
    words = info.get("string", "").split()
    if "optim" not in words:
        return {}
    pairs = words[words.index("optim") + 1:]
    return {k: int(v) for k, v in zip(pairs[::2], pairs[1::2])}


def configure_stage(engine, stage):
    for index, name in enumerate(OPTIONS):
        if name in engine.options:
            engine.configure({name: stage > index})
        elif stage > index:
            raise RuntimeError(f"Stage {stage} needs {name}")


def measure(engine, fen, depth, ms):
    board = chess.Board(fen)
    start = time.perf_counter()
    result = engine.play(board, chess.engine.Limit(depth=depth, time=15) if depth else
                         chess.engine.Limit(time=ms / 1000), info=chess.engine.INFO_ALL)
    wall = time.perf_counter() - start
    info = result.info
    move = result.move if result.move else None
    assert move in board.legal_moves if move else board.is_game_over(claim_draw=True)
    if depth:
        assert info["depth"] == depth, "Fixed-depth pass did not finish"
    else:
        assert wall < ms / 1000 + 2, "Timed search exceeded watchdog"
    pv_board = board.copy()
    for pv_move in info.get("pv", []):
        assert pv_move in pv_board.legal_moves and pv_move
        pv_board.push(pv_move)
    return {"depth": info["depth"], "seldepth": info["seldepth"], "nodes": info["nodes"],
            "seconds": info["time"], "nps": info["nps"], "wall_seconds": wall,
            "score_white": str(info["score"].white()), "move": move.uci() if move else "0000",
            "san": board.san(move) if move else "(none)",
            "pv": [m.uci() for m in info.get("pv", [])], **counters(info)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--stage", type=int, choices=range(4), default=3)
    parser.add_argument("--depth", type=int, choices=range(1, 9), default=5)
    parser.add_argument("--times", type=int, nargs="*", default=[ms for _, ms in THINKING_TIMES])
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--output", type=Path, default=Path("artifacts/optimization-benchmark.json"))
    args = parser.parse_args()
    if args.repeats < 1 or any(ms not in (100, 500, 1000, 3000, 5000) for ms in args.times):
        parser.error("Use positive repeats and the five supported time presets")
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    options = {"AlphaBeta": True, "IterativeDeepening": True, "MoveOrdering": True,
               "UsePST": True, "TranspositionTable": True, "Hash": 16, "Quiescence": True, "PVS": True}
    rows = []
    with chess.engine.SimpleEngine.popen_uci(str(args.engine), timeout=20, **flags) as engine:
        for name, value in (("AspirationDelta", 25), ("LMRReduction", 1)):
            if name in engine.options:
                options[name] = value
        engine.configure(options)
        for mode, depth, ms in [("depth", args.depth, None)] + [("time", None, ms) for ms in args.times]:
            for name, fen in POSITIONS.items():
                samples = {stage: [] for stage in range(args.stage + 1)}
                for repeat in range(args.repeats):
                    order = list(samples) if repeat % 2 == 0 else list(samples)[::-1]
                    for stage in order:
                        configure_stage(engine, stage)
                        samples[stage].append(measure(engine, fen, depth, ms))
                for stage, runs in samples.items():
                    median = statistics.median(r["wall_seconds"] for r in runs)
                    run = min(runs, key=lambda r: abs(r["wall_seconds"] - median))
                    rows.append({"position": name, "fen": fen, "mode": mode, "requested_depth": depth,
                                 "requested_ms": ms, "stage": stage, **run, "samples": runs})
                if mode == "depth" and args.stage >= 1:
                    assert samples[0][0]["score_white"] == samples[1][0]["score_white"], "Aspiration changed exact score"
                print(f"{mode} {ms or depth} {name}: " + "; ".join(
                    f"S{s} d{runs[-1]['depth']} {runs[-1]['nodes']:,} {runs[-1]['san']} {runs[-1]['score_white']}"
                    for s, runs in samples.items()), flush=True)
        data = {"generated_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
                "processor": platform.processor(), "engine_name": engine.id.get("name"),
                "engine_sha256": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
                "settings": options, "max_stage": args.stage, "repeats": args.repeats, "positions": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {args.output}; legal moves/PVs and aspiration score equivalence verified.")


if __name__ == "__main__":
    main()
