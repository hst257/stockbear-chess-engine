"""Compare evaluation modes at identical search settings; optionally play paired games.

Run from the repository root: python -m tools.benchmark_evaluation --match-games 4
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
import chess.pgn

from app.engine_client import DEFAULT_ENGINE

POSITIONS = {
    "opening": chess.STARTING_FEN,
    "middlegame": "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
    "endgame": "8/5pk1/6p1/8/3K4/6P1/5P2/8 w - - 0 1",
}
OPENINGS = ((), ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"))


def measure(engine, depth, seconds, repeats):
    rows = []
    for name, fen in POSITIONS.items():
        board = chess.Board(fen)
        samples = {False: [], True: []}
        for repeat in range(repeats):
            for use_pst in ((False, True) if repeat % 2 == 0 else (True, False)):
                engine.configure({"UsePST": use_pst})
                start = time.perf_counter()
                result = engine.play(board, chess.engine.Limit(depth=depth, time=seconds),
                                     info=chess.engine.INFO_ALL)
                wall = time.perf_counter() - start
                info = result.info
                if info.get("depth") != depth or result.move not in board.legal_moves:
                    raise RuntimeError(f"{name}: target depth not completed; increase --seconds or lower --depth")
                samples[use_pst].append({
                    "bestmove": result.move.uci(), "san": board.san(result.move),
                    "score_white": str(info["score"].white()), "depth": info["depth"],
                    "nodes": info["nodes"], "seconds": info["time"], "nps": info["nps"],
                    "wall_seconds": wall,
                })
        for use_pst, runs in samples.items():
            representative = min(runs, key=lambda run: abs(run["wall_seconds"] -
                                                        statistics.median(r["wall_seconds"] for r in runs)))
            rows.append({"position": name, "fen": fen, "use_pst": use_pst,
                         **representative, "samples": runs})
    return rows


def matches(engine, games, depth, seconds, max_plies):
    records, pgns = [], []
    for index in range(games):
        board = chess.Board()
        opening = OPENINGS[(index // 2) % len(OPENINGS)]
        for move in opening:
            board.push_uci(move)
        pst_white = index % 2 == 0
        termination = "ply limit (unfinished)"
        for _ in range(max_plies):
            if board.is_game_over(claim_draw=True):
                termination = board.outcome(claim_draw=True).termination.name.lower()
                break
            engine.configure({"UsePST": board.turn == pst_white})
            result = engine.play(board, chess.engine.Limit(depth=depth, time=seconds),
                                 info=chess.engine.INFO_ALL)
            if result.move not in board.legal_moves:
                # Match rules take eligible draws, including intended-move claims.
                raise RuntimeError("Match engine returned no legal move in a playable position")
            if result.info.get("depth") != depth:
                termination = "time limit before target depth (unfinished)"
                break
            board.push(result.move)
        outcome = board.outcome(claim_draw=True)
        if outcome:
            termination = outcome.termination.name.lower()
        result_text = outcome.result() if outcome else "*"
        record = {"game": index + 1, "pst_color": "white" if pst_white else "black",
                  "opening": list(opening), "result": result_text,
                  "termination": termination, "plies": len(board.move_stack),
                  "pst_outcome": ("unfinished" if outcome is None else "draw" if outcome.winner is None
                                  else "win" if outcome.winner == pst_white else "loss")}
        records.append(record)
        game = chess.pgn.Game.from_board(board)
        game.headers.update({"Event": "PST smoke match", "White": "PST" if pst_white else "Material",
                             "Black": "Material" if pst_white else "PST", "Result": result_text,
                             "Termination": termination})
        pgns.append(str(game))
    return records, "\n\n".join(pgns) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--depth", type=int, choices=range(1, 9), default=5)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--seconds", type=float, default=15)
    parser.add_argument("--match-games", type=int, choices=(0, 2, 4, 6, 8), default=0)
    parser.add_argument("--match-depth", type=int, choices=range(1, 9), default=3)
    parser.add_argument("--max-plies", type=int, default=160)
    parser.add_argument("--output", type=Path, default=Path("artifacts/pst-benchmark.json"))
    args = parser.parse_args()
    if args.repeats < 1 or args.seconds <= 0 or args.max_plies < 1:
        parser.error("repeats, seconds, and max-plies must be positive")
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    # Preserve the recorded PST-only comparison as new search features are added.
    settings = {"AlphaBeta": True, "IterativeDeepening": True, "MoveOrdering": True,
                "TranspositionTable": False, "Quiescence": False, "PVS": False}
    with chess.engine.SimpleEngine.popen_uci(str(args.engine), timeout=args.seconds + 5, **flags) as engine:
        engine.configure(settings)
        rows = measure(engine, args.depth, args.seconds, args.repeats)
        print("Position     PST   Move   White cp   Nodes      Time(s)       NPS", flush=True)
        for row in rows:
            print(f"{row['position']:12} {str(row['use_pst']):5} {row['san']:6} {row['score_white']:>7} "
                  f"{row['nodes']:9,} {row['seconds']:9.3f} {row['nps']:10,}", flush=True)
        records, pgn = matches(engine, args.match_games, args.match_depth, args.seconds, args.max_plies)
        data = {"generated_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
                "processor": platform.processor(), "engine_name": engine.id.get("name"),
                "engine_sha256": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
                "settings": {**settings, "depth": args.depth, "seconds": args.seconds, "repeats": args.repeats},
                "positions": rows, "match_settings": {"depth": args.match_depth, "max_plies": args.max_plies,
                                                     "seconds": args.seconds, "claim_draw": True},
                "matches": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    if records:
        args.output.with_suffix(".pgn").write_text(pgn, encoding="utf-8")
        print("PST smoke match:", {key: sum(r["pst_outcome"] == key for r in records)
                                  for key in ("win", "draw", "loss", "unfinished")})
    print(f"Saved {args.output}. Node counts/speed do not measure playing strength; small matches do not establish Elo.")


if __name__ == "__main__":
    main()
