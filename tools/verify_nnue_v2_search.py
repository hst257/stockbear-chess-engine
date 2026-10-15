"""Search integration checks for both finalists, without changing search policy."""
import json
import argparse
from pathlib import Path
import time

import chess
import chess.engine
from tools.audit_engine import metadata
from tools.benchmark_nnue_v2 import POSITIONS


def search(engine: chess.engine.SimpleEngine, board: chess.Board, limit: chess.engine.Limit) -> dict:
    r = engine.play(board, limit, info=chess.engine.INFO_ALL)
    assert r.move in board.legal_moves if r.move else board.is_game_over(claim_draw=True)
    replay = board.copy()
    for move in r.info.get("pv", []):
        assert move in replay.legal_moves
        replay.push(move)
    return {"move": r.move.uci() if r.move else None, "score": str(r.info["score"].white()),
            "nodes": r.info["nodes"], "depth": r.info["depth"],
            "pv": [m.uci() for m in r.info.get("pv", [])]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="final", help="Candidate directory prefix under artifacts/nnue-v2")
    parser.add_argument("--output", type=Path, default=Path("docs/nnue-v2/search-verification.json"))
    args = parser.parse_args()
    path = args.output
    if path.exists():
        raise ValueError("Frozen report exists")
    report = {"models": {}}
    for model in ("compact", "small"):
        binary = Path(f"artifacts/nnue-v2/{args.prefix}-{model}/engine.exe")
        old = Path(f"artifacts/nnue-v2/baseline-{model}/engine.exe")
        record = {"metadata": metadata(binary), "original": metadata(old), "positions": [], "cancellations": 0}
        with chess.engine.SimpleEngine.popen_uci(str(binary.resolve()), timeout=30) as engine, chess.engine.SimpleEngine.popen_uci(str(old.resolve()), timeout=30) as original:
            original.configure({"Evaluator": "nnue"})
            engine.configure({"Evaluator": "nnue"})
            assert engine.options["Evaluator"].default == "classical"
            for name, fen in POSITIONS.items():
                board = chess.Board(fen)
                snapshot = board.fen()
                for mode, limit in (("depth", chess.engine.Limit(depth=4)), ("nodes", chess.engine.Limit(nodes=100000))):
                    expected = search(original, board, limit)
                    for kernel in ("reference", "scalar"):
                        engine.configure({"NNUEKernel": kernel})
                        actual = search(engine, board, limit)
                        assert actual == expected, (model, name, mode, kernel, expected, actual)
                    record["positions"].append({"category": name, "limit": mode, "reference_and_scalar_identical": True, **expected})
                for kernel in ("scalar", "quant"):
                    engine.configure({"NNUEKernel": kernel})
                    scores = []
                    for incremental in (False, True):
                        engine.configure({"NNUEIncremental": incremental})
                        value = search(engine, board, chess.engine.Limit(depth=3))
                        scores.append(value["score"])
                    assert scores[0] == scores[1], (model, name, kernel, scores)
                    engine.configure({"NNUEIncremental": True})
                    with engine.analysis(board, chess.engine.Limit(time=1)) as pending:
                        time.sleep(.015)
                        pending.stop()
                        result = pending.wait()
                        assert result.move in board.legal_moves
                    record["cancellations"] += 1
                assert board.fen() == snapshot
            # Terminal and current draw precedence for both integer and float.
            terminal = [chess.Board("7k/6Q1/5K2/8/8/8/8/8 b - - 0 1"),
                        chess.Board("7k/5Q2/5K2/8/8/8/8/8 b - - 0 1"),
                        chess.Board("7k/8/8/8/8/8/8/K7 w - - 0 1"),
                        chess.Board("7k/8/8/8/8/8/8/KR6 w - - 100 1")]
            repeated = chess.Board()
            for uci in ["g1f3", "g8f6", "f3g1", "f6g8"] * 2:
                repeated.push_uci(uci)
            terminal.append(repeated)
            for kernel in ("scalar", "quant"):
                engine.configure({"NNUEKernel": kernel})
                for board in terminal:
                    result = search(engine, board, chess.engine.Limit(depth=3))
                    assert result["move"] is None
                    assert "#" in result["score"] if board.is_checkmate() else result["score"] == "0"
            record["terminal_checks"] = 10
            engine.configure({"Evaluator": "classical"})
            a = search(engine, chess.Board(), chess.engine.Limit(depth=4))
            engine.configure({"Evaluator": "nnue"})
            search(engine, chess.Board(), chess.engine.Limit(depth=3))
            engine.configure({"Evaluator": "classical"})
            b = search(engine, chess.Board(), chess.engine.Limit(depth=4))
            assert a == b
            record["evaluator_switch_and_fresh_tt"] = True
        report["models"][model] = record
        print(model, "passed exact original/scalar/reference trees and integration checks", flush=True)
    path.write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    main()
