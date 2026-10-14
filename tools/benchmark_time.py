"""Measure every GUI thinking-time preset using UCI movetime without a depth cap."""

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

from app.engine_client import DEFAULT_ENGINE, THINKING_TIMES, search_counters, table_stats
from tools.benchmark_evaluation import POSITIONS as BASE_POSITIONS

POSITIONS = {
    "opening": chess.STARTING_FEN,
    "middlegame": "r1bq1rk1/ppp2ppp/2np1n2/2b1p3/2B1P3/2NP1N2/PPP2PPP/R1BQ1RK1 w - - 4 7",
    "tactical": BASE_POSITIONS["middlegame"],
    "endgame": "8/5pk1/6p1/8/3K4/6P1/5P2/8 w - - 0 1",
    "checkmate": "7k/6Q1/5K2/8/8/8/8/8 b - - 0 1",
    "stalemate": "7k/5Q2/6K1/8/8/8/8/8 b - - 0 1",
    "mate-in-one": "7k/8/5KQ1/8/8/8/8/8 w - - 0 1",
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, default=Path("artifacts/time-benchmark.json"))
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("repeats must be positive")
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    options = {"AlphaBeta": True, "IterativeDeepening": True, "UsePST": True,
               "MoveOrdering": True, "TranspositionTable": True, "Hash": 16,
               "Quiescence": True, "PVS": True, "UseAspirationWindows": False, "UseNullMovePruning": False, "UseLMR": False}
    rows = []
    with chess.engine.SimpleEngine.popen_uci(str(args.engine), timeout=8, **flags) as engine:
        engine.configure(options)
        for name, fen in POSITIONS.items():
            board = chess.Board(fen)
            samples = {ms: [] for _, ms in THINKING_TIMES}
            for repeat in range(args.repeats):
                order = THINKING_TIMES if repeat % 2 == 0 else THINKING_TIMES[::-1]
                for label, ms in order:
                    completed = []
                    start = time.perf_counter()
                    with engine.analysis(board, chess.engine.Limit(time=ms / 1000),
                                         info=chess.engine.INFO_ALL) as analysis:
                        for info in analysis:
                            if "depth" in info and "score" in info:
                                completed.append(info)
                        result = analysis.wait()
                        info = analysis.info.copy()
                    wall = time.perf_counter() - start
                    move = result.move if result.move else None
                    assert (move in board.legal_moves) if move else not any(board.legal_moves)
                    assert completed and info["depth"] == completed[-1]["depth"]
                    assert info["score"] == completed[-1]["score"]
                    if move:
                        assert move == completed[-1]["pv"][0]
                    pv_board = board.copy()
                    for pv_move in info.get("pv", []):
                        assert pv_move in pv_board.legal_moves
                        pv_board.push(pv_move)
                    # Generous watchdog catches runaway iterations, not scheduler jitter.
                    assert info["time"] <= ms / 1000 + .5 and wall <= ms / 1000 + 2
                    samples[ms].append({"requested_ms": ms, "engine_seconds": info["time"],
                        "wall_seconds": wall, "depth": info["depth"], "seldepth": info["seldepth"],
                        "nodes": info["nodes"], "nps": info["nps"], "move": move.uci() if move else "0000",
                        "san": board.san(move) if move else "—", "score_white": str(info["score"].white()),
                        "pv": [m.uci() for m in info.get("pv", [])],
                        "completed_depths": [i["depth"] for i in completed],
                        **table_stats(info), **search_counters(info)})
            for label, ms in THINKING_TIMES:
                runs = samples[ms]
                median = statistics.median(r["wall_seconds"] for r in runs)
                selected = min(runs, key=lambda r: abs(r["wall_seconds"] - median))
                rows.append({"position": name, "fen": fen, "preset": label, **selected, "samples": runs})
                print(f"{name:12} {label:8} {ms:4}ms {selected['wall_seconds']:.4f}s "
                      f"depth {selected['depth']:2} {selected['nodes']:12,} nodes {selected['san']}", flush=True)
        data = {"generated_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
                "processor": platform.processor(), "engine_name": engine.id.get("name"),
                "engine_sha256": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
                "settings": options, "repeats": args.repeats, "positions": rows}
    assert any(r["depth"] > 5 for r in rows if r["position"] in ("opening", "middlegame", "tactical", "endgame"))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(f"Saved {args.output}; legal moves/PVs, completed snapshots, and time watchdogs passed.")


if __name__ == "__main__":
    main()
