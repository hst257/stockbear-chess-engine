"""Color-balanced baseline/advanced smoke games; not an Elo estimate."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

import chess
import chess.engine
import chess.pgn

from app.engine_client import DEFAULT_ENGINE
from tools.benchmark_optimizations import configure_stage

OPENINGS = ((), ("e2e4", "e7e5", "g1f3", "b8c6", "f1c4", "g8f6"),
            ("d2d4", "d7d5", "c2c4", "e7e6"), ("e2e4", "c7c5", "g1f3", "d7d6"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--games", type=int, choices=(4, 8), default=4)
    parser.add_argument("--movetime", type=int, choices=(100, 500, 1000, 3000, 5000), default=100)
    parser.add_argument("--max-plies", type=int, default=160)
    parser.add_argument("--output", type=Path, default=Path("artifacts/optimization-matches.json"))
    args = parser.parse_args()
    if args.max_plies < 1:
        parser.error("max-plies must be positive")
    flags = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    records, pgns = [], []
    options = {"AlphaBeta": True, "IterativeDeepening": True, "MoveOrdering": True, "UsePST": True,
               "TranspositionTable": True, "Hash": 16, "PVS": True, "Quiescence": True, "AspirationDelta": 25, "LMRReduction": 1}
    with chess.engine.SimpleEngine.popen_uci(str(args.engine), timeout=10, **flags) as engine:
        engine.configure(options)
        for index in range(args.games):
            board = chess.Board()
            opening = OPENINGS[index // 2]
            for uci in opening:
                board.push_uci(uci)
            advanced_color = index % 2 == 0
            searches = []
            for _ in range(args.max_plies):
                if board.is_game_over(claim_draw=True):
                    break
                advanced = board.turn == advanced_color
                configure_stage(engine, 3 if advanced else 0)
                result = engine.play(board, chess.engine.Limit(time=args.movetime / 1000), info=chess.engine.INFO_ALL)
                assert result.move in board.legal_moves
                searches.append({"advanced": advanced, "move": result.move.uci(),
                                 "depth": result.info.get("depth", 0), "nodes": result.info["nodes"],
                                 "seconds": result.info["time"]})
                board.push(result.move)
            outcome = board.outcome(claim_draw=True)
            result_text = outcome.result() if outcome else "*"
            record = {"game": index + 1, "opening": list(opening),
                      "advanced_color": "white" if advanced_color else "black", "result": result_text,
                      "termination": outcome.termination.name.lower() if outcome else "ply cap (unfinished)",
                      "advanced_outcome": "unfinished" if outcome is None else "draw" if outcome.winner is None else
                                          "win" if outcome.winner == advanced_color else "loss",
                      "plies": len(board.move_stack), "searches": searches}
            records.append(record)
            game = chess.pgn.Game.from_board(board)
            game.headers.update({"Event": "Optimization smoke match", "White": "Advanced" if advanced_color else "Baseline",
                                 "Black": "Baseline" if advanced_color else "Advanced", "Result": result_text,
                                 "ThinkTimeMs": str(args.movetime), "Termination": record["termination"]})
            pgns.append(str(game))
            print(f"Game {index + 1}: advanced {record['advanced_color']} {result_text} "
                  f"({record['advanced_outcome']}; {record['termination']}; {record['plies']} plies)", flush=True)
        data = {"generated_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
                "engine_sha256": hashlib.sha256(args.engine.read_bytes()).hexdigest(),
                "settings": options, "movetime_ms": args.movetime, "max_plies": args.max_plies, "games": records}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    args.output.with_suffix(".pgn").write_text("\n\n".join(pgns) + "\n", encoding="utf-8")
    print(f"Saved {args.output} and PGNs. Tiny samples establish no reliable Elo gain.")


if __name__ == "__main__":
    main()
