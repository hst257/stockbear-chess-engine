"""Verify conversion of bare-king endings with both sides using the real engine."""
import argparse
import json
from pathlib import Path

import chess
import chess.engine

from app.engine_client import DEFAULT_ENGINE
from tools.audit_engine import metadata

POSITIONS = (
    "8/8/8/8/8/5R2/3K4/6k1 w - - 31 128",  # Previously capped audit game.
    "8/8/8/3k4/8/8/8/K3R3 w - - 0 1",
    "8/8/8/4k3/8/8/8/K2Q4 w - - 0 1",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--engine", type=Path, default=DEFAULT_ENGINE)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--movetime", type=int, default=25)
    args = parser.parse_args()
    if args.output.exists() or args.movetime < 1:
        parser.error("Choose a fresh output path and a positive move budget")
    records = []
    with chess.engine.SimpleEngine.popen_uci(str(args.engine), timeout=10) as engine:
        for fen in POSITIONS:
            for mirrored in (False, True):
                board = chess.Board(fen)
                if mirrored:
                    board = board.mirror()
                assert board.is_valid(), board.fen()
                initial = board.fen()
                winning_color = not mirrored
                moves = []
                for _ in range(160):
                    if board.is_game_over(claim_draw=True):
                        break
                    result = engine.play(board, chess.engine.Limit(time=args.movetime / 1000),
                                         info=chess.engine.INFO_ALL)
                    assert result.move in board.legal_moves
                    moves.append(result.move.uci())
                    board.push(result.move)
                outcome = board.outcome(claim_draw=True)
                record = {"fen": initial, "moves": moves, "plies": len(moves),
                          "final_fen": board.fen(), "result": outcome.result() if outcome else "*",
                          "termination": outcome.termination.name if outcome else "CAP",
                          "converted": bool(outcome and outcome.winner == winning_color and board.is_checkmate())}
                records.append(record)
                print(f"{initial}: {record['termination']} in {len(moves)} plies", flush=True)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"engine": metadata(args.engine), "movetime_ms": args.movetime,
                                     "cases": records}, indent=2) + "\n", encoding="utf-8")
    if not all(r["converted"] for r in records):
        raise SystemExit("At least one ending did not convert; see saved evidence")


if __name__ == "__main__":
    main()
